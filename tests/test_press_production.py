import unittest
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.press_production import (read_eligible_moulds, read_eligible_presses,
                                  read_press_production, save_press_production,
                                  validate_press_input, calculate_smdt)
from app.main import production_page
from test_production import DAY, LOT, PLAN, request


class PressProductionCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = []
        self.result = []

    def _set(self, rows):
        self.description = [(key,) for key in rows[0]] if rows else []
        self.result = [tuple(row.values()) for row in rows]

    def execute(self, sql, *args):
        self.conn.sql.append((sql, args))
        if self.conn.fail and self.conn.fail in sql:
            raise RuntimeError('simulated SQL error')
        if 'sys.sp_getapplock' in sql:
            self.result = [(0,)]
        elif 'ProductionDayRuleHistory' in sql:
            self.result = [(self.conn.day_start_time,)]
        elif 'FROM dbo.ProductionLot WITH' in sql:
            self.result = [(self.conn.production_id, self.conn.family, self.conn.code)] if args[0] == self.conn.production_id and self.conn.lot_active else []
        elif 'FROM dbo.vw_PressMcCapabilityMatrix' in sql and 'SELECT 1' in sql:
            is_valid = args[0] == self.conn.press_code and args[1:] == (self.conn.family, self.conn.code)
            self.result = [(1,)] if is_valid and self.conn.press_valid else []
        elif 'FROM dbo.MouldMaster WITH' in sql:
            mould = self.conn.moulds.get(args[0])
            if not mould:
                self.result = []
            elif 'SELECT MouldID, ProductFamily, ProductCode' in sql:
                self.result = [(args[0], mould['ProductFamily'], mould['ProductCode'])]
            else:
                self.result = [(args[0], mould['Status'], mould['ProductFamily'], mould['ProductCode'], mould['CurrentReconditionNo'])]
        elif 'FROM dbo.PressProduction WITH' in sql and 'MachineCode=?' in sql:
            found = any(row['ProductionID'] == args[0] and row['MachineCode'] == args[1] for row in self.conn.press_rows.values())
            self.result = [(1,)] if found else []
        elif 'FROM dbo.PressProduction WITH' in sql:
            row = self.conn.press_rows.get(args[0])
            self.result = [(row['PressProductionID'], row['MachineCode'], row['MouldID'], row['CounterQty'])] if row and row['ProductionID'] == args[1] else []
        elif 'assigned_lot.ProdDate' in sql:
            production_date, mould_id = args
            self.result = [(row['PressProductionID'],) for row in self.conn.press_rows.values()
                           if row.get('MouldID') == mould_id and row.get('ProductionDate') == production_date]
        elif 'FROM dbo.MouldUsage WITH' in sql:
            row = self.conn.usage_rows.get(args[0])
            self.result = [(row['ReconditionNo'],)] if row and 'SELECT ReconditionNo' in sql else ([(row['MouldUsageID'],)] if row else [])
        elif 'FROM dbo.EquipmentTimeEvent WITH' in sql:
            self.result = [(row['TimeEventID'],) for row in self.conn.time_events.values()
                           if (row['ProductionID'], row['EquipmentCode'], row['TimeType'], row['SourceType'])
                           == (*args, 'MANUAL')]
        elif 'INSERT INTO dbo.PressProduction' in sql:
            pp_id = self.conn.next_pp_id
            self.conn.next_pp_id += 1
            row = dict(PressProductionID=pp_id, ProductionID=args[0], MachineCode=args[1],
                       DispatchQty=args[2], CounterQty=args[3], CuringQty=args[4], MouldID=args[5],
                       ProductionDate=self.conn.production_date)
            self.conn.press_rows[pp_id] = row
            self.result = [(pp_id,)]
        elif 'UPDATE dbo.PressProduction' in sql:
            row = self.conn.press_rows[args[-2]]
            row.update(MachineCode=args[0], DispatchQty=args[1], CounterQty=args[2],
                       CuringQty=args[3], MouldID=args[4])
            self.result = []
        elif 'INSERT INTO dbo.MouldUsage' in sql:
            mould_id, pp_id, recondition_no, cycles = args
            self.conn.usage_rows[pp_id] = dict(MouldUsageID=pp_id + 100, MouldID=mould_id,
                PressProductionID=pp_id, ReconditionNo=recondition_no, UsageCycles=cycles)
            self.result = []
        elif 'UPDATE dbo.MouldUsage' in sql:
            cycles, pp_id = args
            self.conn.usage_rows[pp_id]['UsageCycles'] = cycles
            self.result = []
        elif 'UPDATE dbo.EquipmentTimeEvent' in sql:
            duration, event_id, production_id, machine_code, time_type = args
            row = self.conn.time_events[event_id]
            self.assert_event_key(row, production_id, machine_code, time_type)
            row['DurationMin'] = duration
            self.result = []
        elif 'INSERT INTO dbo.EquipmentTimeEvent' in sql:
            production_id, machine_code, time_type, duration = args
            event_id = self.conn.next_event_id
            self.conn.next_event_id += 1
            self.conn.time_events[event_id] = dict(TimeEventID=event_id, ProductionID=production_id,
                EquipmentCode=machine_code, TimeType=time_type, DurationMin=duration, SourceType='MANUAL')
            self.result = []
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def assert_event_key(self, row, production_id, machine_code, time_type):
        assert (row['ProductionID'], row['EquipmentCode'], row['TimeType'], row['SourceType']) == \
            (production_id, machine_code, time_type, 'MANUAL')


