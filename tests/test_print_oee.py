import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch

from app.main import print_oee_pdf_page
from app.print_oee import (_query_rows, calculate_oee_row,
                           read_print_oee_context, summarize)
from app.press_production import calculate_smdt


DAY = date(2026, 9, 26)
SHIFT_RULES = [
    {'ShiftID': 1, 'StartTime': time(6, 0)},
    {'ShiftID': 2, 'StartTime': time(19, 0)},
]


def row(**overrides):
    value = dict(
        MachineCode='F2', Shift='1', AssignmentShiftCode='1',
        AssignmentShiftUnknown=False, LotStartTime='08:00', LotEndTime='10:00',
        ProductionStartTime=None, ProductionEndTime=None,
        SetupMinutes=10, ChangeoverMinutes=5, IdleMinutes=0,
        CleaningMinutes=0, BreakdownMinutes=0, CounterQty=90, CuringQty=80,
        StandardSpeed=Decimal('0.5'), CapabilityIsActive=True,
    )
    value.update(overrides)
    return value


class PrintOeeCalculationTests(unittest.TestCase):
    def calculate(self, **overrides):
        return calculate_oee_row(row(**overrides), DAY, time(8, 0), SHIFT_RULES)

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
        result = self.calculate(Shift='2', AssignmentShiftCode='2',
                                LotStartTime='22:00', LotEndTime='03:00')
        self.assertEqual(result['PlannedTime'], Decimal('300'))
        self.assertEqual(result['StartDateTime'].date(), DAY)
        self.assertEqual(result['EndDateTime'].date(), DAY.replace(day=27))
        self.assertTrue(result['Eligible'])

    def test_production_day_cutoff_moves_early_run_times_to_next_calendar_date(self):
        result = calculate_oee_row(
            row(Shift='2', AssignmentShiftCode='2',
                LotStartTime='05:00', LotEndTime='07:00'),
            DAY, time(8, 0), SHIFT_RULES)
        self.assertEqual(result['StartDateTime'].date(), DAY.replace(day=27))
        self.assertEqual(result['EndDateTime'].date(), DAY.replace(day=27))
        self.assertEqual(result['PlannedTime'], Decimal('60'))

    def test_lot_interval_is_allocated_to_each_assigned_shift(self):
        lot_interval = dict(LotStartTime='08:00', LotEndTime='03:00')
        shift_one = self.calculate(**lot_interval)
        shift_two = self.calculate(Shift='2', AssignmentShiftCode='2', **lot_interval)
        self.assertEqual(shift_one['PlannedTime'], Decimal('660'))
        self.assertEqual(shift_one['Start'], '08:00')
        self.assertEqual(shift_one['End'], '19:00')
        self.assertEqual(shift_two['PlannedTime'], Decimal('480'))
        self.assertEqual(shift_two['Start'], '19:00')
        self.assertEqual(shift_two['End'], '03:00')
        self.assertEqual(shift_two['EndDateTime'].date(), DAY.replace(day=27))

    def test_configured_shift_boundaries_are_used_instead_of_fixed_clock_values(self):
        rules = [
            {'ShiftID': 1, 'StartTime': time(7, 0)},
            {'ShiftID': 2, 'StartTime': time(20, 0)},
        ]
        result = calculate_oee_row(
            row(LotStartTime='08:00', LotEndTime='21:00'),
            DAY, time(8, 0), rules)
        self.assertEqual(result['PlannedTime'], Decimal('720'))
        self.assertEqual(result['Start'], '08:00')
        self.assertEqual(result['End'], '20:00')

    def test_lot_entirely_inside_shift_two_and_partial_shift_edges(self):
        inside = self.calculate(Shift='2', AssignmentShiftCode='2',
                                LotStartTime='21:00', LotEndTime='02:00')
        shift_one_end = self.calculate(LotStartTime='08:00', LotEndTime='15:00')
        after_shift_two_start = self.calculate(
            Shift='2', AssignmentShiftCode='2', LotStartTime='21:00', LotEndTime='03:00')
        self.assertEqual(inside['PlannedTime'], Decimal('300'))
        self.assertEqual(shift_one_end['PlannedTime'], Decimal('420'))
        self.assertEqual(after_shift_two_start['PlannedTime'], Decimal('360'))

    def test_pressproduction_times_are_not_required_or_used(self):
        result = self.calculate(ProductionStartTime='22:00', ProductionEndTime='23:00')
        self.assertEqual(result['PlannedTime'], Decimal('120'))
        self.assertEqual(result['Start'], '08:00')
        self.assertEqual(result['End'], '10:00')

    def test_legacy_unknown_shift_is_not_inferred_from_lot_times(self):
        result = self.calculate(Shift='UNKNOWN', AssignmentShiftCode=None,
                                AssignmentShiftUnknown=True)
        self.assertFalse(result['Eligible'])
        self.assertIn('Assignment Shift unknown', result['Status'])
        self.assertIsNone(result['PlannedTime'])
        self.assertIsNone(result['OEE'])

    def test_downtime_exceeding_shift_interval_is_reported_without_valid_oee(self):
        result = self.calculate(
            Shift='2', AssignmentShiftCode='2', LotStartTime='08:00',
            LotEndTime='03:00', SetupMinutes=995, ChangeoverMinutes=0)
        self.assertEqual(result['PlannedTime'], Decimal('480'))
        self.assertEqual(result['TotalLoss'], Decimal('995'))
        self.assertEqual(result['RunTime'], Decimal('-515'))
        self.assertIn('Downtime exceeds allocated Shift time', result['Status'])
        self.assertFalse(result['Eligible'])
        self.assertIsNone(result['Availability'])
        self.assertIsNone(result['Performance'])
        self.assertIsNone(result['OEE'])

    def test_shift_reports_numerical_oee_released_history_and_excludes_ambiguous_episodes(self):
        def source(press_id, machine, shift_code, start, end, released_at=None,
                   ambiguous=False, **overrides):
            value = row(
                PressProductionID=press_id, ProductionID=19, MachineCode=machine,
                ShiftMasterID=101 if shift_code == '1' else 202,
                AssignmentShiftCode=shift_code, TimeIdentityAmbiguous=ambiguous,
                AssignmentShiftUnknown=False, LotStartTime=start,
                LotEndTime=end, SetupMinutes=10, ChangeoverMinutes=5,
                IdleMinutes=5, CleaningMinutes=2, BreakdownMinutes=8,
                CounterQty=84, CuringQty=70, StandardSpeed=Decimal('0.4'),
                CapabilityIsActive=True, ReleasedAt=released_at)
            value.update(overrides)
            return value

        sources = [
            source(201, 'F2', '1', '09:00', '13:00'),
            source(202, 'F2', '2', '21:00', '02:00',
                   released_at=datetime(2026, 9, 26, 23, 0),
                   CounterQty=108, CuringQty=90),
            source(203, 'F3', '2', '21:00', '02:00', ambiguous=True),
            source(204, 'F3', '2', '21:00', '02:00', ambiguous=True),
        ]
        with patch('app.print_oee.read_day_start_time', return_value=time(8, 0)), \
             patch('app.print_oee.read_plan_week', return_value='2026-W39'), \
             patch('app.print_oee.read_shift_rules', return_value=SHIFT_RULES), \
             patch('app.print_oee._query_rows', return_value=sources):
            report = read_print_oee_context(object(), DAY)

        shift_one = report['summaries']['1']
        shift_two = report['summaries']['2']
        self.assertEqual(shift_one['PlannedTime'], Decimal('240'))
        self.assertEqual(shift_one['RunTime'], Decimal('210'))
        self.assertEqual(shift_one['Availability'], Decimal('0.875'))
        self.assertEqual(shift_one['Performance'], Decimal('1'))
        self.assertEqual(shift_one['Quality'], Decimal(5) / Decimal(6))
        self.assertAlmostEqual(shift_one['OEE'], Decimal(35) / Decimal(48), places=25)
        self.assertEqual(shift_two['PlannedTime'], Decimal('300'))
        self.assertEqual(shift_two['RunTime'], Decimal('270'))
        self.assertEqual(shift_two['Availability'], Decimal('0.9'))
        self.assertEqual(shift_two['Performance'], Decimal('1'))
        self.assertEqual(shift_two['Quality'], Decimal(5) / Decimal(6))
        self.assertEqual(shift_two['OEE'], Decimal('0.75'))
        self.assertEqual(shift_two['EligibleCount'], 1)
        self.assertEqual(shift_two['ExcludedCount'], 2)
        self.assertEqual([item['PressProductionID'] for item in report['rows']],
                         [201, 202, 203, 204])
        self.assertEqual(report['rows'][1]['ReleasedAt'],
                         datetime(2026, 9, 26, 23, 0))
        self.assertIsNone(report['rows'][2]['OEE'])
        self.assertIsNone(report['rows'][3]['OEE'])
        self.assertEqual(
            calculate_smdt(
                report['rows'][0]['StartDateTime'],
                report['rows'][0]['EndDateTime'],
                {'SETUP': Decimal(10), 'CHANGEOVER': Decimal(5),
                 'IDLE': Decimal(5), 'CLEAN': Decimal(2), 'BREAKDOWN': Decimal(8)}),
            Decimal('210'))

    def test_speed_changes_performance_and_summary_uses_raw_components(self):
        first = self.calculate(StandardSpeed=Decimal('1'), CounterQty=100, CuringQty=90)
        second = calculate_oee_row(row(StandardSpeed=Decimal('2'), CounterQty=100, CuringQty=90),
                                   DAY, time(8, 0), SHIFT_RULES)
        summary = summarize([first, second])
        self.assertEqual(summary['Performance'], Decimal(200) / Decimal(315))
        self.assertNotEqual(summary['Performance'], (first['Performance'] + second['Performance']) / 2)

    def test_missing_inactive_null_and_zero_speed_are_not_eligible(self):
        for overrides in ({'StandardSpeed': None}, {'CapabilityIsActive': False}, {'StandardSpeed': 0}):
            result = self.calculate(**overrides)
            self.assertFalse(result['Eligible'])
            self.assertIsNone(result['Performance'])
            self.assertIsNone(result['OEE'])

    def test_ambiguous_episode_downtime_and_unknown_assignment_shift_are_excluded(self):
        for field, expected in (
                ('TimeIdentityAmbiguous', 'Ambiguous Press/Shift downtime'),
                ('AssignmentShiftUnknown', 'Assignment Shift unknown')):
            result = self.calculate(**{field: True})
            self.assertFalse(result['Eligible'])
            self.assertIn(expected, result['Status'])
            self.assertIsNone(result['OEE'])

    def test_oee_query_scopes_time_events_and_flags_reused_press_shift_episodes(self):
        class Cursor:
            def __init__(self, shift_schema=True):
                self.statements = []
                self.description = []
                self.result = []
                self.shift_schema = shift_schema

            def execute(self, sql, *args):
                self.statements.append((sql, args))
                self.result = [(int(self.shift_schema),)] if 'COL_LENGTH(' in sql else []

            def fetchone(self):
                return self.result.pop(0) if self.result else None

            def fetchall(self):
                return []

        cursor = Cursor()
        self.assertEqual(_query_rows(cursor, DAY), [])
        sql, args = cursor.statements[-1]
        self.assertIn('event.ShiftID=TRY_CONVERT(int,shift.ShiftCode)', sql)
        self.assertIn('AS TimeIdentityAmbiguous', sql)
        self.assertIn('LEFT JOIN dbo.ProductionData AS lot_data', sql)
        self.assertIn('lot_data.ProductionStartTime AS LotStartTime', sql)
        self.assertIn('lot_data.ProductionEndTime AS LotEndTime', sql)
        self.assertNotIn('pp.ProductionStartTime', sql)
        self.assertNotIn('pp.ProductionEndTime', sql)
        self.assertIn('other.ShiftMasterID=pp.ShiftMasterID', sql)
        self.assertIn('AND NOT EXISTS', sql)
        self.assertIn('AND pp.ShiftMasterID IS NOT NULL', sql)
        self.assertIn("event.SourceType='MANUAL'", sql)
        self.assertIn("event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN')", sql)
        self.assertNotIn('SMDT', sql)
        self.assertNotIn('pp.ReleasedAt IS NULL', sql)
        self.assertLess(sql.index('LEFT JOIN dbo.ShiftMaster'),
                        sql.index('LEFT JOIN dbo.EquipmentTimeEvent'))
        self.assertEqual(args, (DAY,))

    def test_oee_query_does_not_reference_unapplied_shift_column(self):
        class Cursor:
            def __init__(self):
                self.statements = []
                self.description = []
                self.result = []

            def execute(self, sql, *args):
                self.statements.append((sql, args))
                self.result = [(0,)] if 'COL_LENGTH(' in sql else []

            def fetchone(self):
                return self.result.pop(0) if self.result else None

            def fetchall(self):
                return []

        cursor = Cursor()
        self.assertEqual(_query_rows(cursor, DAY), [])
        sql, args = cursor.statements[-1]
        self.assertNotIn('pp.ShiftMasterID', sql)
        self.assertNotIn('event.ShiftID=TRY_CONVERT', sql)
        self.assertIn('LEFT JOIN dbo.ProductionData AS lot_data', sql)
        self.assertEqual(args, (DAY,))

    def test_invalid_time_and_loss_exclude_row(self):
        for overrides in ({'LotStartTime': None}, {'LotEndTime': None},
                          {'LotStartTime': '10:00', 'LotEndTime': '08:00'}):
            result = self.calculate(**overrides)
            self.assertFalse(result['Eligible'])
            self.assertIn('Invalid production time', result['Status'])
        excessive = self.calculate(SetupMinutes=121)
        self.assertFalse(excessive['Eligible'])
        self.assertIn('Downtime exceeds allocated Shift time', excessive['Status'])
        self.assertNotIn('Invalid production time', excessive['Status'])

    def test_multiple_presses_in_one_shift_keep_individual_planned_time(self):
        first = self.calculate(PressProductionID=1, LotStartTime='08:00', LotEndTime='19:00')
        second = self.calculate(PressProductionID=2, MachineCode='F3',
                                LotStartTime='08:00', LotEndTime='19:00')
        summary = summarize([first, second])
        self.assertEqual(first['PlannedTime'], Decimal('660'))
        self.assertEqual(second['PlannedTime'], Decimal('660'))
        self.assertEqual(summary['PlannedTime'], Decimal('1320'))
        self.assertEqual(summary['EligibleCount'], 2)

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