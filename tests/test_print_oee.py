import tempfile
import unittest
from datetime import date, time
from decimal import Decimal
from unittest.mock import patch

from app.main import print_oee_pdf_page
from app.print_oee import calculate_oee_row, summarize


DAY = date(2026, 9, 26)


def row(**overrides):
    value = dict(
        MachineCode='F2', ProductionStartTime='08:00', ProductionEndTime='10:00',
        SetupMinutes=10, ChangeoverMinutes=5, IdleMinutes=0,
        CleaningMinutes=0, BreakdownMinutes=0, CounterQty=90, CuringQty=80,
        StandardSpeed=Decimal('0.5'), CapabilityIsActive=True,
    )
    value.update(overrides)
    return value


class PrintOeeCalculationTests(unittest.TestCase):
    def calculate(self, **overrides):
        return calculate_oee_row(row(**overrides), DAY, time(6, 0))

    def test_normal_row_uses_standard_oee_algebra(self):
        result = self.calculate()
        self.assertTrue(result['Eligible'])
        self.assertEqual(result['PlannedTime'], Decimal('120'))
        self.assertEqual(result['RunTime'], Decimal('105'))
        self.assertEqual(result['Availability'], Decimal('0.875'))
        self.assertEqual(result['Performance'], Decimal(90) / Decimal('52.5'))
        self.assertEqual(result['Quality'], Decimal(80) / Decimal(90))
        self.assertEqual(result['OEE'], Decimal(80) / Decimal('60'))

    def test_overnight_times_are_resolved(self):
        result = self.calculate(ProductionStartTime='22:00', ProductionEndTime='03:00')
        self.assertEqual(result['PlannedTime'], Decimal('300'))
        self.assertTrue(result['Eligible'])

    def test_speed_changes_performance_and_summary_uses_raw_components(self):
        first = self.calculate(StandardSpeed=Decimal('1'), CounterQty=100, CuringQty=90)
        second = calculate_oee_row(row(StandardSpeed=Decimal('2'), CounterQty=100, CuringQty=90), DAY, time(6, 0))
        summary = summarize([first, second])
        self.assertEqual(summary['Performance'], Decimal(200) / Decimal(315))
        self.assertNotEqual(summary['Performance'], (first['Performance'] + second['Performance']) / 2)

    def test_missing_inactive_null_and_zero_speed_are_not_eligible(self):
        for overrides in ({'StandardSpeed': None}, {'CapabilityIsActive': False}, {'StandardSpeed': 0}):
            result = self.calculate(**overrides)
            self.assertFalse(result['Eligible'])
            self.assertIsNone(result['Performance'])
            self.assertIsNone(result['OEE'])

    def test_invalid_time_and_loss_exclude_row(self):
        for overrides in ({'ProductionStartTime': None}, {'ProductionEndTime': None},
                          {'SetupMinutes': 121}, {'ProductionStartTime': '10:00', 'ProductionEndTime': '08:00'}):
            result = self.calculate(**overrides)
            self.assertFalse(result['Eligible'])
            self.assertIn('Invalid production time', result['Status'])

    def test_invalid_counts_exclude_row_and_zero_counter_has_no_quality(self):
        for overrides in ({'CounterQty': 0, 'CuringQty': 0}, {'CounterQty': 10, 'CuringQty': 11}):
            result = self.calculate(**overrides)
            if overrides['CounterQty'] == 0:
                self.assertTrue(result['Eligible'])
                self.assertIsNone(result['Quality'])
            else:
                self.assertFalse(result['Eligible'])
                self.assertIn('Invalid count', result['Status'])

    def test_performance_over_one_is_not_clamped(self):
        result = self.calculate(StandardSpeed=Decimal('0.1'), CounterQty=200, CuringQty=100)
        self.assertGreater(result['Performance'], 1)
        self.assertGreater(result['OEE'], 1)

    def test_shift_and_all_day_summaries_exclude_ineligible_rows(self):
        eligible = self.calculate()
        excluded = self.calculate(StandardSpeed=None, MachineCode='F3')
        shift_one = summarize([eligible, excluded])
        all_day = summarize([eligible, excluded, eligible])
        self.assertEqual(shift_one['ExcludedCount'], 1)
        self.assertEqual(shift_one['TotalCount'], eligible['Counter'])
        self.assertEqual(all_day['TotalCount'], eligible['Counter'] * 2)
        self.assertEqual(all_day['EligibleCount'], 2)

    def test_pdf_route_preserves_date_and_filename(self):
        output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        output.write(b'%PDF-1.7\nvalid')
        output.close()
        root = tempfile.mkdtemp()
        process = object()
        with patch('app.main.generate_print_oee_pdf', return_value=(root, output.name, process)):
            response = print_oee_pdf_page(date(2026, 9, 26))
        self.assertEqual(response.media_type, 'application/pdf')
        self.assertIn('PRINT_OEE_2026-09-26.pdf', response.headers['content-disposition'])


if __name__ == '__main__':
    unittest.main()