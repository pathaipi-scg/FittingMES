import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.wet_reject import (read_active_reasons, build_wet_reject_context, split_into_groups,
                            validate_wet_reject_input, save_wet_reject, save_wet_reject_batch)
from app.main import production_page
from test_production import DAY, LOT, PLAN, request


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

    def fetchall(self):
        return [tuple(row.values()) for row in self.result]


class ReadContextTests(unittest.TestCase):
    def test_active_reasons_query_filters_and_orders(self):
        cursor = ReadCursor([dict(ReasonCode='R01', ReasonNameTH='Crack', SortOrder=1)])
        result = read_active_reasons(cursor)
        self.assertEqual(result[0]['ReasonCode'], 'R01')
        self.assertIn('WetRejectReasonMaster', cursor.sql)
        self.assertIn('IsActive=1', cursor.sql)
        self.assertIn('ORDER BY SortOrder', cursor.sql)

    def test_context_aggregates_lot_qty_and_daily_qty_per_reason(self):
        cursor = MagicMock()

        def execute(sql, *args):
            cursor.description = []
            if 'wr.WetRejectID' in sql:
                cursor.description = [(k,) for k in ('WetRejectID', 'ProductionID', 'ReasonCode', 'ReasonNameTH',
                                                      'Qty', 'RejectDateTime', 'Remark', 'CreatedAt', 'UpdatedAt')]
                cursor.fetchall.return_value = [
                    (1, 7, 'R01', 'Crack', 2, datetime(2026, 9, 28, 8, 15), None, None, None),
                    (2, 7, 'R01', 'Crack', 3, datetime(2026, 9, 28, 11, 40), None, None, None),
                ]
            elif 'WetRejectReasonMaster' in sql:
                cursor.description = [(k,) for k in ('ReasonCode', 'ReasonNameTH', 'SortOrder')]
                cursor.fetchall.return_value = [('R01', 'Crack', 1), ('R02', 'Short Shot', 2)]
            elif 'FROM dbo.ProductionData' in sql:
                cursor.description = [('CounterQty',), ('CuringQty',)]
                cursor.fetchone.return_value = (10, 5)
            else:
                cursor.description = [('ReasonCode',), ('Qty',)]
                cursor.fetchall.return_value = [('R01', 9)]
            return cursor

        cursor.execute.side_effect = execute
        context = build_wet_reject_context(cursor, 7, '2026-09-28')
        summary = {row['ReasonCode']: row for row in context['wet_reject_summary']}
        self.assertEqual(summary['R01']['Qty'], 5)
        self.assertEqual(summary['R01']['QtyPerDay'], 9)
        self.assertEqual(summary['R02']['Qty'], 0)
        self.assertEqual(context['wet_reject_total'], 5)
        self.assertEqual(len(context['wet_reject_events']), 2)
        # Reason groups mirror the reasons/summary lists 1:1 for the 3-group layout.
        self.assertEqual(len(context['wet_reject_reason_groups']), 3)
        self.assertEqual(sum(len(g) for g in context['wet_reject_reason_groups']), 3)
        self.assertEqual(len(context['wet_reject_summary_groups']), 3)
        self.assertEqual(sum(len(g) for g in context['wet_reject_summary_groups']), 3)


class GroupSplitTests(unittest.TestCase):
    def test_distributes_items_into_three_near_equal_ordered_groups(self):
        for total in (0, 1, 2, 3, 4, 6, 7, 19, 20, 21, 22, 25):
            with self.subTest(total=total):
                items = list(range(total))
                groups = split_into_groups(items)
                self.assertEqual(len(groups), 3)
                sizes = [len(g) for g in groups]
                self.assertEqual(sum(sizes), total)
                self.assertLessEqual(max(sizes) - min(sizes), 1)
                # Order is preserved so Code/Reason columns stay predictable.
                self.assertEqual([x for g in groups for x in g], items)

    def test_nineteen_active_reasons_split_seven_six_six(self):
        sizes = [len(g) for g in split_into_groups(list(range(19)))]
        self.assertEqual(sizes, [7, 6, 6])


