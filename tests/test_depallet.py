import asyncio
import copy
import json
import re
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from starlette.requests import Request
from app.depallet import (read_context, read_reasons, default_entry, summary, validate, save_depallet,
                          read_curing_lots, read_daily_work, save_depallet_batch, read_day_start_time,
                          production_clock_datetime, resolve_run_times, reorder_depallet_run)
from app.main import (load_depallet, save_depallet_route, save_depallet_response, save_depallet_batch_response,
                      save_depallet_batch_route, reorder_depallet_route, reorder_depallet_response,
                      production_page, depallet_page)
from test_production import LOT, PLAN, DAY, request

CODES = [f'R{i:02d}' for i in range(1,25)] + ['R99']
REASONS = [dict(ReasonCode=code,ReasonNameTH='เหตุผล '+code,SortOrder=i,IsActive=True) for i,code in enumerate(CODES)]
RAW = dict(DepalletDate='2026-09-23',Shift='2',LotNo='STORED-LOT-01',Start='20:00',End='21:00',DepalletQty='100',GoodQty='90',
           Remark='บันทึก',rejects={'R01':'7','R99':'3'})
SAVED = dict(DepalletID=10,ProductionID=7,DepalletDate=date(2026,9,23),Shift='2',LotNo='STORED-LOT-01',
             ProductFamily=None,ProductCode='06',MaterialCode=LOT['MaterialCode'],
             MaterialName=LOT['MaterialName'],DepalletQty=100,GoodQty=90,Remark='บันทึก',
             StartDateTime=None,EndDateTime=None,RunSequence=1)
EDIT_RAW = dict(RAW,DepalletID=10)


