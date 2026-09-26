import asyncio
import copy
import html
import json
import re
import unittest
from datetime import date, time
from unittest.mock import patch
from app.main import app, production_page
from app.prod_api import read_prod_records, resolve_plan, build_pis_prodorders_payload, field_mapping, build_pis_date_preview, preview_readiness
from test_production import LOT, PLAN, request

DAY = date(2026, 9, 22)
RECORD = dict(ProductionID=2, ProdDate=DAY, Shift='1', MaterialCode='12345678XX',
              MaterialName='Saved product', LotNo='B006690902', ProductFamily='NeuFit / NeuStile',
              ProductCode='06', PlanName='MTS033',PlanQty=1800, ProductionStartTime=time(7, 30), ProductionEndTime=time(15, 30),
              CounterQty=100, CuringQty=90, Remark='Saved <remark>')


PLAN_SOURCE = dict(Company='CRTC',Plant='30A1',Machine='SB2-3',PlanWeek='2026W36',
                   VersionNo='02',PlanName='MTS033',Shift='1',StartTime=DAY,
                   MaterialCode=RECORD['MaterialCode'],PlanCount=1800,OperationCode='a')


class ReadOnlyConnection:
    def __init__(self, records=None):
        self.records = copy.deepcopy(records if records is not None else [RECORD])
        self.sql = []
        self.closed = False
    def cursor(self): return self
    def execute(self, sql, *args):
        if not sql.lstrip().startswith('SELECT'):
            raise AssertionError('Viewing must only SELECT')
        self.sql.append((sql,args))
        if 'FROM dbo.P_ActivePlan' in sql:
            self.result = [PLAN_SOURCE] if args[-1] == DAY else []
            self.description = [(key,) for key in PLAN_SOURCE]
        else:
            self.result = [record for record in self.records if record['ProdDate'] == args[0]]
            self.description = [(key,) for key in RECORD]
    def fetchall(self): return [tuple(record[key[0]] for key in self.description) for record in self.result]
    def close(self): self.closed = True
    def commit(self): raise AssertionError('Viewing must not commit')
    def rollback(self): raise AssertionError('Viewing must not write')


async def get_page(path, query='', method='GET'):
    messages = []
    async def receive(): return {'type':'http.request','body':b'', 'more_body':False}
    async def send(message): messages.append(message)
    # The event loop is already initialized; block connections during route execution.
    with patch('socket.socket.connect', side_effect=AssertionError('External request forbidden')):
        await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
                   'scheme':'http','path':path,'raw_path':path.encode(),'query_string':query.encode(),
                   'root_path':'','headers':[], 'server':('test',80),'client':('test',1)},receive,send)
    start = next(message for message in messages if message['type']=='http.response.start')
    body = b''.join(message.get('body',b'') for message in messages if message['type']=='http.response.body').decode()
    return start['status'], body