class ValidateInputTests(unittest.TestCase):
    def test_requires_reason_and_qty_but_not_client_datetime(self):
        with self.assertRaisesRegex(ValueError, 'Reason'):
            validate_wet_reject_input(dict(Qty='2', RejectDateTime='2026-09-28T08:15:00'))
        with self.assertRaisesRegex(ValueError, 'Qty'):
            validate_wet_reject_input(dict(ReasonCode='R01', Qty='0', RejectDateTime='2026-09-28T08:15:00'))
        result = validate_wet_reject_input(dict(ReasonCode='R01', Qty='2'))
        self.assertEqual(result, dict(ReasonCode='R01', Qty=2, Remark=None))

    def test_valid_input_ignores_client_datetime_and_keeps_remark(self):
        result = validate_wet_reject_input(dict(ReasonCode='R01', Qty='5',
            RejectDateTime='2026-09-28T08:15:00', Remark='note'))
        self.assertEqual(result, dict(ReasonCode='R01', Qty=5, Remark='note'))


class WetRejectCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = []
        self.result = []

    def execute(self, sql, *args):
        self.conn.sql.append((sql, args))
        if 'FROM dbo.ProductionLot WITH' in sql:
            self.result = [(self.conn.production_id,)] if args[0] == self.conn.production_id and self.conn.lot_active else []
        elif 'FROM dbo.WetRejectReasonMaster WITH' in sql:
            self.result = [(args[0],)] if args[0] == self.conn.active_reason else []
        elif 'INSERT INTO dbo.WetReject' in sql:
            new_id = self.conn.next_id
            self.conn.next_id += 1
            self.conn.rows[new_id] = dict(WetRejectID=new_id, ProductionID=args[0], ReasonCode=args[1],
                                          Qty=args[2], RejectDateTime=datetime.now(), Remark=args[3])
            self.result = [(new_id,)]
        elif 'SELECT WetRejectID FROM dbo.WetReject' in sql:
            row = self.conn.rows.get(args[0])
            self.result = [(row['WetRejectID'],)] if row and row['ProductionID'] == args[1] else []
        elif 'UPDATE dbo.WetReject' in sql:
            row = self.conn.rows[args[-2]]
            row.update(ReasonCode=args[0], Qty=args[1], Remark=args[2])
            self.result = []
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def nextset(self):
        return True


class WetRejectConnection:
    def __init__(self):
        self.production_id = 7
        self.lot_active = True
        self.active_reason = 'R01'
        self.rows = {}
        self.next_id = 1
        self.last_id = None
        self.commits = 0
        self.rollbacks = 0
        self.sql = []
        self.cur = WetRejectCursor(self)

    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class SaveWetRejectTests(unittest.TestCase):
    def valid_input(self, **overrides):
        data = dict(ReasonCode='R01', Qty='2', RejectDateTime='2026-09-28T08:15:00', Remark='')
        data.update(overrides)
        return data

    def test_insert_creates_new_row_and_commits(self):
        conn = WetRejectConnection()
        wet_reject_id = save_wet_reject(conn, 7, self.valid_input())
        self.assertEqual(wet_reject_id, 1)
        self.assertEqual(conn.rows[1]['Qty'], 2)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_multiple_events_same_reason_are_kept_as_separate_rows(self):
        conn = WetRejectConnection()
        first = save_wet_reject(conn, 7, self.valid_input(Qty='2', RejectDateTime='2026-09-28T08:15:00'))
        second = save_wet_reject(conn, 7, self.valid_input(Qty='3', RejectDateTime='2026-09-28T11:40:00'))
        self.assertNotEqual(first, second)
        self.assertEqual(len(conn.rows), 2)
        self.assertEqual(sum(row['Qty'] for row in conn.rows.values()), 5)

    def test_update_preserves_id_and_uses_sysdatetime_for_updatedat(self):
        conn = WetRejectConnection()
        conn.rows[1] = dict(WetRejectID=1, ProductionID=7, ReasonCode='R01', Qty=2,
                            RejectDateTime=None, Remark=None)
        result = save_wet_reject(conn, 7, self.valid_input(Qty='9', Remark='corrected'), wet_reject_id=1)
        self.assertEqual(result, 1)
        self.assertEqual(conn.rows[1]['Qty'], 9)
        self.assertEqual(conn.rows[1]['Remark'], 'corrected')
        update_sql = next(sql for sql, _ in conn.sql if 'UPDATE dbo.WetReject' in sql)
        self.assertIn('UpdatedAt=SYSDATETIME()', update_sql)
        # The application must never write WetRejectHistory directly; the SQL trigger owns it.
        self.assertFalse(any('WetRejectHistory' in sql for sql, _ in conn.sql))
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_rejects_inactive_lot(self):
        conn = WetRejectConnection()
        conn.lot_active = False
        with self.assertRaisesRegex(ValueError, 'no longer active'):
            save_wet_reject(conn, 7, self.valid_input())
        self.assertEqual(conn.rollbacks, 1)

    def test_rejects_inactive_or_unknown_reason(self):
        conn = WetRejectConnection()
        with self.assertRaisesRegex(ValueError, 'active Wet Reject Reason'):
            save_wet_reject(conn, 7, self.valid_input(ReasonCode='R99'))
        self.assertEqual(conn.rollbacks, 1)

    def test_update_of_missing_row_is_rejected(self):
        conn = WetRejectConnection()
        with self.assertRaisesRegex(ValueError, 'not found'):
            save_wet_reject(conn, 7, self.valid_input(), wet_reject_id=99)
        self.assertEqual(conn.rollbacks, 1)


class WetRejectBatchCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def execute(self, sql, *args):
        self.conn.sql.append((sql, args))
        self.description = []
        if 'FROM dbo.ProductionLot WITH' in sql:
            self.result = [(self.conn.production_id,)] if args[0] == self.conn.production_id and self.conn.lot_active else []
        elif 'FROM dbo.WetRejectReasonMaster WITH' in sql:
            self.result = [(code,) for code in self.conn.active_codes]
        elif 'FROM dbo.ProductionData' in sql:
            self.result = [(10, 5)]
        elif 'SELECT WetRejectID,ReasonCode FROM dbo.WetReject' in sql:
            self.description = [('WetRejectID',), ('ReasonCode',)]
            self.result = [(row['WetRejectID'], row['ReasonCode']) for row in self.conn.rows.values()]
        elif 'UPDATE dbo.WetReject' in sql:
            wet_reject_id = args[-2] if 'Qty=?' in sql else args[-2]
            if 'Qty=?' in sql:
                qty = args[0]
                row = self.conn.rows.get(wet_reject_id)
                if row:
                    row['Qty'] = qty
            self.result = []
        elif 'DELETE FROM dbo.WetReject' in sql:
            self.conn.rows.clear()
            self.result = []
        elif 'INSERT INTO dbo.WetReject' in sql:
            new_id = self.conn.next_id
            self.conn.next_id += 1
            self.conn.rows[new_id] = dict(WetRejectID=new_id, ProductionID=args[0], ReasonCode=args[1],
                                          Qty=args[2], RejectDateTime=datetime.now(), Remark=args[3])
            self.result = [(new_id,)]
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchone(self):
        return self.result.pop(0) if self.result else None

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def nextset(self):
        return True