class MemoryConnection:
    """Isolated SQL-write double, with commit/rollback and unique reject row keys."""
    def __init__(self, existing=False):
        self.db=dict(lots=[dict(LOT)],reasons=copy.deepcopy(REASONS),
                     day_rules=[dict(RuleID=1,EffectiveFromDate=date(2026,1,1),DayStartTime=time(8),Remark='Initial')],
                     balances={LOT['ProductionID']:dict(ProductionID=LOT['ProductionID'],ProductionQty=10000,
                         DepalletQtyTotal=0,RemainingCuringQty=10000)},
                     products=[dict(ProductFamily='NeuFit / NeuStile',ProductCode='06',ProductName='Fixture Product')],
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
        elif 'FROM dbo.ProductionDayRuleHistory' in sql:
            eligible=[rule for rule in c.work['day_rules'] if rule['EffectiveFromDate']<=args[0]]
            eligible.sort(key=lambda rule:(rule['EffectiveFromDate'],rule['RuleID']),reverse=True)
            self.set_rows([{'DayStartTime':eligible[0]['DayStartTime']}] if eligible else [])
        elif 'FROM dbo.vw_DepalletCuringBalance WHERE ProductionID' in sql:
            balance=c.work['balances'].get(args[0])
            if balance:
                total=sum(d['DepalletQty'] for d in c.work['depallets'] if d['ProductionID']==args[0])
                balance=dict(balance,DepalletQtyTotal=total,RemainingCuringQty=max(balance['ProductionQty']-total,0))
                self.set_rows([balance])
            else: self.set_rows([])
        elif 'FROM dbo.vw_DepalletCuringBalance b' in sql:
            result=[]
            for lot in c.work['lots']:
                balance=c.work['balances'].get(lot['ProductionID'])
                if balance:
                    total=sum(d['DepalletQty'] for d in c.work['depallets'] if d['ProductionID']==lot['ProductionID'])
                    product=next((p for p in c.work['products'] if p['ProductFamily']=='NeuFit / NeuStile' and p['ProductCode']==lot['ProductCode']),{})
                    result.append(dict(lot,ProductFamily='NeuFit / NeuStile',ProductionQty=balance['ProductionQty'],
                        DepalletQtyTotal=total,RemainingCuringQty=max(balance['ProductionQty']-total,0),DepalletCount=0,
                        FirstDepalletDate=None,LastDepalletDate=None,RunNo=lot.get('RunningNo',1),ProductName=product.get('ProductName')))
            result.sort(key=lambda item:(item['ProdDate'],item['RunNo'],item['ProductionID']),reverse=True)
            self.set_rows(result)
        elif 'FROM dbo.ProductCodeMaster' in sql:
            self.set_rows(c.work['products'])
        elif 'FROM dbo.ProductionLot' in sql:
            self.set_rows([lot for lot in c.work['lots'] if lot['ProductionID']==args[0]])
        elif 'FROM dbo.RejectReasonMaster' in sql:
            self.set_rows([{k:r[k] for k in ('ReasonCode','ReasonNameTH','SortOrder','IsActive')}
                           for r in sorted(c.work['reasons'],key=lambda r:r['SortOrder']) if r['IsActive']])
        elif 'FROM dbo.vw_DepalletValidation v' in sql:
            selected=[d for d in c.work['depallets'] if d['DepalletDate']==args[0]]
            result=[]
            for d in selected:
                rejects={code:q for (depallet_id,code),q in c.work['rejects'].items() if depallet_id==d['DepalletID']}
                lot=next((item for item in c.work['lots'] if item['ProductionID']==d['ProductionID']),{})
                balance=c.work['balances'].get(d['ProductionID'],{})
                total=sum(item['DepalletQty'] for item in c.work['depallets'] if item['ProductionID']==d['ProductionID'])
                prior_total=sum(item['DepalletQty'] for item in c.work['depallets']
                    if item['ProductionID']==d['ProductionID'] and
                    (item['DepalletDate']<d['DepalletDate'] or
                     (item['DepalletDate']==d['DepalletDate'] and item['RunSequence']<d['RunSequence'])))
                product=next((p for p in c.work['products'] if p['ProductFamily']=='NeuFit / NeuStile' and p['ProductCode']==d['ProductCode']),{})
                result.append(dict(d,**summary(d['DepalletQty'],d['GoodQty'],rejects),
                    ProductionQty=balance.get('ProductionQty',10000),DepalletQtyTotal=total,
                    RemainingCuringQty=max(balance.get('ProductionQty',10000)-total,0),
                    ProductName=product.get('ProductName'),RunNo=lot.get('RunningNo',1),
                    AlreadyDepalletedBeforeRun=prior_total))
            result.sort(key=lambda d:(d['RunSequence'],d['DepalletID']))
            self.set_rows(result)
        elif 'FROM dbo.DepalletReject r' in sql and 'd.DepalletDate=?' in sql:
            result=[]
            for (depallet_id,code),qty in c.work['rejects'].items():
                depallet=next(d for d in c.work['depallets'] if d['DepalletID']==depallet_id)
                if depallet['DepalletDate']==args[0]:
                    reason=next(r for r in c.work['reasons'] if r['ReasonCode']==code)
                    result.append(dict(DepalletID=depallet_id,ReasonCode=code,Qty=qty,
                        ReasonNameTH=reason['ReasonNameTH'],IsActive=reason['IsActive'],SortOrder=reason['SortOrder']))
            self.set_rows(result)
        elif 'FROM dbo.DepalletReject r' in sql:
            result=[]
            for (depallet_id,code),qty in c.work['rejects'].items():
                if depallet_id==args[0]:
                    reason=next(r for r in c.work['reasons'] if r['ReasonCode']==code)
                    result.append(dict(ReasonCode=code,Qty=qty,ReasonNameTH=reason['ReasonNameTH'],
                                       IsActive=reason['IsActive'],SortOrder=reason['SortOrder']))
            self.set_rows(result)
        elif 'FROM dbo.vw_DepalletValidation' in sql:
            if 'AND DepalletID=?' in sql:
                selected=[d for d in c.work['depallets'] if d['ProductionID']==args[0] and d['DepalletID']==args[1]]
            elif 'WHERE DepalletID=?' in sql:
                selected=[d for d in c.work['depallets'] if d['DepalletID']==args[0]]
            elif len(args)==2:
                selected=[d for d in c.work['depallets'] if d['ProductionID']==args[0] and d['DepalletDate']==args[1]]
            else:
                selected=[d for d in c.work['depallets'] if d['ProductionID']==args[0]]
            result=[]
            for d in selected:
                rejects={code:q for (id,code),q in c.work['rejects'].items() if id==d['DepalletID']}
                values=dict(d,**summary(d['DepalletQty'],d['GoodQty'],rejects))
                if c.bad_view: continue
                result.append(values)
            self.set_rows(result)
        elif 'FROM dbo.Depallet WITH (UPDLOCK,HOLDLOCK)' in sql and 'WHERE DepalletID=?' in sql:
            found=next((d for d in c.work['depallets'] if d['DepalletID']==args[0] and
                d['ProductionID']==args[1] and d['DepalletDate']==args[2]),None)
            self.set_rows([dict(DepalletID=found['DepalletID'],DepalletQty=found['DepalletQty'],
                StartDateTime=found.get('StartDateTime'),EndDateTime=found.get('EndDateTime'))] if found else [])
        elif 'SELECT ISNULL(MAX(RunSequence),0)+1' in sql:
            target_date=args[0]
            self.set_rows([{'next':max((d.get('RunSequence',0) for d in c.work['depallets']
                if d['DepalletDate']==target_date),default=0)+1}])
        elif 'SELECT ISNULL(MAX(RunSequence),0) FROM dbo.Depallet' in sql:
            target_date=args[0]
            self.set_rows([{'max':max((d.get('RunSequence',0) for d in c.work['depallets']
                if d['DepalletDate']==target_date),default=0)}])
        elif 'SELECT RunSequence FROM dbo.Depallet WHERE DepalletID=?' in sql:
            found=next(d for d in c.work['depallets'] if d['DepalletID']==args[0])
            self.set_rows([{'RunSequence':found['RunSequence']}])
        elif 'SELECT DepalletID,RunSequence FROM dbo.Depallet WITH' in sql:
            found=sorted([dict(DepalletID=d['DepalletID'],RunSequence=d['RunSequence'])
                for d in c.work['depallets'] if d['DepalletDate']==args[0]],
                key=lambda d:(d['RunSequence'],d['DepalletID']))
            self.set_rows(found)
        elif 'UPDATE dbo.Depallet SET RunSequence=?' in sql:
            row=next(d for d in c.work['depallets'] if d['DepalletID']==args[1] and d['DepalletDate']==args[2])
            row['RunSequence']=args[0]
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
                  'MaterialCode','MaterialName','DepalletQty','GoodQty','Remark','StartDateTime','EndDateTime','RunSequence')
            next_id=max((d['DepalletID'] for d in c.work['depallets']),default=9)+1
            new=dict(zip(keys,args),DepalletID=next_id)
            c.work['depallets'].append(new); self.set_rows([dict(DepalletID=new['DepalletID'])])
        elif 'UPDATE dbo.Depallet SET' in sql:
            row=next(d for d in c.work['depallets'] if d['DepalletID']==args[-2] and d['ProductionID']==args[-1])
            row.update(zip(('Shift','LotNo','DepalletQty','GoodQty','Remark','StartDateTime','EndDateTime'),args[:-2]))
        else: raise AssertionError('Unexpected SQL: '+sql)
        return self
    def fetchone(self): return self.result.pop(0) if self.result else None
    def fetchall(self):
        result=self.result; self.result=[]; return result


