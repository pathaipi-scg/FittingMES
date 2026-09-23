import asyncio
import copy
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from app.usage import read_usage_context, save_usage, validate_quantities
from test_prod_api import get_page
from test_production import LOT

DAY=date(2026,9,21)
MASTER=dict(MaterialUsageCode='dynamic',MaterialNameTH='',MaterialNameEN='Dynamic Material',Unit='kg',SortOrder=1)
CALC=dict(MaterialUsageCode='dynamic',Shift='1',RawQty=Decimal('12.345'),QtyPer1000Counter=Decimal('1.234'),QtyPer1000Curing=None,SourceType='MANUAL')


class UsageConnection:
    def __init__(self):
        self.sql=[]; self.commits=0; self.rollbacks=0; self.description=[]; self.results=[]
        self.headers=[]; self.details=[]; self.fail=None
        self.materials=[dict(MASTER)]; self.calculated=[dict(CALC)]
    def cursor(self): return self
    def close(self): pass
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1
    def execute(self,sql,*args):
        self.sql.append((sql,args))
        if self.fail and self.fail in sql: raise RuntimeError('failure')
        result=[]
        if 'sp_getapplock' in sql: result=[{'result':0}]
        elif 'FROM dbo.MaterialUsageMaster' in sql: result=self.materials
        elif 'FROM dbo.P_ActivePlan' in sql:
            result=[]
        elif 'FROM dbo.ProductionLot' in sql:
            result=[dict(LOT,ProductionStartTime=None,ProductionEndTime=None,CounterQty=100,CuringQty=90,Remark='')]
        elif 'FROM dbo.vw_DailyProductionQty' in sql:
            result=[dict(Shift='1',CounterQty=10000,CuringQty=0,LotCount=2)]
        elif 'FROM dbo.vw_DailyMaterialUsageCalc' in sql: result=self.calculated
        elif 'FROM dbo.vw_DailyMaterialUsageTotalCalc' in sql:
            result=[dict(CALC,RawQty=Decimal('20'),QtyPer1000Counter=Decimal('0.987'),QtyPer1000Curing=Decimal('2'))]
        elif 'SELECT MaterialUsageID FROM dbo.DailyMaterialUsage' in sql: result=self.headers
        elif 'INSERT INTO dbo.DailyMaterialUsage (' in sql: result=[{'MaterialUsageID':8}]
        elif 'SELECT MaterialUsageCode,SourceType' in sql: result=self.details
        elif sql.lstrip().startswith(('INSERT','UPDATE','DELETE')): pass
        else: raise AssertionError(sql)
        self.description=[(key,) for key in result[0]] if result else []
        self.results=[tuple(row.values()) for row in result]
        return self
    def fetchall(self): return self.results
    def fetchone(self): return self.results[0] if self.results else None


