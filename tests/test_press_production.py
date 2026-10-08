from copy import deepcopy
import re
import threading
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.press_production import (read_eligible_moulds, read_eligible_presses,
                                  read_active_shifts,
                                  read_press_production, save_press_production,
                                  release_press_production, undo_release_press_production,
                                  validate_press_input, calculate_smdt)
from app.main import production_page, save_press_production_route_action
from test_production import DAY, LOT, PLAN, PRODUCTION_REJECT_CONTEXT, request


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
        if 'COL_LENGTH(' in sql:
            self.result = [(int(self.conn.shift_schema_available),)]
        elif 'sys.sp_getapplock' in sql:
            resource = args[0] if args else 'FittingMES.ProductionLot'
            lock = self.conn.application_locks.setdefault(resource, threading.Lock())
            lock.acquire()
            self.conn.transaction_locks.append(lock)
            self.result = [(0,)]
        elif 'ProductionDayRuleHistory' in sql:
            self.result = [(self.conn.day_start_time,)]
        elif 'FROM dbo.ShiftMaster' in sql:
            if 'SELECT ShiftCode' in sql:
                shift = next((code for code, shift_id in self.conn.shifts.items()
                              if shift_id == args[0]), None)
            else:
                shift = self.conn.shifts.get(str(args[0]))
            self.result = [(shift,)] if shift is not None else []
        elif 'FROM dbo.Fitting_MainMachine' in sql:
            self.result = [(mc_id, machine)
                           for machine, mc_id in self.conn.logger_machines.items()]
        elif 'FROM dbo.ProductionLot WITH' in sql:
            self.result = [(self.conn.production_id, self.conn.family, self.conn.code,
                            self.conn.production_date)] if args[0] == self.conn.production_id and self.conn.lot_active else []
        elif 'FROM dbo.vw_PressMcCapabilityMatrix' in sql and 'SELECT 1' in sql:
            is_valid = args[0] == self.conn.press_code and args[1:] == (self.conn.family, self.conn.code)
            self.result = [(1,)] if is_valid and self.conn.press_valid else []
        elif 'FROM dbo.MouldMaster WITH' in sql:
            mould = self.conn.moulds.get(args[0])
            if not mould:
                self.result = []
            elif 'SELECT MouldID, ProductFamilyID, ProductCode' in sql:
                self.result = [(args[0], mould['ProductFamilyID'], mould['ProductCode'])]
            else:
                self.result = [(args[0], mould['Status'], mould['ProductFamilyID'], mould['ProductCode'], mould['CurrentReconditionNo'])]
        elif 'SELECT TOP (1) PressProductionID, ShiftMasterID' in sql and 'assigned_press' not in sql:
            production_id, machine_code, shift_id, excluded_id = args
            found = next((row for row in self.conn.press_rows.values()
                if row['ProductionID'] == production_id and row['MachineCode'] == machine_code
                and row.get('ReleasedAt') is None
                and (row.get('ShiftMasterID') == shift_id or row.get('ShiftMasterID') is None)
                and row['PressProductionID'] != (excluded_id or 0)), None)
            self.result = [(found['PressProductionID'], found.get('ShiftMasterID'))] if found else []
        elif 'SELECT TOP (1) other.PressProductionID' in sql:
            production_id, machine_code, excluded_id, shift_id = args
            found = next((row for row in self.conn.press_rows.values()
                if row['ProductionID'] == production_id
                and row['MachineCode'] == machine_code
                and row['PressProductionID'] != excluded_id
                and (row.get('ShiftMasterID') == shift_id
                     or row.get('ShiftMasterID') is None)), None)
            self.result = [(found['PressProductionID'],)] if found else []
        elif 'SELECT PressProductionID, ReleasedAt' in sql:
            row = self.conn.press_rows.get(args[0])
            self.result = [(row['PressProductionID'], row.get('ReleasedAt'))] if row and row['ProductionID'] == args[1] else []
        elif 'SELECT pp.PressProductionID, pp.MouldID, pp.ReleasedAt, lot.ProdDate' in sql:
            row = self.conn.press_rows.get(args[0])
            values = (row['PressProductionID'], row['MouldID'], row.get('ReleasedAt'),
                      row['ProductionDate'], row.get('ShiftMasterID'), row.get('MachineCode'))
            self.result = [values] if row and row['ProductionID'] == args[1] else []
        elif 'SELECT lot.ProdDate, pp.ShiftMasterID, pp.MachineCode, pp.MouldID' in sql:
            row = self.conn.press_rows.get(args[0])
            values = (row['ProductionDate'], row.get('ShiftMasterID'),
                      row['MachineCode'], row.get('MouldID'))
            self.result = [values] if row and row['ProductionID'] == args[1] else []
        elif 'later_press.PressProductionID' in sql:
            production_date, mould_id, excluded_id, released_at, *shift_args = args
            shift_id = shift_args[0] if shift_args else None
            self.result = [(row['PressProductionID'],) for row in self.conn.press_rows.values()
                           if row.get('ProductionDate') == production_date and row.get('MouldID') == mould_id
                           and row['PressProductionID'] != excluded_id
                           and (not shift_args or row.get('ShiftMasterID') in (shift_id, None))
                           and row.get('CreatedAt', datetime.min) > released_at]
        elif 'SELECT TOP (1) active_press.PressProductionID' in sql:
            production_date, mould_id, excluded_id, *shift_args = args
            shift_id = shift_args[0] if shift_args else None
            found = next((row for row in self.conn.press_rows.values()
                if row.get('ProductionDate') == production_date and row.get('MouldID') == mould_id
                and row.get('ReleasedAt') is None and row['PressProductionID'] != excluded_id
                and (not shift_args or row.get('ShiftMasterID') in (shift_id, None))), None)
            self.result = [(found['PressProductionID'],)] if found else []
        elif 'assigned_press.MachineCode=?' in sql and 'assigned_lot.ProdDate=?' in sql:
            production_date, machine_code, excluded_id, *shift_args = args
            shift_id = shift_args[0] if shift_args else None
            found = next((row for row in self.conn.press_rows.values()
                if row.get('ProductionDate', self.conn.production_date) == production_date
                and row['MachineCode'] == machine_code
                and row.get('ReleasedAt') is None
                and row['PressProductionID'] != (excluded_id or 0)
                and (not shift_args or row.get('ShiftMasterID') in (shift_id, None))), None)
            self.result = [(found['PressProductionID'], found.get('ShiftMasterID'))] if found else []
        elif 'SELECT TOP (1) assigned_press.PressProductionID' in sql:
            production_date, mould_id, shift_id, excluded_id = args
            found = next((row for row in self.conn.press_rows.values()
                if row.get('MouldID') == mould_id and row.get('ProductionDate') == production_date
                and row.get('ReleasedAt') is None
                and (row.get('ShiftMasterID') == shift_id or row.get('ShiftMasterID') is None)
                and row['PressProductionID'] != (excluded_id or 0)), None)
            self.result = [(found['PressProductionID'], found.get('ShiftMasterID'))] if found else []
        elif 'SELECT TOP (1) PressProductionID' in sql and 'MachineCode=?' in sql:
            production_id, machine_code, excluded_id, *shift_args = args
            shift_id = shift_args[0] if shift_args else None
            found = next((row for row in self.conn.press_rows.values()
                if row['ProductionID'] == production_id and row['MachineCode'] == machine_code
                and row.get('ReleasedAt') is None and row['PressProductionID'] != excluded_id
                and (not shift_args or row.get('ShiftMasterID') in (shift_id, None))), None)
            self.result = [(found['PressProductionID'],)] if found else []
        elif 'SELECT TOP (1) TimeEventID' in sql:
            production_id, machine_code, *shift_args = args
            found = next((row for row in self.conn.time_events.values()
                if row['ProductionID'] == production_id
                and row['EquipmentCode'] == machine_code
                and (not shift_args or str(row.get('ShiftID')) == str(shift_args[0]))), None)
            self.result = [(found['TimeEventID'],)] if found else []
        elif 'SELECT TOP (1) LoggerEventID' in sql:
            production_date, mc_id, instance_no, *shift_args = args
            found = next((event for event in self.conn.logger_events
                if event['ProductionDate'] == production_date
                and event['McId'] == mc_id and event['McInstanceNo'] == instance_no
                and (not shift_args or event.get('ShiftID') is None
                     or str(event.get('ShiftID')) == str(shift_args[0]))), None)
            self.result = [(found['LoggerEventID'], found.get('ShiftID'))] if found else []
        elif 'FROM dbo.PressProduction WITH' in sql:
            row = self.conn.press_rows.get(args[0])
            self.result = [(row['PressProductionID'], row['MachineCode'], row['MouldID'],
                            row['CounterQty'], row.get('ProductionStartTime'),
                            row.get('ProductionEndTime'), row.get('ShiftMasterID'),
                            row.get('ReleasedAt'), row.get('DispatchQty'),
                            row.get('CuringQty'), row.get('Remark'))] if row and row['ProductionID'] == args[1] else []
        elif 'assigned_lot.ProdDate' in sql:
            production_date, *more = args
            mould_id = more[-2] if len(more) > 2 else more[0]
            self.result = [(row['PressProductionID'],) for row in self.conn.press_rows.values()
                           if row.get('MouldID') == mould_id and row.get('ProductionDate') == production_date
                           and row.get('ReleasedAt') is None]
        elif 'FROM dbo.MouldUsage WITH' in sql:
            row = self.conn.usage_rows.get(args[0])
            if row and 'SELECT MouldUsageID, MouldID, ReconditionNo, UsageCycles' in sql:
                self.result = [(row['MouldUsageID'], row['MouldID'],
                                row['ReconditionNo'], row['UsageCycles'])]
            elif row and 'SELECT ReconditionNo' in sql:
                self.result = [(row['ReconditionNo'],)]
            else:
                self.result = [(row['MouldUsageID'],)] if row else []
        elif 'FROM dbo.EquipmentTimeEvent WITH' in sql:
            self.result = [(row['TimeEventID'],) for row in self.conn.time_events.values()
                           if (row['ProductionID'], row['EquipmentCode'], row.get('ShiftID'),
                               row['TimeType'], row['SourceType']) == (*args, 'MANUAL')]
        elif 'INSERT INTO dbo.PressProduction' in sql:
            pp_id = max(self.conn.press_rows, default=self.conn.next_pp_id - 1) + 1
            self.conn.next_pp_id = pp_id + 1
            row = dict(PressProductionID=pp_id, ProductionID=args[0], MachineCode=args[1],
                       ShiftMasterID=args[2], DispatchQty=args[3], CounterQty=args[4],
                       CuringQty=args[5], MouldID=args[6],
                       ProductionDate=self.conn.production_date)
            self.conn.press_rows[pp_id] = row
            self.result = [(pp_id,)]
        elif 'UPDATE dbo.PressProduction' in sql:
            if 'ReleasedAt=NULL' in sql:
                row = self.conn.press_rows[args[0]]
                row['ReleasedAt'] = None
                row['ReleasedBy'] = None
            elif 'ReleasedAt=' in sql:
                row = self.conn.press_rows[args[1]]
                row['ReleasedAt'] = datetime(2026, 9, 26, 14, 25)
                row['ReleasedBy'] = args[0]
            else:
                row = self.conn.press_rows[args[-2]]
                row.update(MachineCode=args[0], ShiftMasterID=args[1],
                           DispatchQty=args[2], CounterQty=args[3],
                           CuringQty=args[4], MouldID=args[5],
                           ProductionStartTime=args[6], ProductionEndTime=args[7])
            self.result = []
        elif 'INSERT INTO dbo.MouldUsage' in sql:
            mould_id, pp_id, recondition_no, cycles = args
            self.conn.usage_rows[pp_id] = dict(MouldUsageID=pp_id + 100, MouldID=mould_id,
                PressProductionID=pp_id, ReconditionNo=recondition_no, UsageCycles=cycles)
            self.result = []
        elif 'UPDATE dbo.MouldUsage' in sql:
            mould_id, recondition_no, cycles, pp_id = args
            self.conn.usage_rows[pp_id].update(
                MouldID=mould_id, ReconditionNo=recondition_no, UsageCycles=cycles)
            self.result = []
        elif 'UPDATE dbo.EquipmentTimeEvent' in sql:
            duration, event_id, production_id, machine_code, shift_id, time_type = args
            row = self.conn.time_events[event_id]
            self.assert_event_key(row, production_id, machine_code, shift_id, time_type)
            row['DurationMin'] = duration
            self.result = []
        elif 'INSERT INTO dbo.EquipmentTimeEvent' in sql:
            production_id, machine_code, shift_id, time_type, duration = args
            event_id = self.conn.next_event_id
            self.conn.next_event_id += 1
            self.conn.time_events[event_id] = dict(TimeEventID=event_id, ProductionID=production_id,
                EquipmentCode=machine_code, ShiftID=shift_id, TimeType=time_type,
                DurationMin=duration, SourceType='MANUAL')
            self.result = []
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def assert_event_key(self, row, production_id, machine_code, shift_id, time_type):
        assert (row['ProductionID'], row['EquipmentCode'], row.get('ShiftID'),
                row['TimeType'], row['SourceType']) == \
            (production_id, machine_code, shift_id, time_type, 'MANUAL')