class DepalletTests(unittest.TestCase):
    def render_lot(self, conn, lot, **kwargs):
        kwargs.setdefault('production_date',lot['ProdDate'])
        conn.work['lots']=[dict(lot)]
        conn.work['balances'].setdefault(lot['ProductionID'],dict(ProductionID=lot['ProductionID'],
            ProductionQty=10000,DepalletQtyTotal=0,RemainingCuringQty=10000))
        with patch('app.main.get_connection',return_value=conn):
            return depallet_page(request(),production_id=lot['ProductionID'],**kwargs)

    def test_selected_production_2_loads_saved_header_and_all_raw_rejects(self):
        conn=MemoryConnection()
        lot=dict(LOT,ProductionID=2,LotNo='B006690902',ProdDate=date(2026,9,22))
        saved=dict(SAVED,DepalletID=1,ProductionID=2,DepalletDate=lot['ProdDate'],
                   Shift='1',LotNo='SAVED-ALIAS',DepalletQty=1000,GoodQty=600,Remark='Saved remark')
        conn.work['depallets']=[saved,dict(SAVED,ProductionID=99)]
        quantities={code:i for i,code in enumerate(CODES[:-1])}
        conn.work['rejects']={(1,code):qty for code,qty in quantities.items()}
        conn.work['rejects'][(1,'R99')]=999
        conn.work['reasons'][7]['IsActive']=False
        response=self.render_lot(conn,lot)
        self.assertEqual(response.status_code,200)
        entry=response.context['entries']['run:1']
        for key,value in saved.items():
            if key not in {'LotNo','ProductFamily'}: self.assertEqual(entry['depallet'][key],value)
        self.assertEqual(entry['depallet']['LotNo'],'B006690902')
        self.assertEqual(entry['reject_values'],{code:qty for code,qty in quantities.items() if code!='R08'})
        self.assertEqual(entry['depallet']['R99'],124)
        text=response.body.decode()
        self.assertIn('data-lot-no="B006690902"',text)
        self.assertIn('id="depallet-reasons-data"',text)
        self.assertIn('data-selected="true"',text)
        self.assertIn('ProductionQty',text)
        self.assertEqual(conn.commits,0)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_new_selected_lot_uses_shared_date_without_second_date_selector(self):
        conn=MemoryConnection()
        response=self.render_lot(conn,LOT)
        self.assertEqual(response.context['entries'][str(LOT['ProductionID'])]['depallet']['DepalletDate'],LOT['ProdDate'])
        self.assertEqual(response.context['entries'][str(LOT['ProductionID'])]['depallet']['LotNo'],LOT['LotNo'])
        text=response.body.decode()
        self.assertEqual(len(re.findall(r'<input[^>]*type="date"',text)),1)
        tag=re.search(r'<input id="depallet-date"[^>]*>',text)[0]
        self.assertIn('type="hidden"',tag)
        self.assertIn('value="2026-09-21"',tag)
        self.assertEqual(conn.work['depallets'],[])
        self.assertEqual(conn.commits,0)

    def test_multiple_dates_remain_date_keyed_and_existing_endpoint_works(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'].append(dict(SAVED,DepalletID=11,DepalletDate=date(2026,9,24),LotNo='SECOND'))
        # The legacy reader still requires a date for ambiguous records.
        context=read_context(conn.cursor(),LOT)
        self.assertEqual(context['depallet_dates'],[date(2026,9,23),date(2026,9,24)])
        lot=dict(LOT,ProdDate=date(2026,9,24))
        response=self.render_lot(conn,lot)
        self.assertEqual(response.context['runs'][0]['DepalletID'],11)
        self.assertEqual(response.context['runs'][0]['LotNo'],LOT['LotNo'])
        self.assertNotIn(b'id="depallet-record"',response.body)
        with patch('app.main.get_connection',return_value=conn):
            response=load_depallet(7,date(2026,9,23))
        self.assertEqual(json.loads(response.body)['depallet']['LotNo'],SAVED['LotNo'])
        self.assertEqual(conn.commits,0)
        self.assertTrue(all(sql.lstrip().startswith('SELECT') for sql,_ in conn.sql))

    def test_explicit_depalet_id_loads_one_run_when_same_lot_has_multiple_runs(self):
        conn=MemoryConnection(existing=True)
        second=dict(SAVED,DepalletID=11,DepalletDate=date(2026,9,23),DepalletQty=80,GoodQty=70)
        conn.work['depallets'].append(second)
        conn.work['rejects'][(11,'R02')]=6
        with self.assertRaisesRegex(ValueError,'Select a DepalletID'):
            read_context(conn.cursor(),LOT,date(2026,9,23))
        context=read_context(conn.cursor(),LOT,date(2026,9,23),depallet_id=11)
        self.assertEqual(context['depallet']['DepalletID'],11)
        self.assertEqual(context['reject_values'],{'R02':6})
        with patch('app.main.get_connection',return_value=conn):
            response=load_depallet(7,date(2026,9,23),depallet_id=11)
        self.assertEqual(json.loads(response.body)['depallet']['DepalletID'],11)

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

    def test_curing_lot_reader_uses_view_production_id_and_date_run_order(self):
        conn=MemoryConnection()
        newer=dict(LOT,ProductionID=8,ProdDate=date(2026,9,23),RunningNo=1,LotNo='NEWER')
        same_day_later=dict(LOT,ProductionID=9,ProdDate=date(2026,9,23),RunningNo=4,LotNo='RUN4')
        conn.work['lots']=[dict(LOT),newer,same_day_later]
        for item in conn.work['lots']:
            conn.work['balances'][item['ProductionID']]=dict(ProductionID=item['ProductionID'],
                ProductionQty=0 if item['ProductionID']==8 else 500,DepalletQtyTotal=0,RemainingCuringQty=0 if item['ProductionID']==8 else 500)
        found=read_curing_lots(conn.cursor())
        self.assertEqual([item['ProductionID'] for item in found],[9,8,7])
        sql=conn.sql[0][0]
        self.assertIn('FROM dbo.vw_DepalletCuringBalance b',sql)
        self.assertIn('p.ProductionID=b.ProductionID',sql)
        self.assertIn('ORDER BY b.ProdDate DESC,p.RunningNo DESC',sql)
        self.assertNotIn('RemainingCuringQty>0',sql)
        self.assertEqual(found[1]['ProductionQty'],0)

    def test_production_clock_conversion_uses_reporting_date_and_day_start(self):
        selected=date(2026,9,26)
        cutoff=time(8)
        self.assertEqual(production_clock_datetime(selected,'01:00',cutoff),datetime(2026,9,27,1))
        self.assertEqual(production_clock_datetime(selected,'20:00',cutoff),datetime(2026,9,26,20))
        self.assertEqual(resolve_run_times(selected,'01:00','03:00',cutoff),
                         (datetime(2026,9,27,1),datetime(2026,9,27,3)))
        self.assertEqual(resolve_run_times(selected,'20:00','23:00',cutoff),
                         (datetime(2026,9,26,20),datetime(2026,9,26,23)))

    def test_historical_day_start_rule_is_selected_by_effective_date(self):
        conn=MemoryConnection()
        conn.work['day_rules']=[
            dict(RuleID=1,EffectiveFromDate=date(2026,1,1),DayStartTime=time(8)),
            dict(RuleID=2,EffectiveFromDate=date(2026,10,1),DayStartTime=time(8,30)),
            dict(RuleID=3,EffectiveFromDate=date(2027,1,15),DayStartTime=time(7,30)),
        ]
        cursor=conn.cursor()
        self.assertEqual(read_day_start_time(cursor,date(2026,9,26)),time(8))
        self.assertEqual(read_day_start_time(cursor,date(2026,10,5)),time(8,30))
        self.assertEqual(read_day_start_time(cursor,date(2027,1,20)),time(7,30))
        self.assertIn('EffectiveFromDate<=?',conn.sql[0][0])
        self.assertIn('ORDER BY EffectiveFromDate DESC,RuleID DESC',conn.sql[0][0])

    def test_clock_validation_rejects_ambiguous_or_out_of_order_pair(self):
        for start,end in (('01:00',''),('24:00','25:00'),('01:00','20:00')):
              with self.subTest(start=start,end=end), self.assertRaises(ValueError):
                resolve_run_times(date(2026,9,26),start,end,time(8))

    def test_same_lot_runs_keep_depallet_id_scoped_rejects_and_allow_null_times(self):
        conn=MemoryConnection()
        first=dict(SAVED,DepalletID=31,DepalletDate=date(2026,9,24),DepalletQty=60,GoodQty=55)
        second=dict(SAVED,DepalletID=33,DepalletDate=date(2026,9,24),DepalletQty=40,GoodQty=35)
        middle=dict(SAVED,DepalletID=32,ProductionID=8,DepalletDate=date(2026,9,24),DepalletQty=20,GoodQty=19)
        conn.work['depallets']=[first,middle,second]
        conn.work['lots'].append(dict(LOT,ProductionID=8,LotNo='OTHER'))
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=100,DepalletQtyTotal=100,RemainingCuringQty=0)
        conn.work['balances'][8]=dict(ProductionID=8,ProductionQty=20,DepalletQtyTotal=20,RemainingCuringQty=0)
        conn.work['rejects']={(31,'R01'):3,(33,'R02'):4,(32,'R01'):2}
        entries,runs,reasons,totals,cutoff=read_daily_work(conn.cursor(),date(2026,9,24),conn.work['lots'])
        self.assertEqual([run['DepalletID'] for run in runs if run['ProductionID']==7],[31,33])
        self.assertEqual(entries['run:31']['reject_values'],{'R01':3})
        self.assertEqual(entries['run:33']['reject_values'],{'R02':4})
        self.assertEqual(totals['R01'],5)
        self.assertEqual(totals['R02'],4)
        self.assertEqual(entries['run:31']['depallet']['StartDateTime'],None)
        self.assertEqual(entries['run:31']['depallet']['EndDateTime'],None)
        self.assertEqual(next(run for run in runs if run['DepalletID']==31)['StartClock'],'')
        self.assertEqual(cutoff,time(8))

    def test_historical_remaining_and_new_over_depalet_are_server_rejected(self):
        conn=MemoryConnection()
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=500,DepalletQtyTotal=200,RemainingCuringQty=300)
        conn.work['depallets']=[dict(SAVED,DepalletID=20,DepalletDate=date(2026,9,20),DepalletQty=200)]
        with self.assertRaisesRegex(ValueError,'Remaining Curing Qty 300'):
            save_depallet(conn,7,dict(RAW,DepalletQty='301'))
        self.assertEqual(conn.db['depallets'],[])
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.rollbacks,1)

    def test_editing_saved_record_adds_its_own_quantity_back_to_authoritative_remaining(self):
        conn=MemoryConnection(existing=True)
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=500,DepalletQtyTotal=300,RemainingCuringQty=200)
        conn.work['depallets'][0]['DepalletQty']=100
        conn.work['depallets'].append(dict(SAVED,DepalletID=20,DepalletDate=date(2026,9,20),DepalletQty=200))
        result=save_depallet(conn,7,dict(EDIT_RAW,DepalletQty='300'))
        self.assertEqual(result['DepalletQty'],300)
        self.assertEqual(sum(row['DepalletQty'] for row in conn.db['depallets']),500)
        with self.assertRaisesRegex(ValueError,'Remaining Curing Qty 300'):
            save_depallet(conn,7,dict(EDIT_RAW,DepalletQty='301'))

    def test_legacy_over_depalet_record_can_remain_but_cannot_increase(self):
        conn=MemoryConnection(existing=True)
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=500,DepalletQtyTotal=600,RemainingCuringQty=0)
        conn.work['depallets'][0]['DepalletQty']=400
        conn.work['depallets'].append(dict(SAVED,DepalletID=20,DepalletDate=date(2026,9,20),DepalletQty=200))
        save_depallet(conn,7,dict(EDIT_RAW,DepalletQty='400'))
        self.assertEqual(sum(row['DepalletQty'] for row in conn.db['depallets']),600)
        with self.assertRaisesRegex(ValueError,'Remaining Curing Qty 400'):
            save_depallet(conn,7,dict(EDIT_RAW,DepalletQty='401'))

    def test_batch_save_is_atomic_and_rejects_duplicate_production_ids(self):
        conn=MemoryConnection()
        second=dict(LOT,ProductionID=8,LotNo='SECOND',RunningNo=2)
        conn.work['lots'].append(second)
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=500,DepalletQtyTotal=0,RemainingCuringQty=500)
        conn.work['balances'][8]=dict(ProductionID=8,ProductionQty=700,DepalletQtyTotal=0,RemainingCuringQty=700)
        items=[dict(ProductionID=7,Shift='1',Start='20:00',End='21:00',DepalletQty='300',GoodQty='280',Remark='',rejects={'R01':'2'}),
               dict(ProductionID=8,Shift='2',Start='21:00',End='22:00',DepalletQty='600',GoodQty='590',Remark='',rejects={'R02':'1'}),
               dict(ProductionID=7,Shift='2',Start='22:00',End='23:00',DepalletQty='200',GoodQty='190',Remark='',rejects={'R03':'1'})]
        saved=save_depallet_batch(conn,'2026-09-23',items)
        self.assertEqual(len(saved),3)
        self.assertEqual([row['ProductionID'] for row in conn.db['depallets']],[7,8,7])
        self.assertEqual([row['Shift'] for row in conn.db['depallets'] if row['ProductionID']==7],['1','2'])
        self.assertEqual(len({row['DepalletID'] for row in conn.db['depallets']}),3)
        self.assertEqual([row['RunSequence'] for row in conn.db['depallets']],[1,2,3])
        self.assertEqual(conn.commits,1)
        before=copy.deepcopy(conn.db)
        with self.assertRaisesRegex(ValueError,'run can only be submitted once'):
            save_depallet_batch(conn,'2026-09-23',[dict(items[0],DepalletID=saved[0]['DepalletID']),
                dict(items[0],DepalletID=saved[0]['DepalletID'])])
        self.assertEqual(conn.db,before)

    def test_new_run_accepts_blank_times_and_appends_date_wide_sequence(self):
        conn=MemoryConnection()
        conn.work['depallets']=[dict(SAVED,DepalletID=20,ProductionID=8,
            DepalletDate=date(2026,9,23),RunSequence=4)]
        result=save_depallet(conn,7,dict(RAW,Start='',End=''))
        self.assertEqual(result['RunSequence'],5)
        self.assertIsNone(result['StartDateTime'])
        self.assertIsNone(result['EndDateTime'])
        self.assertEqual(conn.db['depallets'][-1]['RunSequence'],5)

    def test_batch_save_route_parses_depallet_date_and_rows(self):
        conn=MemoryConnection()
        payload=json.dumps({'depallet_date':'2026-09-26','rows':[
            {'ProductionID':7,'Shift':'1','Start':'01:00','End':'03:00','DepalletQty':'100','GoodQty':'95','Remark':'','rejects':{'R01':'2'}}]})
        async def receive(): return {'type':'http.request','body':payload.encode(),'more_body':False}
        request_obj=Request({'type':'http','method':'POST','path':'/depallet/save',
            'headers':[(b'content-type',b'application/json')]},receive)
        with patch('app.main.get_connection',return_value=conn):
            response=asyncio.run(save_depallet_batch_route(request_obj))
        self.assertEqual(response.status_code,200)
        body=json.loads(response.body)
        self.assertEqual(body['rows'][0]['DepalletDate'].split('T')[0],'2026-09-26')
        self.assertEqual(body['rows'][0]['StartDateTime'],'2026-09-27T01:00:00')
        self.assertEqual(body['rows'][0]['EndDateTime'],'2026-09-27T03:00:00')
        self.assertEqual(conn.db['depallets'][0]['ProductionID'],7)
        self.assertEqual(conn.commits,1)

    def test_daily_work_reject_totals_are_depallet_date_scoped_and_lot_isolated(self):
        conn=MemoryConnection()
        second=dict(LOT,ProductionID=8,LotNo='SECOND')
        first=dict(SAVED,DepalletID=10,ProductionID=7,DepalletDate=date(2026,9,24),DepalletQty=100,GoodQty=90)
        other=dict(SAVED,DepalletID=11,ProductionID=8,DepalletDate=date(2026,9,24),DepalletQty=80,GoodQty=70)
        historical=dict(SAVED,DepalletID=12,ProductionID=8,DepalletDate=date(2026,9,21),DepalletQty=20,GoodQty=10)
        conn.work['depallets']=[first,other,historical]
        conn.work['reasons'][7]['IsActive']=False
        conn.work['rejects']={(10,'R01'):5,(10,'R08'):6,(10,'R99'):5,
            (11,'R01'):3,(11,'R02'):4,(12,'R01'):50}
        entries,runs,reasons,totals,cutoff=read_daily_work(conn.cursor(),date(2026,9,24),[LOT,second])
        self.assertEqual(totals['R01'],8)
        self.assertEqual(totals['R02'],4)
        self.assertEqual(totals['R08'],6)
        self.assertEqual(totals['R99'],5)
        self.assertEqual(entries['run:10']['reject_values'],{'R01':5})
        self.assertEqual(entries['run:10']['inactive_rejects'][0]['ReasonCode'],'R08')
        self.assertEqual(entries['run:11']['reject_values'],{'R01':3,'R02':4})
        self.assertNotIn(50,entries['run:11']['reject_values'].values())
        self.assertEqual([run['DepalletID'] for run in runs],[10,11])
        self.assertEqual(cutoff,time(8))
        self.assertTrue(any('DepalletDate=?' in sql for sql,_ in conn.sql))

    def test_run_sequence_migration_has_deterministic_date_scoped_backfill_and_unique_rule(self):
        migration=Path('sql/008_depallet_run_sequence.sql').read_text(encoding='utf-8')
        self.assertIn('PARTITION BY DepalletDate ORDER BY DepalletID',migration)
        self.assertIn('UX_Depallet_DepalletDate_RunSequence',migration)
        self.assertIn('CHECK (RunSequence > 0)',migration)
        self.assertIn("COL_LENGTH('dbo.Depallet', 'RunSequence') IS NULL",migration)
        self.assertNotIn('UPDATE dbo.Depallet SET DepalletID',migration)
        self.assertNotIn('UPDATE dbo.Depallet SET DepalletQty',migration)

    def test_sequence_reorder_swaps_adjacent_runs_without_changing_run_or_reject_identity(self):
        conn=MemoryConnection()
        runs=[
            dict(SAVED,DepalletID=10,ProductionID=7,RunSequence=1,
                 StartDateTime=datetime(2026,9,23,20),EndDateTime=datetime(2026,9,23,21)),
            dict(SAVED,DepalletID=11,ProductionID=8,RunSequence=2),
            dict(SAVED,DepalletID=12,ProductionID=7,RunSequence=3,
                 StartDateTime=datetime(2026,9,23,10),EndDateTime=datetime(2026,9,23,11)),
        ]
        conn.work['depallets']=copy.deepcopy(runs)
        conn.work['rejects']={(10,'R01'):5,(12,'R02'):9}
        result=reorder_depallet_run(conn,date(2026,9,23),12,'up')
        self.assertTrue(result['moved'])
        self.assertEqual(result['RunSequence'],2)
        self.assertEqual([(run['DepalletID'],run['RunSequence']) for run in
            sorted(conn.db['depallets'],key=lambda row:row['RunSequence'])],[(10,1),(12,2),(11,3)])
        self.assertEqual(conn.db['rejects'],{(10,'R01'):5,(12,'R02'):9})
        self.assertEqual({run['DepalletID'] for run in conn.db['depallets']},{10,11,12})
        self.assertEqual(sum(run['DepalletQty'] for run in conn.db['depallets']),sum(row['DepalletQty'] for row in runs))
        self.assertEqual(next(row for row in conn.db['depallets'] if row['DepalletID']==12)['StartDateTime'],datetime(2026,9,23,10))

    def test_reorder_http_route_uses_depallet_id_and_persists_direction(self):
        conn=MemoryConnection()
        conn.work['depallets']=[dict(SAVED,DepalletID=10,RunSequence=1),dict(SAVED,DepalletID=11,RunSequence=2)]
        payload=json.dumps({'production_date':'2026-09-23','direction':'up'})
        async def receive(): return {'type':'http.request','body':payload.encode(),'more_body':False}
        req=Request({'type':'http','method':'POST','path':'/depallet/11/move',
            'headers':[(b'content-type',b'application/json')]},receive)
        with patch('app.main.get_connection',return_value=conn):
            response=asyncio.run(reorder_depallet_route(11,req))
        self.assertEqual(response.status_code,200)
        self.assertTrue(json.loads(response.body)['moved'])
        self.assertEqual([(row['DepalletID'],row['RunSequence']) for row in
            sorted(conn.db['depallets'],key=lambda row:row['RunSequence'])],[(11,1),(10,2)])

    def test_read_daily_order_uses_run_sequence_not_shift_or_times(self):
        conn=MemoryConnection()
        conn.work['depallets']=[
            dict(SAVED,DepalletID=40,ProductionID=7,DepalletDate=date(2026,9,24),RunSequence=1,
                Shift='2',StartDateTime=None,EndDateTime=None),
            dict(SAVED,DepalletID=41,ProductionID=8,DepalletDate=date(2026,9,24),RunSequence=2,
                Shift='1',StartDateTime=datetime(2026,9,24,14),EndDateTime=datetime(2026,9,24,15)),
            dict(SAVED,DepalletID=42,ProductionID=7,DepalletDate=date(2026,9,24),RunSequence=3,
                Shift='1',StartDateTime=datetime(2026,9,24,10),EndDateTime=datetime(2026,9,24,11)),
        ]
        conn.work['lots'].append(dict(LOT,ProductionID=8,LotNo='B'))
        entries,runs,_,_,_=read_daily_work(conn.cursor(),date(2026,9,24),conn.work['lots'])
        self.assertEqual([run['DepalletID'] for run in runs],[40,41,42])
        self.assertEqual([run['StartDateTime'] for run in runs],[None,datetime(2026,9,24,14),datetime(2026,9,24,10)])

    def test_reorder_boundaries_and_failure_roll_back_without_duplicate_sequences(self):
        conn=MemoryConnection()
        conn.work['depallets']=[dict(SAVED,DepalletID=10,RunSequence=1),
                                dict(SAVED,DepalletID=11,RunSequence=2)]
        self.assertFalse(reorder_depallet_run(conn,date(2026,9,23),10,'up')['moved'])
        self.assertFalse(reorder_depallet_run(conn,date(2026,9,23),11,'down')['moved'])
        before=copy.deepcopy(conn.db)
        conn.fail='UPDATE dbo.Depallet SET RunSequence=?'
        with self.assertRaises(RuntimeError): reorder_depallet_run(conn,date(2026,9,23),11,'up')
        self.assertEqual(conn.db,before)
        self.assertEqual(conn.work,before)
        self.assertEqual(len({row['RunSequence'] for row in conn.db['depallets']}),2)

    def test_a_b_a_c_a_balance_uses_only_earlier_same_production_sequences(self):
        conn=MemoryConnection()
        ids=[(10,7,'A',1,600),(11,8,'B',2,300),(12,7,'A',3,200),
             (13,9,'C',4,400),(14,7,'A',5,250)]
        conn.work['depallets']=[dict(SAVED,DepalletID=run_id,ProductionID=production_id,
            LotNo=lot,DepalletDate=date(2026,9,23),RunSequence=sequence,DepalletQty=qty,GoodQty=qty)
            for run_id,production_id,lot,sequence,qty in ids]
        conn.work['lots']=[dict(LOT,ProductionID=production_id,LotNo=lot) for production_id,lot in
            ((7,'A'),(8,'B'),(9,'C'))]
        conn.work['balances']={7:dict(ProductionID=7,ProductionQty=1050,DepalletQtyTotal=1050,RemainingCuringQty=0),
            8:dict(ProductionID=8,ProductionQty=300,DepalletQtyTotal=300,RemainingCuringQty=0),
            9:dict(ProductionID=9,ProductionQty=400,DepalletQtyTotal=400,RemainingCuringQty=0)}
        entries,runs,reasons,totals,cutoff=read_daily_work(conn.cursor(),date(2026,9,23),conn.work['lots'])
        observed=[(run['ProductionID'],run['DepalletID'],run['AlreadyDepalletedBeforeRun'],run['RemainingCuringBeforeRun']) for run in runs]
        self.assertEqual(observed,[(7,10,0,1050),(8,11,0,300),(7,12,600,450),(9,13,0,400),(7,14,800,250)])

    def test_edit_earlier_run_changes_only_its_quantity_then_recalculates_later_balances(self):
        conn=MemoryConnection()
        conn.work['depallets']=[
            dict(SAVED,DepalletID=10,ProductionID=7,DepalletDate=date(2026,9,23),RunSequence=1,DepalletQty=600,GoodQty=600),
            dict(SAVED,DepalletID=12,ProductionID=7,DepalletDate=date(2026,9,23),RunSequence=3,DepalletQty=200,GoodQty=200),
            dict(SAVED,DepalletID=14,ProductionID=7,DepalletDate=date(2026,9,23),RunSequence=5,DepalletQty=250,GoodQty=250)]
        conn.work['balances'][7]=dict(ProductionID=7,ProductionQty=1050,DepalletQtyTotal=1050,RemainingCuringQty=0)
        conn.work['rejects']={(10,'R01'):5,(12,'R02'):6,(14,'R03'):7}
        edit=dict(DepalletID=10,DepalletDate='2026-09-23',Shift='2',LotNo='A',Start='',End='',
            DepalletQty='500',GoodQty='500',Remark='changed',rejects={'R01':'5'})
        save_depallet(conn,7,edit)
        self.assertEqual([(r['DepalletID'],r['DepalletQty']) for r in conn.db['depallets']],[(10,500),(12,200),(14,250)])
        self.assertEqual(conn.db['rejects'],{(10,'R01'):5,(12,'R02'):6,(14,'R03'):7})
        read_lots=[dict(LOT,ProductionID=7,LotNo='A')]
        entries,runs,_,_,_=read_daily_work(conn.cursor(),date(2026,9,23),read_lots)
        self.assertEqual([(run['DepalletID'],run['AlreadyDepalletedBeforeRun'],run['RemainingCuringBeforeRun'])
            for run in runs],[(10,0,1050),(12,500,550),(14,700,350)])

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
        self.assertEqual(conn.db['depallets'][0]['LotNo'],LOT['LotNo'])
        self.assertEqual(conn.db['depallets'][0]['ProductionID'],7)
        self.assertEqual(conn.db['lots'],before)
        self.assertFalse(any(('UPDATE dbo.Production' in sql or 'DepalletPISLog' in sql) for sql,_ in conn.sql))

    def test_repeat_create_adds_a_distinct_run_instead_of_upserting(self):
        conn=MemoryConnection()
        save_depallet(conn,7,RAW)
        save_depallet(conn,7,dict(RAW,Remark='second run'))
        self.assertEqual(len(conn.db['depallets']),2)
        self.assertEqual(len({row['DepalletID'] for row in conn.db['depallets']}),2)
        self.assertEqual(conn.db['depallets'][1]['Remark'],'second run')

    def test_blank_zero_removes_obsolete_reject_rows(self):
        conn=MemoryConnection(existing=True)
        save_depallet(conn,7,dict(EDIT_RAW,GoodQty='100',rejects={'R01':'','R99':'0'}))
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
                       {'rejects':{'R00':'10'}},{'Shift':''},
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
                    result=save_depallet(conn,7,dict(raw,DepalletID=10) if existing else raw)
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
            result=save_depallet(conn,7,dict(EDIT_RAW,DepalletQty=str(depallet),GoodQty=str(good),rejects={'R01':str(classified)}))
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
                result=save_depallet(conn,7,dict(EDIT_RAW,DepalletQty='3140',GoodQty='2980',
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
            raw=dict(EDIT_RAW,GoodQty='100',rejects={}) if failure.startswith('DELETE') else (
                dict(EDIT_RAW) if conn.work['depallets'] else dict(RAW))
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
        added=save_depallet(conn,7,RAW)
        self.assertNotIn(added['DepalletID'],{10,11})
        self.assertEqual(len(conn.db['depallets']),3)

    def test_inactive_saved_rejects_are_preserved_and_counted(self):
        conn=MemoryConnection(existing=True)
        conn.work['reasons'][0]['IsActive']=False
        context=read_context(conn.cursor(),LOT,date(2026,9,23))
        self.assertEqual(context['inactive_rejects'][0]['Qty'],7)
        save_depallet(conn,7,dict(EDIT_RAW,rejects={}))
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
        body=urlencode(dict(depallet_date='2026-09-23',shift='2',lot_no='OTHER',start='20:00',end='21:00',
                    depallet_qty='1',good_qty='0',reject_R99='99999')).encode()
        async def receive(): return {'type':'http.request','body':body,'more_body':False}
        req=Request({'type':'http','method':'POST','path':'/lots/7/depallet','headers':[(b'content-type',b'application/x-www-form-urlencoded')]},receive)
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn):
            response=asyncio.run(save_depallet_route(req,7))
        self.assertEqual(response.status_code,200)
        self.assertEqual(conn.db['rejects'],{(10,'R99'):1})

    def test_production_page_has_no_depallet_input_or_reads(self):
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[LOT]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_production_data',return_value={}),patch('app.main.read_depallet_context') as reader:
            response=production_page(request(),production_id=7,production_date=DAY)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'SAVE PRODUCTION',response.body)
        self.assertNotIn(b'id="depallet-input"',response.body)
        self.assertNotIn(b'data-reject-code',response.body)
        reader.assert_not_called()

    def test_depallet_grid_and_dynamic_grouped_detail(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'][0]['DepalletDate']=LOT['ProdDate']
        response=self.render_lot(conn,LOT)
        text=response.body.decode()
        grid=re.search(r'<table[^>]*id="depallet-lots".*?</table>',text,re.S)[0]
        self.assertEqual(re.findall(r'<th scope="col">(.*?)</th>',grid),
                         ['Select','Move','Order','Lot No.','Product','Shift','Start','End','Produced Qty','Already Depalleted','Remaining Curing','Depallet Qty','Good Qty','Remark'])
        self.assertIn('data-selected="true"',grid)
        self.assertIn('data-production-qty="10000"',grid)
        self.assertIn('Qty/Day',text)
        self.assertIn('data-daily-total',text)
        self.assertIn('data-reject-code',text)
        self.assertIn('rejects.replaceChildren()',text)

    def test_saved_run_move_buttons_respect_sequence_boundaries(self):
        conn=MemoryConnection()
        conn.work['depallets']=[dict(SAVED,DepalletID=20,RunSequence=1,DepalletDate=LOT['ProdDate']),
            dict(SAVED,DepalletID=21,RunSequence=2,LotNo='SECOND',DepalletDate=LOT['ProdDate'])]
        response=self.render_lot(conn,LOT)
        grid=re.search(r'<table[^>]*id="depallet-lots".*?</table>',response.body.decode(),re.S)[0]
        rows=re.findall(r'<tr data-run-key=.*?</tr>',grid,re.S)
        self.assertEqual(len(rows),2)
        self.assertIn('SEQ 1 / RUN 20',rows[0])
        self.assertIn('SEQ 2 / RUN 21',rows[1])
        self.assertIn('data-move="up"',rows[0])
        self.assertIn('data-move="down"',rows[0])
        self.assertRegex(rows[0],r'data-move="up"[^>]*disabled')
        self.assertRegex(rows[1],r'data-move="down"[^>]*disabled')

    def test_compact_reject_groups_preserve_vertical_code_order_and_dynamic_names(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'][0]['DepalletDate']=LOT['ProdDate']
        conn.work['reasons'].reverse()
        for reason in conn.work['reasons']:
            reason['SortOrder']=100-int(reason['ReasonCode'][1:])
            reason['ReasonNameTH']='Dynamic long reason '+reason['ReasonCode']+' '+('wrapped text '*12)
            if reason['ReasonCode']=='R01': reason['IsActive']=False
        text=self.render_lot(conn,LOT).body.decode()
        self.assertIn("for (const text of ['Code','Reject Reason','Qty','Qty/Day'])",text)
        self.assertIn('data-daily-total',text)
        for rule in ('#depallet-detail{max-width:900px}', '.reject-code-column{width:38px}',
                     '.reject-reason-column{width:auto}', '.reject-qty-column{width:50px}',
                     '.reject-day-column{width:58px}', '-webkit-line-clamp:2', 'overflow-wrap:anywhere'):
            self.assertIn(rule,text)

    def test_depallet_filters_date_selects_lot_and_loads_correct_detail(self):
        conn=MemoryConnection(existing=True)
        lots=[dict(LOT,ProdDate=date(2026,9,23)),dict(LOT,ProductionID=8,LotNo='OTHER',ProdDate=date(2026,9,23)),
              dict(LOT,ProductionID=9,LotNo='WRONG-DATE',ProdDate=date(2026,9,22))]
        conn.work['lots']=lots
        for item in lots:
            conn.work['balances'][item['ProductionID']]=dict(ProductionID=item['ProductionID'],ProductionQty=1000,
                DepalletQtyTotal=0,RemainingCuringQty=1000)
        with patch('app.main.get_connection',return_value=conn):
            response=depallet_page(request(),production_date=date(2026,9,23),production_id=8)
        self.assertEqual(response.status_code,200)
        self.assertEqual([lot['ProductionID'] for lot in response.context['lots']],[8,7,9])
        self.assertEqual(response.context['current']['ProductionID'],8)
        self.assertIn(b'WRONG-DATE',response.body)
        self.assertIn(b'action="/depallet/save"',response.body)
        self.assertIn(b'id="depallet-production-lot"',response.body)
        self.assertEqual(conn.commits,0)

    def test_selected_lot_save_reload_and_repeat_update_on_depallet_page(self):
        conn=MemoryConnection()
        lot=dict(LOT,ProdDate=date(2026,9,23))
        for qty in (7,15):
            payload=urlencode(dict(depallet_date='2026-09-23',shift='2',lot_no=lot['LotNo'],start='20:00',end='21:00',
                                   depallet_qty='100',good_qty='90',remark='saved',
                                   reject_R01=str(qty),reject_R99='999')).encode()
            async def receive(): return {'type':'http.request','body':payload,'more_body':False}
            req=Request({'type':'http','method':'POST','path':'/lots/7/depallet',
                         'headers':[(b'content-type',b'application/x-www-form-urlencoded')]},receive)
            with patch('app.main.get_connection',return_value=conn):
                saved=asyncio.run(save_depallet_route(req,7))
            self.assertEqual(saved.status_code,200)
            page=self.render_lot(conn,lot)
            self.assertEqual(page.context['active_tab'],'depallet')
            self.assertEqual(page.context['production_date'],date(2026,9,23))
            self.assertEqual(page.context['current']['ProductionID'],7)
            run_key='run:'+str(max(row['DepalletID'] for row in page.context['runs']))
            entry=page.context['entries'][run_key]
            self.assertEqual(entry['reject_values']['R01'],qty)
            self.assertEqual(entry['depallet']['R99'],max(10-qty,0))
            self.assertEqual(entry['depallet']['PhysicalRejectQty'],10)
        self.assertEqual(len(conn.db['depallets']),2)
        self.assertEqual(conn.commits,2)
        self.assertNotIn((11,'R99'),conn.db['rejects'])
        self.assertFalse(any('UPDATE dbo.ProductionLot' in sql for sql,_ in conn.sql))

    def test_depallet_load_errors_do_not_render_editable_grid(self):
        conn=MemoryConnection(existing=True)
        conn.work['depallets'].append(dict(SAVED,DepalletID=11))
        response=self.render_lot(conn,dict(LOT,ProdDate=SAVED['DepalletDate']))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['runs']),2)
        self.assertIn(b'id="depallet-input"',response.body)
        with patch('app.main.get_connection',side_effect=RuntimeError('private')):
            response=depallet_page(request())
        self.assertEqual(response.status_code,503)
        self.assertNotIn(b'private',response.body)

    def test_new_load_failure_does_not_break_production_page(self):
        conn=MemoryConnection()
        with patch('app.main.get_connection',return_value=conn),patch('app.main.read_lots',return_value=[LOT]),patch('app.main.read_plans',return_value=[PLAN]),patch('app.main.read_production_data',return_value={}),patch('app.main.read_depallet_context',side_effect=RuntimeError('unavailable')):
            response=production_page(request(),production_id=7)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'SAVE PRODUCTION',response.body)
        self.assertNotIn(b'id="depallet-input"',response.body)
