import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.main import print_oee_page, print_oee_pdf_page
from app.print_oee import (
    LOGGER_CATEGORIES, LOGGER_CATEGORY_CODES, _breakdown_details,
    _process_logger_events,
    _query_logger_details, _query_rows, build_press_production_summary,
    build_press_production_totals, build_logger_category_table,
    calculate_oee_row,
    read_print_oee_context, summarize,
)


DAY = date(2026, 9, 26)


def row(**overrides):
    value = dict(
        PressProductionID=101, ProductionID=21, MachineCode='F2',
        Shift='1', ShiftMasterID=301, AssignmentShiftCode='1',
        AssignmentShiftUnknown=False, LotStartTime='08:00', LotEndTime='10:00',
        ProductionStartTime=datetime(2026, 9, 26, 8),
        ProductionEndTime=datetime(2026, 9, 26, 10),
        DispatchQty=100, SetupMinutes=10, ChangeoverMinutes=5, IdleMinutes=0,
        CleaningMinutes=0, BreakdownMinutes=0, CounterQty=90, CuringQty=80,
        StandardSpeed=Decimal('0.5'), CapabilityIsActive=True,
    )
    value.update(overrides)
    return value


class PrintOeeCalculationTests(unittest.TestCase):
    def calculate(self, **overrides):
        return calculate_oee_row(row(**overrides))

    def test_row_uses_press_times_and_preserves_standard_oee_algebra(self):
        result = self.calculate()
        self.assertTrue(result['Eligible'])
        self.assertEqual(result['ActualProductionMinutes'], Decimal('120'))
        self.assertEqual(result['RunTime'], Decimal('105'))
        self.assertEqual(result['Reject'], Decimal('10'))
        self.assertEqual(result['Availability'], Decimal('0.875'))
        self.assertEqual(result['Performance'], Decimal(90) / Decimal('52.5'))
        self.assertEqual(result['Quality'], Decimal(80) / Decimal(90))
        self.assertEqual(result['OEE'], Decimal(80) / Decimal('60'))
        self.assertEqual((result['Start'], result['End']), ('08:00', '10:00'))

    def test_cross_midnight_press_interval_uses_elapsed_time(self):
        result = self.calculate(
            Shift='2', AssignmentShiftCode='2',
            ProductionStartTime=datetime(2026, 9, 26, 22),
            ProductionEndTime=datetime(2026, 9, 27, 3),
            LotStartTime=None, LotEndTime=None)
        self.assertEqual(result['ActualProductionMinutes'], Decimal('300'))
        self.assertEqual(result['Start'], '22:00')
        self.assertEqual(result['End'], '03:00')
        self.assertEqual(result['EndDateTime'].date(), DAY + timedelta(days=1))
        self.assertTrue(result['Eligible'])

    def test_missing_press_times_are_explicit_and_do_not_fall_back_to_lot_times(self):
        for overrides in (
                {'ProductionStartTime': None, 'ProductionEndTime': None},
                {'ProductionStartTime': datetime(2026, 9, 26, 8),
                 'ProductionEndTime': None}):
            result = self.calculate(**overrides)
            self.assertFalse(result['Eligible'])
            self.assertIn('Missing Press Start/End time', result['Status'])
            self.assertIsNone(result['ActualProductionMinutes'])
            self.assertIsNone(result['Availability'])
            self.assertIsNone(result['OEE'])

    def test_invalid_or_zero_length_press_interval_is_rejected(self):
        for end in (datetime(2026, 9, 26, 7), datetime(2026, 9, 26, 8)):
            result = self.calculate(ProductionEndTime=end)
            self.assertFalse(result['Eligible'])
            self.assertIn('Invalid Press Start/End time', result['Status'])
            self.assertIsNone(result['OEE'])

    def test_unknown_assignment_shift_is_not_inferred_from_lot_times(self):
        result = self.calculate(
            Shift='UNKNOWN', ShiftMasterID=None, AssignmentShiftCode=None,
            AssignmentShiftUnknown=True)
        self.assertFalse(result['Eligible'])
        self.assertIn('Assignment Shift unknown', result['Status'])
        self.assertEqual(result['ActualProductionMinutes'], Decimal('120'))
        self.assertIsNone(result['OEE'])

    def test_shift_rows_keep_independent_press_intervals_and_summary_values(self):
        first = self.calculate(
            PressProductionID=201, Shift='1', AssignmentShiftCode='1',
            ProductionStartTime=datetime(2026, 9, 26, 8),
            ProductionEndTime=datetime(2026, 9, 26, 12))
        second = self.calculate(
            PressProductionID=202, Shift='2', AssignmentShiftCode='2',
            ProductionStartTime=datetime(2026, 9, 26, 19),
            ProductionEndTime=datetime(2026, 9, 27, 2))
        self.assertEqual(first['ActualProductionMinutes'], Decimal('240'))
        self.assertEqual(second['ActualProductionMinutes'], Decimal('420'))
        self.assertEqual(summarize([first])['ActualProductionMinutes'], Decimal('240'))
        self.assertEqual(summarize([second])['ActualProductionMinutes'], Decimal('420'))

    def test_logger_and_breakdown_details_do_not_change_manual_downtime_oee(self):
        baseline = self.calculate()
        with_logger = self.calculate(LoggerEvents=[{'DurationMin': 45, 'CauseId': 3}])
        _breakdown_details([{
            'StopId': 7, 'DurationMin': Decimal(45),
            'LoggerEventID': 1,
        }])
        for field in ('TotalLoss', 'RunTime', 'Availability', 'Performance', 'Quality', 'OEE'):
            self.assertEqual(with_logger[field], baseline[field])

    def test_invalid_manual_loss_is_excluded_and_excessive_loss_has_no_oee(self):
        excessive = self.calculate(SetupMinutes=121)
        self.assertFalse(excessive['Eligible'])
        self.assertIn('Downtime exceeds actual production time', excessive['Status'])
        self.assertIsNone(excessive['Availability'])
        self.assertIsNone(excessive['OEE'])

    def test_summary_uses_raw_components_and_excludes_ineligible_rows(self):
        eligible = self.calculate()
        excluded = self.calculate(ProductionStartTime=None, ProductionEndTime=None)
        summary = summarize([eligible, excluded, eligible])
        self.assertEqual(summary['ActualProductionMinutes'], Decimal('240'))
        self.assertEqual(summary['TotalCount'], Decimal('180'))
        self.assertEqual(summary['EligibleCount'], 2)
        self.assertEqual(summary['ExcludedCount'], 1)

    def test_missing_speed_and_invalid_counts_remain_ineligible(self):
        missing_speed = self.calculate(StandardSpeed=None)
        invalid_counts = self.calculate(CounterQty=10, CuringQty=11)
        self.assertIsNone(missing_speed['Performance'])
        self.assertIsNone(missing_speed['OEE'])
        self.assertIn('Invalid count', invalid_counts['Status'])
        self.assertIsNone(invalid_counts['Reject'])

    def test_press_summary_aligns_shift_one_and_two_on_one_press_row(self):
        first = calculate_oee_row(row(
            PressProductionID=1, MachineCode='F7', Shift='1',
            ShiftMasterID=101, MouldName='Mould Alpha',
            StandardSpeed=Decimal('0.50'),
            ProductionStartTime=datetime(2026, 9, 26, 8),
            ProductionEndTime=datetime(2026, 9, 26, 10),
            CounterQty=100, CuringQty=95))
        second = calculate_oee_row(row(
            PressProductionID=2, MachineCode='F7', Shift='2',
            ShiftMasterID=102, MouldName='Mould Alpha',
            StandardSpeed=Decimal('0.50'),
            ProductionStartTime=datetime(2026, 9, 26, 22),
            ProductionEndTime=datetime(2026, 9, 27, 1),
            CounterQty=80, CuringQty=79))
        summaries = build_press_production_summary([first, second])
        self.assertEqual(len(summaries), 1)
        press = summaries[0]
        self.assertEqual((press['Press'], press['Mould']), ('F7', 'Mould Alpha'))
        self.assertEqual(press['StandardSpeed'], '0.5')
        self.assertEqual(press['Shift1']['ProductionMinutes'], Decimal(120))
        self.assertEqual(press['Shift1']['Counter'], Decimal(100))
        self.assertEqual(press['Shift1']['Curing'], Decimal(95))
        self.assertEqual(press['Shift1']['WetReject'], Decimal(5))
        self.assertEqual(press['Shift2']['ProductionMinutes'], Decimal(180))
        self.assertEqual(press['Shift2']['WetReject'], Decimal(1))
        self.assertEqual(press['TotalProductionMinutes'], Decimal(300))

    def test_press_summary_bottom_totals_add_each_press_once(self):
        episodes = [
            calculate_oee_row(row(
                PressProductionID=1, MachineCode='F7', Shift='1',
                ShiftMasterID=101,
                ProductionStartTime=datetime(2026, 9, 26, 8),
                ProductionEndTime=datetime(2026, 9, 26, 10),
                CounterQty=100, CuringQty=95)),
            calculate_oee_row(row(
                PressProductionID=2, MachineCode='F7', Shift='2',
                ShiftMasterID=102,
                ProductionStartTime=datetime(2026, 9, 26, 22),
                ProductionEndTime=datetime(2026, 9, 27, 1),
                CounterQty=80, CuringQty=79)),
            calculate_oee_row(row(
                PressProductionID=3, MachineCode='F8', Shift='1',
                ShiftMasterID=101,
                ProductionStartTime=datetime(2026, 9, 26, 9),
                ProductionEndTime=datetime(2026, 9, 26, 10),
                CounterQty=50, CuringQty=45)),
        ]
        press_rows = build_press_production_summary(episodes)
        totals = build_press_production_totals(press_rows)
        self.assertEqual(totals['Shift1']['ProductionMinutes'], Decimal(180))
        self.assertEqual(totals['Shift1']['Counter'], Decimal(150))
        self.assertEqual(totals['Shift1']['Curing'], Decimal(140))
        self.assertEqual(totals['Shift1']['WetReject'], Decimal(10))
        self.assertEqual(totals['Shift2']['ProductionMinutes'], Decimal(180))
        self.assertEqual(totals['Shift2']['WetReject'], Decimal(1))
        self.assertEqual(totals['TotalProductionMinutes'], Decimal(360))

    def test_multiple_press_shift_episodes_are_preserved_and_additive(self):
        episodes = [
            calculate_oee_row(row(
                PressProductionID=1, MachineCode='F7', Shift='1',
                ShiftMasterID=101, MouldName='Mould Alpha',
                StandardSpeed=Decimal('0.50'),
                ProductionStartTime=datetime(2026, 9, 26, 8),
                ProductionEndTime=datetime(2026, 9, 26, 9),
                CounterQty=100, CuringQty=90)),
            calculate_oee_row(row(
                PressProductionID=2, MachineCode='F7', Shift='1',
                ShiftMasterID=101, MouldName='Mould Beta',
                StandardSpeed=Decimal('0.75'),
                ProductionStartTime=datetime(2026, 9, 26, 10),
                ProductionEndTime=datetime(2026, 9, 26, 12),
                CounterQty=200, CuringQty=180)),
        ]
        press, = build_press_production_summary(episodes)
        self.assertEqual(press['Mould'], 'Mould Alpha / Mould Beta')
        self.assertEqual(press['StandardSpeed'], '0.5 / 0.75')
        self.assertEqual(press['Shift1']['Start'], '1: 08:00; 2: 10:00')
        self.assertEqual(press['Shift1']['End'], '1: 09:00; 2: 12:00')
        self.assertEqual(press['Shift1']['ProductionMinutes'], Decimal(180))
        self.assertEqual(press['Shift1']['Counter'], Decimal(300))
        self.assertEqual(press['Shift1']['Curing'], Decimal(270))
        self.assertEqual(press['Shift1']['WetReject'], Decimal(30))
        self.assertFalse(press['Shift2']['HasEpisodes'])
        self.assertEqual(press['TotalProductionMinutes'], Decimal(180))

    def test_missing_times_and_unknown_shift_are_not_attributed_or_underreported(self):
        episodes = [
            calculate_oee_row(row(
                PressProductionID=1, MachineCode='F7', Shift='1',
                ShiftMasterID=101,
                ProductionStartTime=datetime(2026, 9, 26, 8),
                ProductionEndTime=None)),
            calculate_oee_row(row(
                PressProductionID=2, MachineCode='F7', Shift='UNKNOWN',
                ShiftMasterID=None,
                ProductionStartTime=datetime(2026, 9, 26, 19),
                ProductionEndTime=datetime(2026, 9, 26, 20))),
        ]
        press, = build_press_production_summary(episodes)
        self.assertEqual(press['Shift1']['Start'], '08:00')
        self.assertEqual(press['Shift1']['End'], 'N/A')
        self.assertIsNone(press['Shift1']['ProductionMinutes'])
        self.assertFalse(press['Shift2']['HasEpisodes'])
        self.assertTrue(press['HasUnknownShift'])
        self.assertIsNone(press['TotalProductionMinutes'])
        totals = build_press_production_totals([press])
        self.assertIsNone(totals['Shift1']['ProductionMinutes'])
        self.assertEqual(totals['Shift1']['Counter'], Decimal(90))
        self.assertIsNone(totals['TotalProductionMinutes'])

    def test_overlapping_press_episodes_do_not_double_count_production_minutes(self):
        episodes = [
            calculate_oee_row(row(
                PressProductionID=1, MachineCode='F7', Shift='1',
                ShiftMasterID=101,
                ProductionStartTime=datetime(2026, 9, 26, 8),
                ProductionEndTime=datetime(2026, 9, 26, 10))),
            calculate_oee_row(row(
                PressProductionID=2, MachineCode='F7', Shift='1',
                ShiftMasterID=101,
                ProductionStartTime=datetime(2026, 9, 26, 9),
                ProductionEndTime=datetime(2026, 9, 26, 11))),
        ]
        press, = build_press_production_summary(episodes)
        self.assertIn('1: 08:00', press['Shift1']['Start'])
        self.assertIn('2: 09:00', press['Shift1']['Start'])
        self.assertIsNone(press['Shift1']['ProductionMinutes'])
        self.assertIsNone(press['TotalProductionMinutes'])