class ProdApiTests(unittest.TestCase):
    def page(self, query='', conn=None):
        conn = conn or ReadOnlyConnection()
        before = copy.deepcopy(conn.records)
        with patch('app.main.get_connection',return_value=conn):
            status, body = asyncio.run(get_page('/prod-api',query))
        self.assertEqual(conn.records,before)
        self.assertTrue(conn.closed)
        self.assertEqual(len(conn.sql),2)
        return status, body, conn

    def test_query_uses_existing_tables_parameterized_date_and_active_lots(self):
        conn = ReadOnlyConnection()
        self.assertEqual(read_prod_records(conn,DAY)[0]['Plant'],'30A1')
        sql,args = conn.sql[0]
        self.assertIn('LEFT JOIN dbo.ProductionData d ON d.ProductionID=p.ProductionID',sql)
        self.assertIn('WHERE p.IsActive=1 AND p.ProdDate=?',sql)
        self.assertEqual(args,(DAY,))
        self.assertNotIn('PIS',sql)

    def test_prod_route_displays_saved_values_and_navigation(self):
        status, body, _ = self.page('production_date=2026-09-22')
        self.assertEqual(status,200)
        for text in ['B006690902','07:30:00','15:30:00','12345678XX','Saved product',
                     'NeuFit / NeuStile','>100<','>90<','Saved &lt;remark&gt;', 'NOT SENT']:
            self.assertIn(text,body)
        self.assertIn('local preview label',body)
        self.assertEqual(body.count('aria-current="page"'),1)
        self.assertRegex(body,r'href="/prod-api\?production_date=2026-09-22" aria-current="page"')
        self.assertIn('href="/reject-api?production_date=2026-09-22"',body)
        self.assertIn('href="/?production_date=2026-09-22"',body)
        scripts=re.findall(r'<script>(.*?)</script>',body,re.S)
        self.assertEqual(len(scripts),1)
        self.assertIn("dateInput.addEventListener('change'",scripts[0])
        self.assertNotRegex(scripts[0],r'fetch\s*\(|XMLHttpRequest|\.submit\s*\(|\.requestSubmit\s*\(')
        self.assertNotIn('https://',body)
        self.assertNotIn('method="post"',body)
        self.assertNotIn('>SEND<',body)

    def test_default_today_and_historical_filter(self):
        _,_,conn = self.page()
        self.assertEqual(conn.sql[0][1],(date.today(),))
        status,body,conn = self.page('production_date=2020-01-01')
        self.assertEqual(status,200)
        self.assertEqual(conn.sql[0][1],(date(2020,1,1),))
        self.assertIn('No active Production Lots',body)
        self.assertNotIn('B006690902',body)

    def test_preview_is_read_only_exact_available_fields(self):
        status,body,_ = self.page('production_date=2026-09-22&preview_all=true')
        self.assertEqual(status,200)
        preview = json.loads(html.unescape(re.search(r'<pre id="prod-preview-1" class="prod-preview">(.*?)</pre>',body,re.S)[1]))
        self.assertEqual(preview['plantCode'],'30A1')
        self.assertEqual(preview['machineCode'],'SB2-3')
        self.assertEqual(preview['productionDate'],'2026-09-22')
        self.assertEqual(preview['shiftCode'],'1')
        item=preview['productionItems'][0]
        self.assertEqual(item['dateTimeStart'],'2026-09-22T07:30')
        self.assertEqual(item['dateTimeEnd'],'2026-09-22T15:30')
        self.assertEqual(item['planName'],'MTS033')
        self.assertEqual(item['versionNo'],'02')
        self.assertEqual(item['planWeek'],'2026W36')
        self.assertEqual(item['operationCode'],'a')
        self.assertFalse(item['followPlan'])
        for key in ('itemDetails','itemInputs','itemProperties'):
            self.assertEqual(item[key],[])
        output=item['itemOutputs'][0]
        self.assertEqual(output['gross0'],90)
        self.assertEqual(output['lotNo'],RECORD['LotNo'])
        self.assertEqual(output['materialCode'],RECORD['MaterialCode'])
        detail=output['outputDetails'][0]
        self.assertEqual(detail['count'],90)
        self.assertEqual(detail['effectiveDate'],'2026-09-22')
        self.assertEqual(detail['statusCode'],'Curing')
        self.assertIn('FIELD MAPPING',body)
        self.assertIn('PIS JSON PREVIEW',body)
        self.assertIn('ProductionData.CuringQty &gt;= ProductionLot.PlanQty',body)
        for column in ('Plan','Version','Wet Reject'):
            self.assertIn('<th>'+column+'</th>',body)
        self.assertIn('Saved &lt;remark&gt;',body)

    def test_missing_measurements_remain_null_and_zero_is_displayed(self):
        record = dict(RECORD,CounterQty=0,CuringQty=None,ProductionStartTime=None,ProductionEndTime=None,Remark=None)
        status,body,_ = self.page('production_date=2026-09-22&preview_all=true',ReadOnlyConnection([record]))
        self.assertEqual(status,200)
        self.assertIn('>0<',body)
        self.assertIn('"gross0": null',html.unescape(body))

    def test_empty_date_has_no_request(self):
        status,body,_ = self.page('production_date=2020-01-01&preview_all=true')
        self.assertEqual(status,200)
        self.assertIn('Nothing to preview',body)
        self.assertNotIn('class="prod-preview"',body)

    def test_all_lots_included_once_and_selection_cannot_filter_all(self):
        other=dict(RECORD,ProductionID=3,LotNo='SECOND',CuringQty=80)
        historical=dict(RECORD,ProductionID=4,LotNo='HISTORICAL',ProdDate=date(2020,1,1))
        status,body,_=self.page('production_date=2026-09-22&preview_all=true&production_id=2',
                               ReadOnlyConnection([RECORD,other,historical]))
        self.assertEqual(status,200)
        preview=json.loads(html.unescape(re.search(r'<pre id="prod-preview-1" class="prod-preview">(.*?)</pre>',body,re.S)[1]))
        self.assertEqual([item['itemOutputs'][0]['lotNo'] for item in preview['productionItems']],
                         ['B006690902','SECOND'])
        self.assertNotIn('HISTORICAL',body)
        self.assertIn('type="radio"',body)
        self.assertIn('name="production_id"',body)
        self.assertIn('PREVIEW ALL PROD',body)
        self.assertIn('>REFRESH<',body)
        self.assertIn('>PREVIEW PROD<',body)
        self.assertIn('2 lots included',body)

    def test_multiple_groups_preserve_all_lots_without_inventing_request_wrapper(self):
        other=dict(RECORD,ProductionID=3,LotNo='SECOND',Shift='2',CuringQty=None)
        status,body,_=self.page('production_date=2026-09-22&preview_all=true',ReadOnlyConnection([RECORD,other]))
        self.assertEqual(status,200)
        groups=[json.loads(html.unescape(value)) for value in re.findall(r'<pre id="prod-preview-\d+" class="prod-preview">(.*?)</pre>',body,re.S)]
        self.assertEqual([group['shiftCode'] for group in groups],['1','2'])
        self.assertEqual(sum(len(group['productionItems']) for group in groups),2)
        self.assertIsNone(groups[1]['productionItems'][0]['itemOutputs'][0]['gross0'])
        self.assertIn('Each group below is a separate ProdOrders request body',body)
        self.assertIn('no batch wrapper',body)
        self.assertEqual(len(groups),2)

    def test_date_builder_checks_date_and_keeps_unmapped_records(self):
        rows=[dict(RECORD,Plant='30A1',Machine='SB2-3'),dict(RECORD,ProductionID=3,LotNo='UNMAPPED')]
        groups=build_pis_date_preview(rows,DAY)
        self.assertEqual(len(groups),2)
        self.assertIsNone(groups[1]['plantCode'])
        self.assertEqual(groups[1]['productionItems'][0]['itemOutputs'][0]['lotNo'],'UNMAPPED')
        self.assertEqual(build_pis_date_preview([],DAY),[])
        with self.assertRaises(ValueError): build_pis_date_preview(rows,date(2020,1,1))

    def test_routes_reject_invalid_dates_and_posts_without_database_access(self):
        with patch('app.main.get_connection') as connection:
            for path in ('/prod-api','/reject-api'):
                self.assertEqual(asyncio.run(get_page(path,'production_date=invalid'))[0],422)
                self.assertEqual(asyncio.run(get_page(path,method='POST'))[0],405)
            connection.assert_not_called()

    def test_reject_placeholder_has_navigation_without_database_access(self):
        with patch('app.main.get_connection') as connection:
            status,body = asyncio.run(get_page('/reject-api','production_date=2026-09-22'))
        connection.assert_not_called()
        self.assertEqual(status,200)
        self.assertIn('Coming next',body)
        self.assertRegex(body,r'href="/reject-api\?production_date=2026-09-22" aria-current="page"')
        scripts=re.findall(r'<script>(.*?)</script>',body,re.S)
        self.assertEqual(len(scripts),1)
        self.assertIn("dateInput.addEventListener('change'",scripts[0])
        self.assertNotRegex(scripts[0],r'fetch\s*\(|XMLHttpRequest|\.submit\s*\(|\.requestSubmit\s*\(')

    def test_database_failure_shows_safe_error(self):
        with patch('app.main.get_connection',side_effect=RuntimeError('private details')):
            status,body = asyncio.run(get_page('/prod-api'))
        self.assertEqual(status,503)
        self.assertIn('Unable to load Production records',body)
        self.assertNotIn('private details',body)

    def test_production_navigation_uses_selected_lot_date(self):
        from unittest.mock import MagicMock
        with patch('app.main.get_connection',return_value=MagicMock()), \
             patch('app.main.read_lots',return_value=[LOT]), \
             patch('app.main.read_plans',return_value=[PLAN]):
            response=production_page(request(),production_id=7)
        body=response.body.decode()
        self.assertIn('href="/prod-api?production_date=2026-09-21"',body)
        self.assertRegex(body,r'href="/\?production_date=2026-09-21&amp;production_id=7" aria-current="page"')
        self.assertIn('SAVE PRODUCTION',body)

    def test_unresolved_and_ambiguous_sources_are_not_guessed(self):
        missing=resolve_plan(RECORD,[])
        payload=build_pis_prodorders_payload([dict(RECORD,**missing)])
        self.assertIsNone(payload['plantCode'])
        self.assertIsNone(payload['machineCode'])
        self.assertIsNone(payload['productionItems'][0]['operationCode'])
        changed=dict(PLAN_SOURCE,VersionNo='03',OperationCode='b')
        resolved=resolve_plan(RECORD,[PLAN_SOURCE,changed])
        self.assertEqual(resolved['Plant'],'30A1')
        self.assertEqual(resolved['Machine'],'SB2-3')
        self.assertIsNone(resolved['VersionNo'])
        self.assertIsNone(resolved['OperationCode'])
        for key,value in [('PlanName','other'),('MaterialCode','other'),('PlanCount',99),('StartTime',date(2020,1,1))]:
            self.assertIsNone(resolve_plan(RECORD,[dict(PLAN_SOURCE,**{key:value})])['Plant'])

    def test_builder_supports_grouped_items_without_hardcoded_context(self):
        row=dict(RECORD,Plant='actual-plant',Machine='actual-machine')
        payload=build_pis_prodorders_payload([row,dict(row,ProductionID=3,LotNo='OTHER')])
        self.assertEqual(payload['plantCode'],'actual-plant')
        self.assertEqual(payload['machineCode'],'actual-machine')
        self.assertEqual(len(payload['productionItems']),2)
        for key,value in [('ProdDate',date(2020,1,1)),('Shift','2'),('Plant','other'),('Machine','other')]:
            with self.assertRaises(ValueError):
                build_pis_prodorders_payload([row,dict(row,**{key:value})])
        with self.assertRaises(ValueError): build_pis_prodorders_payload([])

    def test_zero_curing_and_false_like_values_are_not_missing(self):
        row=dict(RECORD,CuringQty=0,**resolve_plan(RECORD,[PLAN_SOURCE]))
        payload=build_pis_prodorders_payload([row])
        self.assertEqual(payload['productionItems'][0]['itemOutputs'][0]['gross0'],0)
        self.assertFalse(next(item for item in field_mapping(row) if item['field']=='gross0')['missing'])

    def test_selected_lot_preview_only_contains_selection_and_no_external_request(self):
        other=dict(RECORD,ProductionID=3,LotNo='SECOND',CuringQty=80)
        status,body,_=self.page('production_date=2026-09-22&preview_one=true&production_id=3',
                               ReadOnlyConnection([RECORD,other]))
        self.assertEqual(status,200)
        groups=[json.loads(html.unescape(value)) for value in re.findall(
            r'<pre id="prod-preview-\d+" class="prod-preview">(.*?)</pre>',body,re.S)]
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['productionItems']),1)
        self.assertEqual(groups[0]['productionItems'][0]['itemOutputs'][0]['lotNo'],'SECOND')
        self.assertEqual(groups[0]['productionItems'][0]['itemOutputs'][0]['gross0'],80)
        self.assertIn('1 lots included',body)
        self.assertIn('SELECTED LOT',body)
        scripts=re.findall(r'<script>(.*?)</script>',body,re.S)
        self.assertEqual(len(scripts),1)
        self.assertIn("dateInput.addEventListener('change'",scripts[0])
        self.assertNotRegex(scripts[0],r'fetch\s*\(|XMLHttpRequest|\.submit\s*\(|\.requestSubmit\s*\(')
        self.assertNotIn('method="post"',body)
        # get_page blocks socket connections throughout route execution.
        self.assertNotIn('Unable to load',body)

    def test_single_preview_requires_valid_selection_from_date(self):
        for query in ('preview_one=true','preview_one=true&production_id=999'):
            status,body,_=self.page('production_date=2026-09-22&'+query)
            self.assertEqual(status,400)
            self.assertIn('Select a Production Lot from this date',body)
            self.assertNotIn('class="prod-preview"',body)

    def test_all_preview_without_selection_and_several_items_per_group(self):
        records=[RECORD,dict(RECORD,ProductionID=3,LotNo='SECOND'),
                 dict(RECORD,ProductionID=4,LotNo='THIRD',Shift='2')]
        status,body,_=self.page('production_date=2026-09-22&preview_all=true',ReadOnlyConnection(records))
        self.assertEqual(status,200)
        groups=[json.loads(html.unescape(value)) for value in re.findall(
            r'<pre id="prod-preview-\d+" class="prod-preview">(.*?)</pre>',body,re.S)]
        self.assertEqual([len(group['productionItems']) for group in groups],[2,1])
        self.assertEqual([item['itemOutputs'][0]['lotNo'] for group in groups for item in group['productionItems']],
                         ['B006690902','SECOND','THIRD'])
        self.assertRegex(body,r'name="preview_all"[^>]*formnovalidate')

    def test_no_production_send_action_or_endpoint(self):
        status,body,_=self.page('production_date=2026-09-22')
        self.assertEqual(status,200)
        self.assertNotIn('SEND PROD',body)
        self.assertNotIn('SEND LOT PROD',body)
        self.assertNotIn('SEND ALL PROD',body)
        self.assertNotIn('method="post"',body)
        self.assertFalse(any('send' in route.path.lower() for route in app.routes))
        self.assertEqual(next(route for route in app.routes if route.path=='/prod-api').methods,{'GET'})
        with patch('app.main.get_connection') as connection:
            for path in ('/prod-api','/prod-api/2/send','/lots/2/send-prod'):
                self.assertIn(asyncio.run(get_page(path,method='POST'))[0],(404,405))
            connection.assert_not_called()

    def test_local_same_day_overnight_and_calendar_boundaries(self):
        for production_date,start,end,expected_start,expected_end in [
            (DAY,time(7,30,59),time(15,30,22),'2026-09-22T07:30','2026-09-22T15:30'),
            (DAY,time(22,10),time(6,5),'2026-09-22T22:10','2026-09-23T06:05'),
            (date(2026,12,31),time(23),time(0),'2026-12-31T23:00','2027-01-01T00:00'),
            (DAY,time(7),time(7),'2026-09-22T07:00','2026-09-22T07:00')]:
            with self.subTest(end=expected_end):
                row=dict(RECORD,ProdDate=production_date,ProductionStartTime=start,ProductionEndTime=end)
                before=copy.deepcopy(row)
                payload=build_pis_prodorders_payload([row])
                item=payload['productionItems'][0]
                self.assertEqual(item['dateTimeStart'],expected_start)
                self.assertEqual(item['dateTimeEnd'],expected_end)
                self.assertEqual(item['itemOutputs'][0]['outputDetails'][0]['effectiveDate'],production_date)
                self.assertEqual(row,before)

    def test_trimmed_fields_group_together_without_defaults(self):
        base=dict(RECORD,**resolve_plan(RECORD,[PLAN_SOURCE]))
        padded={key:('  '+value+'  ' if isinstance(value,str) else value) for key,value in base.items()}
        padded.update(ProductionID=3,LotNo=' SECOND ')
        groups=build_pis_date_preview([padded,base],DAY)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['plantCode'],'30A1')
        self.assertEqual(groups[0]['shiftCode'],'1')
        self.assertEqual(len(groups[0]['productionItems']),2)
        for item in groups[0]['productionItems']:
            self.assertEqual(item['versionNo'],'02')
            self.assertEqual(item['remark'],'Saved <remark>')
            self.assertEqual(item['itemOutputs'][0]['materialCode'],'12345678XX')
        self.assertEqual(groups[0]['productionItems'][1]['itemOutputs'][0]['lotNo'],'SECOND')

    def test_required_missing_values_remain_null_and_are_reported(self):
        base=dict(RECORD,**resolve_plan(RECORD,[PLAN_SOURCE]))
        cases={'Plant':'plantCode','Machine':'machineCode','OperationCode':'operationCode',
               'PlanWeek':'planWeek','VersionNo':'versionNo','ProductionStartTime':'dateTimeStart',
               'ProductionEndTime':'dateTimeEnd','MaterialCode':'materialCode','LotNo':'lotNo','CuringQty':'gross0'}
        for key,field in cases.items():
            with self.subTest(key=key):
                row=dict(base,**{key:None})
                payload=build_pis_prodorders_payload([row])
                readiness=preview_readiness(payload)
                self.assertFalse(readiness['ready'])
                self.assertTrue(any(field in missing for missing in readiness['missing']))
                mapping=next(item for item in field_mapping(row) if item['field']==field)
                self.assertIsNone(mapping['value'])
                self.assertEqual(mapping['severity'],'required')
        payload=build_pis_prodorders_payload([dict(base,Plant='  ',Machine=' ',VersionNo=' ',MaterialCode=' ')])
        self.assertIsNone(payload['plantCode'])
        self.assertIsNone(payload['machineCode'])
        self.assertIsNone(payload['productionItems'][0]['versionNo'])
        self.assertIsNone(payload['productionItems'][0]['itemOutputs'][0]['materialCode'])

    def test_followplan_false_is_ready_for_lot_and_group(self):
        row=dict(RECORD,CuringQty=0,**resolve_plan(RECORD,[PLAN_SOURCE]))
        payload=build_pis_prodorders_payload([row])
        self.assertTrue(preview_readiness(payload)['ready'])
        self.assertEqual(preview_readiness(payload)['missing'],[])
        self.assertFalse(payload['productionItems'][0]['followPlan'])
        self.assertEqual(next(item for item in field_mapping(row) if item['field']=='followPlan')['severity'],'mapped')
        status,body,_=self.page('production_date=2026-09-22&preview_one=true&production_id=2')
        self.assertEqual(status,200)
        self.assertIn('READY FOR PIS PREVIEW',body)
        self.assertIn('DRY RUN / NO PIS SEND',body)
        self.assertNotIn('MISSING REQUIRED DATA',body)
        self.assertNotIn('followPlan source not implemented',body)

    def test_group_missing_fields_do_not_omit_lots(self):
        status,body,_=self.page('production_date=2026-09-22&preview_all=true',ReadOnlyConnection([
            RECORD,dict(RECORD,ProductionID=3,LotNo='SECOND',CuringQty=None,ProductionEndTime=None)]))
        self.assertEqual(status,200)
        self.assertIn('2 lots included',body)
        self.assertIn('Item 2: gross0 (CuringQty)',body)
        self.assertIn('Item 2: dateTimeEnd',body)
        self.assertIn('MISSING REQUIRED DATA',body)

    def test_followplan_uses_saved_plan_per_lot_not_counter_or_aggregate(self):
        from decimal import Decimal
        rows=[dict(RECORD,ProductionID=i+2,LotNo='LOT'+str(i),PlanQty=Decimal(str(plan)),
                   CuringQty=curing,CounterQty=99999,**resolve_plan(RECORD,[PLAN_SOURCE]))
              for i,(plan,curing) in enumerate([(1800,1790),(1800,1800),(1000,1050),(0,0)])]
        payload=build_pis_date_preview(rows,DAY)[0]
        self.assertEqual([item['followPlan'] for item in payload['productionItems']],[False,True,True,True])
        for row,expected in zip(rows,[False,True,True,True]):
            mapping=next(item for item in field_mapping(row) if item['field']=='followPlan')
            self.assertEqual(mapping['source'],'ProductionData.CuringQty >= ProductionLot.PlanQty')
            self.assertEqual(mapping['value'],expected)
            self.assertFalse(mapping['missing'])
            self.assertEqual(build_pis_prodorders_payload([row])['productionItems'][0]['followPlan'],expected)

    def test_missing_followplan_sources_are_null_and_named(self):
        base=dict(RECORD,**resolve_plan(RECORD,[PLAN_SOURCE]))
        for changes,expected in [({'CuringQty':None},['ProductionData.CuringQty']),
                                 ({'PlanQty':None},['ProductionLot.PlanQty']),
                                 ({'CuringQty':None,'PlanQty':None},['ProductionData.CuringQty','ProductionLot.PlanQty'])]:
            row=dict(base,**changes)
            payload=build_pis_prodorders_payload([row])
            self.assertIsNone(payload['productionItems'][0]['followPlan'])
            mapping=next(item for item in field_mapping(row) if item['field']=='followPlan')
            self.assertEqual(mapping['missing_sources'],expected)
            readiness=preview_readiness(payload,[row])
            self.assertFalse(readiness['ready'])
            for source in expected:
                self.assertTrue(any(source in message for message in readiness['missing']))
            for mode in ('preview_one=true&production_id=2','preview_all=true'):
                status,body,_=self.page('production_date=2026-09-22&'+mode,ReadOnlyConnection([row]))
                self.assertEqual(status,200)
                self.assertIn('"followPlan": null',html.unescape(body))
                for source in expected: self.assertIn(source,body)

    def test_both_preview_modes_use_each_saved_plan_quantity(self):
        records=[dict(RECORD,PlanQty=1800,CuringQty=1790,CounterQty=5000),
                 dict(RECORD,ProductionID=3,LotNo='SECOND',PlanQty=1000,CuringQty=1050,CounterQty=5000)]
        for mode,expected in [('preview_one=true&production_id=2',[False]),
                              ('preview_one=true&production_id=3',[True]),('preview_all=true',[False,True])]:
            status,body,_=self.page('production_date=2026-09-22&'+mode,ReadOnlyConnection(records))
            self.assertEqual(status,200)
            groups=[json.loads(html.unescape(value)) for value in re.findall(
                r'<pre id="prod-preview-\d+" class="prod-preview">(.*?)</pre>',body,re.S)]
            self.assertEqual([item['followPlan'] for group in groups for item in group['productionItems']],expected)

    def test_plan_quantity_column_uses_saved_value_and_integer_format(self):
        from decimal import Decimal
        for value,display in [(Decimal('1234567.000'),'1,234,567'),(Decimal('1800.000'),'1,800'),
                              (0,'0'),(None,'-')]:
            with self.subTest(value=value):
                status,body,_=self.page('production_date=2026-09-22',
                    ReadOnlyConnection([dict(RECORD,PlanQty=value)]))
                self.assertEqual(status,200)
                self.assertIn('<th>Product</th><th>Plan Qty</th><th>Counter</th><th>Curing</th>'
                              '<th>Wet Reject</th><th>Remark</th><th>Local status</th>',body)
                table=re.search(r'<table>(.*?)</table>',body,re.S)[1]
                cells=re.findall(r'<td[^>]*>(.*?)</td>',table,re.S)
                self.assertEqual(cells[10],display)
                self.assertEqual(cells[11],'100')
        _,body,_=self.page('production_date=2020-01-01')
        self.assertIn('colspan="16"',body)