class PressProductionConnection:
    application_locks = {}

    def __init__(self):
        self.production_id = 7
        self.family = 3
        self.code = '02'
        self.shifts = {'1': 101, '2': 202}
        self.shift_schema_available = True
        self.logger_machines = {'F': 7, 'G': 8}
        self.logger_events = []
        self.press_code = 'F2'
        self.press_valid = True
        self.lot_active = True
        self.moulds = {
            4: dict(Status='ACTIVE', ProductFamilyID=3, ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=2),
            5: dict(Status='RECONDITION', ProductFamilyID=3, ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=1),
            6: dict(Status='RETIRED', ProductFamilyID=3, ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=0),
            7: dict(Status='DENIED', ProductFamilyID=3, ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=0),
            8: dict(Status='ACTIVE', ProductFamilyID=2, ProductFamily='Oriental', ProductCode='02', CurrentReconditionNo=0),
            9: dict(Status='ACTIVE', ProductFamilyID=3, ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=2),
        }
        self.press_rows = {}
        self.usage_rows = {}
        self.time_events = {}
        self.next_pp_id = 30
        self.next_event_id = 100
        self.commits = 0
        self.rollbacks = 0
        self.transaction_locks = []
        self.sql = []
        self.fail = None
        self.day_start_time = time(8)
        self.production_date = date(2026, 9, 26)
        self.cur = PressProductionCursor(self)

    def cursor(self): return self.cur
    def _release_locks(self):
        for lock in self.transaction_locks:
            lock.release()
        self.transaction_locks.clear()
    def commit(self):
        self.commits += 1
        self._release_locks()
    def rollback(self):
        self.rollbacks += 1
        self._release_locks()
    def close(self): pass


class RollbackAwarePressProductionConnection(PressProductionConnection):
    def __init__(self):
        super().__init__()
        self.transaction_snapshot = None

    def cursor(self):
        if self.transaction_snapshot is None:
            self.transaction_snapshot = deepcopy((
                self.press_rows, self.usage_rows, self.time_events,
                self.next_pp_id, self.next_event_id))
        return super().cursor()

    def commit(self):
        super().commit()
        self.transaction_snapshot = None

    def rollback(self):
        snapshot = self.transaction_snapshot
        super().rollback()
        if snapshot is not None:
            (self.press_rows, self.usage_rows, self.time_events,
             self.next_pp_id, self.next_event_id) = snapshot
            self.transaction_snapshot = None