class WetRejectBatchConnection:
    def __init__(self):
        self.production_id = 7
        self.lot_active = True
        self.active_codes = {'R01', 'R02', 'R03'}
        self.rows = {}
        self.next_id = 1
        self.last_id = None
        self.commits = 0
        self.rollbacks = 0
        self.sql = []
        self.cur = WetRejectBatchCursor(self)

    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class SaveWetRejectBatchTests(unittest.TestCase):
    def valid_input(self, **overrides):
        data = dict(Remark='batch note',
                    Quantities={'R01': '2', 'R02': '0', 'R03': ''})
        data.update(overrides)
        return data

    def test_creates_one_row_per_nonzero_entered_qty_only(self):
        conn = WetRejectBatchConnection()
        ids = save_wet_reject_batch(conn, 7, self.valid_input())
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(conn.rows), 2)
        rows_by_code = {row['ReasonCode']: row for row in conn.rows.values()}
        self.assertEqual(rows_by_code['R01']['Qty'], 2)
        self.assertEqual(rows_by_code['R99']['Qty'], 3)
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))

    def test_batch_replaces_existing_lot_rows_without_duplicates(self):
        conn = WetRejectBatchConnection()
        conn.rows[7] = dict(WetRejectID=7, ProductionID=7, ReasonCode='R01', Qty=9, RejectDateTime=datetime(2026, 9, 27, 8), Remark=None)
        ids = save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2', 'R02': '3'}))
        self.assertEqual(len(conn.rows), 2)
        self.assertEqual(sorted(row['Qty'] for row in conn.rows.values()), [2, 3])
        self.assertEqual(len(ids), 2)

    def test_shares_one_rejectdatetime_and_remark_across_rows(self):
        conn = WetRejectBatchConnection()
        ids = save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2', 'R02': '3'}))
        self.assertEqual(len(ids), 2)
        for row in conn.rows.values():
            self.assertIsInstance(row['RejectDateTime'], datetime)
            self.assertEqual(row['Remark'], 'batch note')
        self.assertEqual(sorted(row['Qty'] for row in conn.rows.values()), [2, 3])

    def test_blank_and_zero_qty_do_not_create_rows(self):
        conn = WetRejectBatchConnection()
        with self.assertRaisesRegex(ValueError, 'at least one'):
            save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '0', 'R02': ''}))
        self.assertEqual(conn.rows, {})
        self.assertEqual(conn.commits, 0)

    def test_ignores_derived_r99_input(self):
        conn = WetRejectBatchConnection()
        ids = save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R99': '5', 'R01': '1'}))
        self.assertEqual(len(ids), 2)
        self.assertEqual({row['ReasonCode'] for row in conn.rows.values()}, {'R01', 'R99'})

    def test_rejects_inactive_lot(self):
        conn = WetRejectBatchConnection()
        conn.lot_active = False
        with self.assertRaisesRegex(ValueError, 'no longer active'):
            save_wet_reject_batch(conn, 7, self.valid_input())
        self.assertEqual(conn.rollbacks, 1)

    def test_invalid_qty_format_is_rejected(self):
        conn = WetRejectBatchConnection()
        with self.assertRaisesRegex(ValueError, 'whole number'):
            save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '-1'}))

    def test_reconciliation_preserves_rows_timestamps_and_total_is_idempotent(self):
        conn = WetRejectBatchConnection()
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2'}))
        original = {code: (row['WetRejectID'], row['RejectDateTime'])
                    for code, row in ((row['ReasonCode'], row) for row in conn.rows.values())}
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2'}))
        self.assertEqual(len(conn.rows), 2)
        self.assertEqual(sum(row['Qty'] for row in conn.rows.values()), 5)
        for code, (wet_reject_id, timestamp) in original.items():
            self.assertEqual(conn.rows[wet_reject_id]['RejectDateTime'], timestamp)
        self.assertNotIn('DELETE FROM dbo.WetReject', '\n'.join(sql for sql, _ in conn.sql))

    def test_increasing_and_decreasing_reason_reconciles_r99(self):
        conn = WetRejectBatchConnection()
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '1'}))
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '4'}))
        quantities = {row['ReasonCode']: row['Qty'] for row in conn.rows.values()}
        self.assertEqual(quantities, {'R01': 4, 'R99': 1})
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2'}))
        quantities = {row['ReasonCode']: row['Qty'] for row in conn.rows.values()}
        self.assertEqual(quantities, {'R01': 2, 'R99': 3})

    def test_total_wet_reject_source_drives_r99(self):
        conn = WetRejectBatchConnection()
        save_wet_reject_batch(conn, 7, self.valid_input(Quantities={'R01': '2'}))
        self.assertEqual(conn.rows[next(row_id for row_id, row in conn.rows.items()
                                        if row['ReasonCode'] == 'R99')]['Qty'], 3)
        self.assertEqual(conn.commits, 1)


