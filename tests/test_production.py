import re
import unittest
from datetime import date
from unittest.mock import MagicMock, patch
from starlette.requests import Request
from app.main import lot_prefix, production_page, read_plans, mark_used, choose_plan
from app.lots import insert_lot, update_lot, delete_lot, lot_has_dependencies, next_running_no, read_lots

DAY = date(2026, 9, 21)
PLAN = dict(selection_id='p1', StartTime=DAY, Shift='D', PlanName='Plan 1',
            MaterialCode='12345678XX', MaterialName='Product brown', PlanCount=3600)
LOT = dict(ProductionID=7, ProdDate=DAY, Shift='D', PlanName='Plan 1',
           MaterialCode='12345678XX', MaterialName='Product brown', PlanQty=3600,
           ProductFamilyID=1, ProductFamily='NeuFit / NeuStile', ProductCode='06',
           LotPrefix='B0066909', RunningNo=1, LotNo='B006690901', CanVoid=1)
PRODUCTION_REJECT_CONTEXT = dict(
    production_reject_reasons=[],
    production_reject_total=0,
    production_reject_final_classified=0,
    production_reject_difference=0,
    production_reject_remark='',
    production_reject_error=None,
)

def request():
    return Request({'type':'http', 'method':'GET', 'path':'/', 'headers':[]})

def insert_test_lot(conn, plan=PLAN, prefix='B066909', running_no=1, family_id=1):
    with patch('app.lots.lot_prefix', return_value=prefix):
        suffix = running_no if isinstance(running_no, str) else f'{running_no:02d}'
        return insert_lot(conn, plan, '06', prefix, suffix, product_family_id=family_id)