class UsageTests(unittest.TestCase):
    def test_read_uses_authoritative_views_and_dynamic_materials(self):
        conn=UsageConnection()
        context=read_usage_context(conn,DAY)
        self.assertEqual([s['shift'] for s in context['shifts']],['1','2'])
        material=context['shifts'][0]['materials'][0]
        self.assertEqual(material['RawQty'],Decimal('12.345'))
        self.assertEqual(material['QtyPer1000Counter'],Decimal('1.234'))
        self.assertIsNone(material['QtyPer1000Curing'])
        self.assertIsNone(context['shifts'][1]['materials'][0]['RawQty'])
        self.assertEqual(context['daily'][0]['QtyPer1000Counter'],Decimal('0.987'))
        self.assertEqual(conn.commits,0)
        for sql,args in conn.sql:
            self.assertTrue(sql.lstrip().startswith('SELECT'))
            if args: self.assertEqual(args[-1],DAY)
        self.assertIn('WHERE IsActive=1',conn.sql[0][0])

    def test_page_layout_shared_date_and_no_radio(self):
        with patch('app.main.get_connection',return_value=UsageConnection()):
            status,body=asyncio.run(get_page('/usage','production_date=2026-09-21'))
        self.assertEqual(status,200)
        headings=['PRODUCTION LOTS','SHIFT 1 MATERIAL USAGE','SHIFT 1 CALCULATION',
                  'SHIFT 2 MATERIAL USAGE','SHIFT 2 CALCULATION','ALL DAY CALCULATION']
        positions=[body.index('<h2>'+text+'</h2>') for text in headings]
        self.assertEqual(positions,sorted(positions))
        self.assertIn('Dynamic Material</td><td>kg',body)
        for label in ('Version','Wet Reject','Unit','Qty / 1000 Counter','Total Raw Qty'):
            self.assertIn('<th>'+label+'</th>',body)
        self.assertIn('name="qty_dynamic"',body)
        self.assertIn('value="12.345"',body)
        self.assertIn('0.987',body)
        self.assertNotIn('type="radio"',body)
        self.assertIn('action="/usage"',body)
        self.assertIn('href="/usage?production_date=2026-09-21" aria-current="page"',body)

    def test_usage_quantities_validation(self):
        self.assertEqual(validate_quantities({'dynamic':'0'},['dynamic']),{'dynamic':Decimal(0)})
        self.assertEqual(validate_quantities({'dynamic':''},['dynamic']),{'dynamic':None})
        for value in ('-1','1.0001','NaN','Infinity','1e5','1000000000000000'):
            with self.assertRaises(ValueError): validate_quantities({'dynamic':value},['dynamic'])
        with self.assertRaises(ValueError): validate_quantities({'unknown':'1'},['dynamic'])

    def test_insert_and_update_only_usage_tables(self):
        for existing in (False,True):
            conn=UsageConnection()
            if existing:
                conn.headers=[{'MaterialUsageID':8}]
                conn.details=[dict(MaterialUsageCode='dynamic',SourceType='MANUAL')]
            save_usage(conn,DAY,'1',{'dynamic':'12.345'})
            self.assertEqual(conn.commits,1)
            self.assertEqual(conn.rollbacks,0)
            writes=[(sql,args) for sql,args in conn.sql if sql.lstrip().startswith(('INSERT','UPDATE','DELETE'))]
            self.assertTrue(all('dbo.DailyMaterialUsage' in sql for sql,_ in writes))
            self.assertTrue(any(Decimal('12.345') in args for _,args in writes))
            if not existing:
                self.assertTrue(any('OUTPUT INSERTED.MaterialUsageID' in sql for sql,_ in writes))
            else:
                self.assertFalse(any('INSERT INTO dbo.DailyMaterialUsage (' in sql for sql,_ in writes))

    def test_blank_zero_and_nonmanual_protection(self):
        conn=UsageConnection()
        save_usage(conn,DAY,'1',{'dynamic':''})
        self.assertEqual(conn.commits,0)
        self.assertFalse(any(sql.startswith('INSERT') for sql,_ in conn.sql))
        conn=UsageConnection(); conn.headers=[{'MaterialUsageID':8}]
        conn.details=[dict(MaterialUsageCode='dynamic',SourceType='MANUAL')]
        save_usage(conn,DAY,'2',{'dynamic':''})
        self.assertTrue(any(sql.startswith('DELETE') for sql,_ in conn.sql))
        conn=UsageConnection(); conn.headers=[{'MaterialUsageID':8}]
        conn.details=[dict(MaterialUsageCode='dynamic',SourceType='EXTERNAL')]
        with self.assertRaises(ValueError): save_usage(conn,DAY,'1',{'dynamic':'4'})
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.rollbacks,1)

    def test_write_failure_rolls_back(self):
        conn=UsageConnection(); conn.fail='INSERT INTO dbo.DailyMaterialUsageDetail'
        with self.assertRaises(RuntimeError): save_usage(conn,DAY,'1',{'dynamic':'1'})
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.rollbacks,1)

    def test_save_route_preserves_date(self):
        from starlette.requests import Request
        from app.main import save_usage_route
        async def receive(): return {'type':'http.request','body':b'production_date=2026-09-21&qty_dynamic=2.500','more_body':False}
        request=Request({'type':'http','method':'POST','path':'/usage/1','headers':[(b'content-type',b'application/x-www-form-urlencoded')]},receive)
        conn=UsageConnection()
        with patch('app.main.get_connection',return_value=conn): response=asyncio.run(save_usage_route(request,'1'))
        self.assertEqual(response.status_code,303)
        self.assertEqual(response.headers['location'],'/usage?production_date=2026-09-21&saved=true')
        self.assertEqual(conn.commits,1)

    def test_load_failure_and_invalid_date(self):
        with patch('app.main.get_connection',side_effect=RuntimeError('private')):
            status,body=asyncio.run(get_page('/usage'))
        self.assertEqual(status,503)
        self.assertNotIn('private',body)
        with patch('app.main.get_connection') as connection:
            self.assertEqual(asyncio.run(get_page('/usage','production_date=bad'))[0],422)
            connection.assert_not_called()


