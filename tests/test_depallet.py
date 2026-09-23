import asyncio
import copy
import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urlencode
from starlette.requests import Request
from app.depallet import read_context, read_reasons, default_entry, summary, validate, save_depallet
from app.main import load_depallet, save_depallet_route, save_depallet_response, production_page
from test_production import LOT, PLAN, DAY, request

CODES = [f'R{i:02d}' for i in range(1,25)] + ['R99']
REASONS = [dict(ReasonCode=code,ReasonNameTH='เหตุผล '+code,SortOrder=i,IsActive=True) for i,code in enumerate(CODES)]
RAW = dict(DepalletDate='2026-09-23',Shift='2',LotNo='STORED-LOT-01',DepalletQty='100',GoodQty='90',
           Remark='บันทึก',rejects={'R01':'7','R99':'3'})
SAVED = dict(DepalletID=10,ProductionID=7,DepalletDate=date(2026,9,23),Shift='2',LotNo='STORED-LOT-01',
             ProductFamily=None,ProductCode='06',MaterialCode=LOT['MaterialCode'],
             MaterialName=LOT['MaterialName'],DepalletQty=100,GoodQty=90,Remark='บันทึก')


class MemoryConnection:
    """Isolated SQL-write double, with commit/rollback and unique reject row keys."""
    def __init__(self, existing=False):
        self.db=dict(lots=[dict(LOT)],reasons=copy.deepcopy(REASONS),
                     depallets=[dict(SAVED)] if existing else [],
                     rejects={(10,'R01'):7,(10,'R99'):3} if existing else {})
        self.work=copy.deepcopy(self.db)
        self.commits=0; self.rollbacks=0; self.sql=[]; self.fail=None; self.bad_view=False
        self.cur=MemoryCursor(self)
    def cursor(self): return self.cur
    def commit(self):
        self.db=copy.deepcopy(self.work); self.commits+=1
    def rollback(self):
        self.work=copy.deepcopy(self.db); self.rollbacks+=1
    def close(self): pass


class MemoryCursor:
    def __init__(self, conn):
        self.conn=conn; self.description=[]; self.result=[]
    def set_rows(self, records):
        self.description=[(key,) for key in records[0]] if records else []
        self.result=[tuple(record.values()) for record in records]
    def execute(self, sql, *args):
        c=self.conn; c.sql.append((sql,args)); self.result=[]; self.description=[]
        if c.fail and c.fail in sql: raise RuntimeError('simulated SQL failure')
        if 'sp_getapplock' in sql:
            self.set_rows([{'result':0}])
        elif 'FROM dbo.ProductionLot' in sql:
            self.set_rows([lot for lot in c.work['lots'] if lot['ProductionID']==args[0]])
        elif 'FROM dbo.RejectReasonMaster' in sql:
            self.set_rows([{k:r[k] for k in ('ReasonCode','ReasonNameTH','SortOrder')}
                           for r in sorted(c.work['reasons'],key=lambda r:r['SortOrder']) if r['IsActive']])
        elif 'FROM dbo.DepalletReject r' in sql:
            result=[]
            for (depallet_id,code),qty in c.work['rejects'].items():
                if depallet_id==args[0]:
                    reason=next(r for r in c.work['reasons'] if r['ReasonCode']==code)
                    result.append(dict(ReasonCode=code,Qty=qty,ReasonNameTH=reason['ReasonNameTH'],
                                       IsActive=reason['IsActive'],SortOrder=reason['SortOrder']))
            self.set_rows(result)
        elif 'FROM dbo.vw_DepalletValidation' in sql:
            selected=[d for d in c.work['depallets'] if
                      (d['ProductionID']==args[0] and d['DepalletDate']==args[1]) if len(args)==2] if len(args)==2 else [
                      d for d in c.work['depallets'] if d['ProductionID' if 'WHERE ProductionID=?' in sql else 'DepalletID']==args[0]]
            result=[]
            for d in selected:
                rejects={code:q for (id,code),q in c.work['rejects'].items() if id==d['DepalletID']}
                values=dict(d,**summary(d['DepalletQty'],d['GoodQty'],rejects))
                if c.bad_view: continue
                result.append(values)
            self.set_rows(result)
        elif 'SELECT DepalletID FROM dbo.Depallet' in sql:
            self.set_rows([dict(DepalletID=d['DepalletID']) for d in c.work['depallets']
                           if d['ProductionID']==args[0] and d['DepalletDate']==args[1]])
        elif 'INSERT INTO dbo.DepalletReject' in sql:
            key=(args[0],args[1])
            if key in c.work['rejects']: raise RuntimeError('duplicate reject')
            c.work['rejects'][key]=args[2]
        elif 'UPDATE dbo.DepalletReject' in sql:
            c.work['rejects'][(args[1],args[2])]=args[0]
        elif 'DELETE FROM dbo.DepalletReject' in sql:
            c.work['rejects'].pop((args[0],args[1]),None)
        elif 'INSERT INTO dbo.Depallet' in sql:
            keys=('ProductionID','DepalletDate','Shift','LotNo','ProductFamily','ProductCode',
                  'MaterialCode','MaterialName','DepalletQty','GoodQty','Remark')
            new=dict(zip(keys,args),DepalletID=10+len(c.work['depallets']))
            c.work['depallets'].append(new); self.set_rows([dict(DepalletID=new['DepalletID'])])
        elif 'UPDATE dbo.Depallet SET' in sql:
            row=next(d for d in c.work['depallets'] if d['DepalletID']==args[-1])
            row.update(zip(('Shift','LotNo','DepalletQty','GoodQty','Remark'),args[:-1]))
        else: raise AssertionError('Unexpected SQL: '+sql)
        return self
    def fetchone(self): return self.result.pop(0) if self.result else None
    def fetchall(self):
        result=self.result; self.result=[]; return result