class ProductionTests(unittest.TestCase):
    def test_prefix(self):
        cursor=MagicMock(); cursor.fetchone.return_value=('B',)
        self.assertEqual(lot_prefix(cursor, 1, '06', DAY), 'B066909')

    def test_date_filtered_source(self):
        cursor = MagicMock()
        cursor.description = [(k,) for k in PLAN if k != 'selection_id']
        cursor.fetchall.return_value = [tuple(v for k,v in PLAN.items() if k != 'selection_id')]
        result = read_plans(cursor, DAY)
        self.assertIn('dbo.P_ActivePlan', cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1:], ('CRTC','30A1','SB2-3',DAY))
        self.assertEqual(len(result[0]['selection_id']),64)

    def test_used_and_current_plan(self):
        plans = mark_used([dict(PLAN)], [LOT])
        self.assertEqual(plans[0]['used_by'], LOT['LotNo'])
        with self.assertRaises(ValueError): choose_plan(plans,'p1')
        self.assertIsNone(mark_used(plans,[LOT],7)[0]['used_by'])

    def render(self, **kwargs):
        conn=MagicMock()
        conn.cursor.return_value.fetchone.return_value=('06',)
        with patch('app.main.get_connection',return_value=conn), patch('app.main.read_lots',return_value=[dict(LOT)]), patch('app.main.read_plans',return_value=[dict(PLAN)]), patch('app.main.read_production_reject_context',return_value=dict(PRODUCTION_REJECT_CONTEXT)):
            response=production_page(request(), **kwargs)
        return response,conn

    def test_browse_information_and_disabled_plan(self):
        response, conn=self.render(production_id=7)
        self.assertEqual(response.status_code,200)
        text=response.body.decode()
        for value in ['B006690901','Product brown','3,600','USED: B006690901','disabled','PRODUCTION LOT','VOID LOT','aria-current="true"']:
            self.assertIn(value,text)
        self.assertIn('class="clock-input"', text)
        self.assertIn('placeholder="HH:mm"', text)
        self.assertNotIn('type="time"', text)
        self.assertNotIn('name="MaterialName"',text)
        self.assertNotIn('replacement_plan',text)
        self.assertIn("start.addEventListener('input', updateShift);", text)
        self.assertIn("start.addEventListener('change', updateShift);", text)
        self.assertIn('    updateShift();', text)
        lot_table=text.split('<table class="depallet-grid lot-table">',1)[1].split('</table>',1)[0]
        selected_row=re.search(r'<tr class="selected".*?</tr>',lot_table,re.S)
        self.assertIsNotNone(selected_row)
        self.assertEqual(selected_row[0].count('<td'),16)
        self.assertRegex(selected_row[0],r'<td><button[^>]*>Save</button></td>')
        action_cell=selected_row[0].split('<td class="lot-actions">',1)[1].split('</td>',1)[0]
        self.assertIn('EDIT',action_cell)
        self.assertIn('VOID LOT',action_cell)
        self.assertIn('.depallet-grid td.lot-actions{vertical-align:middle;',text)
        self.assertIn('.lot-table td.lot-actions>a,.lot-table td.lot-actions>form{display:inline-flex;',text)
        conn.commit.assert_not_called()

    def test_edit_original_date_and_current_selectable(self):
        response,_=self.render(production_id=7,edit=True,production_date=DAY)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.context['edit_plans'][0]['used_by'])
        self.assertIn('SAVE',response.body.decode())
        self.assertIn('CANCEL',response.body.decode())

    def test_stale_lot(self):
        response,conn=self.render(production_id=99)
        self.assertEqual(response.status_code,400)
        conn.commit.assert_not_called()

    def test_remembered_lot_is_restored_only_for_requested_date(self):
        response, _ = self.render(
            production_date=DAY, remembered_production_id=LOT['ProductionID'],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current']['ProductionID'], LOT['ProductionID'])
        self.assertIn('checked', response.body.decode())
        self.assertIn('remembered_lot_invalid', response.context)
        response, _ = self.render(
            production_date=date(2026, 9, 22), remembered_production_id=LOT['ProductionID'],
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['current'])
        self.assertTrue(response.context['remembered_lot_invalid'])

    def test_invalid_remembered_lot_falls_back_without_error(self):
        response, conn = self.render(
            production_date=DAY, remembered_production_id=999,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['current'])
        self.assertTrue(response.context['remembered_lot_invalid'])
        conn.commit.assert_not_called()

    def test_list_order(self):
        cursor=MagicMock(); cursor.fetchall.return_value=[]
        read_lots(cursor)
        sql=cursor.execute.call_args.args[0]
        self.assertIn('ORDER BY p.ProdDate DESC, p.LotSequence, p.ProductionID',sql)
        self.assertIn('WHERE p.IsActive=1',sql)
        self.assertIn('later.LotPrefix=p.LotPrefix',sql)
        self.assertNotIn('later.IsActive=1',sql)

    def test_mapping_and_create_redirect(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[
            (1,'06'),('NeuFit / NeuStile','Product'),('B',),(1,)]
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[]),patch('app.main.read_plans',return_value=[dict(PLAN)]),patch('app.main.insert_lot',return_value=8) as insert:
            response=production_page(request(),'p1',create=True,running_no='01',production_date=DAY)
        self.assertEqual(response.status_code,303)
        self.assertIn('production_id=8',response.headers['location'])
        self.assertEqual(insert.call_args.args[2:5],('06','B066909','01'))

    def test_mapped_product_header_includes_authoritative_product_name(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value=('Prestige Common','Angle HIP')
        with patch('app.main.get_connection', return_value=conn), \
             patch('app.main.read_lots', return_value=[]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_mapping', return_value=(4, '13')), \
             patch('app.main.next_running_no', return_value=1), \
             patch('app.main.lot_prefix', return_value='P013'):
            response = production_page(request(), 'p1', production_date=DAY)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Prestige Common / 13 / Angle HIP', response.body.decode())

    def test_lot_create_form_suggests_next_historical_suffix_and_exposes_reusable_override(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value=('Prestige Common','Angle HIP')
        with patch('app.main.get_connection', return_value=conn), \
             patch('app.main.read_lots', return_value=[]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_reject_context', return_value=dict(PRODUCTION_REJECT_CONTEXT)), \
             patch('app.main.read_mapping', return_value=(4, '13')), \
             patch('app.main.next_running_no', return_value=8), \
             patch('app.main.lot_prefix', return_value='I136909'):
            response = production_page(request(), 'p1', production_date=DAY)
        text = response.body.decode()
        self.assertIn('id="running_no" value="8" readonly', text)
        self.assertIn('name="running_no" type="text" inputmode="numeric" maxlength="2"', text)
        self.assertIn('value="08"', text)
        self.assertNotIn('data-historical-max', text)
        self.assertIn('id="create-lot-button"', text)
        self.assertIn('create.disabled = Boolean(blockingMessage);', text)

    def test_exhausted_automatic_sequence_still_allows_manual_suffix(self):
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value=('Prestige Common','Angle HIP')
        with patch('app.main.get_connection', return_value=conn), \
             patch('app.main.read_lots', return_value=[]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_reject_context', return_value=dict(PRODUCTION_REJECT_CONTEXT)), \
             patch('app.main.read_mapping', return_value=(4, '13')), \
             patch('app.main.next_running_no', return_value=100), \
             patch('app.main.lot_prefix', return_value='I136909'):
            response = production_page(request(), 'p1', production_date=DAY)
        text = response.body.decode()
        self.assertIn('Next Running No</label><input id="running_no" value="100" readonly', text)
        self.assertIn('Automatic sequence exhausted (maximum 99); enter an available suffix.', text)
        self.assertIn('id="running_suffix" name="running_no"', text)
        self.assertNotIn('id="running_suffix" name="running_no" type="text" inputmode="numeric" maxlength="2" pattern="[0-9]{2}" aria-label="Lot running number suffix" value="" disabled', text)
        self.assertIn('id="create-lot-button" class="primary" type="submit">CREATE LOT', text)

    def test_workflow_product_does_not_push_lot_controls_right(self):
        response, _ = self.render(production_id=7)
        text = response.body.decode()
        self.assertIn('.workflow .product-display{flex:0 1 auto;', text)
        self.assertNotIn('.workflow .product-display{flex:1 1 auto;', text)

    def test_plan_trigger_allows_long_desktop_description(self):
        response, _ = self.render(production_id=7)
        text = response.body.decode()
        self.assertIn('.plan-trigger{display:inline-flex;width:max-content;max-width:min(460px,100%);', text)

    def test_mapping_confirmation(self):
        conn=MagicMock()
        with patch('app.main.get_connection',return_value=conn), \
             patch('app.main.read_lots',return_value=[]), \
             patch('app.main.read_plans',return_value=[dict(PLAN)]), \
             patch('app.main.confirm_mapping',return_value=(1,'06')) as confirm, \
             patch('app.main.read_mapping',return_value=(1,'06')), \
             patch('app.main.lot_prefix',return_value='B066909'), \
             patch('app.main.next_running_no',return_value=1):
            response=production_page(request(),'p1','06',confirm=True,production_date=DAY,product_family=1)
        self.assertEqual(response.status_code,200)
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.args[2:],(1,'06'))

class TransactionTests(unittest.TestCase):
    def test_reorder_lot_swaps_persisted_sequence(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[('ProductionID',),('LotSequence',)]
        cursor.fetchall.return_value=[(7,1),(8,2),(9,3)]
        cursor.fetchone.side_effect=[(0,),(3,)]
        from app.lots import reorder_lot
        result=reorder_lot(conn,DAY,8,'up')
        self.assertEqual(result, {'moved':True,'ProductionID':8,'LotSequence':1})
        updates=[entry.args for entry in cursor.execute.call_args_list if 'UPDATE dbo.ProductionLot SET LotSequence' in entry.args[0]]
        self.assertEqual(len(updates),6)
        conn.commit.assert_called_once()

    def test_reorder_lot_boundary_is_noop(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[('ProductionID',),('LotSequence',)]
        cursor.fetchall.return_value=[(7,1),(8,2)]
        cursor.fetchone.return_value=(0,)
        from app.lots import reorder_lot
        result=reorder_lot(conn,DAY,7,'up')
        self.assertFalse(result['moved'])
        self.assertEqual([entry for entry in cursor.execute.call_args_list if 'UPDATE dbo.ProductionLot SET LotSequence' in entry.args[0]], [])
        conn.commit.assert_called_once()
    def test_create_history_and_lock(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(1,),(7,)]
        self.assertEqual(insert_test_lot(conn),7)
        sqls=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertIn('sp_getapplock',sqls[0])
        self.assertTrue(any('UPDLOCK,HOLDLOCK' in sql for sql in sqls))
        self.assertTrue(any('ProductionLotHistory' in s for s in sqls))
        conn.commit.assert_called_once()

    def test_duplicate_plan_rollback(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),('used',)]
        with self.assertRaisesRegex(ValueError,'already assigned'): insert_test_lot(conn)
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_suffix_at_or_below_historical_max_is_available_without_active_conflict(self):
        for number in ('01','02'):
            conn=MagicMock(); conn.cursor.return_value.fetchone.side_effect=[
                (0,),('NeuFit / NeuStile',),(1,'06'),None,None,(1,),(7,)]
            self.assertEqual(insert_test_lot(conn,running_no=number),7)
            conn.commit.assert_called_once()

    def test_manual_override_above_max_is_inserted(self):
        for suffix in ('04','05'):
            conn=MagicMock(); cursor=conn.cursor.return_value
            cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(1,),(7,)]
            self.assertEqual(insert_test_lot(conn,running_no=suffix),7)
            insert_args=next(call.args for call in cursor.execute.call_args_list
                             if 'INSERT INTO dbo.ProductionLot' in call.args[0])
            self.assertEqual(insert_args[8:10],(int(suffix),f'B066909{suffix}'))
            conn.commit.assert_called_once()

    def test_suffix_validation_and_leading_zero_preservation(self):
        for suffix in ('1','001','00','٠1',' 1','+1'):
            conn=MagicMock()
            with self.assertRaisesRegex(ValueError,'two ASCII digits|between 01 and 99'):
                insert_test_lot(conn,running_no=suffix)
            conn.rollback.assert_called_once()
            self.assertFalse(any('INSERT INTO dbo.ProductionLot' in call.args[0]
                                 for call in conn.cursor.return_value.execute.call_args_list))

        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(1,),(7,)]
        self.assertEqual(insert_test_lot(conn,running_no='01'),7)
        insert_args=next(call.args for call in cursor.execute.call_args_list
                         if 'INSERT INTO dbo.ProductionLot' in call.args[0])
        self.assertEqual(insert_args[8:10],(1,'B06690901'))

    def test_duplicate_lot_number_rejected_even_when_above_running_max(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,('duplicate',)]
        with self.assertRaisesRegex(ValueError,'already assigned to an active Lot'):
            insert_test_lot(conn,running_no='04')
        conn.rollback.assert_called_once()
        self.assertFalse(any('INSERT INTO dbo.ProductionLot' in call.args[0]
                             for call in cursor.execute.call_args_list))

    def test_automatic_running_sequence_advances_past_99(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.return_value=(100,)
        self.assertEqual(next_running_no(cursor,'B066909',1,'06',DAY),100)

    def test_voided_suffix_05_can_be_reused_without_changing_history(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(5,),(8,)]
        self.assertEqual(insert_test_lot(conn,running_no='05'),8)
        insert_args=next(call.args for call in cursor.execute.call_args_list
                         if 'INSERT INTO dbo.ProductionLot' in call.args[0])
        self.assertEqual(insert_args[8:10],(5,'B06690905'))
        self.assertEqual(insert_args[-1],5)
        sqls=[call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any('UPDATE dbo.ProductionLot' in sql or 'DELETE' in sql
                             for sql in sqls))
        self.assertNotEqual(7, 8)
        conn.commit.assert_called_once()

    def test_voided_suffix_02_can_be_reused_below_active_max_05(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(5,),(8,)]
        self.assertEqual(insert_test_lot(conn,running_no='02'),8)
        insert_args=next(call.args for call in cursor.execute.call_args_list
                         if 'INSERT INTO dbo.ProductionLot' in call.args[0])
        self.assertEqual(insert_args[8:10],(2,'B06690902'))
        self.assertEqual(insert_args[-1],5)
        conn.commit.assert_called_once()

    def test_active_suffix_07_cannot_be_reused(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,(7,)]
        with self.assertRaisesRegex(ValueError,'already assigned to an active Lot'):
            insert_test_lot(conn,running_no='07')
        conn.rollback.assert_called_once()
        self.assertFalse(any('INSERT INTO dbo.ProductionLot' in call.args[0]
                             for call in cursor.execute.call_args_list))

    def test_deleted_lot_number_can_be_recreated_with_new_production_id_and_create_history(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[
            (0,), (7,'B06690907','Plan 1'), None, (0,), (7,),
            (0,), ('NeuFit / NeuStile',), (1,'06'), None, None, (5,), (8,),
        ]
        delete_lot(conn,7)
        new_production_id=insert_test_lot(conn,running_no='07')
        insert_args=next(call.args for call in cursor.execute.call_args_list
                         if 'INSERT INTO dbo.ProductionLot' in call.args[0])
        self.assertEqual(insert_args[8:10],(7,'B06690907'))
        self.assertNotEqual(new_production_id,7)
        history_call=next(call for call in cursor.execute.call_args_list
                          if 'INSERT INTO dbo.ProductionLotHistory' in call.args[0])
        self.assertEqual(history_call.args[1:],(8,None,'B06690907',None,'Plan 1','CREATE'))
        self.assertEqual(conn.commit.call_count,2)

    def test_unused_lot_with_create_history_can_be_deleted(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),(7,'B06690905','Plan 1'),None,(0,),(7,)]
        delete_lot(conn,7)
        history_delete=next(call for call in cursor.execute.call_args_list
                            if 'DELETE FROM dbo.ProductionLotHistory' in call.args[0])
        self.assertEqual(history_delete.args[1:],(7,'B06690905','Plan 1'))
        self.assertIn("ChangeType='CREATE'",history_delete.args[0])
        self.assertIn('OldLotNo IS NULL',history_delete.args[0])
        self.assertTrue(any(call.args[0].startswith('DELETE FROM dbo.ProductionLot\n')
                            for call in cursor.execute.call_args_list))
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()

    def test_lot_with_operational_data_cannot_be_deleted(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),(7,'B06690905','Plan 1'),None,(1,)]
        with self.assertRaisesRegex(ValueError,'related or historical data'):
            delete_lot(conn,7)
        self.assertFalse(any(call.args[0].startswith('DELETE FROM dbo.ProductionLot')
                             for call in cursor.execute.call_args_list))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_lot_with_meaningful_history_cannot_be_deleted(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),(7,'B06690905','Plan 1'),(14,)]
        with self.assertRaisesRegex(ValueError,'related or historical data'):
            delete_lot(conn,7)
        history_check=next(call.args[0] for call in cursor.execute.call_args_list
                           if 'FROM dbo.ProductionLotHistory AS h' in call.args[0])
        self.assertIn("h.ChangeType='CREATE'",history_check)
        self.assertFalse(any(call.args[0].startswith('DELETE FROM dbo.ProductionLot')
                             for call in cursor.execute.call_args_list))
        conn.rollback.assert_called_once()

    def test_delete_failure_rolls_back_history_and_lot(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[(0,),(7,'B06690905','Plan 1'),None,(0,)]
        def execute(sql,*args):
            if sql.startswith('DELETE FROM dbo.ProductionLot\n'):
                raise RuntimeError('Lot delete failed')
        cursor.execute.side_effect=execute
        with self.assertRaisesRegex(RuntimeError,'Lot delete failed'):
            delete_lot(conn,7)
        self.assertTrue(any('DELETE FROM dbo.ProductionLotHistory' in call.args[0]
                            for call in cursor.execute.call_args_list))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_dependency_query_checks_all_production_id_tables(self):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.fetchone.side_effect=[None,(1,)]
        self.assertTrue(lot_has_dependencies(cursor,7,lock=True))
        queries=[call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn('ProductionLotHistory',queries[0])
        self.assertIn('sys.tables',queries[1])
        self.assertIn('sys.columns',queries[1])
        self.assertIn('ProductionID',queries[1])
        self.assertIn('UPDLOCK,HOLDLOCK',queries[1])

    def setup_update(self, next_no=2):
        conn=MagicMock(); cursor=conn.cursor.return_value
        cursor.description=[(k,) for k in LOT]
        cursor.fetchall.return_value=[tuple(LOT.values())]
        cursor.fetchone.side_effect=[(0,),None,(next_no,)]
        return conn,cursor

    def test_latest_void_history_no_delete(self):
        conn,cursor=self.setup_update()
        cursor.fetchone.side_effect=[(0,),None,(2,)]
        update_lot(conn,7,void=True)
        sqls=[c.args[0] for c in cursor.execute.call_args_list]
        self.assertTrue(any('SET IsActive=0' in s for s in sqls))
        self.assertFalse(any('DELETE' in s for s in sqls))
        self.assertEqual(cursor.execute.call_args.args[-1],'VOID')
        conn.commit.assert_called_once()

    def test_older_lot_can_be_voided_without_latest_number_check(self):
        conn,cursor=self.setup_update(3)
        cursor.fetchone.side_effect=[(0,)]
        update_lot(conn,7,void=True)
        sqls=[call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any('SET IsActive=0' in sql for sql in sqls))
        self.assertFalse(any('MAX(RunningNo)' in sql for sql in sqls))
        conn.commit.assert_called_once()

    def test_void_with_press_and_mould_usage_preserves_related_records(self):
        conn,cursor=self.setup_update()
        cursor.fetchone.side_effect=[(0,)]
        update_lot(conn,7,void=True)
        sqls=[call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any('SET IsActive=0' in sql for sql in sqls))
        self.assertFalse(any('DELETE' in sql for sql in sqls))
        self.assertFalse(any('FROM dbo.PressProduction' in sql for sql in sqls))
        conn.commit.assert_called_once()

    def test_plan_date_locked(self):
        conn,_=self.setup_update()
        with self.assertRaisesRegex(ValueError,'original Plan Date'):
            update_lot(conn,7,dict(PLAN,StartTime=date(2026,9,22)))
        conn.commit.assert_not_called()

    def test_other_lot_plan_rejected(self):
        conn,cursor=self.setup_update(); cursor.fetchone.side_effect=[(0,),('another',)]
        with self.assertRaisesRegex(ValueError,'already assigned'): update_lot(conn,7,PLAN)
        conn.commit.assert_not_called()

    def test_plan_update_keeps_lot_and_date(self):
        conn,cursor=self.setup_update(); cursor.fetchone.side_effect=[(0,),None]
        update_lot(conn,7,dict(PLAN,PlanName='Replacement',MaterialName='New product',PlanCount=50))
        args=next(c.args for c in cursor.execute.call_args_list if 'UPDATE dbo.ProductionLot' in c.args[0])
        self.assertEqual(args[1:],('Replacement','12345678XX','New product',50,7))
        self.assertNotIn('LotNo=',args[0]); self.assertNotIn('ProdDate=',args[0])
        self.assertEqual(cursor.execute.call_args.args[-1],'PLAN_CHANGE')

    def test_void_releases_plan_but_keeps_running_number_consumed(self):
        conn,cursor=self.setup_update()
        voided_lot=dict(LOT, LotNo='B06690907', LotPrefix='B066909', RunningNo=7)
        cursor.fetchall.return_value=[tuple(voided_lot.values())]
        update_lot(conn,7,void=True)
        cursor.fetchone.side_effect=[(0,),('NeuFit / NeuStile',),(1,'06'),None,None,(5,),(8,)]
        self.assertEqual(insert_test_lot(conn,running_no='07'),8)
        create_args=next(call.args[1:] for call in cursor.execute.call_args_list
                         if 'INSERT INTO dbo.ProductionLotHistory' in call.args[0]
                         and call.args[-1] == 'CREATE')
        self.assertEqual(create_args,(8,None,'B06690907',None,'Plan 1','CREATE'))
        void_args=next(call.args[1:] for call in cursor.execute.call_args_list
                       if 'INSERT INTO dbo.ProductionLotHistory' in call.args[0]
                       and call.args[-1] == 'VOID')
        self.assertEqual(void_args[0],7)
        self.assertFalse(any('DELETE' in call.args[0] for call in cursor.execute.call_args_list))
        cursor.fetchone.side_effect=None
        cursor.fetchone.return_value=(8,)
        self.assertEqual(next_running_no(cursor,'B066909',1,'06',DAY),8)
        self.assertNotIn('IsActive=1',cursor.execute.call_args.args[0])

    def test_history_failure_rolls_back(self):
        conn,cursor=self.setup_update()
        def execute(sql,*args):
            if 'INSERT INTO dbo.ProductionLotHistory' in sql: raise RuntimeError('history failure')
        cursor.execute.side_effect=execute
        with self.assertRaises(RuntimeError): update_lot(conn,7,void=True)
        conn.rollback.assert_called_once(); conn.commit.assert_not_called()

    def test_lock_timeout(self):
        conn=MagicMock(); conn.cursor.return_value.fetchone.return_value=(-1,)
        with self.assertRaisesRegex(ValueError,'retry'): insert_test_lot(conn)
        conn.commit.assert_not_called()

if __name__=='__main__':
    unittest.main()
