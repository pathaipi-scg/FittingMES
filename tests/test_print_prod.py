import asyncio
import tempfile
import unittest
from datetime import date, time
from decimal import Decimal
from html.parser import HTMLParser
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


class ProductionTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.bands = []
        self.current_band = None
        self.current_table = None
        self.current_row = None
        self.current_cell = None
        self.reading_colgroup = False
        self.band_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'div' and 'shift-band' in classes:
            self.current_band = []
            self.band_depth = 1
        elif tag == 'div' and self.current_band is not None:
            self.band_depth += 1
        elif tag == 'table' and {'production-table', 'usage-table'} & set(classes):
            table_type = 'production' if 'production-table' in classes else 'usage'
            self.current_table = dict(type=table_type, rows=[], columns=[])
        elif self.current_table is not None and tag == 'colgroup':
            self.reading_colgroup = True
        elif self.current_table is not None and self.reading_colgroup and tag == 'col':
            self.current_table['columns'].append(attrs.get('class'))
        elif self.current_table is not None and tag == 'tr':
            self.current_row = []
        elif self.current_row is not None and tag in ('th', 'td'):
            self.current_cell = [int(attrs.get('colspan', '1')), '']
            self.current_row.append(self.current_cell)

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell[1] += data

    def handle_endtag(self, tag):
        if tag in ('th', 'td'):
            self.current_cell = None
        elif tag == 'tr' and self.current_row is not None:
            self.current_table['rows'].append(self.current_row)
            self.current_row = None
        elif tag == 'colgroup':
            self.reading_colgroup = False
        elif tag == 'table' and self.current_table is not None:
            self.current_band.append(self.current_table)
            if self.current_table['type'] == 'production':
                self.tables.append(self.current_table)
            self.current_table = None
        elif tag == 'div' and self.current_band is not None:
            self.band_depth -= 1
            if self.band_depth == 0:
                self.bands.append(self.current_band)
                self.current_band = None


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

    def test_print_prod_formats_decimal_usage_to_one_place(self):
        report = dict(records=[dict(ProdDate=DAY, Shift='1', LotNo='I01690901',
                                    ProductCode='01', ProductName='ปิดจั่ว', PlanQty=800,
                                    CounterQty=910, CuringQty=890, WetRejectQty=5,
                                    WetRejectPercent=5.26)],
                      shifts=[dict(shift='1', records=[], totals=dict(PlanQty=800,
                               CounterQty=910, CuringQty=890), materials=[
                                   dict(MaterialNameEN='Cement', RawQty=Decimal('30.000'),
                                        QtyPer1000Counter=Decimal('6.896551'),
                                        QtyPer1000Curing=Decimal('7.145409'),
                                        CounterPerUnit=Decimal('13.553806'))])],
                      daily_totals=dict(PlanQty=800, CounterQty=910, CuringQty=890),
                      daily_materials=[dict(MaterialNameEN='Cement', RawQty=Decimal('20.000'),
                                            QtyPer1000Counter=Decimal('13.123359'),
                                            QtyPer1000Curing=Decimal('33.707865'))],
                      plan_week='2026W37')
        with patch('app.main.read_print_prod_context', return_value=report):
            status, body = asyncio.run(get_page('/print-prod', 'production_date=2026-09-22'))[:2]
        self.assertEqual(status, 200)
        for value in ('30.0', '6.9', '7.1', '20.0', '13.1', '33.7'):
            self.assertIn(value, body)
        self.assertIn('>800<', body)
        self.assertNotIn('800.0', body)
        self.assertIn('/print-prod/pdf?production_date=2026-09-22', body)

    def test_print_prod_three_decimal_materials_and_compact_shift_layout(self):
        three_decimal_codes = (
            'flyAsh', 'cementBody', 'cementColor', 'sandBody', 'sandColor',
            'calcium', 'waterBaseSpray', 'mouldOil', 'palletOil', 'ft30',
            'bl', 'adva',
        )
        materials = [
            dict(MaterialUsageCode=code, MaterialNameEN=code,
                 RawQty=Decimal(f'{index}.0'),
                 QtyPer1000Counter=Decimal(f'{100 + index}.0'),
                 QtyPer1000Curing=Decimal(f'{200 + index}.4'))
            for index, code in enumerate(three_decimal_codes, 1)
        ]
        materials.append(dict(MaterialUsageCode='cementBatchUsed', MaterialNameEN='Batch',
                              RawQty=Decimal('0.2'), QtyPer1000Counter=None,
                              QtyPer1000Curing=None))
        records = [dict(Shift=shift, LotNo='LOT-' + shift, PlanName='Plan',
                        MaterialName='Long product name to wrap safely', PlanQty=8,
                        CounterQty=7, CuringQty=6, WetRejectQty=None)
                   for shift in ('1', '2')]
        report = dict(
            records=records,
            shifts=[
                dict(shift=shift, records=[record], totals=dict(PlanQty=8, CounterQty=7,
                     CuringQty=6), materials=materials)
                for shift, record in zip(('1', '2'), records)
            ],
            daily_totals=dict(PlanQty=16, CounterQty=14, CuringQty=12),
            daily_materials=materials,
            plan_week='2026W37',
        )
        with patch('app.main.read_print_prod_context', return_value=report):
            status, body = asyncio.run(get_page('/print-prod', 'production_date=2026-09-22'))[:2]

        self.assertEqual(status, 200)
        self.assertIn('กะ1', body)
        self.assertIn('กะ2', body)
        self.assertNotIn('class="shift-row"', body)
        self.assertIn('grid-template-columns:minmax(0,33fr) minmax(0,67fr)', body)
        self.assertIn('td.product{white-space:normal;overflow-wrap:anywhere', body)
        self.assertNotIn('line-clamp', body)
        for index in range(1, len(three_decimal_codes) + 1):
            for value in (f'{index}.000', f'{100 + index}.000',
                          f'{200 + index}.400'):
                self.assertIn(f'>{value}</td>', body)
        self.assertIn('0.2', body)
        self.assertNotIn('0.200', body)
        self.assertIn("content:none", body)
        self.assertIn("window.print()", body)
        self.assertIn('/print-prod/pdf?production_date=2026-09-22', body)

    def test_production_tables_share_columns_and_all_shift_totals_align(self):
        shift_materials = [
            dict(MaterialUsageCode='flyAsh', MaterialNameTH='เถ้าลอย',
                 RawQty=Decimal('20.0'), QtyPer1000Counter=Decimal('2.0'),
                 QtyPer1000Curing=Decimal('3.0')),
            dict(MaterialUsageCode='cementBatchUsed', MaterialNameEN='Batch',
                 RawQty=Decimal('1.2'), QtyPer1000Counter=None,
                 QtyPer1000Curing=None),
        ]
        daily_materials = [
            dict(MaterialUsageCode='flyAsh', MaterialNameTH='เถ้าลอย',
                 RawQty=Decimal('45.0'), QtyPer1000Counter=Decimal('4.5'),
                 QtyPer1000Curing=Decimal('5.5')),
            dict(MaterialUsageCode='cementBatchUsed', MaterialNameEN='Batch',
                 RawQty=Decimal('3.4'), QtyPer1000Counter=None,
                 QtyPer1000Curing=None),
        ]
        report = dict(
            records=[],
            shifts=[
                dict(shift=shift, records=[
                    dict(Shift=shift, LotNo='LOT-' + shift, PlanName='Plan',
                         MaterialName='Readable two-line product title',
                         PlanQty=10, CounterQty=9, CuringQty=8, WetRejectQty=1,
                         WetRejectPercent=10)
                ], totals=dict(PlanQty=10, CounterQty=9, CuringQty=8),
                     materials=shift_materials)
                for shift in ('1', '2')
            ],
            daily_totals=dict(PlanQty=20, CounterQty=18, CuringQty=16),
            daily_materials=daily_materials, plan_week='2026W37',
        )
        with patch('app.main.read_print_prod_context', return_value=report):
            status, body = asyncio.run(get_page('/print-prod', 'production_date=2026-09-22'))[:2]

        self.assertEqual(status, 200)
        parser = ProductionTableParser()
        parser.feed(body)
        self.assertEqual(len(parser.tables), 3)
        self.assertEqual(len(parser.bands), 3)
        production_columns = ['shift-column', 'lot-column', 'product-column',
                              'plan-column', 'counter-column', 'curing-column',
                              'reject-column']
        material_columns = ['usage-label-column', 'usage-material-column',
                            'usage-material-column']
        for table in parser.tables:
            self.assertEqual(table['columns'], production_columns)
            for row in table['rows']:
                self.assertEqual(sum(cell[0] for cell in row), 7)
        for band in parser.bands:
            self.assertEqual([table['type'] for table in band], ['production', 'usage'])
            self.assertEqual(band[1]['columns'], material_columns)

        for table, shift in zip(parser.tables[:2], ('1', '2')):
            self.assertEqual([cell[1].strip() for cell in table['rows'][0]],
                             [f'กะ{shift}', 'LOT NO.', 'Product', 'Plan',
                              'Counter', 'Curing', 'Wet Reject'])
            self.assertEqual(table['rows'][-1][0][0], 3)

        all_shift_row = parser.tables[2]['rows'][0]
        self.assertEqual([cell[0] for cell in all_shift_row], [3, 1, 1, 1, 1])
        self.assertEqual([cell[1].strip() for cell in all_shift_row],
                         ['รวมทุกกะ', '20', '18', '16', '-'])
        total_material_rows = parser.bands[2][1]['rows']
        self.assertEqual([cell[1].strip() for cell in total_material_rows[0]],
                         ['ปริมาณการใช้รวม', '45.000', '3.4'])
        self.assertEqual([cell[1].strip() for cell in total_material_rows[1]],
                         ['คำนวณจาก Counter (ต่อพันแผ่น)', '4.500', '-'])
        self.assertEqual([cell[1].strip() for cell in total_material_rows[2]],
                         ['คำนวณจาก ห้องบ่ม (ต่อพันแผ่น)', '5.500', '-'])
        self.assertNotIn('<table class="report-table overall-usage-table"', body)
        self.assertNotIn('ปริมาณการใช้รวม / คำนวณจากรวมทุกกะ', body)
        self.assertIn('.shift-band{grid-template-columns:minmax(0,33fr) minmax(0,67fr)', body)
        self.assertIn('@media print', body)
        self.assertIn('.production-table,.production-table th,.production-table td{font-size:8px}', body)
        self.assertIn('overflow-wrap:anywhere', body)
        self.assertIn('/print-prod/pdf?production_date=2026-09-22', body)

    def test_print_oee_route_preserves_date(self):
        with patch('app.main.read_print_oee_context', return_value={
                'rows': [], 'excluded': [], 'summaries': {'1': {}, '2': {}, 'ALL DAY': {}},
                'shifts': ('1', '2')}):
            status, body, _ = self.page('/print-oee', 'production_date=2026-09-22')
        self.assertEqual(status, 200)
        self.assertIn('รายงานประสิทธิภาพการผลิต / OEE', body)
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