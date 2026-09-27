import unittest
from datetime import datetime
from unittest.mock import patch

from app.press_production import (read_eligible_moulds, read_eligible_presses,
                                  save_press_production)
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
        elif 'FROM dbo.MouldUsage WITH' in sql:
            row = self.conn.usage_rows.get(args[0])
            self.result = [(row['ReconditionNo'],)] if row and 'SELECT ReconditionNo' in sql else ([(row['MouldUsageID'],)] if row else [])
        elif 'INSERT INTO dbo.PressProduction' in sql:
            pp_id = self.conn.next_pp_id
            self.conn.next_pp_id += 1
            row = dict(PressProductionID=pp_id, ProductionID=args[0], MachineCode=args[1],
                       DispatchQty=args[2], CounterQty=args[3], CuringQty=args[4], MouldID=args[5])
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
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result


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
        self.next_pp_id = 30
        self.commits = 0
        self.rollbacks = 0
        self.sql = []
        self.fail = None
        self.cur = PressProductionCursor(self)

    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


def valid_input(**overrides):
    data = dict(MachineCode='F2', MouldID='4', DispatchQty='100', CounterQty='100',
                CuringQty='95', ProductionStartTime='2026-09-27T08:00:00',
                ProductionEndTime='2026-09-27T10:00:00', Remark='press note')
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
        self.assertEqual(cursor.args, ('Special Ridge', '02'))
        self.assertEqual(read_eligible_moulds(cursor, None, '02'), [])

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
            with self.assertRaises(ValueError): save_press_production(PressProductionConnection(), 7, data)

    def test_sql_failure_rolls_back_press_row_and_usage_transaction(self):
        conn = PressProductionConnection()
        conn.fail = 'INSERT INTO dbo.MouldUsage'
        with self.assertRaisesRegex(RuntimeError, 'simulated SQL error'):
            save_press_production(conn, 7, valid_input())
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_datetime_input_is_parsed_as_local_naive_value(self):
        conn = PressProductionConnection()
        save_press_production(conn, 7, valid_input())
        insert = next(args for sql, args in conn.sql if 'INSERT INTO dbo.PressProduction' in sql)
        self.assertEqual(insert[6], datetime(2026, 9, 27, 8, 0))

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
        for item in ('PRESS PRODUCTION', 'F2 / Press 2', 'M000001 / Ridge', 'Counter',
                     '/lots/7/press-production/30', '/lots/7/press-production'):
            self.assertIn(item, page)
        self.assertIn('action="/lots/7/production"', page)
        self.assertIn('name="counter"', page)
        self.assertIn('name="counter_qty"', page)


if __name__ == '__main__':
    unittest.main()