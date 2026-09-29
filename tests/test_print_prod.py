import asyncio
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from app.main import app, print_prod_pdf_page
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
              daily_materials=[])


class PrintProdTests(unittest.TestCase):
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