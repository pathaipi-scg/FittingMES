import unittest
import asyncio
import json
from starlette.requests import Request
from unittest.mock import patch
from datetime import date
from test_production import request
from app.main import press_mc_page, press_mc_capability_route

from app.press_mc import (add_press, assign_line, page_context, read_capability_matrix,
                          read_press_list, remove_from_line, save_capabilities,
                          set_active, update_press_name)

PRODUCTS = [
    dict(PressCode='F3',PressName='Press 3',CurrentLine='LINE1',CurrentLineName='Line 1',
         ProductFamily='Family A',ProductCode='01',ProductName='Product 1',ProductNameTH='ชื่อ 1',CanProduce=1),
    dict(PressCode='F3',PressName='Press 3',CurrentLine='LINE1',CurrentLineName='Line 1',
         ProductFamily='Family A',ProductCode='02',ProductName='Product 2',ProductNameTH='ชื่อ 2',CanProduce=0),
    dict(PressCode='F3',PressName='Press 3',CurrentLine='LINE1',CurrentLineName='Line 1',
         ProductFamily='Family B',ProductCode='01',ProductName='Other 1',ProductNameTH=None,CanProduce=0),
]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = []
        self.result = []

    def set_records(self, records):
        self.description = [(key,) for key in records[0]] if records else []
        self.result = [tuple(record.values()) for record in records]

    def execute(self, sql, *args):
        self.conn.sql.append((sql,args))
        if self.conn.fail and self.conn.fail in sql:
            raise RuntimeError('simulated SQL error')
        if 'MAX(DisplayOrder)' in sql:
            self.result=[(max((row['DisplayOrder'] for row in self.conn.presses),default=0)+1,)]
        elif 'vw_PressMcPressList' in sql:
            self.set_records(self.conn.presses)
        elif 'vw_PressMcCapabilityMatrix' in sql:
            code=args[0]
            self.set_records([row for row in self.conn.matrix if row['PressCode']==code])
        elif "EquipmentType='LINE'" in sql:
            self.set_records(self.conn.lines)
        elif 'EquipmentLineHistory' in sql:
            self.set_records([])
        elif 'SELECT DisplayOrder FROM dbo.EquipmentMaster' in sql:
            press=next((row for row in self.conn.presses if row['PressCode']==args[0]),None)
            self.result=[(press['DisplayOrder'],)] if press else []
        elif 'EXEC dbo.sp_SetPressProductCapability' in sql:
            self.conn.capability_calls.append(args)
        elif sql.strip() == 'BEGIN TRANSACTION':
            self.conn.begins += 1
        elif 'EXEC dbo.sp_Press_' in sql:
            self.conn.proc_calls.append((sql,args))
        else:
            raise AssertionError('Unexpected SQL: '+sql)
        return self

    def fetchall(self):
        result=self.result; self.result=[]; return result

    def fetchone(self):
        return self.result.pop(0) if self.result else None


class FakeConnection:
    def __init__(self):
        self.presses=[dict(PressCode='F3',PressName='Press 3',DisplayOrder=3,IsActive=True,
                           CurrentLine='LINE1',CurrentLineName='Line 1',LineAssignedAt=None)]
        self.lines=[dict(EquipmentCode='LINE1',EquipmentName='Line 1',DisplayOrder=101),
                    dict(EquipmentCode='LINE2',EquipmentName='Line 2',DisplayOrder=102)]
        self.matrix=list(PRODUCTS)
        self.sql=[]; self.proc_calls=[]; self.capability_calls=[]; self.begins=0
        self.commits=0; self.rollbacks=0; self.fail=None; self.cur=FakeCursor(self)
    def cursor(self): return self.cur
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
    def close(self): pass