class StoredUsageConnection(UsageConnection):
    """Persistent transaction double to verify header/detail identity and reload."""
    def __init__(self):
        super().__init__()
        self.store={'headers':{},'details':{}}
        self.committed=copy.deepcopy(self.store)

    def commit(self):
        super().commit()
        self.committed=copy.deepcopy(self.store)

    def rollback(self):
        super().rollback()
        self.store=copy.deepcopy(self.committed)

    def execute(self,sql,*args):
        super().execute(sql,*args)
        result=None
        if 'SELECT MaterialUsageID FROM dbo.DailyMaterialUsage' in sql:
            usage_id=self.store['headers'].get(args)
            result=[{'MaterialUsageID':usage_id}] if usage_id else []
        elif 'INSERT INTO dbo.DailyMaterialUsage (' in sql:
            if args in self.store['headers']: raise AssertionError('Duplicate header')
            usage_id=len(self.store['headers'])+1
            self.store['headers'][args]=usage_id
            result=[{'MaterialUsageID':usage_id}]
        elif 'SELECT MaterialUsageCode,SourceType' in sql:
            result=[dict(MaterialUsageCode=code,SourceType='MANUAL') for (usage_id,code) in self.store['details'] if usage_id==args[0]]
        elif 'INSERT INTO dbo.DailyMaterialUsageDetail' in sql:
            key=args[:2]
            if key in self.store['details']: raise AssertionError('Duplicate detail')
            self.store['details'][key]=args[2]
        elif 'UPDATE dbo.DailyMaterialUsageDetail' in sql:
            self.store['details'][args[1:]]=args[0]
        elif 'DELETE FROM dbo.DailyMaterialUsageDetail' in sql:
            self.store['details'].pop(args,None)
        elif 'FROM dbo.vw_DailyMaterialUsageCalc' in sql:
            result=[]
            for (report_date,shift),usage_id in self.store['headers'].items():
                if report_date!=args[0]: continue
                for (parent,code),qty in self.store['details'].items():
                    if parent==usage_id:
                        # Fixed view results: application must not recompute them.
                        result.append(dict(CALC,Shift=shift,MaterialUsageCode=code,RawQty=qty))
        if result is not None:
            self.description=[(key,) for key in result[0]] if result else []
            self.results=[tuple(row.values()) for row in result]
        return self


class UsageContractTests(unittest.TestCase):
    def test_first_save_repeat_update_and_shift_isolation_reload(self):
        conn=StoredUsageConnection()
        before=read_usage_context(conn,DAY)
        self.assertTrue(all(section['materials'][0]['RawQty'] is None for section in before['shifts']))
        save_usage(conn,DAY,'1',{'dynamic':'12.345'})
        first_id=conn.store['headers'][(DAY,'1')]
        save_usage(conn,DAY,'2',{'dynamic':'7.250'})
        save_usage(conn,DAY,'1',{'dynamic':'15.500'})
        self.assertEqual(len(conn.store['headers']),2)
        self.assertEqual(len(conn.store['details']),2)
        self.assertEqual(conn.store['headers'][(DAY,'1')],first_id)
        loaded=read_usage_context(conn,DAY)
        self.assertEqual([section['materials'][0]['RawQty'] for section in loaded['shifts']],
                         [Decimal('15.500'),Decimal('7.250')])
        self.assertEqual(loaded['shifts'][0]['materials'][0]['QtyPer1000Counter'],CALC['QtyPer1000Counter'])
        with patch('app.main.get_connection',return_value=conn):
            status,body=asyncio.run(get_page('/usage','production_date=2026-09-21'))
        self.assertEqual(status,200)
        self.assertIn('value="15.500"',body)
        self.assertIn('value="7.250"',body)

    def test_empty_initial_usage_renders_every_master_for_both_shifts(self):
        conn=StoredUsageConnection()
        conn.materials=[dict(MASTER),dict(MASTER,MaterialUsageCode='newCode',MaterialNameTH='Display only',SortOrder=2)]
        with patch('app.main.get_connection',return_value=conn):
            status,body=asyncio.run(get_page('/usage','production_date=2026-09-21'))
        self.assertEqual(status,200)
        for code in ('dynamic','newCode'):
            self.assertEqual(body.count('name="qty_'+code+'"'),2)
        self.assertNotIn('name="qty_Display only"',body)
        self.assertEqual(conn.commits,0)
        self.assertEqual(conn.store,{'headers':{},'details':{}})

    def test_rollback_preserves_saved_shift_after_detail_failure(self):
        conn=StoredUsageConnection()
        save_usage(conn,DAY,'1',{'dynamic':'5'})
        before=copy.deepcopy(conn.store)
        conn.fail='UPDATE dbo.DailyMaterialUsageDetail'
        with self.assertRaises(RuntimeError): save_usage(conn,DAY,'1',{'dynamic':'6'})
        self.assertEqual(conn.store,before)

    def test_usage_lots_reuse_prod_api_reader(self):
        expected=[dict(LOT,VersionNo='02',WetRejectQty=10)]
        with patch('app.usage.read_prod_records',return_value=expected) as reader:
            result=read_usage_context(UsageConnection(),DAY)
        reader.assert_called_once()
        self.assertEqual(reader.call_args.args[1],DAY)
        self.assertEqual(result['lots'],expected)