class PressProductionConnection:
    def __init__(self):
        self.production_id = 7
        self.family = 'Special Ridge'
        self.code = '02'
        self.press_code = 'F2'
        self.press_valid = True
        self.lot_active = True
        self.moulds = {
            4: dict(Status='ACTIVE', ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=2),
            5: dict(Status='RECONDITION', ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=1),
            6: dict(Status='RETIRED', ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=0),
            7: dict(Status='DENIED', ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=0),
            8: dict(Status='ACTIVE', ProductFamily='Oriental', ProductCode='02', CurrentReconditionNo=0),
            9: dict(Status='ACTIVE', ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=2),
        }
        self.press_rows = {}
        self.usage_rows = {}
        self.time_events = {}
        self.next_pp_id = 30
        self.next_event_id = 100
        self.commits = 0
        self.rollbacks = 0
        self.sql = []
        self.fail = None
        self.day_start_time = time(8)
        self.production_date = date(2026, 9, 26)
        self.cur = PressProductionCursor(self)

    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


def valid_input(**overrides):
    data = dict(MachineCode='F2', MouldID='4', DispatchQty='100', CounterQty='100',
                CuringQty='95', ProductionDate='2026-09-26', ProductionStartTime='22:00',
                ProductionEndTime='00:15', Remark='press note')
    data.update(overrides)
    return data


class ReadCursor:
    def __init__(self, result):
        self.result = result
        self.sql = ''
        self.args = ()
        self.description = []
    def execute(self, sql, *args):
        self.sql, self.args = sql, args
        self.description = [(key,) for key in self.result[0]] if self.result else []
        return self
    def fetchall(self): return [tuple(row.values()) for row in self.result]