class PressMcTests(unittest.TestCase):
    def test_remove_from_line_calls_history_procedure_and_commits_without_nested_begin(self):
        conn=FakeConnection()
        remove_from_line(conn,'F1','PressMc test remove')
        self.assertEqual(len(conn.proc_calls),1)
        sql,args=conn.proc_calls[0]
        self.assertIn('EXEC dbo.sp_Press_RemoveFromLine',sql)
        self.assertEqual(args,('F1','FittingMES','PressMc test remove'))
        self.assertEqual(conn.commits,1)
        self.assertEqual(conn.rollbacks,0)
        self.assertFalse(any(sql.strip()=='BEGIN TRANSACTION' for sql,_ in conn.sql))

    def test_remove_from_line_rolls_back_and_reraises_procedure_exception(self):
        conn=FakeConnection(); conn.fail='EXEC dbo.sp_Press_RemoveFromLine'
        with self.assertRaisesRegex(RuntimeError,'simulated SQL error'):
            remove_from_line(conn,'F1','PressMc test remove')
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.rollbacks,1)
        self.assertFalse(any(sql.strip()=='BEGIN TRANSACTION' for sql,_ in conn.sql))

    def test_assign_line_uses_same_commit_rollback_transaction_contract(self):
        conn=FakeConnection()
        assign_line(conn,'F1','LINE2','PressMc test move')
        sql,args=conn.proc_calls[0]
        self.assertIn('EXEC dbo.sp_Press_AssignLine',sql)
        self.assertEqual(args,('F1','LINE2','FittingMES','PressMc test move'))
        self.assertEqual(conn.commits,1)
        self.assertEqual(conn.rollbacks,0)
        failed=FakeConnection(); failed.fail='EXEC dbo.sp_Press_AssignLine'
        with self.assertRaisesRegex(RuntimeError,'simulated SQL error'):
            assign_line(failed,'F1','LINE2','PressMc test move')
        self.assertEqual(failed.commits,0)
        self.assertEqual(failed.rollbacks,1)
        self.assertFalse(any(sql.strip()=='BEGIN TRANSACTION' for sql,_ in failed.sql))

    def test_press_mc_page_renders_dynamic_list_and_grouped_checkbox_matrix(self):
        conn=FakeConnection()
        conn.presses.extend([
            dict(PressCode='F15',PressName='Future Press',DisplayOrder=15,IsActive=True,
                 CurrentLine=None,CurrentLineName=None,LineAssignedAt=None)])
        with patch('app.main.get_connection',return_value=conn):
            response=press_mc_page(request(),production_date=date(2026,9,26),press_code='F3')
        self.assertEqual(response.status_code,200)
        html=response.body.decode()
        self.assertIn('F15',html)
        self.assertIn('Future Press',html)
        self.assertIn('Product Capability',html)
        self.assertEqual(html.count('type="checkbox"'),4)
        self.assertIn('data-family="Family A" data-product-code="01" data-original="1" checked',html)
        self.assertIn('data-family="Family A" data-product-code="02" data-original="0"',html)
        self.assertIn('LINE1 / Line 1',html)
        self.assertIn('Disable Press',html)
        self.assertEqual(conn.commits,0)

    def test_press_list_uses_dynamic_view_and_does_not_filter_inactive(self):
        conn=FakeConnection()
        conn.presses.extend([
            dict(PressCode='F15',PressName='New press',DisplayOrder=15,IsActive=False,
                 CurrentLine=None,CurrentLineName=None,LineAssignedAt=None),
            dict(PressCode='P-X',PressName='Flexible code',DisplayOrder=16,IsActive=True,
                 CurrentLine='LINE2',CurrentLineName='Line 2',LineAssignedAt=None)])
        result=read_press_list(conn.cursor())
        self.assertEqual([press['PressCode'] for press in result],['F3','F15','P-X'])
        sql=conn.sql[0][0]
        self.assertIn('FROM dbo.vw_PressMcPressList',sql)
        self.assertNotIn('F14',sql)
        self.assertNotIn('IsActive=1',sql)

    def test_selected_press_loads_full_grouped_capability_matrix_and_lines(self):
        conn=FakeConnection()
        context=page_context(conn.cursor(),'F3')
        self.assertEqual(context['selected']['CurrentLine'],'LINE1')
        self.assertEqual(context['lines'][1]['EquipmentCode'],'LINE2')
        self.assertEqual([group['ProductFamily'] for group in context['capability_groups']],['Family A','Family B'])
        self.assertEqual([len(group['products']) for group in context['capability_groups']],[2,1])
        self.assertEqual([row['CanProduce'] for row in context['capability_groups'][0]['products']],[1,0])
        self.assertTrue(any('vw_PressMcCapabilityMatrix' in sql for sql,_ in conn.sql))

    def test_full_41_product_matrix_is_read_from_sql_view(self):
        conn=FakeConnection()
        conn.matrix=[]
        for family,count in (('NeuFit / NeuStile',11),('Oriental',11),('Prestige Common',10),('Special Ridge',9)):
            for number in range(1,count+1):
                conn.matrix.append(dict(PressCode='F3',PressName='Press 3',CurrentLine='LINE1',
                    CurrentLineName='Line 1',ProductFamily=family,ProductCode=f'{number:02d}',
                    ProductName='Product '+str(number),ProductNameTH=None,CanProduce=0))
        matrix=read_capability_matrix(conn.cursor(),'F3')
        self.assertEqual(len(matrix),41)
        self.assertEqual({row['ProductFamily'] for row in matrix},
            {'NeuFit / NeuStile','Oriental','Prestige Common','Special Ridge'})
        self.assertTrue(all(row['CanProduce']==0 for row in matrix))

    def test_capability_save_calls_history_procedure_only_for_changed_product(self):
        conn=FakeConnection()
        changed=save_capabilities(conn,'F3',[
            {'ProductFamily':'Family A','ProductCode':'01','CanProduce':True},
            {'ProductFamily':'Family A','ProductCode':'02','CanProduce':True}],
            'operator note')
        self.assertEqual(changed,1)
        self.assertEqual(conn.begins,0)
        self.assertEqual(len(conn.capability_calls),1)
        self.assertEqual(conn.capability_calls[0],('F3','Family A','02',True,'operator note','FittingMES'))
        self.assertEqual(conn.commits,1)
        self.assertFalse(any(sql.strip() == 'BEGIN TRANSACTION' for sql,_ in conn.sql))
        self.assertFalse(any('DELETE FROM dbo.PressProductCapability' in sql for sql,_ in conn.sql))

    def test_capability_http_route_passes_f1_composite_key_to_procedure_and_commits(self):
        conn=FakeConnection()
        payload=json.dumps({'changes':[{'ProductFamily':'Family B','ProductCode':'01','CanProduce':True}],
                            'remark':'PressMc capability update'})
        async def receive(): return {'type':'http.request','body':payload.encode(),'more_body':False}
        req=Request({'type':'http','method':'POST','path':'/press-mc/F3/capabilities',
            'headers':[(b'content-type',b'application/json')]},receive)
        with patch('app.main.get_connection',return_value=conn):
            response=asyncio.run(press_mc_capability_route('F3',req))
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(response.body)['message'],'Press capability changes saved.')
        self.assertEqual(conn.capability_calls,[('F3','Family B','01',True,'PressMc capability update','FittingMES')])
        self.assertEqual(conn.commits,1)
        self.assertFalse(any(sql.strip() == 'BEGIN TRANSACTION' for sql,_ in conn.sql))

    def test_capability_save_rolls_back_all_requested_changes_on_procedure_error(self):
        conn=FakeConnection(); conn.fail='EXEC dbo.sp_SetPressProductCapability'
        with self.assertRaises(RuntimeError):
            save_capabilities(conn,'F3',[{'ProductFamily':'Family A','ProductCode':'02','CanProduce':True}])
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.rollbacks,1)

    def test_capability_request_rejects_unknown_product_and_duplicate_keys(self):
        for changes in (
            [{'ProductFamily':'Not a family','ProductCode':'01','CanProduce':True}],
            [{'ProductFamily':'Family A','ProductCode':'01','CanProduce':True},
             {'ProductFamily':'Family A','ProductCode':'01','CanProduce':False}],
        ):
            conn=FakeConnection()
            with self.assertRaises(ValueError): save_capabilities(conn,'F3',changes)
            self.assertEqual(conn.capability_calls,[])
            self.assertEqual(conn.commits,0)

    def test_machine_changes_call_existing_history_aware_procedures(self):
        conn=FakeConnection()
        add_press(conn,'F15','Press 15','LINE2','added')
        update_press_name(conn,'F3','Press Three')
        assign_line(conn,'F3','LINE2','move')
        remove_from_line(conn,'F3','unassign')
        set_active(conn,'F3',False,'service')
        calls='\n'.join(sql for sql,_ in conn.sql)
        for procedure in ('sp_Press_Add','sp_Press_UpdateInfo','sp_Press_AssignLine',
                          'sp_Press_RemoveFromLine','sp_Press_SetActive'):
            self.assertIn('EXEC dbo.'+procedure,calls)
        self.assertFalse(any(sql.lstrip().startswith('DELETE') for sql,_ in conn.sql))
        add_args=next(args for sql,args in conn.sql if 'EXEC dbo.sp_Press_Add' in sql)
        self.assertEqual(add_args,('F15','Press 15',4,'LINE2','FittingMES','added'))
        self.assertEqual(conn.commits,5)

    def test_press_add_supports_unassigned_line_and_validation(self):
        conn=FakeConnection()
        add_press(conn,'F16','Press 16','', 'initial')
        args=next(args for sql,args in conn.sql if 'EXEC dbo.sp_Press_Add' in sql)
        self.assertEqual(args[3],None)
        with self.assertRaisesRegex(ValueError,'Press Code is required'):
            add_press(FakeConnection(),'','Name',None,'')


if __name__ == '__main__':
    unittest.main()