class DepalletTests(unittest.TestCase):
    def render_lot(self, conn, lot, **kwargs):
        with patch('app.main.get_connection',return_value=conn), \
             patch('app.main.read_lots',return_value=[lot]), \
             patch('app.main.read_plans',return_value=[PLAN]), \
             patch('app.main.read_production_data',return_value={'CounterQty':500,'CuringQty':450}):
            return production_page(request(),production_id=lot['ProductionID'],**kwargs)

    def test_selected_production_2_loads_saved_header_and_all_raw_rejects(self):
        import re
        conn=MemoryConnection()
        lot=dict(LOT,ProductionID=2,LotNo='B006690902')
        saved=dict(SAVED,DepalletID=1,ProductionID=2,DepalletDate=date(2026,9,22),
                   Shift='1',LotNo='B006690902',DepalletQty=1000,GoodQty=600,Remark='Saved remark')
        conn.work['depallets']=[saved,dict(SAVED,ProductionID=99)]
        quantities={code:i for i,code in enumerate(CODES[:-1])}
        conn.work['rejects']={(1,code):qty for code,qty in quantities.items()}
        conn.work['rejects'][(1,'R99')]=999
        conn.work['reasons'][7]['IsActive']=False
        before=copy.deepcopy(conn.work)
        # Implicit and explicit matching lot dates retain the saved Depallet date.
        for page_date in (None,lot['ProdDate']):
            response=self.render_lot(conn,lot,production_date=page_date)
            self.assertEqual(response.status_code,200)
            context=response.context
            for key,value in saved.items():
                self.assertEqual(context['depallet'][key],value)
            self.assertEqual(context['reject_values'],quantities)
            self.assertEqual(context['depallet']['R99'],124)
            text=response.body.decode()
            for field,value in [('date','2026-09-22'),('shift','1'),('lot','B006690902'),
                                ('qty','1000'),('good','600'),('remark','Saved remark')]:
                tag=re.search(r'<input id="depallet-'+field+r'"[^>]*>',text)[0]
                self.assertIn('value="'+value+'"',tag)
            for code,qty in quantities.items():
                tag=re.search(r'<input id="reject-'+code+r'"[^>]*>',text)[0]
                self.assertIn('value="'+str(qty)+'"',tag)
            r99=re.search(r'<input id="depallet-r99"[^>]*>',text)[0]
            self.assertIn('value="124"',r99)
            self.assertIn('readonly',r99)
            self.assertEqual(context['production_data'],{'CounterQty':500,'CuringQty':450})
            self.assertIn('SAVE PRODUCTION',text)
        self.assertEqual(conn.work,before)
        self.assertEqual(conn.commits,0)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_new_selected_lot_defaults_to_lot_date_not_page_date(self):
        import re
        conn=MemoryConnection()
        response=self.render_lot(conn,LOT)
        self.assertEqual(response.context['depallet']['DepalletDate'],LOT['ProdDate'])
        self.assertEqual(response.context['depallet']['LotNo'],LOT['LotNo'])
        tag=re.search(r'<input id="depallet-date"[^>]*>',response.body.decode())[0]
        self.assertIn('value="2026-09-21"',tag)
        self.assertNotIn('readonly',tag)
        self.assertNotIn('disabled',tag)
        self.assertEqual(conn.work['depallets'],[])
        self.assertEqual(conn.commits,0)

    def test_multiple_dates_require_operator_selection(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'].append(dict(SAVED,DepalletID=11,DepalletDate=date(2026,9,24),LotNo='SECOND'))
        response=self.render_lot(conn,LOT)
        self.assertEqual(response.context['depallet_dates'],[date(2026,9,23),date(2026,9,24)])
        self.assertEqual(response.context['depallet']['DepalletDate'],'')
        self.assertEqual(response.context['reject_values'],{})
        self.assertIn(b'id="depallet-record"',response.body)
        import re
        self.assertIn('disabled',re.search(r'<button id="save-depallet"[^>]*>',response.body.decode())[0])
        with patch('app.main.get_connection',return_value=conn):
            response=load_depallet(7,date(2026,9,24))
        self.assertEqual(json.loads(response.body)['depallet']['LotNo'],'SECOND')
        self.assertEqual(conn.commits,0)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_defaults_keep_independent_date_lot_shift(self):
        lot=dict(LOT,Shift='2')
        defaults=default_entry(lot,date(2026,10,1))
        self.assertEqual(defaults['LotNo'],LOT['LotNo'])
        self.assertEqual(defaults['Shift'],'2')
        self.assertEqual(defaults['DepalletDate'],date(2026,10,1))
        self.assertEqual(defaults['ProductionID'],7)

    def test_reasons_are_active_sorted_unicode(self):
        conn=MemoryConnection()
        conn.work['reasons'].reverse()
        conn.work['reasons'][0]['IsActive']=False
        reasons=read_reasons(conn.cursor())
        self.assertEqual([r['ReasonCode'] for r in reasons],CODES[:-1])
        self.assertIn('เหตุผล',reasons[0]['ReasonNameTH'])
        self.assertIn('WHERE IsActive=1 ORDER BY SortOrder',conn.sql[0][0])

    def test_read_new_does_not_write(self):
        conn=MemoryConnection()
        context=read_context(conn.cursor(),LOT,DAY)
        self.assertEqual(context['depallet']['LotNo'],LOT['LotNo'])
        self.assertEqual(context['reject_values'],{})
        self.assertEqual(conn.commits,0)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_edit_reloads_values_and_uses_validation_view(self):
        conn=MemoryConnection(existing=True)
        context=read_context(conn.cursor(),LOT,date(2026,9,23))
        self.assertEqual(context['depallet']['LotNo'],'STORED-LOT-01')
        self.assertEqual(context['reject_values'],{'R01':7})
        self.assertEqual(context['depallet']['R99'],3)
        self.assertEqual(context['depallet']['AccountedQty'],100)
        self.assertEqual(context['depallet']['RejectPct'],Decimal(10))
        self.assertFalse(context['depallet']['IsBalanced'])

    def test_all_reason_quantities_save_as_rows(self):
        conn=MemoryConnection()
        raw=dict(RAW,DepalletQty='25',GoodQty='0',rejects={code:'1' for code in CODES})
        result=save_depallet(conn,7,raw)
        self.assertEqual(len(conn.db['rejects']),25)
        self.assertEqual({key[1] for key in conn.db['rejects']},set(CODES))
        self.assertEqual(result['R99'],1)
        self.assertEqual(result['DifferenceQty'],1)

    def test_editable_depallet_lot_never_modifies_production(self):
        conn=MemoryConnection(); before=copy.deepcopy(conn.db['lots'])
        save_depallet(conn,7,RAW)
        self.assertEqual(conn.db['depallets'][0]['LotNo'],'STORED-LOT-01')
        self.assertEqual(conn.db['depallets'][0]['ProductionID'],7)
        self.assertEqual(conn.db['lots'],before)
        self.assertFalse(any(('UPDATE dbo.Production' in sql or 'DepalletPISLog' in sql) for sql,_ in conn.sql))

    def test_repeat_save_updates_instead_of_duplicate(self):
        conn=MemoryConnection()
        save_depallet(conn,7,RAW)
        save_depallet(conn,7,dict(RAW,Remark='updated'))
        self.assertEqual(len(conn.db['depallets']),1)
        self.assertEqual(len(conn.db['rejects']),2)
        self.assertEqual(conn.db['depallets'][0]['Remark'],'updated')

    def test_blank_zero_removes_obsolete_reject_rows(self):
        conn=MemoryConnection(existing=True)
        save_depallet(conn,7,dict(RAW,GoodQty='100',rejects={'R01':'','R99':'0'}))
        self.assertEqual(conn.db['rejects'],{})
        conn=MemoryConnection()
        save_depallet(conn,7,dict(RAW,GoodQty='100',rejects={'R01':'','R99':'0'}))
        self.assertEqual(conn.db['rejects'],{})

    def test_date_selects_separate_record(self):
        conn=MemoryConnection(existing=True)
        save_depallet(conn,7,dict(RAW,DepalletDate='2026-10-01'))
        self.assertEqual(len(conn.db['depallets']),2)
        self.assertEqual(conn.db['depallets'][0],SAVED)

    def test_integer_and_required_field_validation(self):
        for change in ({'DepalletQty':'-1'},
                       {'GoodQty':'2.5'},{'DepalletQty':'2147483648'},
                       {'rejects':{'R01':'-1'}},{'rejects':{'R01':'1.5'}},
                       {'rejects':{'R00':'10'}},{'LotNo':''},{'Shift':''},
                       {'Remark':'x'*501},{'DepalletDate':'2026-02-30'}):
            with self.subTest(change=change):
                conn=MemoryConnection()
                with self.assertRaises(ValueError): save_depallet(conn,7,dict(RAW,**change))
                self.assertEqual(conn.db['depallets'],[])
                self.assertEqual(conn.commits,0)
                self.assertEqual(conn.rollbacks,1)

    def test_unbalanced_save_preserves_raw_reasons_on_insert_and_update(self):
        for existing in (False, True):
            for classified, difference in ((175, 25), (215, -15)):
                with self.subTest(existing=existing, classified=classified):
                    conn=MemoryConnection(existing=existing)
                    # Exercise every operator-classified raw code.
                    entered={code:'1' for code in CODES[:-1]}
                    entered['R01']=str(classified-23)
                    raw=dict(RAW,DepalletQty='3000',GoodQty='2800',rejects=entered)
                    before=copy.deepcopy(raw)
                    result=save_depallet(conn,7,raw)
                    self.assertEqual(conn.commits,1)
                    self.assertEqual(conn.rollbacks,0)
                    self.assertEqual(raw,before)
                    expected={(10,code):int(qty) for code,qty in entered.items()}
                    if difference > 0: expected[(10,'R99')]=difference
                    self.assertEqual(conn.db['rejects'],expected)
                    self.assertEqual(result['R99'],max(difference,0))
                    self.assertEqual(result['PhysicalRejectQty'],200)
                    self.assertEqual(result['ClassifiedRejectQty'],classified)
                    self.assertEqual(result['DifferenceQty'],difference)
                    self.assertFalse(result['IsBalanced'])
                    loaded=read_context(conn.cursor(),LOT,date(2026,9,23))
                    self.assertEqual(loaded['depallet']['DifferenceQty'],difference)
                    self.assertEqual(loaded['reject_values'],{code:int(qty) for code,qty in entered.items()})

    def test_positive_difference_stores_calculated_r99(self):
        conn=MemoryConnection()
        result=save_depallet(conn,7,dict(RAW,DepalletQty='3140',GoodQty='2980',rejects={'R01':'41'}))
        self.assertEqual(result['PhysicalRejectQty'],160)
        self.assertEqual(result['ClassifiedRejectQty'],41)
        self.assertEqual(result['DifferenceQty'],119)
        self.assertEqual(result['R99'],119)
        self.assertEqual(conn.db['rejects'],{(10,'R01'):41,(10,'R99'):119})

    def test_edit_replaces_deletes_and_recreates_r99(self):
        conn=MemoryConnection(existing=True)
        # Even an inactive R99 master must not preserve stale stored R99.
        conn.work['reasons'][-1]['IsActive']=False
        for depallet,good,classified,expected in ((3140,2980,41,119),
                                                (3000,2800,215,0),
                                                (3000,2800,200,0),
                                                (3000,2790,200,10)):
            result=save_depallet(conn,7,dict(RAW,DepalletQty=str(depallet),GoodQty=str(good),rejects={'R01':str(classified)}))
            self.assertEqual(result['R99'],expected)
            self.assertEqual(conn.db['rejects'][(10,'R01')],classified)
            if expected:
                self.assertEqual(conn.db['rejects'][(10,'R99')],expected)
            else:
                self.assertNotIn((10,'R99'),conn.db['rejects'])

    def test_client_r99_is_ignored(self):
        for supplied in ('999999','-15','not a quantity',None):
            for classified,expected in ((41,119),(215,0)):
                conn=MemoryConnection(existing=True)
                result=save_depallet(conn,7,dict(RAW,DepalletQty='3140',GoodQty='2980',
                    rejects={'R01':str(classified),'R99':supplied}))
                self.assertEqual(result['R99'],expected)
                self.assertEqual(conn.db['rejects'].get((10,'R99'),0),expected)

    def test_loading_stale_r99_recalculates_without_writing(self):
        conn=MemoryConnection(existing=True)
        conn.work['rejects'][(10,'R99')]=999
        context=read_context(conn.cursor(),LOT,date(2026,9,23))
        self.assertEqual(context['depallet']['R99'],3)
        self.assertEqual(context['depallet']['ClassifiedRejectQty'],7)
        self.assertEqual(conn.work['rejects'][(10,'R99')],999)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_unbalanced_save_response_is_successful(self):
        for classified in (175,215):
            conn=MemoryConnection()
            with patch('app.main.get_connection',return_value=conn):
                response=save_depallet_response(7,dict(RAW,DepalletQty='3000',GoodQty='2800',rejects={'R01':str(classified)}))
            self.assertEqual(response.status_code,200)
            self.assertEqual(json.loads(response.body)['depallet']['DifferenceQty'],200-classified)

    def test_zero_quantity_safe(self):
        data,rejects=validate(dict(RAW,DepalletQty='0',GoodQty='0',rejects={}),CODES)
        self.assertEqual(summary(data['DepalletQty'],data['GoodQty'],rejects)['RejectPct'],0)

    def test_transaction_rolls_back_header_and_rejects(self):
        for failure in ('INSERT INTO dbo.DepalletReject','UPDATE dbo.DepalletReject','DELETE FROM dbo.DepalletReject'):
            conn=MemoryConnection(existing=failure.startswith(('UPDATE','DELETE')))
            before=copy.deepcopy(conn.db)
            conn.fail=failure
            raw=dict(RAW,GoodQty='100',rejects={}) if failure.startswith('DELETE') else RAW
            with self.assertRaises(RuntimeError): save_depallet(conn,7,raw)
            self.assertEqual(conn.db,before); self.assertEqual(conn.work,before)
            self.assertEqual(conn.commits,0); self.assertEqual(conn.rollbacks,1)

    def test_final_view_failure_rolls_back_everything(self):
        conn=MemoryConnection(); conn.bad_view=True
        with self.assertRaises(ValueError): save_depallet(conn,7,RAW)
        self.assertEqual(conn.db['depallets'],[])
        self.assertEqual(conn.db['rejects'],{})

    def test_duplicate_existing_records_are_not_arbitrarily_overwritten(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'].append(dict(SAVED,DepalletID=11))
        with self.assertRaisesRegex(ValueError,'Multiple'): read_context(conn.cursor(),LOT,date(2026,9,23))
        with self.assertRaisesRegex(ValueError,'Multiple'): save_depallet(conn,7,RAW)
        self.assertEqual(conn.commits,0)

    def test_inactive_saved_rejects_are_preserved_and_counted(self):
        conn=MemoryConnection(existing=True)
        conn.work['reasons'][0]['IsActive']=False
        context=read_context(conn.cursor(),LOT,date(2026,9,23))
        self.assertEqual(context['inactive_rejects'][0]['Qty'],7)
        save_depallet(conn,7,dict(RAW,rejects={}))
        self.assertEqual(conn.db['rejects'][(10,'R01')],7)
        self.assertEqual(conn.db['rejects'][(10,'R99')],3)

    def test_server_load_and_save_response(self):
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn):
            response=load_depallet(7,date(2026,9,23))
            self.assertEqual(response.status_code,200)
            self.assertEqual(json.loads(response.body)['depallet']['LotNo'],LOT['LotNo'])
            response=save_depallet_response(7,RAW)
            self.assertEqual(response.status_code,200)
            self.assertEqual(json.loads(response.body)['message'],'Depallet data saved.')

    def test_save_route_parses_dynamic_reject_fields(self):
        body=urlencode(dict(depallet_date='2026-09-23',shift='2',lot_no='OTHER',depallet_qty='1',good_qty='0',reject_R99='99999')).encode()
        async def receive(): return {'type':'http.request','body':body,'more_body':False}
        req=Request({'type':'http','method':'POST','path':'/lots/7/depallet','headers':[(b'content-type',b'application/x-www-form-urlencoded')]},receive)
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn):
            response=asyncio.run(save_depallet_route(req,7))
        self.assertEqual(response.status_code,200)
        self.assertEqual(conn.db['rejects'],{(10,'R99'):1})

    def test_page_renders_inline_below_calculated_and_lot_editable(self):
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[LOT]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_production_data',return_value={}):
            response=production_page(request(),production_id=7,production_date=DAY)
        self.assertEqual(response.status_code,200)
        text=response.body.decode()
        self.assertLess(text.index('id="wet-reject-qty"'),text.index('DEPALLET INPUT'))
        for heading in ('CALCULATED DATA','REJECT DETAIL','CALCULATED DEPALLET DATA'):
            self.assertNotIn('<h2>'+heading+'</h2>',text)
        self.assertIn('name="lot_no"',text)
        self.assertIn('R99 อื่นๆ',text)
        import re
        r99=re.search(r'<input id="depallet-r99"[^>]*>',text)[0]
        self.assertIn('readonly',r99)
        self.assertNotIn('name=',r99)
        self.assertNotIn('id="reject-R99"',text)
        self.assertEqual(text.count('data-reject-code='),24)
        import re
        tag=re.search(r'<input id="depallet-lot"[^>]*>',text)[0]
        self.assertNotIn('readonly',tag)

    def test_new_load_failure_does_not_break_production_page(self):
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[LOT]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_production_data',return_value={}),patch('app.main.read_depallet_context',side_effect=RuntimeError('unavailable')):
            response=production_page(request(),production_id=7)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'SAVE PRODUCTION',response.body)
        self.assertNotIn(b'id="depallet-input"',response.body)