class PressProductionTests(unittest.TestCase):
    def test_smdt_same_day_and_downtime_changes(self):
        start = datetime(2026, 9, 26, 8)
        end = datetime(2026, 9, 26, 16)
        downtime = {'SETUP': Decimal('20'), 'CHANGEOVER': Decimal('10'), 'IDLE': Decimal('30'),
                     'CLEAN': Decimal('10'), 'BREAKDOWN': Decimal('20')}
        self.assertEqual(calculate_smdt(start, end, downtime), Decimal('390'))
        downtime['IDLE'] = Decimal('40')
        self.assertEqual(calculate_smdt(start, end, downtime), Decimal('380'))

    def test_smdt_crosses_midnight_and_end_at_midnight(self):
        self.assertEqual(calculate_smdt(datetime(2026, 9, 26, 22), datetime(2026, 9, 27, 3), {}), Decimal('300'))
        self.assertEqual(calculate_smdt(datetime(2026, 9, 26, 23, 30), datetime(2026, 9, 27), {}), Decimal('30'))

    def test_smdt_blank_downtime_is_zero(self):
        self.assertEqual(calculate_smdt(datetime(2026, 9, 26, 8), datetime(2026, 9, 26, 9), {}), Decimal('60'))

    def test_smdt_follows_historical_cutoff_resolution(self):
        from app.production_clock import production_clock_datetime
        cutoff = time(6, 30)
        start = production_clock_datetime(DAY, '05:00', cutoff)
        end = production_clock_datetime(DAY, '05:30', cutoff)
        self.assertEqual(calculate_smdt(start, end, {}), Decimal('30'))

    def test_press_production_rows_are_filtered_by_production_id(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        read_press_production(cursor, 42)
        sql, args = cursor.execute.call_args.args
        self.assertIn('WHERE pp.ProductionID=?', sql)
        self.assertEqual(args, 42)

    def test_eligible_press_query_reuses_pressmc_capability_and_requires_active_press(self):
        cursor = ReadCursor([dict(PressCode='F2', PressName='Press 2', CurrentLine='LINE1', CurrentLineName='Line 1')])
        result = read_eligible_presses(cursor, 'Special Ridge', '02')
        self.assertEqual(result[0]['PressCode'], 'F2')
        self.assertIn('dbo.vw_PressMcCapabilityMatrix', cursor.sql)
        self.assertIn('capability.CanProduce=1', cursor.sql)
        self.assertIn('equipment.IsActive=1', cursor.sql)
        self.assertIn("equipment.EquipmentType='PRESS'", cursor.sql)
        self.assertEqual(cursor.args, ('Special Ridge', '02'))

    def test_eligible_mould_query_uses_authoritative_view_active_status_and_product(self):
        cursor = ReadCursor([dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  ProductFamily='Special Ridge', ProductCode='02')])
        result = read_eligible_moulds(cursor, 'Special Ridge', '02')
        self.assertEqual(result[0]['MouldID'], 4)
        self.assertIn('dbo.vw_MouldList', cursor.sql)
        self.assertIn("Status='ACTIVE'", cursor.sql)
        self.assertEqual(cursor.args, (None, 'Special Ridge', '02'))
        self.assertEqual(read_eligible_moulds(cursor, None, '02'), [])

    def test_mould_assignment_is_scoped_to_production_date(self):
        cursor = ReadCursor([dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  ProductFamily='Special Ridge', ProductCode='02',
                                  AssignedOnProductionDate=True)])
        result = read_eligible_moulds(cursor, 'Special Ridge', '02', DAY)
        self.assertTrue(result[0]['AssignedOnProductionDate'])

    def test_direct_post_rejects_same_date_duplicate_without_modifying_existing_rows(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            MouldID=4, CounterQty=0, ProductionDate=conn.production_date)
        before = dict(conn.press_rows)
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual(conn.press_rows, before)
        self.assertEqual(conn.commits, 0)

    def test_mould_can_be_reused_on_a_different_production_date(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            MouldID=4, CounterQty=0, ProductionDate=date(2026, 9, 25))
        conn.production_date = date(2026, 9, 26)
        save_press_production(conn, 7, valid_input())
        self.assertEqual(len(conn.press_rows), 2)

    def test_midnight_crossing_does_not_change_mould_business_date(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            MouldID=4, CounterQty=0, ProductionDate=conn.production_date)
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            save_press_production(conn, 7, valid_input(ProductionStartTime='22:00', ProductionEndTime='03:00'))

    def test_create_press_row_and_initial_usage_are_atomic(self):
        conn = PressProductionConnection()
        pp_id = save_press_production(conn, 7, valid_input())
        self.assertEqual(pp_id, 30)
        self.assertEqual(conn.press_rows[30]['CounterQty'], 100)
        self.assertEqual(conn.usage_rows[30], dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=2, UsageCycles=100))
        sql = [query for query, _ in conn.sql]
        self.assertTrue(any("@Resource='FittingMES.ProductionLot'" in query for query in sql))
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_counter_edit_replaces_existing_usage_without_double_count_and_keeps_generation(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=100)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        conn.moulds[4]['CurrentReconditionNo'] = 2
        save_press_production(conn, 7, valid_input(CounterQty='120'), 30)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 120)
        self.assertEqual(conn.usage_rows[30]['ReconditionNo'], 1)
        self.assertEqual(sum(row['UsageCycles'] for row in conn.usage_rows.values()), 120)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_existing_usage_counter_correction_allowed_after_mould_status_changes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=100)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        conn.moulds[4]['Status'] = 'RECONDITION'
        save_press_production(conn, 7, valid_input(CounterQty='125'), 30)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 125)
        self.assertEqual(conn.usage_rows[30]['ReconditionNo'], 1)
        self.assertEqual(conn.usage_rows[30]['MouldID'], 4)

    def test_assignment_change_is_rejected_after_counter_or_usage_exists(self):
        for with_usage in (False, True):
            conn = PressProductionConnection()
            conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=0 if with_usage else 10)
            if with_usage:
                conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30, ReconditionNo=2, UsageCycles=0)
            with self.subTest(with_usage=with_usage), self.assertRaisesRegex(ValueError, 'locked'):
                save_press_production(conn, 7, valid_input(MouldID='9', CounterQty='10', CuringQty='5'), 30)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.rollbacks, 1)

    def test_mould_can_be_changed_or_cleared_before_usage_begins(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=0)
        save_press_production(conn, 7, valid_input(MouldID='', CounterQty='0', CuringQty='0'), 30)
        self.assertIsNone(conn.press_rows[30]['MouldID'])
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual(conn.commits, 1)

    def test_positive_counter_requires_mould(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=0)
        with self.assertRaisesRegex(ValueError, 'Mould is required'):
            save_press_production(conn, 7, valid_input(MouldID='', CounterQty='1', CuringQty='0'), 30)
        self.assertEqual(conn.commits, 0)

    def test_inactive_or_unsupported_press_is_rejected(self):
        conn = PressProductionConnection()
        conn.press_valid = False
        with self.assertRaisesRegex(ValueError, 'inactive or is not enabled'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual(conn.press_rows, {})
        self.assertEqual(conn.rollbacks, 1)

    def test_duplicate_press_per_lot_is_rejected(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=0)
        with self.assertRaisesRegex(ValueError, 'already has a production row'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_wrong_product_and_nonactive_moulds_rejected(self):
        for mould_id, message in ((5, 'ACTIVE'), (6, 'ACTIVE'), (7, 'ACTIVE'), (8, 'match')):
            conn = PressProductionConnection()
            with self.subTest(mould_id=mould_id), self.assertRaisesRegex(ValueError, message):
                save_press_production(conn, 7, valid_input(MouldID=str(mould_id)))
            self.assertEqual(conn.press_rows, {})
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.rollbacks, 1)

    def test_legacy_lot_without_family_is_rejected(self):
        conn = PressProductionConnection()
        conn.family = None
        with self.assertRaisesRegex(ValueError, 'legacy Lot'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual(conn.press_rows, {})

    def test_missing_lot_and_quantity_validation_reject_without_commit(self):
        conn = PressProductionConnection()
        conn.lot_active = False
        with self.assertRaisesRegex(ValueError, 'no longer active'):
            save_press_production(conn, 7, valid_input())
        for data in (valid_input(CounterQty=''), valid_input(CounterQty='5', CuringQty='6')):
            with self.assertRaises(ValueError): validate_press_input(data, production_date=DAY, day_start_time=time(8))

    def test_new_press_mould_assignment_can_start_without_production_values(self):
        conn = PressProductionConnection()
        data = valid_input(CounterQty='', CuringQty='', ProductionStartTime='', ProductionEndTime='', Remark='')
        save_press_production(conn, 7, data)
        self.assertEqual(len(conn.press_rows), 1)

    def test_manual_minutes_create_five_rows_and_reload_values(self):
        conn = PressProductionConnection()
        save_press_production(conn, 7, valid_input(SetupMinutes='20', ChgOverMinutes='15',
            IdleMinutes='30.5', CleaningMinutes='15', BreakdownMinutes='25'))
        self.assertEqual(len(conn.time_events), 5)
        setup = next(row for row in conn.time_events.values() if row['TimeType'] == 'SETUP')
        self.assertEqual(setup['DurationMin'], Decimal('20'))
        self.assertEqual({row['TimeType'] for row in conn.time_events.values()},
                         {'SETUP', 'CHANGEOVER', 'IDLE', 'CLEAN', 'BREAKDOWN'})
        save_press_production(conn, 7, valid_input(SetupMinutes='21', ChgOverMinutes='16',
            IdleMinutes='31', CleaningMinutes='16', BreakdownMinutes='26'), 30)
        self.assertEqual(len(conn.time_events), 5)
        setup = next(row for row in conn.time_events.values() if row['TimeType'] == 'SETUP')
        self.assertEqual(setup['DurationMin'], Decimal('21'))

    def test_zero_minutes_update_existing_row_and_press_key_is_independent(self):
        conn = PressProductionConnection()
        save_press_production(conn, 7, valid_input(SetupMinutes='20'))
        conn.press_code = 'F3'
        save_press_production(conn, 7, valid_input(MachineCode='F3', MouldID='9', SetupMinutes='9'))
        conn.press_code = 'F2'
        save_press_production(conn, 7, valid_input(SetupMinutes='0'), 30)
        f2 = [row for row in conn.time_events.values() if row['EquipmentCode'] == 'F2' and row['TimeType'] == 'SETUP']
        f3 = [row for row in conn.time_events.values() if row['EquipmentCode'] == 'F3' and row['TimeType'] == 'SETUP']
        self.assertEqual(len(f2), 1)
        self.assertEqual(f2[0]['DurationMin'], Decimal('0'))
        self.assertEqual(f3[0]['DurationMin'], Decimal('9'))

    def test_manual_save_does_not_update_plc_row(self):
        conn = PressProductionConnection()
        conn.time_events[99] = dict(TimeEventID=99, ProductionID=7, EquipmentCode='F2',
            TimeType='SETUP', DurationMin=Decimal('40'), SourceType='PLC')
        save_press_production(conn, 7, valid_input(SetupMinutes='20'))
        self.assertEqual(conn.time_events[99]['DurationMin'], Decimal('40'))
        self.assertEqual(sum(row['SourceType'] == 'MANUAL' for row in conn.time_events.values()), 5)

    def test_manual_minutes_reject_negative_and_non_numeric_values(self):
        conn = PressProductionConnection()
        for value in ('-1', 'abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                save_press_production(conn, 7, valid_input(SetupMinutes=value))
        self.assertEqual(conn.commits, 0)

    def test_sql_failure_rolls_back_press_row_and_usage_transaction(self):
        conn = PressProductionConnection()
        conn.fail = 'INSERT INTO dbo.MouldUsage'
        with self.assertRaisesRegex(RuntimeError, 'simulated SQL error'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_clock_input_is_resolved_against_production_date(self):
        conn = PressProductionConnection()
        save_press_production(conn, 7, valid_input())
        insert = next(args for sql, args in conn.sql if 'INSERT INTO dbo.PressProduction' in sql)
        self.assertEqual(insert[6], datetime(2026, 9, 26, 22, 0))
        self.assertEqual(insert[7], datetime(2026, 9, 27, 0, 15))

    def test_clock_resolution_uses_historical_rule_value_not_hardcoded_cutoff(self):
        conn = PressProductionConnection()
        conn.day_start_time = time(6)
        save_press_production(conn, 7, valid_input(ProductionStartTime='05:00', ProductionEndTime='05:30'))
        insert = next(args for sql, args in conn.sql if 'INSERT INTO dbo.PressProduction' in sql)
        self.assertEqual(insert[6], datetime(2026, 9, 27, 5, 0))
        self.assertEqual(insert[7], datetime(2026, 9, 27, 5, 30))

    def test_selected_lot_renders_additional_press_section_without_changing_lot_input(self):
        press_row = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MachineName='Press 2',
            DispatchQty=100, CounterQty=120, CuringQty=110, MouldID=4, MouldNo='M000001',
            MouldName='Ridge', ProductionStartTime=None, ProductionEndTime=None, Remark='press note',
            UsageCycles=120, UsageReconditionNo=2)
        press_context = dict(press_production=[press_row], eligible_presses=[dict(PressCode='F3', PressName='Press 3')],
            eligible_moulds=[dict(MouldID=4, MouldNo='M000001', MouldName='Ridge')], press_product_error=None)
        with patch('app.main.get_connection', return_value=PressProductionConnection()), \
             patch('app.main.read_lots', return_value=[dict(LOT)]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data', return_value={}), \
             patch('app.main.build_press_production_context', return_value=press_context):
            response = production_page(request(), production_id=7, production_date=DAY)
        self.assertEqual(response.status_code, 200)
        page = response.body.decode()
        for item in ('PRESS PRODUCTION', 'F2', 'M000001 / Ridge', 'Counter',
                     '/lots/7/press-production/30', '/lots/7/press-production'):
            self.assertIn(item, page)
        self.assertNotIn('F2 / Press 2', page)
        self.assertIn('action="/lots/7/production"', page)
        self.assertIn('name="counter"', page)
        self.assertIn('name="counter_qty"', page)


if __name__ == '__main__':
    unittest.main()