class WetRejectPageTests(unittest.TestCase):
    def render(self, wet_context):
        with patch('app.main.get_connection', return_value=MagicMock()), \
             patch('app.main.read_lots', return_value=[dict(LOT)]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]), \
             patch('app.main.read_production_data', return_value={}), \
             patch('app.main.build_press_production_context', return_value=dict(
                 press_production=[], eligible_presses=[], eligible_moulds=[], press_product_error=None)), \
             patch('app.main.build_wet_reject_context', return_value=wet_context):
            return production_page(request(), production_id=7, production_date=DAY)

    def test_selected_lot_renders_summary_without_events_or_datetime_editor(self):
        reasons = [dict(ReasonCode='R01', ReasonNameTH='Crack', SortOrder=1)]
        wet_context = dict(
            wet_reject_reasons=reasons,
            wet_reject_reason_groups=[reasons, [], []],
            wet_reject_events=[dict(WetRejectID=5, ProductionID=7, ReasonCode='R01', ReasonNameTH='Crack',
                Qty=5, RejectDateTime=datetime(2026, 9, 28, 8, 15), Remark='note',
                CreatedAt=None, UpdatedAt=datetime(2026, 9, 28, 9, 0))],
            wet_reject_summary=[dict(ReasonCode='R01', ReasonNameTH='Crack', Qty=5, QtyPerDay=5)],
            wet_reject_summary_groups=[[dict(ReasonCode='R01', ReasonNameTH='Crack', Qty=5, QtyPerDay=5)], [], []],
            wet_reject_total=5)
        response = self.render(wet_context)
        self.assertEqual(response.status_code, 200)
        page = response.body.decode()
        for item in ('WET REJECT', 'R01', 'Crack', 'Total Wet Reject', 'name="qty_R01"',
                 '/lots/7/wet-reject/batch', 'SAVE WET REJECT'):
            self.assertIn(item, page)
        self.assertNotIn('Individual Wet Reject events', page)
        self.assertNotIn('name="reject_datetime"', page)
        self.assertNotIn('/lots/7/wet-reject/5', page)
        # Reason selection is no longer a single dropdown; Qty is entered per reason.
        self.assertNotIn('name="reason_code" required><option value="">Select Reason', page)
        # Only ONE Wet Reject grid: the editable Qty cell and the Qty/Day cell
        # live in the same row, not in two separate tables (entry + summary).
        self.assertEqual(page.count('name="qty_R01"'), 1)
        self.assertEqual(page.count('class="wet-reject-groups"'), 1)

    def test_no_active_reasons_reports_missing_master_data(self):
        wet_context = dict(wet_reject_reasons=[], wet_reject_reason_groups=[[], [], []],
                           wet_reject_events=[], wet_reject_summary=[],
                           wet_reject_summary_groups=[[], [], []], wet_reject_total=0)
        response = self.render(wet_context)
        page = response.body.decode()
        self.assertIn('No active Wet Reject Reasons are configured', page)
        self.assertIn('disabled', page)

    def test_dynamic_reason_codes_render_without_any_hardcoded_list(self):
        # Arbitrary, non-standard codes prove the grid is driven purely by
        # WetRejectReasonMaster rows, not a hardcoded R01-R99 list in the template.
        reasons = [dict(ReasonCode='ZZ1', ReasonNameTH='Custom reason one', SortOrder=1),
                   dict(ReasonCode='ZZ2', ReasonNameTH='Custom reason two', SortOrder=2)]
        wet_context = dict(
            wet_reject_reasons=reasons, wet_reject_reason_groups=[reasons, [], []],
            wet_reject_events=[], wet_reject_summary=[
                dict(ReasonCode='ZZ1', ReasonNameTH='Custom reason one', Qty=0, QtyPerDay=0),
                dict(ReasonCode='ZZ2', ReasonNameTH='Custom reason two', Qty=0, QtyPerDay=0)],
            wet_reject_summary_groups=[[
                dict(ReasonCode='ZZ1', ReasonNameTH='Custom reason one', Qty=0, QtyPerDay=0),
                dict(ReasonCode='ZZ2', ReasonNameTH='Custom reason two', Qty=0, QtyPerDay=0)], [], []],
            wet_reject_total=0)
        page = self.render(wet_context).body.decode()
        for item in ('name="qty_ZZ1"', 'name="qty_ZZ2"', 'Custom reason one', 'Custom reason two', 'ZZ1', 'ZZ2'):
            self.assertIn(item, page)

    def test_inactive_reason_excluded_from_context_does_not_render(self):
        # An inactive master row (e.g. R16) is simply absent from the context
        # produced by build_wet_reject_context's IsActive=1 filter.
        reasons = [dict(ReasonCode='R01', ReasonNameTH='Crack', SortOrder=1)]
        wet_context = dict(wet_reject_reasons=reasons, wet_reject_reason_groups=[reasons, [], []],
                           wet_reject_events=[], wet_reject_summary=[], wet_reject_summary_groups=[[], [], []],
                           wet_reject_total=0)
        page = self.render(wet_context).body.decode()
        self.assertNotIn('name="qty_R16"', page)

    def test_lots_for_date_filters_by_selected_production_date(self):
        other_day_lot = dict(LOT, ProductionID=8, ProdDate=date(2026, 9, 22), LotNo='B006690902')
        with patch('app.main.get_connection', return_value=MagicMock()), \
             patch('app.main.read_lots', return_value=[dict(LOT), other_day_lot]), \
             patch('app.main.read_plans', return_value=[dict(PLAN)]):
            response = production_page(request(), production_date=DAY)
        self.assertEqual([lot['ProductionID'] for lot in response.context['lots_for_date']], [7])


if __name__ == '__main__':
    unittest.main()