def valid_input(**overrides):
    data = dict(ShiftCode='1', MachineCode='F2', MouldID='4', DispatchQty='100', CounterQty='100',
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
    def test_smdt_calculation_does_not_use_logger_guide(self):
        self.assertEqual(calculate_smdt(datetime(2026, 9, 26, 8),
                        datetime(2026, 9, 26, 16),
                        {'SETUP': Decimal('10'), 'CHANGEOVER': Decimal('5'),
                         'CLEAN': Decimal('8'), 'BREAKDOWN': Decimal('20')}), Decimal('437'))

    def test_production_template_uses_inline_shift_aware_log_cal(self):
        from pathlib import Path
        template = Path('app/templates/production.html').read_text(encoding='utf-8')
        for name in ('setup_minutes', 'chgover_minutes', 'idle_minutes',
                     'cleaning_minutes', 'breakdown_minutes', 'smdt_minutes'):
            self.assertIn(f'name="{name}"', template)
        self.assertNotIn('shift1_', template)
        self.assertNotIn('shift2_', template)
        self.assertNotIn('>TOTAL</th>', template)
        self.assertIn('<th>ChgOver</th>', template)
        self.assertIn('<th>Breakdown</th><th>SMDT</th>', template)
        self.assertNotIn('log-cal-row', template)
        self.assertNotIn('log-cal-editor', template)
        self.assertNotIn('>Log SMDT</th>', template)
        self.assertNotIn('class="logger-smdt-guide"', template)
        self.assertIn('>LOG CAL</button>', template)
        self.assertIn('<th>Release</th><th>Shift</th><th>Press</th><th>Mould</th>', template)
        self.assertIn('Downtime attribution is ambiguous. Saved values are retained; downtime editing is disabled.', template)
        self.assertLess(template.rindex('>LOG CAL</button>'), template.rindex('>SAVE</button>'))
        self.assertNotIn('SAVE DOWNTIME', template)
        self.assertNotIn('name="save_action"', template)
        self.assertNotIn('SuggestedSetupMinutes', template)
        self.assertNotIn('name="logger_smdt"', template)

    def test_undo_release_restores_same_row_without_changing_history(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2',
            ShiftMasterID=101,
            MouldID=4, DispatchQty=100, CounterQty=500, CuringQty=480,
            ProductionDate=conn.production_date, Remark='history',
            ReleasedAt=datetime(2026, 9, 26, 14, 25), ReleasedBy='operator')
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30,
            ReconditionNo=2, UsageCycles=500)
        conn.time_events[100] = dict(TimeEventID=100, ProductionID=7, EquipmentCode='F2',
            TimeType='BREAKDOWN', DurationMin=15, SourceType='MANUAL')
        before = dict(conn.press_rows[30])
        usage = dict(conn.usage_rows[30])
        events = dict(conn.time_events[100])
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'RESTORED')
        self.assertEqual(conn.press_rows[30]['PressProductionID'], before['PressProductionID'])
        for key in ('ProductionID', 'MachineCode', 'MouldID', 'DispatchQty', 'CounterQty', 'CuringQty', 'ProductionDate', 'Remark'):
            self.assertEqual(conn.press_rows[30][key], before[key])
        self.assertIsNone(conn.press_rows[30]['ReleasedAt'])
        self.assertIsNone(conn.press_rows[30]['ReleasedBy'])
        self.assertEqual(conn.usage_rows[30], usage)
        self.assertEqual(conn.time_events[100], events)

    def test_undo_release_rejects_reassigned_mould_and_is_idempotent(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2',
            MouldID=4, CounterQty=500, ProductionDate=conn.production_date,
            ReleasedAt=datetime(2026, 9, 26, 14, 25), ReleasedBy='operator')
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8, MachineCode='F3',
            MouldID=4, CounterQty=0, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 15),
            ReleasedAt=None, ReleasedBy=None)
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'MOULD_ALREADY_REASSIGNED')
        self.assertIsNotNone(conn.press_rows[30]['ReleasedAt'])
        conn.press_rows.pop(31)
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'RESTORED')
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'ALREADY_ACTIVE')

    def test_undo_history_blocks_old_row_after_later_row_is_released(self):
        conn = PressProductionConnection()
        first_release = datetime(2026, 9, 26, 14, 25)
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F7',
            MouldID=4, CounterQty=70, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 14), ReleasedAt=first_release, ReleasedBy='operator')
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8, MachineCode='F2',
            MouldID=4, CounterQty=0, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 15), ReleasedAt=None, ReleasedBy=None)
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'MOULD_ALREADY_REASSIGNED')
        conn.press_rows[31]['ReleasedAt'] = datetime(2026, 9, 26, 16)
        conn.press_rows[31]['ReleasedBy'] = 'operator'
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'MOULD_ALREADY_REASSIGNED')
        self.assertEqual(undo_release_press_production(conn, 8, 31), 'RESTORED')

    def test_undo_history_blocks_both_rows_after_third_assignment(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F7',
            MouldID=4, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 14), ReleasedAt=datetime(2026, 9, 26, 15), ReleasedBy='operator')
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8, MachineCode='F2',
            MouldID=4, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 16), ReleasedAt=datetime(2026, 9, 26, 17), ReleasedBy='operator')
        conn.press_rows[32] = dict(PressProductionID=32, ProductionID=9, MachineCode='F3',
            MouldID=4, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 18), ReleasedAt=None, ReleasedBy=None)
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'MOULD_ALREADY_REASSIGNED')
        self.assertEqual(undo_release_press_production(conn, 8, 31), 'MOULD_ALREADY_REASSIGNED')

    def test_undo_history_allows_release_without_later_assignment(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F7',
            MouldID=4, ProductionDate=conn.production_date,
            CreatedAt=datetime(2026, 9, 26, 14), ReleasedAt=datetime(2026, 9, 26, 15), ReleasedBy='operator')
        self.assertEqual(undo_release_press_production(conn, 7, 30), 'RESTORED')

    def test_release_preserves_history_and_double_release_is_noop(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2',
            MouldID=4, DispatchQty=100, CounterQty=500, CuringQty=480,
            ProductionDate=conn.production_date, Remark='history')
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30,
            ReconditionNo=2, UsageCycles=500)
        conn.time_events[100] = dict(TimeEventID=100, ProductionID=7, EquipmentCode='F2',
            TimeType='BREAKDOWN', DurationMin=15, SourceType='MANUAL')
        before = dict(conn.press_rows[30])
        self.assertEqual(release_press_production(conn, 7, 30, 'operator'), 'RELEASED')
        self.assertEqual({key: conn.press_rows[30][key] for key in before}, before)
        self.assertEqual(conn.press_rows[30]['ReleasedBy'], 'operator')
        usage = dict(conn.usage_rows[30])
        event = dict(conn.time_events[100])
        self.assertEqual(release_press_production(conn, 7, 30, 'other'), 'ALREADY_RELEASED')
        self.assertEqual(conn.usage_rows[30], usage)
        self.assertEqual(conn.time_events[100], event)

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
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.return_value = []
        read_press_production(cursor, 42)
        sql, args = cursor.execute.call_args.args
        self.assertIn('WHERE pp.ProductionID=?', sql)
        self.assertIn('time_event.ShiftID=TRY_CONVERT(int,shift.ShiftCode)', sql)
        self.assertIn('EquipmentTimeIdentityAmbiguous', sql)
        self.assertIn('other_episode.ShiftMasterID IS NULL', sql)
        self.assertIn('CASE WHEN pp.ShiftMasterID IS NULL OR EXISTS', sql)
        self.assertIn('AS LaterPressAssignmentMachineCode', sql)
        self.assertIn('later_press.MachineCode=pp.MachineCode', sql)
        self.assertIn('later_press.ReleasedAt IS NULL', sql)
        self.assertIn('later_lot.ProdDate=target_lot.ProdDate', sql)
        self.assertIn('later_press.ShiftMasterID=pp.ShiftMasterID', sql)
        self.assertLess(sql.index('LEFT JOIN dbo.ShiftMaster'),
                        sql.index('LEFT JOIN dbo.EquipmentTimeEvent'))
        self.assertNotIn('Shift1SetupMinutes', sql)
        self.assertNotIn('Shift2SetupMinutes', sql)
        self.assertIn('AS SetupMinutes', sql)
        self.assertEqual(args, 42)

    def test_press_production_reads_remain_compatible_before_migration_027(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (0,)
        cursor.fetchall.return_value = []
        read_press_production(cursor, 42)
        sql, args = cursor.execute.call_args.args
        self.assertIn('CAST(NULL AS bigint) AS ShiftMasterID', sql)
        self.assertNotIn('pp.ShiftMasterID', sql)
        self.assertEqual(args, 42)

    def test_eligible_press_query_reuses_pressmc_capability_and_requires_active_press(self):
        cursor = ReadCursor([dict(PressCode='F2', PressName='Press 2', CurrentLine='LINE1', CurrentLineName='Line 1')])
        result = read_eligible_presses(cursor, 3, '02')
        self.assertEqual(result[0]['PressCode'], 'F2')
        self.assertIn('dbo.vw_PressMcCapabilityMatrix', cursor.sql)
        self.assertIn('capability.CanProduce=1', cursor.sql)
        self.assertIn('equipment.IsActive=1', cursor.sql)
        self.assertIn("equipment.EquipmentType='PRESS'", cursor.sql)
        self.assertEqual(cursor.args, (3, '02'))

    def test_press_availability_is_filtered_by_production_date_shift_and_edit_exclusion(self):
        class ShiftPressCursor:
            def __init__(self):
                self.calls = []
                self.result = []
                self.description = []
            def execute(self, sql, *args):
                self.calls.append((sql, args))
                if 'COL_LENGTH(' in sql:
                    self.result = [(1,)]
                elif 'FROM dbo.ShiftMaster' in sql:
                    self.result = [(101,)]
                else:
                    self.result = [dict(PressCode='F2', PressName='Press 2',
                                        CurrentLine='LINE1', CurrentLineName='Line 1',
                                        StandardSpeed=5, AssignedOnProductionDate=True)]
                    self.description = [(name,) for name in self.result[0]]
                return self
            def fetchone(self):
                return self.result.pop(0) if self.result else None
            def fetchall(self):
                result, self.result = self.result, []
                return [tuple(row.values()) for row in result]

        cursor = ShiftPressCursor()
        result = read_eligible_presses(cursor, 3, '02', DAY, '2', 30)
        self.assertTrue(result[0]['AssignedOnProductionDate'])
        query, args = cursor.calls[-1]
        self.assertIn('assigned_lot.ProdDate=?', query)
        self.assertIn('assigned_press.ShiftMasterID=?', query)
        self.assertIn('assigned_press.ShiftMasterID IS NULL', query)
        self.assertIn('assigned_press.PressProductionID<>COALESCE(?,0)', query)
        self.assertEqual(args, (DAY, 101, 30, 3, '02'))

    def test_active_shift_choices_use_shift_master_business_codes(self):
        cursor = ReadCursor([dict(ShiftCode='1', ShiftName='Shift 1'),
                             dict(ShiftCode='2', ShiftName='Shift 2')])
        result = read_active_shifts(cursor)
        self.assertEqual([shift['ShiftCode'] for shift in result], ['1', '2'])
        self.assertIn('WHERE IsActive=1', cursor.sql)
        self.assertNotIn('WHERE id=', cursor.sql)

    def test_press_assignment_requires_explicit_shift_code(self):
        with self.assertRaisesRegex(ValueError, 'Choose an active Shift'):
            validate_press_input(valid_input(ShiftCode=''),
                production_date=DAY, day_start_time=time(8), allow_incomplete=True)

    def test_eligible_mould_query_uses_authoritative_view_active_status_and_product(self):
        cursor = ReadCursor([dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  ProductFamilyID=3,ProductFamily='Special Ridge', ProductCode='02')])
        result = read_eligible_moulds(cursor, 3, '02')
        self.assertEqual(result[0]['MouldID'], 4)
        self.assertIn('dbo.vw_MouldList', cursor.sql)
        self.assertIn("Status='ACTIVE'", cursor.sql)
        self.assertEqual(cursor.args, (None, None, 3, '02'))
        self.assertEqual(read_eligible_moulds(cursor, None, '02'), [])

    def test_mould_assignment_is_scoped_to_production_date(self):
        cursor = ReadCursor([dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  ProductFamily='Special Ridge', ProductCode='02',
                                  AssignedOnProductionDate=True)])
        result = read_eligible_moulds(cursor, 3, '02', DAY)
        self.assertTrue(result[0]['AssignedOnProductionDate'])

    def test_selected_shift_mould_list_includes_unknown_legacy_occupancy(self):
        class ShiftMouldCursor:
            def __init__(self):
                self.calls = []
                self.result = []
                self.description = []
            def execute(self, sql, *args):
                self.calls.append((sql, args))
                if 'COL_LENGTH(' in sql:
                    self.result = [(1,)]
                elif 'FROM dbo.ShiftMaster' in sql:
                    self.result = [(202,)]
                else:
                    self.result = [(4, 'M000001', 'Ridge', 3, 'Special Ridge', '02', True)]
                    self.description = [(name,) for name in (
                        'MouldID', 'MouldNo', 'MouldName', 'ProductFamilyID',
                        'ProductFamily', 'ProductCode', 'AssignedOnProductionDate')]
                return self
            def fetchone(self):
                return self.result.pop(0) if self.result else None
            def fetchall(self):
                result, self.result = self.result, []
                return result

        cursor = ShiftMouldCursor()
        moulds = read_eligible_moulds(cursor, 3, '02', DAY, '2', 30)
        self.assertTrue(moulds[0]['AssignedOnProductionDate'])
        allocation_sql, allocation_args = cursor.calls[-1]
        self.assertIn('assigned_press.ShiftMasterID=?', allocation_sql)
        self.assertIn('assigned_press.ShiftMasterID IS NULL', allocation_sql)
        self.assertIn('assigned_press.PressProductionID<>COALESCE(?,0)', allocation_sql)
        self.assertEqual(allocation_args, (DAY, 30, 202, 3, '02'))

    def test_mould_026_on_another_lot_is_unavailable_for_same_date_and_shift(self):
        class ShiftMouldCursor:
            def __init__(self):
                self.calls = []
                self.result = []
                self.description = []
            def execute(self, sql, *args):
                self.calls.append((sql, args))
                if 'COL_LENGTH(' in sql:
                    self.result = [(1,)]
                elif 'FROM dbo.ShiftMaster' in sql:
                    self.result = [(101,)]
                else:
                    self.result = [(29, 'M000026', 'Angle_Ridge_01', 3,
                                    'Special Ridge', '02', True)]
                    self.description = [(name,) for name in (
                        'MouldID', 'MouldNo', 'MouldName', 'ProductFamilyID',
                        'ProductFamily', 'ProductCode', 'AssignedOnProductionDate')]
                return self
            def fetchone(self):
                return self.result.pop(0) if self.result else None
            def fetchall(self):
                result, self.result = self.result, []
                return result

        production_date = date(2026, 9, 3)
        cursor = ShiftMouldCursor()
        moulds = read_eligible_moulds(cursor, 3, '02', production_date, '1')
        self.assertTrue(moulds[0]['AssignedOnProductionDate'])
        query, args = cursor.calls[-1]
        self.assertIn('assigned_lot.ProdDate=?', query)
        self.assertIn('assigned_lot.IsActive=1', query)
        self.assertIn('assigned_press.MouldID=moulds.MouldID', query)
        self.assertIn('assigned_press.ShiftMasterID=?', query)
        self.assertEqual(args, (production_date, None, 101, 3, '02'))

    def test_same_date_same_shift_mould_is_blocked_across_lots(self):
        conn = PressProductionConnection()
        production_date = date(2026, 9, 3)
        conn.production_date = production_date
        conn.press_code = 'F8'
        conn.moulds[29] = dict(Status='ACTIVE', ProductFamilyID=3,
            ProductFamily='Special Ridge', ProductCode='02', CurrentReconditionNo=0)
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=29, CounterQty=1050,
            ProductionDate=production_date, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'already assigned for the selected'):
            save_press_production(conn, 7, valid_input(
                ShiftCode='1', MachineCode='F8', MouldID='29',
                ProductionDate=production_date.isoformat()))
        self.assertEqual(set(conn.press_rows), {20})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_direct_post_rejects_same_date_duplicate_without_modifying_existing_rows(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            ShiftMasterID=101, MouldID=4, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        before = dict(conn.press_rows)
        with self.assertRaisesRegex(ValueError, 'already assigned for the selected'):
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

    def test_same_mould_can_be_added_to_a_different_shift(self):
        conn = PressProductionConnection()
        save_press_production(conn, 7, valid_input())
        conn.production_id = 8
        conn.press_code = 'F3'
        second_id = save_press_production(conn, 8, valid_input(ShiftCode='2', MachineCode='F3'))
        self.assertEqual(conn.press_rows[30]['ShiftMasterID'], 101)
        self.assertEqual(conn.press_rows[second_id]['ShiftMasterID'], 202)
        self.assertEqual(conn.press_rows[30]['MouldID'], conn.press_rows[second_id]['MouldID'])

    def test_same_press_same_date_shift_is_exclusive_across_lots(self):
        conn = PressProductionConnection()
        conn.production_id = 8
        conn.press_code = 'F7'
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=7,
            MachineCode='F7', ShiftMasterID=101, MouldID=9, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        before = dict(conn.press_rows)
        with self.assertRaisesRegex(ValueError, 'Production Date and Shift'):
            save_press_production(conn, 8, valid_input(MachineCode='F7'))
        self.assertEqual(conn.press_rows, before)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_same_press_is_available_in_a_different_shift(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=4, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.press_code = 'F7'
        new_id = save_press_production(
            conn, 7, valid_input(MachineCode='F7', ShiftCode='2'))
        self.assertEqual(conn.press_rows[new_id]['ShiftMasterID'], 202)
        self.assertEqual(len(conn.press_rows), 2)

    def test_same_press_is_available_on_a_different_production_date(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=4, CounterQty=0,
            ProductionDate=date(2026, 9, 25), ReleasedAt=None)
        conn.press_code = 'F7'
        new_id = save_press_production(conn, 7, valid_input(MachineCode='F7'))
        self.assertEqual(conn.press_rows[new_id]['ProductionDate'], conn.production_date)
        self.assertEqual(len(conn.press_rows), 2)

    def test_released_press_can_be_reassigned_to_another_lot_in_same_shift(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=4, CounterQty=80,
            ProductionDate=conn.production_date, ReleasedAt=None, ReleasedBy=None)
        conn.press_code = 'F7'
        self.assertEqual(release_press_production(conn, 8, 20), 'RELEASED')
        new_id = save_press_production(conn, 7, valid_input(MachineCode='F7'))
        self.assertNotEqual(new_id, 20)
        self.assertIsNotNone(conn.press_rows[20]['ReleasedAt'])
        self.assertEqual(conn.press_rows[new_id]['MachineCode'], 'F7')

    def test_edit_to_press_occupied_by_another_lot_is_atomic(self):
        conn = PressProductionConnection()
        conn.press_code = 'F7'
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F3', ShiftMasterID=101, MouldID=9, CounterQty=100,
            CuringQty=90, ProductionDate=conn.production_date, ReleasedAt=None)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=4, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        before = dict(conn.press_rows[30])
        with self.assertRaisesRegex(ValueError, 'Production Date and Shift'):
            save_press_production(
                conn, 7, valid_input(MachineCode='F7', MouldID='9'), 30)
        self.assertEqual(conn.press_rows[30], before)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_undo_release_rejects_press_occupied_by_another_lot(self):
        conn = PressProductionConnection()
        released_at = datetime(2026, 9, 26, 14, 25)
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F7', ShiftMasterID=101, MouldID=4, CounterQty=80,
            ProductionDate=conn.production_date, ReleasedAt=released_at)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8,
            MachineCode='F7', ShiftMasterID=101, MouldID=9, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'Production Date and Shift'):
            undo_release_press_production(conn, 7, 30)
        self.assertEqual(conn.press_rows[30]['ReleasedAt'], released_at)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_concurrent_cross_lot_same_press_allocation_only_one_succeeds(self):
        first = PressProductionConnection()
        second = PressProductionConnection()
        second.production_id = 8
        second.press_code = 'F7'
        for attribute in ('press_rows', 'usage_rows', 'moulds', 'time_events',
                          'logger_events'):
            setattr(second, attribute, getattr(first, attribute))
        barrier = threading.Barrier(2)
        outcomes = []

        def allocate(connection, production_id, mould_id):
            barrier.wait()
            try:
                save_press_production(
                    connection, production_id,
                    valid_input(MachineCode='F7', MouldID=str(mould_id)))
                outcomes.append('saved')
            except ValueError:
                outcomes.append('conflict')

        threads = [
            threading.Thread(target=allocate, args=(first, 7, 4)),
            threading.Thread(target=allocate, args=(second, 8, 9)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ['saved', 'conflict'])
        self.assertEqual(sum(row['MachineCode'] == 'F7'
                             for row in first.press_rows.values()), 1)

    def test_legacy_unknown_shift_press_blocks_allocation_without_guessing(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8,
            MachineCode='F7', ShiftMasterID=None, MouldID=9, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.press_code = 'F7'
        with self.assertRaisesRegex(ValueError, 'legacy Press assignment has unknown Shift'):
            save_press_production(conn, 7, valid_input(MachineCode='F7', ShiftCode='2'))
        self.assertEqual(set(conn.press_rows), {20})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_undo_legacy_unknown_shift_press_does_not_guess_against_other_shift(self):
        conn = PressProductionConnection()
        released_at = datetime(2026, 9, 26, 14, 25)
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F7', ShiftMasterID=None, MouldID=4, CounterQty=80,
            ProductionDate=conn.production_date, ReleasedAt=released_at)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8,
            MachineCode='F7', ShiftMasterID=202, MouldID=9, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'unknown Shift while another active assignment'):
            undo_release_press_production(conn, 7, 30)
        self.assertEqual(conn.press_rows[30]['ReleasedAt'], released_at)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_legacy_unknown_shift_blocks_allocation_without_guessing(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            MouldID=4, CounterQty=0, ProductionDate=conn.production_date, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'legacy Mould assignment has unknown Shift'):
            save_press_production(conn, 7, valid_input(ShiftCode='2'))
        self.assertEqual(conn.press_rows.keys(), {20})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_release_then_add_reuses_same_shift_and_preserves_old_assignment(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=80,
            ProductionDate=conn.production_date, ReleasedAt=None, ReleasedBy=None)
        conn.usage_rows[20] = dict(MouldUsageID=120, MouldID=4,
            PressProductionID=20, ReconditionNo=2, UsageCycles=80)
        before_usage = dict(conn.usage_rows[20])
        self.assertEqual(release_press_production(conn, 7, 20, 'operator'), 'RELEASED')
        new_id = save_press_production(conn, 7, valid_input())
        self.assertNotEqual(new_id, 20)
        self.assertEqual(conn.press_rows[20]['CounterQty'], 80)
        self.assertEqual(conn.usage_rows[20], before_usage)

    def test_midnight_crossing_does_not_change_mould_business_date(self):
        conn = PressProductionConnection()
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=8, MachineCode='F1',
            ShiftMasterID=101, MouldID=4, CounterQty=0,
            ProductionDate=conn.production_date, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'already assigned for the selected'):
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

    def test_shift_log_cal_values_are_saved_separately_without_total_row(self):
        conn = PressProductionConnection()
        data = valid_input(
            Shift1SetupMinutes='11', Shift1ChgOverMinutes='12',
            Shift1IdleMinutes='13',
            Shift1SmdtMinutes='13', Shift1BreakdownMinutes='14',
            Shift1CleaningMinutes='15', Shift2SetupMinutes='0',
            Shift2ChgOverMinutes='0', Shift2SmdtMinutes='0',
            Shift2IdleMinutes='0', Shift2BreakdownMinutes='0',
            Shift2CleaningMinutes='0')
        save_press_production(conn, 7, data)
        values = {(row['ShiftID'], row['TimeType']): row['DurationMin']
                  for row in conn.time_events.values()}
        self.assertEqual(values[(1, 'SETUP')], Decimal('11'))
        self.assertEqual(values[(1, 'IDLE')], Decimal('13'))
        self.assertEqual(len(values), 6)
        self.assertNotIn((2, 'SMDT'), values)
        self.assertNotIn((1, 'TOTAL'), values)
        self.assertNotIn((2, 'TOTAL'), values)

    def test_shift_one_save_preserves_shift_two_downtime_event(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=2, TimeType='SETUP',
            DurationMin=24, SourceType='MANUAL')
        save_press_production(conn, 7, valid_input(
            Shift1SetupMinutes='0', Shift2SetupMinutes='0'), 30)
        self.assertEqual(conn.time_events[50]['DurationMin'], 24)
        self.assertEqual(conn.time_events[50]['ShiftID'], 2)

    def test_shift_one_single_set_updates_only_shift_one_and_does_not_duplicate(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=2, TimeType='SETUP',
            DurationMin=24, SourceType='MANUAL')
        data = valid_input(SetupMinutes='9', ChgOverMinutes='0', IdleMinutes='0',
            CleaningMinutes='0', BreakdownMinutes='0', SmdtMinutes='7')
        save_press_production(conn, 7, data, 30)
        save_press_production(conn, 7, data, 30)
        self.assertEqual(conn.time_events[50]['DurationMin'], 24)
        self.assertEqual(conn.time_events[50]['ShiftID'], 2)
        events = [event for event in conn.time_events.values()
                  if event['ShiftID'] == 1 and event['TimeType'] == 'SETUP']
        smdt = [event for event in conn.time_events.values()
                if event['ShiftID'] == 1 and event['TimeType'] == 'SMDT']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['DurationMin'], Decimal('9'))
        self.assertEqual(len(smdt), 1)
        self.assertEqual(smdt[0]['DurationMin'], Decimal('7'))

    def test_shift_two_single_set_updates_only_shift_two(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=202, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=14, SourceType='MANUAL')
        save_press_production(conn, 7, valid_input(
            ShiftCode='2', SetupMinutes='19'), 30)
        self.assertEqual(conn.time_events[50]['DurationMin'], 14)
        self.assertEqual(conn.time_events[50]['ShiftID'], 1)
        self.assertTrue(any(event['ShiftID'] == 2 and event['TimeType'] == 'SETUP'
                            and event['DurationMin'] == Decimal('19')
                            for event in conn.time_events.values()))

    def test_shift_one_save_rejects_nonzero_shift_two_downtime_without_event_write(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=2, TimeType='SETUP',
            DurationMin=24, SourceType='MANUAL')
        with self.assertRaisesRegex(ValueError, 'different Shift cannot be saved'):
            save_press_production(conn, 7, valid_input(
                Shift1SetupMinutes='0', Shift2SetupMinutes='5'), 30)
        self.assertEqual(conn.time_events[50]['DurationMin'], 24)
        self.assertFalse(any('UPDATE dbo.EquipmentTimeEvent' in sql
                             or 'INSERT INTO dbo.EquipmentTimeEvent' in sql
                             for sql, _ in conn.sql))
        self.assertEqual(conn.rollbacks, 1)

    def test_update_without_start_end_fields_preserves_existing_times(self):
        conn = PressProductionConnection()
        start = datetime(2026, 9, 26, 22, 0)
        end = datetime(2026, 9, 27, 0, 15)
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', MouldID=4, CounterQty=100,
            ProductionStartTime=start, ProductionEndTime=end)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        data = valid_input()
        data.pop('ProductionStartTime')
        data.pop('ProductionEndTime')
        save_press_production(conn, 7, data, 30)
        self.assertEqual(conn.press_rows[30]['ProductionStartTime'], start)
        self.assertEqual(conn.press_rows[30]['ProductionEndTime'], end)

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

    def test_mould_only_edit_preserves_persisted_quantities_and_assignment_id(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)

        result = save_press_production(conn, 7, dict(
            ShiftCode='1', MachineCode='F2', MouldID='9',
            ProductionDate='2026-09-26'), 30)

        self.assertEqual(result, 30)
        self.assertEqual(conn.press_rows[30]['PressProductionID'], 30)
        self.assertEqual(conn.press_rows[30]['MouldID'], 9)
        self.assertEqual(
            (conn.press_rows[30]['DispatchQty'], conn.press_rows[30]['CounterQty'],
             conn.press_rows[30]['CuringQty']), (75, 100, 80))
        self.assertEqual(conn.usage_rows[30]['MouldUsageID'], 130)
        self.assertEqual(conn.usage_rows[30]['MouldID'], 9)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 100)

    def test_mould_only_edit_uses_persisted_counter_and_preserves_downtime(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=125)
        conn.time_events[70] = dict(TimeEventID=70, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=Decimal('15'), SourceType='MANUAL')

        save_press_production(conn, 7, valid_input(
            MouldID='9', DispatchQty='999', CounterQty='999',
            CuringQty='999', SetupMinutes='33'), 30)

        self.assertEqual(conn.press_rows[30]['CounterQty'], 100)
        self.assertEqual(conn.press_rows[30]['DispatchQty'], 75)
        self.assertEqual(conn.press_rows[30]['CuringQty'], 80)
        self.assertEqual(conn.usage_rows[30]['MouldUsageID'], 130)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 100)
        self.assertEqual(conn.time_events[70]['DurationMin'], Decimal('15'))
        self.assertEqual(len(conn.time_events), 1)

    def test_repeated_identical_mould_edit_does_not_duplicate_usage(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        edit_data = dict(ShiftCode='1', MachineCode='F2', MouldID='9',
                         ProductionDate='2026-09-26')

        save_press_production(conn, 7, edit_data, 30)
        save_press_production(conn, 7, edit_data, 30)

        self.assertEqual(len(conn.usage_rows), 1)
        self.assertEqual(conn.usage_rows[30]['MouldUsageID'], 130)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 100)

    def test_mould_conflict_rejects_edit_without_partial_writes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8,
            MachineCode='F3', ShiftMasterID=101, MouldID=9, CounterQty=20,
            ProductionDate=conn.production_date, ReleasedAt=None)
        before_press = {key: dict(row) for key, row in conn.press_rows.items()}
        before_usage = {key: dict(row) for key, row in conn.usage_rows.items()}

        with self.assertRaisesRegex(ValueError, 'already assigned for the selected'):
            save_press_production(conn, 7, dict(
                ShiftCode='1', MachineCode='F2', MouldID='9',
                ProductionDate='2026-09-26'), 30)

        self.assertEqual(conn.press_rows, before_press)
        self.assertEqual(conn.usage_rows, before_usage)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_failed_mould_usage_update_rolls_back_press_edit(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        before_press = {key: dict(row) for key, row in conn.press_rows.items()}
        before_usage = {key: dict(row) for key, row in conn.usage_rows.items()}
        conn.fail = 'UPDATE dbo.MouldUsage'

        def rollback():
            conn.rollbacks += 1
            conn.press_rows = {key: dict(row) for key, row in before_press.items()}
            conn.usage_rows = {key: dict(row) for key, row in before_usage.items()}
            conn._release_locks()

        conn.rollback = rollback
        with self.assertRaisesRegex(RuntimeError, 'simulated SQL error'):
            save_press_production(conn, 7, valid_input(MouldID='9'), 30)

        self.assertEqual(conn.press_rows, before_press)
        self.assertEqual(conn.usage_rows, before_usage)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_edit_corrects_press_mould_shift_and_quantities_on_same_assignment(self):
        conn = PressProductionConnection()
        conn.press_code = 'F3'
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            CuringQty=90, ProductionDate=conn.production_date, ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        result = save_press_production(
            conn, 7, valid_input(ShiftCode='2', MachineCode='F3',
                                 MouldID='9', CounterQty='120', CuringQty='110'), 30)
        self.assertEqual(result, 30)
        self.assertEqual(conn.press_rows[30]['MachineCode'], 'F3')
        self.assertEqual(conn.press_rows[30]['ShiftMasterID'], 202)
        self.assertEqual(conn.press_rows[30]['MouldID'], 9)
        self.assertEqual(conn.press_rows[30]['CounterQty'], 120)
        self.assertEqual(conn.usage_rows[30]['MouldUsageID'], 130)
        self.assertEqual(conn.usage_rows[30]['MouldID'], 9)
        self.assertEqual(conn.usage_rows[30]['ReconditionNo'], 2)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 120)

    def test_conflicting_edit_rolls_back_without_partial_writes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            CuringQty=90, ProductionDate=conn.production_date, ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4,
            PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=8,
            MachineCode='F3', ShiftMasterID=202, MouldID=9, CounterQty=20,
            ProductionDate=conn.production_date, ReleasedAt=None)
        before_press = {key: dict(row) for key, row in conn.press_rows.items()}
        before_usage = {key: dict(row) for key, row in conn.usage_rows.items()}
        with self.assertRaisesRegex(ValueError, 'already assigned for the selected'):
            save_press_production(conn, 7, valid_input(
                ShiftCode='2', MouldID='9', CounterQty='120', CuringQty='110'), 30)
        self.assertEqual(conn.press_rows, before_press)
        self.assertEqual(conn.usage_rows, before_usage)
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_press_or_shift_edit_is_blocked_by_logger_event_for_old_identity(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.logger_events.append(dict(LoggerEventID=50,
            ProductionDate=conn.production_date, McId=7, McInstanceNo=2,
            ShiftID=1))
        before = dict(conn.press_rows[30])
        with self.assertRaisesRegex(ValueError, 'LOGGER entry 50 exists for F2, Shift 1'):
            save_press_production(conn, 7, valid_input(ShiftCode='2'), 30)
        self.assertEqual(conn.press_rows[30], before)
        self.assertEqual(conn.rollbacks, 1)

    def test_unrelated_logger_machine_on_same_date_does_not_block_edit(self):
        conn = PressProductionConnection()
        conn.press_code = 'F3'
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.logger_events.append(dict(LoggerEventID=51,
            ProductionDate=conn.production_date, McId=7, McInstanceNo=8,
            ShiftID=1))
        save_press_production(
            conn, 7, valid_input(ShiftCode='2', MachineCode='F3'), 30)
        self.assertEqual(conn.press_rows[30]['MachineCode'], 'F3')
        self.assertEqual(conn.press_rows[30]['ShiftMasterID'], 202)

    def test_unknown_shift_logger_entry_for_affected_machine_is_reported(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.logger_events.append(dict(LoggerEventID=52,
            ProductionDate=conn.production_date, McId=7, McInstanceNo=2,
            ShiftID=None))
        with self.assertRaisesRegex(ValueError, 'LOGGER entry 52.*no ShiftID'):
            save_press_production(conn, 7, valid_input(ShiftCode='2'), 30)
        self.assertEqual(conn.rollbacks, 1)

    def test_press_or_shift_edit_is_blocked_by_existing_equipment_time_events(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[100] = dict(TimeEventID=100, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='BREAKDOWN',
            DurationMin=15, SourceType='MANUAL')
        before_press = dict(conn.press_rows[30])
        before_event = dict(conn.time_events[100])
        with self.assertRaisesRegex(ValueError, 'EquipmentTimeEvent rows exist'):
            save_press_production(conn, 7, valid_input(ShiftCode='2'), 30)
        self.assertEqual(conn.press_rows[30], before_press)
        self.assertEqual(conn.time_events[100], before_event)
        self.assertEqual(conn.rollbacks, 1)

    def test_equipment_time_event_for_unaffected_shift_does_not_block_edit(self):
        conn = PressProductionConnection()
        conn.press_code = 'F3'
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.time_events[100] = dict(TimeEventID=100, ProductionID=7,
            EquipmentCode='F2', ShiftID=2, TimeType='BREAKDOWN',
            DurationMin=15, SourceType='MANUAL')
        save_press_production(
            conn, 7, valid_input(ShiftCode='2', MachineCode='F3'), 30)
        self.assertEqual(conn.press_rows[30]['MachineCode'], 'F3')

    def test_downtime_write_is_blocked_when_press_shift_has_multiple_episodes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=9, CounterQty=50,
            ProductionDate=conn.production_date,
            ReleasedAt=datetime(2026, 9, 26, 15))
        with self.assertRaisesRegex(ValueError, 'multiple Press Production episodes'):
            save_press_production(
                conn, 7, valid_input(Shift1SetupMinutes='5'), 30)
        self.assertEqual(conn.time_events, {})
        self.assertEqual(conn.rollbacks, 1)

    def test_zero_downtime_submission_preserves_events_on_ambiguous_episodes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=100,
            ProductionDate=conn.production_date, ReleasedAt=None)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=9, CounterQty=50,
            ProductionDate=conn.production_date,
            ReleasedAt=datetime(2026, 9, 26, 15))
        conn.time_events[100] = dict(TimeEventID=100, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=12, SourceType='MANUAL')
        save_press_production(
            conn, 7, valid_input(CounterQty='120', Shift1SetupMinutes='0'), 30)
        self.assertEqual(conn.time_events[100]['DurationMin'], 12)
        self.assertEqual(conn.press_rows[30]['CounterQty'], 120)

    def test_concurrent_same_shift_mould_allocations_serialize(self):
        first = PressProductionConnection()
        second = PressProductionConnection()
        second.production_id = 8
        second.press_code = 'F3'
        for attribute in ('press_rows', 'usage_rows', 'moulds', 'time_events',
                          'logger_events'):
            setattr(second, attribute, getattr(first, attribute))
        barrier = threading.Barrier(2)
        outcomes = []

        def allocate(connection, production_id, press):
            barrier.wait()
            try:
                save_press_production(
                    connection, production_id,
                    valid_input(MachineCode=press))
                outcomes.append('saved')
            except ValueError:
                outcomes.append('conflict')

        threads = [
            threading.Thread(target=allocate, args=(first, 7, 'F2')),
            threading.Thread(target=allocate, args=(second, 8, 'F3')),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(outcomes, ['saved', 'conflict'])
        self.assertEqual(len(first.press_rows), 1)
        lock_sql = [sql for sql, _ in first.sql + second.sql if 'sys.sp_getapplock' in sql]
        self.assertTrue(any("@LockOwner='Transaction'" in sql for sql in lock_sql))

    def test_existing_usage_counter_correction_allowed_after_mould_status_changes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MouldID=4, CounterQty=100)
        conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30, ReconditionNo=1, UsageCycles=100)
        conn.moulds[4]['Status'] = 'RECONDITION'
        save_press_production(conn, 7, valid_input(CounterQty='125'), 30)
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 125)
        self.assertEqual(conn.usage_rows[30]['ReconditionNo'], 1)
        self.assertEqual(conn.usage_rows[30]['MouldID'], 4)

    def test_mould_assignment_can_be_corrected_after_counter_or_usage_exists(self):
        for with_usage in (False, True):
            conn = PressProductionConnection()
            conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
                MachineCode='F2', ShiftMasterID=101, MouldID=4,
                CounterQty=0 if with_usage else 10, ReleasedAt=None)
            if with_usage:
                conn.usage_rows[30] = dict(MouldUsageID=130, MouldID=4, PressProductionID=30, ReconditionNo=2, UsageCycles=0)
            with self.subTest(with_usage=with_usage):
                save_press_production(conn, 7, valid_input(MouldID='9', CounterQty='10', CuringQty='5'), 30)
                self.assertEqual(conn.press_rows[30]['PressProductionID'], 30)
                self.assertEqual(conn.press_rows[30]['MouldID'], 9)
                if with_usage:
                    self.assertEqual(conn.usage_rows[30]['MouldID'], 9)
                    self.assertEqual(conn.press_rows[30]['CounterQty'], 0)
                    self.assertEqual(conn.usage_rows[30]['UsageCycles'], 0)
                    self.assertEqual(conn.usage_rows[30]['MouldUsageID'], 130)
                self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

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
        with self.assertRaisesRegex(ValueError, 'ACTIVE Mould is required'):
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
        conn.press_rows[20] = dict(PressProductionID=20, ProductionID=7, MachineCode='F2',
            ShiftMasterID=101, MouldID=4, CounterQty=0, ReleasedAt=None)
        with self.assertRaisesRegex(ValueError, 'Production Date and Shift'):
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

    def test_single_save_persists_quantities_usage_and_downtime_together(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=70,
            CounterQty=80, CuringQty=75, ProductionDate=conn.production_date,
            ReleasedAt=None)

        save_press_production(conn, 7, valid_input(
            DispatchQty='100', CounterQty='100', CuringQty='95',
            SetupMinutes='20', ChgOverMinutes='5', IdleMinutes='3',
            CleaningMinutes='2', BreakdownMinutes='4', SmdtMinutes='12'), 30)

        self.assertEqual(
            (conn.press_rows[30]['DispatchQty'], conn.press_rows[30]['CounterQty'],
             conn.press_rows[30]['CuringQty']), (100, 100, 95))
        self.assertEqual(conn.usage_rows[30]['UsageCycles'], 100)
        self.assertEqual(
            {event['TimeType']: event['DurationMin'] for event in conn.time_events.values()},
            {'SETUP': Decimal('20'), 'CHANGEOVER': Decimal('5'), 'IDLE': Decimal('3'),
             'CLEAN': Decimal('2'), 'BREAKDOWN': Decimal('4'), 'SMDT': Decimal('12')})
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_single_save_saves_downtime_without_counter_or_mould_usage(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=None,
            CounterQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        data = {'ShiftCode': '1', 'MachineCode': 'F2', 'MouldID': '4',
                'ProductionDate': conn.production_date.isoformat(), 'SetupMinutes': '12.5'}

        save_press_production(conn, 7, data, 30)

        self.assertEqual(conn.press_rows[30]['CounterQty'], None)
        self.assertEqual(conn.press_rows[30]['DispatchQty'], None)
        self.assertEqual(conn.press_rows[30]['CuringQty'], None)
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual(len(conn.time_events), 1)
        self.assertEqual(next(iter(conn.time_events.values()))['DurationMin'], Decimal('12.5'))
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_single_save_downtime_does_not_create_usage_when_counter_is_omitted(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=70,
            CounterQty=80, CuringQty=75, ProductionDate=conn.production_date,
            ReleasedAt=None)
        data = {'ShiftCode': '1', 'MachineCode': 'F2', 'MouldID': '4',
                'ProductionDate': conn.production_date.isoformat(), 'SetupMinutes': '12.5'}

        save_press_production(conn, 7, data, 30)

        self.assertEqual(conn.press_rows[30]['CounterQty'], 80)
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual(len(conn.time_events), 1)

    def test_single_save_downtime_with_zero_counter_does_not_create_usage(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=0,
            CounterQty=0, CuringQty=0, ProductionDate=conn.production_date,
            ReleasedAt=None)
        data = {'ShiftCode': '1', 'MachineCode': 'F2', 'MouldID': '4',
                'ProductionDate': conn.production_date.isoformat(),
                'DispatchQty': '0', 'CounterQty': '0', 'CuringQty': '0',
                'SetupMinutes': '12.5'}

        save_press_production(conn, 7, data, 30)

        self.assertEqual(conn.press_rows[30]['CounterQty'], 0)
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual(len(conn.time_events), 1)

    def test_repeated_single_save_updates_existing_manual_events_without_duplicates(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=None,
            CounterQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        data = {'ShiftCode': '1', 'MachineCode': 'F2', 'MouldID': '4',
                'ProductionDate': conn.production_date.isoformat(), 'SetupMinutes': '12'}

        save_press_production(conn, 7, data, 30)
        event_ids = set(conn.time_events)
        save_press_production(conn, 7, dict(data, SetupMinutes='18'), 30)

        self.assertEqual(set(conn.time_events), event_ids)
        self.assertEqual(len(conn.time_events), 1)
        self.assertEqual(next(iter(conn.time_events.values()))['DurationMin'], Decimal('18'))

    def test_single_save_preserves_omitted_quantities_and_downtime_fields(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=70,
            CounterQty=80, CuringQty=75, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, PressProductionID=30,
            MouldID=4, ReconditionNo=1, UsageCycles=80)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=Decimal('11'), SourceType='MANUAL')
        conn.time_events[51] = dict(TimeEventID=51, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='BREAKDOWN',
            DurationMin=Decimal('22'), SourceType='MANUAL')
        original_usage = dict(conn.usage_rows[30])
        data = {'ShiftCode': '1', 'MachineCode': 'F2', 'MouldID': '4',
                'ProductionDate': conn.production_date.isoformat(), 'SetupMinutes': '15'}

        save_press_production(conn, 7, data, 30)

        self.assertEqual(
            (conn.press_rows[30]['DispatchQty'], conn.press_rows[30]['CounterQty'],
             conn.press_rows[30]['CuringQty']), (70, 80, 75))
        self.assertEqual(conn.usage_rows[30], original_usage)
        self.assertEqual(conn.time_events[50]['DurationMin'], Decimal('15'))
        self.assertEqual(conn.time_events[51]['DurationMin'], Decimal('22'))

    def test_single_save_validation_failure_rolls_back_quantities_usage_and_events(self):
        conn = RollbackAwarePressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=70,
            CounterQty=80, CuringQty=75, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, PressProductionID=30,
            MouldID=4, ReconditionNo=1, UsageCycles=80)
        conn.time_events[50] = dict(TimeEventID=50, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=Decimal('11'), SourceType='MANUAL')
        original_press = deepcopy(conn.press_rows)
        original_usage = deepcopy(conn.usage_rows)
        original_events = deepcopy(conn.time_events)

        with self.assertRaisesRegex(ValueError, 'ChgOver must be a numeric minute value'):
            save_press_production(conn, 7, valid_input(
                DispatchQty='100', CounterQty='100', CuringQty='95',
                SetupMinutes='12', ChgOverMinutes='invalid'), 30)

        self.assertEqual(conn.press_rows, original_press)
        self.assertEqual(conn.usage_rows, original_usage)
        self.assertEqual(conn.time_events, original_events)
        self.assertTrue(any('UPDATE dbo.PressProduction' in sql for sql, _ in conn.sql))
        self.assertTrue(any('UPDATE dbo.MouldUsage' in sql for sql, _ in conn.sql))
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

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
        self.assertEqual(sum(row['SourceType'] == 'MANUAL' for row in conn.time_events.values()), 1)

    def test_independent_downtime_save_allows_null_counter_without_mould_usage(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=None,
            CounterQty=None, CuringQty=None, ProductionStartTime=None,
            ProductionEndTime=None, Remark=None, ProductionDate=conn.production_date,
            ReleasedAt=None)

        save_press_production(conn, 7, valid_input(
            DowntimeOnly=True, DispatchQty='', CounterQty='', CuringQty='',
            SetupMinutes='12.5'), 30)

        self.assertEqual(conn.time_events[100]['TimeType'], 'SETUP')
        self.assertEqual(conn.time_events[100]['DurationMin'], Decimal('12.5'))
        self.assertEqual(conn.time_events[100]['SourceType'], 'MANUAL')
        self.assertEqual(conn.press_rows[30]['CounterQty'], None)
        self.assertEqual(conn.press_rows[30]['DispatchQty'], None)
        self.assertEqual(conn.press_rows[30]['CuringQty'], None)
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_independent_breakdown_and_multiple_categories_allow_null_counter(self):
        for minutes, expected in (
                ({'BreakdownMinutes': '9'}, {'BREAKDOWN'}),
                ({'SetupMinutes': '5', 'BreakdownMinutes': '9',
                  'CleaningMinutes': '2'}, {'SETUP', 'BREAKDOWN', 'CLEAN'})):
            with self.subTest(expected=expected):
                conn = PressProductionConnection()
                conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
                    MachineCode='F2', ShiftMasterID=101, MouldID=4,
                    DispatchQty=None, CounterQty=None, CuringQty=None,
                    ProductionDate=conn.production_date, ReleasedAt=None)
                save_press_production(conn, 7, valid_input(
                    DowntimeOnly=True, DispatchQty='', CounterQty='', CuringQty='',
                    **minutes), 30)
                self.assertEqual(
                    {row['TimeType'] for row in conn.time_events.values()} & expected,
                    expected)
                self.assertEqual(conn.press_rows[30]['CounterQty'], None)
                self.assertEqual(conn.usage_rows, {})

    def test_independent_downtime_save_accepts_zero_counter_and_multiple_categories(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=0,
            CounterQty=0, CuringQty=0, ProductionDate=conn.production_date,
            ReleasedAt=None)

        save_press_production(conn, 7, valid_input(
            DowntimeOnly=True, CounterQty='0', DispatchQty='0', CuringQty='0',
            SetupMinutes='5', ChgOverMinutes='3', IdleMinutes='2',
            CleaningMinutes='1', BreakdownMinutes='4', SmdtMinutes='10'), 30)

        self.assertEqual({row['TimeType'] for row in conn.time_events.values()},
                         {'SETUP', 'CHANGEOVER', 'IDLE', 'CLEAN', 'BREAKDOWN', 'SMDT'})
        self.assertEqual(len(conn.time_events), 6)
        self.assertEqual(conn.usage_rows, {})

    def test_independent_downtime_save_preserves_quantities_and_existing_mould_usage(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=75,
            CounterQty=100, CuringQty=80, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.usage_rows[30] = dict(MouldUsageID=130, PressProductionID=30,
            MouldID=4, ReconditionNo=1, UsageCycles=100)
        original_press = dict(conn.press_rows[30])
        original_usage = dict(conn.usage_rows[30])

        save_press_production(conn, 7, valid_input(
            DowntimeOnly=True, CounterQty='999', DispatchQty='999',
            CuringQty='999', SetupMinutes='15'), 30)

        self.assertEqual(conn.press_rows[30], original_press)
        self.assertEqual(conn.usage_rows[30], original_usage)
        self.assertEqual(len(conn.time_events), 1)

    def test_repeated_independent_downtime_save_updates_manual_summary_rows(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        data = valid_input(DowntimeOnly=True, CounterQty='', SetupMinutes='12')

        save_press_production(conn, 7, data, 30)
        event_ids = set(conn.time_events)
        save_press_production(conn, 7, dict(data, SetupMinutes='18'), 30)

        self.assertEqual(set(conn.time_events), event_ids)
        self.assertEqual(len(conn.time_events), 1)
        setup = next(row for row in conn.time_events.values() if row['TimeType'] == 'SETUP')
        self.assertEqual(setup['DurationMin'], Decimal('18'))

    def test_independent_downtime_save_keeps_shift_rows_isolated(self):
        conn = PressProductionConnection()
        for press_id, shift_id in ((30, 101), (31, 202)):
            conn.press_rows[press_id] = dict(PressProductionID=press_id,
                ProductionID=7, MachineCode='F2', ShiftMasterID=shift_id,
                MouldID=4, CounterQty=None, DispatchQty=None, CuringQty=None,
                ProductionDate=conn.production_date, ReleasedAt=None)

        for press_id, shift_code, minutes in ((30, '1', '11'), (31, '2', '22')):
            save_press_production(conn, 7, valid_input(
                DowntimeOnly=True, ShiftCode=shift_code, CounterQty='',
                SetupMinutes=minutes), press_id)

        self.assertEqual(
            {(row['ShiftID'], row['DurationMin']) for row in conn.time_events.values()
             if row['TimeType'] == 'SETUP'},
            {(1, Decimal('11')), (2, Decimal('22'))})

    def test_independent_downtime_save_leaves_plc_and_system_events_untouched(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.time_events[98] = dict(TimeEventID=98, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='SETUP',
            DurationMin=Decimal('7'), SourceType='PLC')
        conn.time_events[99] = dict(TimeEventID=99, ProductionID=7,
            EquipmentCode='F2', ShiftID=1, TimeType='BREAKDOWN',
            DurationMin=Decimal('8'), SourceType='SYSTEM')
        original = {event_id: dict(event) for event_id, event in conn.time_events.items()}

        save_press_production(conn, 7, valid_input(
            DowntimeOnly=True, CounterQty='', SetupMinutes='12'), 30)

        self.assertEqual({key: conn.time_events[key] for key in original}, original)
        self.assertEqual(sum(row['SourceType'] == 'MANUAL'
                             for row in conn.time_events.values()), 1)

    def test_independent_downtime_save_rejects_ambiguous_episode_without_writes(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.press_rows[31] = dict(PressProductionID=31, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=9, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)

        with self.assertRaisesRegex(ValueError, 'multiple Press Production episodes'):
            save_press_production(conn, 7, valid_input(
                DowntimeOnly=True, CounterQty='', SetupMinutes='12'), 30)

        self.assertEqual(conn.time_events, {})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_independent_downtime_database_failure_rolls_back(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        conn.fail = 'INSERT INTO dbo.EquipmentTimeEvent'

        with self.assertRaisesRegex(RuntimeError, 'simulated SQL error'):
            save_press_production(conn, 7, valid_input(
                DowntimeOnly=True, CounterQty='', SetupMinutes='12'), 30)

        self.assertEqual(conn.time_events, {})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_independent_downtime_save_rejects_empty_submission(self):
        conn = PressProductionConnection()
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, CounterQty=None,
            DispatchQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)

        with self.assertRaisesRegex(ValueError, 'Enter downtime values'):
            save_press_production(conn, 7, valid_input(
                DowntimeOnly=True, CounterQty='', SetupMinutes='',
                ChgOverMinutes='', IdleMinutes='', CleaningMinutes='',
                BreakdownMinutes='', SmdtMinutes=''), 30)

        self.assertEqual(conn.time_events, {})
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

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
        self.assertEqual(insert[7], datetime(2026, 9, 26, 22, 0))
        self.assertEqual(insert[8], datetime(2026, 9, 27, 0, 15))

    def test_clock_resolution_uses_historical_rule_value_not_hardcoded_cutoff(self):
        conn = PressProductionConnection()
        conn.day_start_time = time(6)
        save_press_production(conn, 7, valid_input(ProductionStartTime='05:00', ProductionEndTime='05:30'))
        insert = next(args for sql, args in conn.sql if 'INSERT INTO dbo.PressProduction' in sql)
        self.assertEqual(insert[7], datetime(2026, 9, 27, 5, 0))
        self.assertEqual(insert[8], datetime(2026, 9, 27, 5, 30))

    def test_selected_lot_renders_additional_press_section_without_changing_lot_input(self):
        press_row = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MachineName='Press 2',
            ShiftCode='1', EquipmentTimeIdentityAmbiguous=True,
            DispatchQty=100, CounterQty=120, CuringQty=110, MouldID=4, MouldNo='M000001',
            MouldName='Ridge', ProductionStartTime=None, ProductionEndTime=None, Remark='press note',
            UsageCycles=120, UsageReconditionNo=2)
        second_episode = dict(press_row, PressProductionID=31, MouldID=5,
                              MouldNo='M000002', MouldName='Other Mould',
                              ReleasedAt=datetime(2026, 9, 27, 12, 0),
                              LaterMouldAssignmentPress='F8')
        press_conflict_episode = dict(press_row, PressProductionID=32, MouldID=6,
            MouldNo='M000003', MouldName='Retired Mould',
            ReleasedAt=datetime(2026, 9, 27, 13, 0),
            LaterPressAssignmentMachineCode='F2')
        legacy_shift_episode = dict(press_row, PressProductionID=33, ShiftCode=None,
                                    MouldID=7, MouldNo='M000004', MouldName='Legacy Shift')
        shift_two_episode = dict(press_row, PressProductionID=34, ShiftCode='2',
                                 MouldID=8, MouldNo='M000005', MouldName='Shift Two Mould')
        save_actions_episode = dict(press_row, PressProductionID=35,
                                    EquipmentTimeIdentityAmbiguous=False, ReleasedAt=None,
                                    MouldID=9, MouldNo='M000006', MouldName='Save Actions')
        press_context = dict(press_production=[press_row, second_episode, press_conflict_episode,
                                               legacy_shift_episode, shift_two_episode,
                                               save_actions_episode], eligible_shifts=[
            dict(ShiftCode='1', ShiftName='Shift 1'), dict(ShiftCode='2', ShiftName='Shift 2')],
            eligible_presses=[dict(PressCode='F3', PressName='Press 3', AvailableShiftCodes=['1', '2'])],
            eligible_moulds=[dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  AvailableShiftCodes=['1', '2'])], press_product_error=None)
        with patch('app.main.get_connection', return_value=PressProductionConnection()), \
             patch('app.main.read_lots', return_value=[dict(LOT)]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data', return_value={}), \
             patch('app.main.build_press_production_context', return_value=press_context), \
             patch('app.main.read_production_reject_context', return_value=dict(PRODUCTION_REJECT_CONTEXT)):
            response = production_page(request(), production_id=7, production_date=DAY)
        self.assertEqual(response.status_code, 200)
        page = response.body.decode()
        for item in ('PRESS PRODUCTION', 'F2',
                     'M000001 / Ridge', 'M000002 / Other Mould', 'Counter',
                     '/lots/7/press-production/30', '/lots/7/press-production'):
            self.assertIn(item, page)
        press_row_30 = re.search(
            r'<tr data-guide-url="/lots/7/press-production/30/logger-guide"[^>]*>(.*?)</tr>',
            page, re.DOTALL).group(1)
        legacy_row_33 = re.search(
            r'<tr data-guide-url="/lots/7/press-production/33/logger-guide"[^>]*>(.*?)</tr>',
            page, re.DOTALL).group(1)
        press_row_34 = re.search(
            r'<tr data-guide-url="/lots/7/press-production/34/logger-guide"[^>]*>(.*?)</tr>',
            page, re.DOTALL).group(1)
        save_row_35 = re.search(
            r'<tr data-guide-url="/lots/7/press-production/35/logger-guide"[^>]*>(.*?)</tr>',
            page, re.DOTALL).group(1)
        self.assertIn('<td><span>1</span>', press_row_30)
        self.assertNotIn('<strong>ACTIVE</strong>', press_row_30)
        self.assertIn('class="release-mould-button"', press_row_30)
        self.assertNotIn('SHIFT 1', press_row_30)
        self.assertNotIn('PPID', press_row_30)
        self.assertIn('data-press-production-id="30"', press_row_30)
        self.assertIn('<td><span>-</span>', legacy_row_33)
        self.assertNotIn('SHIFT UNKNOWN', legacy_row_33)
        self.assertIn('<td><span>2</span>', press_row_34)
        self.assertNotIn('SHIFT 2', press_row_34)
        self.assertRegex(save_row_35,
            r'<button form="press-production-35" type="submit"[^>]*>SAVE</button>')
        self.assertNotIn('SAVE DOWNTIME', save_row_35)
        self.assertNotRegex(save_row_35, r'<button form="press-production-35"[^>]*disabled')
        self.assertNotIn('PPID', page)
        self.assertNotIn('F2 / Press 2</option>', page)
        self.assertIn('value="1" selected>Shift 1', page)
        self.assertIn('Downtime attribution is ambiguous. Saved values are retained; downtime editing is disabled.', page)
        self.assertNotIn('name="shift1_setup_minutes"', page)
        self.assertIn('>MOULD</button>', page)
        self.assertNotIn('>RELEASE MOULD</button>', page)
        self.assertIn('<strong>RELEASED</strong>', page)
        self.assertIn('Undo Release before editing this assignment.', page)
        self.assertRegex(page, r'<button form="undo-release-31" type="submit" disabled[^>]*>UNDO RELEASE</button>')
        self.assertRegex(page, r'<button form="undo-release-32" type="submit" disabled[^>]*>UNDO RELEASE</button>')
        self.assertIn('This Mould was later assigned to F8.', page)
        self.assertIn('Press F2 has another active assignment in this Production Date/Shift.', page)
        self.assertIn('class="table-scroll press-production-scroll"', page)
        self.assertIn('min-width:1120px', page)
        self.assertIn('.press-production-table col:nth-child(1){width:6%}', page)
        self.assertIn('.press-production-table col:nth-child(15){width:6%}', page)
        self.assertIn('action="/lots/7/production"', page)
        self.assertIn('name="counter"', page)
        self.assertIn('name="counter_qty"', page)

    def test_edit_form_renders_shift_codes_and_preserves_submitted_values(self):
        press_row = dict(PressProductionID=30, ProductionID=7, MachineCode='F2', MachineName='Press 2',
            ShiftCode='1', ReleasedAt=None, EquipmentTimeIdentityAmbiguous=False,
            DispatchQty=100, CounterQty=120, CuringQty=110, MouldID=4, MouldNo='M000001',
            MouldName='Ridge', UsageCycles=120, UsageReconditionNo=2,
            Shift1SetupMinutes=0, Shift1ChgOverMinutes=0, Shift1IdleMinutes=0,
            Shift1CleaningMinutes=0, Shift1SmdtMinutes=0, Shift1BreakdownMinutes=0,
            Shift2SetupMinutes=0, Shift2ChgOverMinutes=0, Shift2IdleMinutes=0,
            Shift2CleaningMinutes=0, Shift2SmdtMinutes=0, Shift2BreakdownMinutes=0)
        press_context = dict(press_production=[press_row],
            eligible_shifts=[dict(ShiftCode='1', ShiftName='Shift 1'),
                             dict(ShiftCode='2', ShiftName='Shift 2')],
            eligible_presses=[dict(PressCode='F2', PressName='Press 2', AvailableShiftCodes=['1', '2'])],
            eligible_moulds=[dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  AvailableShiftCodes=['1', '2'])], press_product_error=None)
        form_data = dict(PressProductionID=30, ShiftCode='2', MachineCode='F2', MouldID='4')
        with patch('app.main.get_connection', return_value=PressProductionConnection()), \
             patch('app.main.read_lots', return_value=[dict(LOT)]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data', return_value={}), \
             patch('app.main.build_press_production_context', return_value=press_context), \
             patch('app.main.read_production_reject_context', return_value=dict(PRODUCTION_REJECT_CONTEXT)):
            response = production_page(request(), production_id=7, production_date=DAY,
                press_form=form_data, press_message='Mould is already assigned.', press_message_type='error')
        page = response.body.decode()
        self.assertIn('action="/lots/7/press-production/30"', page)
        self.assertIn('value="2" selected>Shift 2', page)
        self.assertIn('value="F2" data-available-shifts="1,2" selected', page)
        self.assertIn('value="4" data-available-shifts="1,2" selected', page)
        self.assertIn('EDIT FITTING', page)
        self.assertIn('CANCEL EDIT', page)
        self.assertIn('Mould is already assigned.', page)


class PressProductionRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_operator_save_persists_logger_guide_values_without_changing_logger(self):
        from app.main import save_press_production_route_action

        payload = {
            'production_date': DAY.isoformat(), 'shift_code': '1',
            'machine_code': 'F2', 'mould_id': '4',
            'dispatch_qty': '', 'counter_qty': '', 'curing_qty': '',
            'setup_minutes': '5', 'chgover_minutes': '0', 'idle_minutes': '7',
            'cleaning_minutes': '0', 'breakdown_minutes': '9', 'smdt_minutes': '11',
        }
        conn = PressProductionConnection()
        conn.production_date = DAY
        conn.press_rows[30] = dict(PressProductionID=30, ProductionID=7,
            MachineCode='F2', ShiftMasterID=101, MouldID=4, DispatchQty=None,
            CounterQty=None, CuringQty=None, ProductionDate=conn.production_date,
            ReleasedAt=None)
        logger_events_before = [dict(event) for event in conn.logger_events]
        req = request()

        async def read_form():
            return payload

        req.form = read_form
        with patch('app.main.get_connection', return_value=conn):
            response = await save_press_production_route_action(req, 7, 30)

        self.assertEqual(response.status_code, 303)
        self.assertIn('Press+Production+saved.', response.headers['location'])
        self.assertEqual(
            {(event['ShiftID'], event['TimeType'], event['DurationMin'],
              event['SourceType']) for event in conn.time_events.values()},
            {
                (1, 'SETUP', Decimal('5'), 'MANUAL'),
                (1, 'CHANGEOVER', Decimal('0'), 'MANUAL'),
                (1, 'IDLE', Decimal('7'), 'MANUAL'),
                (1, 'CLEAN', Decimal('0'), 'MANUAL'),
                (1, 'BREAKDOWN', Decimal('9'), 'MANUAL'),
                (1, 'SMDT', Decimal('11'), 'MANUAL'),
            })
        self.assertEqual(conn.press_rows[30]['CounterQty'], None)
        self.assertEqual(conn.press_rows[30]['DispatchQty'], None)
        self.assertEqual(conn.press_rows[30]['CuringQty'], None)
        self.assertEqual(conn.usage_rows, {})
        self.assertEqual(conn.logger_events, logger_events_before)

    async def test_single_save_route_omits_blank_quantities_and_reports_success(self):
        from app import main

        payload = {'production_date': DAY.isoformat(), 'shift_code': '1',
                   'machine_code': 'F2', 'mould_id': '4', 'dispatch_qty': '',
                   'counter_qty': '', 'curing_qty': '', 'setup_minutes': '12',
                   'chgover_minutes': '3'}
        req = request()
        submitted_data = {}

        async def read_form():
            return payload

        async def dispatch(func, *args, **kwargs):
            submitted_data.update(args[1])
            return press_production_id

        press_production_id = 30
        req.form = read_form
        with patch('app.main.run_in_threadpool', side_effect=dispatch):
            response = await save_press_production_route_action(req, 7, press_production_id)

        self.assertEqual(response.status_code, 303)
        self.assertIn('press_message=Press+Production+saved.', response.headers['location'])
        self.assertNotIn('DowntimeOnly', submitted_data)
        self.assertNotIn('DispatchQty', submitted_data)
        self.assertNotIn('CounterQty', submitted_data)
        self.assertNotIn('CuringQty', submitted_data)
        self.assertEqual(submitted_data['SetupMinutes'], '12')
        self.assertEqual(submitted_data['ChgOverMinutes'], '3')

    async def test_single_save_route_passes_quantities_and_downtime_together(self):
        payload = {'production_date': DAY.isoformat(), 'shift_code': '1',
                   'machine_code': 'F2', 'mould_id': '4', 'dispatch_qty': '100',
                   'counter_qty': '100', 'curing_qty': '95', 'setup_minutes': '12',
                   'breakdown_minutes': '3'}
        req = request()
        submitted_data = {}

        async def read_form():
            return payload

        async def dispatch(func, *args, **kwargs):
            submitted_data.update(args[1])
            return 30

        req.form = read_form
        with patch('app.main.run_in_threadpool', side_effect=dispatch):
            response = await save_press_production_route_action(req, 7, 30)

        self.assertEqual(response.status_code, 303)
        self.assertIn('press_message=Press+Production+saved.', response.headers['location'])
        self.assertEqual(
            (submitted_data['DispatchQty'], submitted_data['CounterQty'],
             submitted_data['CuringQty'], submitted_data['SetupMinutes'],
             submitted_data['BreakdownMinutes']),
            ('100', '100', '95', '12', '3'))
        self.assertNotIn('DowntimeOnly', submitted_data)

    async def test_edit_conflict_renders_error_with_submitted_assignment_values(self):
        from app import main

        payload = {'production_date': DAY.isoformat(), 'shift_code': '2',
                   'machine_code': 'F2', 'mould_id': '4',
                   'dispatch_qty': '', 'counter_qty': '', 'curing_qty': '',
                   'setup_minutes': '0'}
        req = request()
        submitted_data = {}

        async def read_form():
            return payload

        req.form = read_form

        async def dispatch(func, *args, **kwargs):
            if func is main.save_press_production_change:
                submitted_data.update(args[1])
                raise ValueError('Mould is already assigned in Shift 2.')
            return func(*args, **kwargs)

        press_context = dict(press_production=[], day_start_time=None,
            eligible_shifts=[dict(ShiftCode='1', ShiftName='Shift 1'),
                             dict(ShiftCode='2', ShiftName='Shift 2')],
            eligible_presses=[dict(PressCode='F2', PressName='Press 2',
                                   AvailableShiftCodes=['1', '2'])],
            eligible_moulds=[dict(MouldID=4, MouldNo='M000001', MouldName='Ridge',
                                  AvailableShiftCodes=['1', '2'])],
            press_product_error=None)
        with patch('app.main.run_in_threadpool', side_effect=dispatch), \
             patch('app.main.get_connection', return_value=PressProductionConnection()), \
             patch('app.main.read_lots', return_value=[dict(LOT)]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data', return_value={}), \
             patch('app.main.build_press_production_context', return_value=press_context), \
             patch('app.main.read_production_reject_context',
                   return_value=dict(PRODUCTION_REJECT_CONTEXT)):
            response = await save_press_production_route_action(req, 7, 30)

        page = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('Mould is already assigned in Shift 2.', page)
        self.assertIn('action="/lots/7/press-production/30"', page)
        self.assertIn('value="2" selected>Shift 2', page)
        self.assertIn('value="F2" data-available-shifts="1,2" selected', page)
        self.assertIn('value="4" data-available-shifts="1,2" selected', page)
        self.assertNotIn('CounterQty', submitted_data)
        self.assertNotIn('DispatchQty', submitted_data)
        self.assertNotIn('CuringQty', submitted_data)
        self.assertNotIn('DowntimeOnly', submitted_data)


if __name__ == '__main__':
    unittest.main()