class PrintOeeQueryTests(unittest.TestCase):
    class Cursor:
        def __init__(self, shift_schema=True, assignments=None, events=None):
            self.shift_schema = shift_schema
            self.assignments = assignments or []
            self.events = events or []
            self.statements = []
            self.description = []
            self.result = []

        def execute(self, sql, *args):
            self.statements.append((sql, args))
            if 'COL_LENGTH(' in sql:
                self.description = [('HasShiftSchema',)]
                self.result = [(int(self.shift_schema),)]
            elif 'FROM dbo.Fitting_MainMachine' in sql:
                self.description = [('McId',), ('Machine',), ('No',)]
                self.result = [(7, 'F', 16)]
            elif 'FROM dbo.ProductionLot' in sql:
                self.description = [('PressProductionID',), ('MachineCode',), ('ShiftCode',)]
                self.result = list(self.assignments)
            elif 'FROM dbo.LoggerEvent' in sql:
                self.description = [(name,) for name in (
                    'LoggerEventID', 'ProductionDate', 'StopDateTime', 'StartDateTime',
                    'DurationMin', 'MachineNameSnapshot', 'RelatedMachineSnapshot',
                    'SubMachineSnapshot', 'CauseSnapshot', 'StopTypeSnapshot',
                    'SubStopTypeSnapshot', 'MEO', 'Note', 'McId', 'McInstanceNo',
                    'RelatedMcId', 'RelatedMcInstanceNo', 'ShiftID', 'SubMcId',
                    'SubMcInstanceNo', 'StopId', 'SubStopId', 'CauseId')]
                self.result = list(self.events)
            else:
                self.description = []
                self.result = []

        def fetchone(self):
            return self.result.pop(0) if self.result else None

        def fetchall(self):
            result, self.result = self.result, []
            return result

    @staticmethod
    def mapping():
        return dict(
            main_codes={2: 'ก.1', 5: None, 6: None, 7: 'ค.1'},
            codes_by_stop={
                2: {'ก.1'}, 3: {'ก.2', 'ก.3', 'ก.4'},
                4: {'ง.1', 'ง.2', 'ง.3', 'ง.4', 'ง.5', 'ง.6', 'ง.7'},
                5: {'ก.5'}, 6: {'ค.2', 'ค.3', 'ค.4', 'ค.5', 'ค.6'},
                7: {'ค.1'},
            },
            available_codes={'ก.1', 'ก.2', 'ก.3', 'ก.4', 'ก.5',
                             'ค.1', 'ค.2', 'ค.3', 'ค.4', 'ค.5', 'ค.6',
                             'ง.1', 'ง.2', 'ง.3', 'ง.4', 'ง.5', 'ง.6', 'ง.7'},
            missing_codes={'ข.1', 'ข.2'}, orphan_subtypes=[])

    @staticmethod
    def logger_event(event_id, stop_id, sub_stop_id, code, minutes,
                     instance=7, shift_id=1, **overrides):
        event = dict(
            LoggerEventID=event_id, DurationMin=Decimal(minutes),
            MainMachine='F', MainMachineCount=16, McInstanceNo=instance,
            ShiftID=shift_id, StopDateTime=datetime(2026, 9, 26, 9, 15),
            StopId=stop_id, SubStopId=sub_stop_id,
            EffectiveOEEExcelCode=code, InvalidSubStopRelationship=False,
        )
        event.update(overrides)
        return event

    def process(self, events, assignments=None):
        mapping = self.mapping()
        assignment_rows = assignments or [
            row(MachineCode='F7', Shift='1', AssignmentShiftUnknown=False)]
        from app.print_oee import _press_shift_groups
        groups, by_key = _press_shift_groups(assignment_rows, mapping)
        rules = [
            {'ShiftID': 1, 'StartTime': datetime.strptime('06:00', '%H:%M').time()},
            {'ShiftID': 2, 'StartTime': datetime.strptime('18:00', '%H:%M').time()},
        ]
        result = _process_logger_events(events, groups, by_key, mapping, DAY, rules)
        return result, mapping

    def test_oee_query_reads_pressproduction_times_and_only_manual_losses(self):
        cursor = self.Cursor()
        self.assertEqual(_query_rows(cursor, DAY), [])
        sql, args = cursor.statements[-1]
        self.assertIn('pp.ProductionStartTime, pp.ProductionEndTime', sql)
        self.assertNotIn('ProductionData', sql)
        self.assertNotIn('LotStartTime', sql)
        self.assertNotIn('LotEndTime', sql)
        self.assertIn("event.SourceType='MANUAL'", sql)
        self.assertIn("event.TimeType IN ('SETUP','CHANGEOVER','IDLE','CLEAN','BREAKDOWN')", sql)
        self.assertNotIn('LoggerEvent', sql)
        self.assertEqual(args, (DAY,))
        self.assertTrue(all(statement.lstrip().upper().startswith('SELECT')
                            for statement, _ in cursor.statements))

    def test_logger_query_uses_saved_code_precedence_and_stop_relationship(self):
        class MappingCursor:
            def __init__(self):
                self.description = []
                self.result = []
                self.statements = []

            def execute(self, sql, *args):
                self.statements.append(sql)
                if 'FROM dbo.Fitting_StopType AS main' in sql:
                    self.description = [(name,) for name in (
                        'StopId', 'StopType', 'MainCode', 'SubStopId',
                        'SubStopType', 'SubCode', 'EffectiveCode')]
                    self.result = [(7, 'BD', 'ค.1', 21, '--', None, 'ค.1')]
                elif 'WHERE main.StopId IS NULL' in sql:
                    self.description = [('SubStopId',), ('StopId',),
                                        ('SubStopType',), ('OEEExcelCode',)]
                    self.result = []
                elif 'FROM dbo.ProductionShiftRuleHistory' in sql:
                    self.description = [('EffectiveFromDate',), ('ShiftID',),
                                        ('StartTime',)]
                    self.result = [(DAY, 1, datetime.strptime('06:00', '%H:%M').time())]
                elif 'FROM dbo.LoggerEvent AS event' in sql:
                    self.description = [(name,) for name in (
                        'LoggerEventID', 'ProductionDate', 'StopDateTime',
                        'StartDateTime', 'DurationMin', 'McId', 'McInstanceNo',
                        'MainMachine', 'MainMachineCount', 'RelatedMcId',
                        'RelatedMcInstanceNo', 'SubMcId', 'SubMcInstanceNo',
                        'ShiftID', 'StopId', 'SubStopId', 'CauseId', 'MEO',
                        'Note', 'SourceType', 'MachineNameSnapshot',
                        'RelatedMachineSnapshot', 'SubMachineSnapshot',
                        'StopTypeLabel', 'SubStopTypeLabel', 'CauseLabel',
                        'MainOEEExcelCode', 'SubOEEExcelCode',
                        'EffectiveOEEExcelCode', 'InvalidSubStopRelationship')]
                    self.result = [(
                        20, DAY, datetime(2026, 9, 26, 9, 15),
                        datetime(2026, 9, 26, 9), Decimal(15), 7, 7, 'F', 16,
                        None, None, None, None, 1, 7, 21, None, 'M', None,
                        'LOGGER', 'F7', None, None, 'BD', '--', None, 'ค.1',
                        None, 'ค.1', False)]
                else:
                    self.description = []
                    self.result = []

            def fetchall(self):
                result, self.result = self.result, []
                return result

        cursor = MappingCursor()
        report = _query_logger_details(cursor, DAY, [
            row(MachineCode='F7', Shift='1', AssignmentShiftUnknown=False)])
        logger_sql = next(sql for sql in cursor.statements
                          if 'FROM dbo.LoggerEvent AS event' in sql)
        self.assertIn('COALESCE(NULLIF(sub.OEEExcelCode,N\'\'),NULLIF(main.OEEExcelCode,N\'\'))',
                      cursor.statements[0])
        self.assertIn('sub_map.SubStopId=event.SubStopId', logger_sql)
        self.assertIn('sub_map.StopId=event.StopId', logger_sql)
        self.assertIn('event.StartDateTime', logger_sql)
        self.assertIn('event.StopDateTime', logger_sql)
        self.assertIn('event.DurationMin', logger_sql)
        self.assertIn('COALESCE(event.CauseSnapshot, cause.Cause) AS CauseLabel',
                      logger_sql)
        self.assertIn('machine.Machine AS MainMachine', logger_sql)
        self.assertIn('event.Note', logger_sql)
        self.assertIn('event.ProductionDate=?', logger_sql)
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT')
                            for sql in cursor.statements))
        group = report['groups'][0]
        self.assertEqual(group['CategoryMinutes']['ค.1'], Decimal(15))
        self.assertEqual(report['events'][0]['MappingStatus'], 'Mapped: ค.1')

    def test_breakdown_detail_is_bd_only_formatted_and_deduplicated(self):
        events = [
            dict(
                LoggerEventID=12, StopId=7,
                StartDateTime=datetime(2026, 9, 26, 8, 5),
                StopDateTime=datetime(2026, 9, 26, 9, 17),
                DurationMin=Decimal('72'), CauseLabel='Bearing failure',
                LoggerMachine='F7', MainMachine='F', Note='Replaced bearing',
                ResolvedShift='1'),
            dict(LoggerEventID=13, StopId=6, CauseLabel='Not BD'),
            dict(
                LoggerEventID=12, StopId=7,
                StartDateTime=datetime(2026, 9, 26, 8, 5),
                StopDateTime=datetime(2026, 9, 26, 9, 17),
                DurationMin=Decimal('72'), CauseLabel='Bearing failure',
                LoggerMachine='F7', MainMachine='F', Note='Replaced bearing',
                ResolvedShift='1'),
            dict(LoggerEventID=14, StopId=7),
        ]
        details = _breakdown_details(events)
        self.assertEqual(len(details), 2)
        self.assertEqual(details[0]['StartTime'], '08:05')
        self.assertEqual(details[0]['StopTime'], '09:17')
        self.assertEqual(details[0]['DurationMinutes'], Decimal(72))
        self.assertEqual(details[0]['Cause'], 'Bearing failure')
        self.assertEqual(details[0]['Machine'], 'F7')
        self.assertEqual(details[0]['MachineType'], 'F')
        self.assertIsNone(details[0]['MachineCode'])
        self.assertEqual(details[0]['CorrectiveAction'], 'Replaced bearing')
        self.assertEqual(details[1]['StartTime'], None)
        self.assertEqual(details[1]['StopTime'], None)
        self.assertIsNone(details[1]['DurationMinutes'])
        self.assertIsNone(details[1]['Cause'])
        self.assertIsNone(details[1]['Machine'])
        self.assertIsNone(details[1]['MachineCode'])
        self.assertIsNone(details[1]['CorrectiveAction'])

    def test_old_schema_does_not_reference_missing_shift_column(self):
        cursor = self.Cursor(shift_schema=False)
        self.assertEqual(_query_rows(cursor, DAY), [])
        sql, _ = cursor.statements[-1]
        self.assertNotIn('pp.ShiftMasterID', sql)
        self.assertIn('CAST(1 AS bit) AS AssignmentShiftUnknown', sql)

    def test_mapping_precedence_and_clean_subtypes_aggregate(self):
        clean = [self.logger_event(1, 5, 14, 'ก.5', 5),
                 self.logger_event(2, 5, 15, 'ก.5', 7)]
        result, _ = self.process(clean)
        group = result['groups'][0]
        self.assertEqual(group['CategoryMinutes']['ก.5'], Decimal(12))
        self.assertEqual(result['unmapped_count'], 0)
        self.assertEqual(result['events'][0]['MappingStatus'], 'Mapped: ก.5')

    def test_main_fallback_smdt_bd_and_subcategory_overrides(self):
        events = [
            self.logger_event(1, 2, 2, 'ก.1', 3),
            self.logger_event(2, 6, None, None, 4),
            self.logger_event(3, 6, 16, 'ค.2', 6),
            self.logger_event(4, 7, 21, 'ค.1', 8),
        ]
        result, _ = self.process(events)
        categories = result['groups'][0]['CategoryMinutes']
        self.assertEqual(categories['ก.1'], Decimal(3))
        self.assertEqual(categories['ค.2'], Decimal(6))
        self.assertEqual(categories['ค.1'], Decimal(8))
        self.assertIsNone(categories['ข.1'])
        self.assertEqual(result['unmapped_count'], 1)

    def test_stop_substop_relationship_is_validated_and_unmapped_event_is_visible(self):
        event = self.logger_event(
            1, 6, 14, None, 5, InvalidSubStopRelationship=True)
        result, _ = self.process([event])
        self.assertIn('does not belong', result['events'][0]['MappingStatus'])
        self.assertEqual(result['unmapped_count'], 1)
        self.assertEqual(result['unmapped_minutes'], Decimal(5))
        self.assertIsNotNone(result['events'][0]['LoggerEventID'])

    def test_exact_press_shift_isolation_and_unattributed_event(self):
        assignments = [
            row(MachineCode='F7', Shift='1', AssignmentShiftUnknown=False),
            row(MachineCode='F7', Shift='2', AssignmentShiftUnknown=False),
            row(MachineCode='F8', Shift='1', AssignmentShiftUnknown=False),
        ]
        events = [
            self.logger_event(1, 2, 2, 'ก.1', 3, instance=7, shift_id=1),
            self.logger_event(2, 2, 2, 'ก.1', 5, instance=7, shift_id=2),
            self.logger_event(3, 2, 2, 'ก.1', 8, instance=8, shift_id=2),
        ]
        result, _ = self.process(events, assignments)
        groups = {(group['MachineCode'], group['Shift']): group
                  for group in result['groups']}
        self.assertEqual(groups[('F7', '1')]['CategoryMinutes']['ก.1'], Decimal(3))
        self.assertEqual(groups[('F7', '2')]['CategoryMinutes']['ก.1'], Decimal(5))
        self.assertEqual(groups[('F8', '1')]['CategoryMinutes']['ก.1'], Decimal(0))
        self.assertEqual(result['unattributed_count'], 1)
        self.assertEqual(result['unattributed_minutes'], Decimal(8))

    def test_excel_category_table_aligns_machine_order_and_assignment_state(self):
        assignments = [
            dict(Press='F8', Shift1=dict(HasEpisodes=True),
                 Shift2=dict(HasEpisodes=False)),
            dict(Press='F7', Shift1=dict(HasEpisodes=True),
                 Shift2=dict(HasEpisodes=True)),
        ]
        values = dict.fromkeys(LOGGER_CATEGORY_CODES, Decimal(0))
        missing_code_values = dict(values)
        missing_code_values['ก.2'] = None
        shift2_values = dict(values)
        shift2_values['ก.1'] = Decimal(4)
        groups = [
            dict(MachineCode='F8', Shift='1', CategoryMinutes=values),
            dict(MachineCode='F7', Shift='1',
                 CategoryMinutes=missing_code_values),
            dict(MachineCode='F7', Shift='2', CategoryMinutes=shift2_values),
        ]
        all_values = dict(values)
        all_values['ก.1'] = Decimal(4)
        all_values['ก.2'] = None
        table = build_logger_category_table(dict(
            groups=groups,
            all_shift_category_minutes=all_values,
            all_shift_unavailable_codes={'ก.2'},
        ), assignments)

        self.assertEqual(
            [machine['MachineCode'] for machine in table['Machines']],
            ['F8', 'F7'])
        section_a = table['Sections'][0]
        category_a1 = section_a['Rows'][0]
        self.assertEqual([cell['value'] for cell in category_a1['Shift1']],
                         [Decimal(0), Decimal(0)])
        self.assertEqual([cell['assigned'] for cell in category_a1['Shift2']],
                         [False, True])
        self.assertEqual(category_a1['Shift1Total']['value'], Decimal(0))
        self.assertEqual(category_a1['Shift2Total']['value'], Decimal(4))
        self.assertEqual(category_a1['AllShiftsTotal']['value'], Decimal(4))

        category_a2 = section_a['Rows'][1]
        self.assertIsNone(category_a2['Shift1'][1]['value'])
        self.assertFalse(category_a2['Shift2'][0]['assigned'])
        self.assertIsNone(category_a2['AllShiftsTotal']['value'])
        subtotal_a = section_a['Rows'][-1]
        self.assertEqual(subtotal_a['Label'], 'Subtotal (ก)')
        self.assertIsNone(subtotal_a['Shift1'][1]['value'])
        self.assertIsNone(subtotal_a['AllShiftsTotal']['value'])
        self.assertEqual(
            [len(section['Rows']) for section in table['Sections']],
            [6, 3, 7, 8])

    def test_duplicate_event_ids_are_not_double_counted(self):
        event = self.logger_event(1, 2, 2, 'ก.1', 3)
        result, _ = self.process([event, dict(event)])
        self.assertIsNone(result['groups'][0]['CategoryMinutes']['ก.1'])
        self.assertEqual(result['duplicate_count'], 1)
        self.assertEqual(result['unmapped_count'], 1)
        self.assertEqual(
            {code for code, _, _ in LOGGER_CATEGORIES}, LOGGER_CATEGORY_CODES)

    def test_template_displays_category_totals_and_event_mapping_states(self):
        template = Path(__file__).parents[1] / 'app' / 'templates' / 'print_oee.html'
        text = template.read_text(encoding='utf-8')
        self.assertIn('LOGGER DOWNTIME BY EXCEL CATEGORY', text)
        self.assertIn('logger_category_table.Machines', text)
        self.assertIn('item.Label', text)
        self.assertIn('>N/A</td>', text)
        self.assertIn('N/A = mapping, duration, or event attribution incomplete', text)
        self.assertNotIn('Unavailable: incomplete Press/Shift data', text)
        self.assertIn('EXCEL BREAKDOWN DETAIL', text)
        self.assertIn('only StopId 7 Breakdown events', text)
        self.assertIn('Machine (F-code)', text)
        self.assertIn('Corrective Action (Note)', text)
        self.assertIn('presentation-only and are not added to OEE losses', text)
        self.assertIn('@media print', text)
        self.assertIn('@media screen', text)

    def test_context_uses_saved_assignment_shift_without_time_inference(self):
        sources = [
            row(PressProductionID=201, ShiftMasterID=301, AssignmentShiftCode='1'),
            row(PressProductionID=202, ShiftMasterID=302, AssignmentShiftCode='2',
                ProductionStartTime=datetime(2026, 9, 26, 19),
                ProductionEndTime=datetime(2026, 9, 27, 2)),
        ]
        category_minutes = dict.fromkeys(LOGGER_CATEGORY_CODES, Decimal(0))
        category_minutes['ก.1'] = Decimal(2)
        with patch('app.print_oee.read_plan_week',
                   return_value='2026-W39') as read_week, \
             patch('app.print_oee._query_rows', return_value=sources), \
             patch('app.print_oee._query_logger_details', return_value=dict(
                 groups=[], mapping_missing_codes=[], mapping_orphan_subtypes=[],
                 events=[], unmapped_count=0, unmapped_minutes=Decimal(0),
                 unattributed_count=0, unattributed_minutes=Decimal(0),
                 duplicate_count=0)):
            report = read_print_oee_context(object(), DAY)
        self.assertEqual([item['Shift'] for item in report['rows']], ['1', '2'])
        read_week.assert_called_once()
        self.assertEqual(read_week.call_args.args[1], DAY)
        self.assertEqual(report['plan_week'], '2026-W39')
        self.assertEqual(len(report['production_summary_rows']), 1)
        self.assertEqual(report['summaries']['1']['ActualProductionMinutes'], Decimal('120'))
        self.assertEqual(report['summaries']['2']['ActualProductionMinutes'], Decimal('420'))

    def test_top_production_table_excludes_oee_and_manual_loss_columns(self):
        template = Path(__file__).parents[1] / 'app' / 'templates' / 'print_oee.html'
        text = template.read_text(encoding='utf-8')
        top = text.split('<div class="oee-section">PRESS / SHIFT PRODUCTION SUMMARY</div>', 1)[1]
        top = top.split('<div class="oee-section">LOGGER DOWNTIME BY EXCEL CATEGORY', 1)[0]
        for excluded in ('Setup', 'ChgOver', 'Idle', 'Cleaning', 'Breakdown',
                         'SMDT', 'AR', 'PR', 'QR', 'OEE'):
            self.assertNotIn(excluded, top)
        self.assertIn('SHIFT 1', top)
        self.assertIn('SHIFT 2', top)
        self.assertIn('Total production minutes', top)
        self.assertIn('>Speed<', top)
        self.assertIn('>Min<', top)
        self.assertIn('>Wet Rej.<', top)
        self.assertIn('oee-summary-wrap{overflow:visible}', text)
        self.assertIn('.oee-press-summary{min-width:0;width:100%', text)
        self.assertIn('class="total-row"', top)

    def test_print_oee_route_renders_complete_report_context(self):
        from starlette.requests import Request

        sample = calculate_oee_row(row(
            PressProductionID=20, ProductionID=21, MachineCode='F7',
            LotNo='I11690904',
            ProductionStartTime=datetime(2026, 9, 3, 8, 5),
            ProductionEndTime=datetime(2026, 9, 3, 18, 30),
            SetupMinutes=10, BreakdownMinutes=10))
        summaries = {
            '1': summarize([sample]),
            '2': summarize([]),
            'ALL DAY': summarize([sample]),
        }
        category_minutes = dict.fromkeys(LOGGER_CATEGORY_CODES, Decimal(0))
        category_minutes['ก.1'] = Decimal(2)
        logger_report = dict(
            groups=[dict(MachineCode='F7', Shift='1',
                         UnavailableCodes={'ข.1', 'ข.2'},
                         UnavailableReasons={},
                         CategoryMinutes=category_minutes)],
            all_shift_unavailable_codes={'ข.1', 'ข.2'},
            all_shift_category_minutes=category_minutes,
            mapping_missing_codes=['ข.1', 'ข.2'],
            mapping_orphan_subtypes=[], events=[],
            unmapped_count=0, unmapped_minutes=Decimal(0),
            unattributed_count=0, unattributed_minutes=Decimal(0),
            duplicate_count=0)
        production_summary_rows = build_press_production_summary([sample])
        report = dict(
            rows=[sample], summaries=summaries, excluded=[],
            production_summary_rows=production_summary_rows,
            production_summary_totals=build_press_production_totals(
                production_summary_rows),
            logger_category_table=build_logger_category_table(
                logger_report, production_summary_rows),
            breakdown_details=[dict(
                StartTime='08:05', StopTime='08:15',
                DurationMinutes=Decimal(10), Cause='Bearing failure',
                Machine='F7', MachineType='F', MachineCode=None,
                CorrectiveAction='Replaced bearing')],
            logger_report=logger_report,
            logger_categories=(('ก.1', 'ก', 'เตรียมการผลิต'),),
            shifts=('1', '2'), plan_week='2026-W36', press_count=1)

        class Connection:
            def cursor(self):
                return object()

            def close(self):
                pass

        request = Request({
            'type': 'http', 'http_version': '1.1', 'method': 'GET',
            'scheme': 'http', 'path': '/print-oee', 'raw_path': b'/print-oee',
            'query_string': b'', 'headers': [],
            'server': ('127.0.0.1', 1868), 'client': ('127.0.0.1', 40000),
        })
        with patch('app.main.get_connection', return_value=Connection()), \
             patch('app.main.read_print_oee_context', return_value=report):
            response = print_oee_page(request, DAY)

        self.assertEqual(response.status_code, 200)
        self.assertIn('08:05', response.body.decode('utf-8'))
        self.assertIn('18:30', response.body.decode('utf-8'))
        self.assertIn('625.00', response.body.decode('utf-8'))
        self.assertIn('N/A', response.body.decode('utf-8'))
        self.assertIn('EXCEL BREAKDOWN DETAIL', response.body.decode('utf-8'))
        self.assertIn('08:05', response.body.decode('utf-8'))
        self.assertIn('Bearing failure', response.body.decode('utf-8'))
        self.assertIn('Replaced bearing', response.body.decode('utf-8'))
        body = response.body.decode('utf-8')
        self.assertIn('>Speed<', body)
        self.assertIn('SHIFT 1', body)
        self.assertIn('SHIFT 2', body)
        category_table = body.split(
            'LOGGER DOWNTIME BY EXCEL CATEGORY', 1)[1].split(
                'EXCEL BREAKDOWN DETAIL', 1)[0]
        self.assertIn('F7', category_table)
        self.assertIn('Subtotal (ก)', category_table)
        self.assertIn('Subtotal (ข)', category_table)
        self.assertIn('Subtotal (ค)', category_table)
        self.assertIn('Subtotal (ง)', category_table)
        self.assertIn('>N/A</td>', category_table)
        self.assertNotIn('Unavailable:', category_table)
        self.assertIn('TOTAL', body)
        self.assertLess(body.index('PRESS / SHIFT PRODUCTION SUMMARY'),
                        body.index('OEE CALCULATION DETAILS'))

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
