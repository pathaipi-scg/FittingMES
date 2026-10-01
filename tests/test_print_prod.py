import asyncio
import tempfile
import unittest
from datetime import date, time
from unittest.mock import patch

from app.main import app, print_prod_pdf_page
from app.print_prod import read_print_prod_context
from test_prod_api import get_page


DAY = date(2026, 9, 22)
OTHER_DAY = date(2026, 9, 23)
REPORT = dict(records=[dict(ProdDate=DAY, Shift='1', LotNo='I01690901', ProductCode='01',
                             ProductName='ปิดจั่ว', PlanQty=100, CounterQty=95, CuringQty=90,
                             WetRejectQty=5, WetRejectPercent=5.26)],
              shifts=[dict(shift='1', records=[dict(ProdDate=DAY, Shift='1', LotNo='I01690901',
                             ProductCode='01', ProductName='ปิดจั่ว', PlanQty=100, CounterQty=95,
                             CuringQty=90, WetRejectQty=5, WetRejectPercent=5.26)],
                            totals=dict(PlanQty=100, CounterQty=95, CuringQty=90), materials=[])],
              daily_totals=dict(PlanQty=100, CounterQty=95, CuringQty=90),
              daily_materials=[], plan_week='2026W37')


class PrintProdTests(unittest.TestCase):
    RULES = [dict(EffectiveFromDate=DAY, ShiftID=1, StartTime=time(6, 0)),
             dict(EffectiveFromDate=DAY, ShiftID=2, StartTime=time(20, 0))]

    def page(self, path, query=''):
        with patch('app.main.get_connection') as connection, \
             patch('app.main.read_print_prod_context', return_value=REPORT):
            status, body = asyncio.run(get_page(path, query))
        return status, body, connection

    def test_print_prod_route_preserves_date_and_contains_selected_lot(self):
        status, body, _ = self.page('/print-prod', 'production_date=2026-09-22')
        self.assertEqual(status, 200)
        self.assertIn('value="2026-09-22"', body)
        self.assertIn('I01690901', body)
        self.assertIn('สัปดาห์ที่: <strong>2026W37</strong>', body)
        self.assertIn('>PRINT<', body)
        self.assertIn('>SAVE PDF<', body)
        self.assertIn('/print-prod/pdf?production_date=2026-09-22', body)

    def test_print_prod_does_not_include_another_date(self):
        status, body, _ = self.page('/print-prod', 'production_date=2026-09-22')
        self.assertEqual(status, 200)
        self.assertNotIn(str(OTHER_DAY), body)

    def test_print_oee_placeholder_route_preserves_date(self):
        status, body, _ = self.page('/print-oee', 'production_date=2026-09-22')
        self.assertEqual(status, 200)
        self.assertIn('Coming next', body)
        self.assertIn('value="2026-09-22"', body)

    def test_pdf_route_returns_date_based_attachment(self):
        output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        output.write(b'%PDF-1.7\nvalid')
        output.close()
        root = tempfile.mkdtemp()
        process = object()
        with patch('app.main.generate_print_prod_pdf', return_value=(root, output.name, process)), \
             patch('app.main.finish_pdf_process'):
            status, body = asyncio.run(get_page('/print-prod/pdf', 'production_date=2026-09-26'))
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith('%PDF-'))
        with patch('app.main.generate_print_prod_pdf', return_value=(root, output.name, process)):
            response = print_prod_pdf_page(date(2026, 9, 26))
        self.assertEqual(response.media_type, 'application/pdf')
        self.assertIn('DailyProductionReport_2026-09-26.pdf', response.headers['content-disposition'])

    def test_pdf_route_rejects_invalid_date(self):
        status, body, _ = self.page('/print-prod/pdf', 'production_date=not-a-date')
        self.assertEqual(status, 422)

    def test_print_prod_context_is_read_only(self):
        status, _, connection = self.page('/print-prod', 'production_date=2026-09-22')
        self.assertEqual(status, 200)
        connection.assert_called_once()

    def test_context_groups_by_effective_shift_without_writing(self):
        records = [
            dict(ProductionID=1, ProdDate=DAY, Shift='1', ProductionStartTime=time(8, 10),
                 ProductFamily='F', ProductCode='01', PlanQty=800, CounterQty=910, CuringQty=890),
            dict(ProductionID=2, ProdDate=DAY, Shift='1', ProductionStartTime=time(21, 0),
                 ProductFamily='F', ProductCode='02', PlanQty=1400, CounterQty=1410, CuringQty=1390),
            dict(ProductionID=3, ProdDate=DAY, Shift='2', ProductionStartTime=time(22, 0),
                 ProductFamily='F', ProductCode='03', PlanQty=1400, CounterQty=1490, CuringQty=1409),
        ]
        usage = dict(shifts=[dict(shift='1', materials=[]), dict(shift='2', materials=[])], daily=[])
        cursor = unittest.mock.MagicMock()
        cursor.fetchone.return_value = ('2026W37',)
        with patch('app.print_prod.read_prod_records', return_value=records), \
             patch('app.print_prod.read_shift_rules', return_value=self.RULES) as read_rules, \
             patch('app.print_prod.read_usage_context', return_value=usage), \
             patch('app.print_prod.rows', return_value=[]):
            context = read_print_prod_context(cursor, DAY)

        read_rules.assert_called_once_with(cursor, DAY)
        self.assertEqual(context['plan_week'], '2026W37')
        self.assertEqual([row['Shift'] for row in context['records']], ['1', '2', '2'])
        self.assertEqual([row['ProductionID'] for row in context['shifts'][0]['records']], [1])
        self.assertEqual([row['ProductionID'] for row in context['shifts'][1]['records']], [2, 3])
        self.assertEqual(context['shifts'][0]['totals'], dict(PlanQty=800, CounterQty=910, CuringQty=890))
        self.assertEqual(context['shifts'][1]['totals'], dict(PlanQty=2800, CounterQty=2900, CuringQty=2799))
        self.assertEqual(context['daily_totals'], dict(PlanQty=3600, CounterQty=3810, CuringQty=3689))
        plan_query = next(call for call in cursor.execute.call_args_list
                  if 'dbo.P_ActivePlan' in call.args[0])
        self.assertIn('dbo.P_ActivePlan', plan_query.args[0])
        self.assertIn('ORDER BY VersionNo DESC, Shift', plan_query.args[0])
        self.assertEqual(plan_query.args[1:], ('CRTC', '30A1', 'SB2-3', DAY))
        sqls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(sqls)
        self.assertTrue(all('UPDATE' not in sql.upper() for sql in sqls))
        self.assertTrue(all('INSERT' not in sql.upper() for sql in sqls))

    def test_context_preserves_stored_shift_without_valid_start(self):
        records = [
            dict(ProductionID=1, ProdDate=DAY, Shift='2', ProductionStartTime=None,
                 ProductFamily='F', ProductCode='01', PlanQty=1, CounterQty=1, CuringQty=1),
            dict(ProductionID=2, ProdDate=DAY, Shift='1', ProductionStartTime='not-a-time',
                 ProductFamily='F', ProductCode='02', PlanQty=1, CounterQty=1, CuringQty=1),
        ]
        usage = dict(shifts=[dict(shift='1', materials=[]), dict(shift='2', materials=[])], daily=[])
        with patch('app.print_prod.read_prod_records', return_value=records), \
             patch('app.print_prod.read_shift_rules', return_value=self.RULES), \
             patch('app.print_prod.read_usage_context', return_value=usage), \
             patch('app.print_prod.rows', return_value=[]):
            context = read_print_prod_context(unittest.mock.MagicMock(), DAY)
        self.assertEqual([row['Shift'] for row in context['records']], ['2', '1'])