import unittest
from datetime import date
from unittest.mock import patch

from test_production import request
from app.main import mould_page
from app.mould import (page_context, read_mould_detail, read_mould_list, read_products,
                       register_mould, return_from_recondition, send_to_recondition,
                       set_mould_status, update_mould_info)


PRODUCTS = [
    dict(ProductFamily='Family A', ProductCode='01', ProductName='Product One'),
    dict(ProductFamily='Family B', ProductCode='02', ProductName='Product Two'),
]
MOULD = dict(MouldID=4, MouldNo='M000001', MouldName='Mould One', ProductFamily='Family A',
             ProductCode='01', ProductName='Product One', Status='ACTIVE', CurrentReconditionNo=2,
             CurrentAge=70, LifetimeAge=220, UsageRecordCount=4,
             LastUsageDateTime='2026-09-27 10:00:00', Remark='Checked',
             CreatedAt='2026-01-01', UpdatedAt='2026-09-27')
STATUS_HISTORY = [dict(FromStatus='RECONDITION', ToStatus='ACTIVE', ChangeType='RETURN_RECONDITION',
                       Remark='Returned', ChangedBy='FittingMES', ChangedAt='2026-09-27')]
RECONDITION_HISTORY = [dict(ReconditionNo=2, ReconditionDate=date(2026, 9, 1), ReturnDate=date(2026, 9, 2),
                            CycleCountBefore=75, LifetimeCountAtRecondition=150, Remark='RC2')]
USAGE_HISTORY = [dict(LotNo='I0260901', ProductionID=19, ProdDate=date(2026, 9, 27), MachineCode='F1',
                      ReconditionNo=2, UsageCycles=70, UsageDateTime='2026-09-27 10:00:00',
                      ProductionStartTime='2026-09-27 08:00:00', ProductionEndTime='2026-09-27 10:00:00')]


class FakeCursor:
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
            raise RuntimeError('simulated SQL failure')
        if 'ProductCodeMaster' in sql:
            self._set(self.conn.products)
        elif 'vw_MouldList' in sql:
            if 'WHERE MouldID=?' in sql:
                self._set([self.conn.mould] if args[0] == self.conn.mould['MouldID'] else [])
            else:
                rows = [self.conn.mould]
                search, _, _, family, _, code, status, _ = args
                if search and search.casefold() not in (self.conn.mould['MouldNo'] + self.conn.mould['MouldName']).casefold():
                    rows = []
                if family and (self.conn.mould['ProductFamily'] != family or self.conn.mould['ProductCode'] != code):
                    rows = []
                if status and self.conn.mould['Status'] != status:
                    rows = []
                self._set(rows)
        elif 'MouldStatusHistory' in sql:
            self._set(self.conn.status_history)
        elif 'vw_MouldReconditionHistory' in sql:
            self._set(self.conn.recondition_history)
        elif 'FROM dbo.MouldUsage' in sql:
            self._set(self.conn.usage_history)
        elif sql.lstrip().startswith('EXEC dbo.sp_Mould_'):
            self.conn.procedures.append((sql, args))
            changed = dict(self.conn.mould)
            if 'sp_Mould_Register' in sql:
                changed.update(MouldID=5, MouldNo='M000002', MouldName=args[0],
                               ProductFamily=args[1], ProductCode=args[2], Status='ACTIVE')
            elif 'sp_Mould_UpdateInfo' in sql:
                changed.update(MouldName=args[1], Remark=args[2])
            elif 'sp_Mould_SendToRecondition' in sql:
                changed['Status'] = 'RECONDITION'
            elif 'sp_Mould_ReturnFromRecondition' in sql:
                changed.update(Status='ACTIVE', CurrentReconditionNo=3, CurrentAge=0)
            elif 'sp_Mould_SetStatus' in sql:
                changed['Status'] = args[1]
            self.conn.mould = changed
            self._set([changed])
        else:
            raise AssertionError('Unexpected SQL: ' + sql)
        return self

    def fetchall(self):
        result, self.result = self.result, []
        return result

    def fetchone(self):
        return self.result.pop(0) if self.result else None


class FakeConnection:
    def __init__(self):
        self.products = [dict(row) for row in PRODUCTS]
        self.mould = dict(MOULD)
        self.status_history = [dict(row) for row in STATUS_HISTORY]
        self.recondition_history = [dict(row) for row in RECONDITION_HISTORY]
        self.usage_history = [dict(row) for row in USAGE_HISTORY]
        self.sql = []
        self.procedures = []
        self.commits = 0
        self.rollbacks = 0
        self.fail = None
        self.cursor_instance = FakeCursor(self)

    def cursor(self): return self.cursor_instance
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class MouldTests(unittest.TestCase):
    def test_product_choices_come_from_active_product_master(self):
        conn = FakeConnection()
        products = read_products(conn.cursor())
        self.assertEqual(products, PRODUCTS)
        self.assertIn('FROM dbo.ProductCodeMaster', conn.sql[0][0])
        self.assertIn('IsActive=1', conn.sql[0][0])

    def test_list_reads_authoritative_view_and_applies_search_product_status_filters(self):
        conn = FakeConnection()
        rows = read_mould_list(conn.cursor(), 'M000001', 'Family A|01', 'ACTIVE')
        self.assertEqual(rows[0]['CurrentAge'], 70)
        sql, args = conn.sql[-1]
        self.assertIn('FROM dbo.vw_MouldList', sql)
        self.assertEqual(args, ('M000001', '%M000001%', '%M000001%', 'Family A', 'Family A', '01', 'ACTIVE', 'ACTIVE'))
        self.assertEqual(read_mould_list(conn.cursor(), 'absent'), [])
        with self.assertRaisesRegex(ValueError, 'valid Mould status'):
            read_mould_list(conn.cursor(), status='UNKNOWN')
        with self.assertRaisesRegex(ValueError, 'valid Product'):
            read_mould_list(conn.cursor(), product='bad')

    def test_detail_loads_three_histories_with_read_only_join(self):
        conn = FakeConnection()
        detail = read_mould_detail(conn.cursor(), 4)
        self.assertEqual(detail['mould']['LifetimeAge'], 220)
        self.assertEqual(detail['status_history'][0]['ChangeType'], 'RETURN_RECONDITION')
        self.assertEqual(detail['recondition_history'][0]['CycleCountBefore'], 75)
        self.assertEqual(detail['usage_history'][0]['LotNo'], 'I0260901')
        usage_sql = next(sql for sql, _ in conn.sql if 'FROM dbo.MouldUsage' in sql)
        self.assertIn('JOIN dbo.PressProduction', usage_sql)
        self.assertIn('JOIN dbo.ProductionLot', usage_sql)
        self.assertIn('usage.UsageCycles', usage_sql)
        self.assertFalse(any(not sql.lstrip().startswith('SELECT') for sql, _ in conn.sql))

    def test_invalid_mould_id_and_missing_detail_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Invalid MouldID'):
            read_mould_detail(FakeConnection().cursor(), 0)
        conn = FakeConnection()
        with self.assertRaisesRegex(ValueError, 'Mould not found'):
            read_mould_detail(conn.cursor(), 99)

    def test_page_context_combines_products_filtered_list_and_detail(self):
        context = page_context(FakeConnection().cursor(), mould_id=4)
        self.assertEqual(len(context['products']), 2)
        self.assertEqual(context['selected']['MouldNo'], 'M000001')
        self.assertEqual(len(context['usage_history']), 1)

    def test_register_calls_database_numbering_procedure_and_reloads_view(self):
        conn = FakeConnection()
        mould = register_mould(conn, 'New Mould', 'Family B', '02', 'Intake')
        sql, args = conn.procedures[0]
        self.assertIn('EXEC dbo.sp_Mould_Register', sql)
        self.assertEqual(args, ('New Mould', 'Family B', '02', 'Intake', 'FittingMES'))
        self.assertEqual(mould['MouldNo'], 'M000002')
        self.assertTrue(any('FROM dbo.vw_MouldList WHERE MouldID=?' in query for query, _ in conn.sql))
        self.assertEqual((conn.commits, conn.rollbacks), (1, 0))
        self.assertFalse(any('BEGIN TRANSACTION' in query for query, _ in conn.sql))

    def test_update_info_only_sends_name_remark_not_product_or_number(self):
        conn = FakeConnection()
        update_mould_info(conn, 4, 'Renamed', 'New note')
        sql, args = conn.procedures[0]
        self.assertIn('EXEC dbo.sp_Mould_UpdateInfo', sql)
        self.assertEqual(args, (4, 'Renamed', 'New note'))
        self.assertNotIn('MouldNo', sql)
        self.assertNotIn('ProductFamily', sql)
        self.assertEqual(conn.commits, 1)

    def test_send_and_return_use_dedicated_procedures_without_nested_transaction(self):
        for operation, expected, resulting_status in (
            (send_to_recondition, 'sp_Mould_SendToRecondition', 'RECONDITION'),
            (return_from_recondition, 'sp_Mould_ReturnFromRecondition', 'ACTIVE'),
        ):
            with self.subTest(procedure=expected):
                conn = FakeConnection()
                result = operation(conn, 4, 'service note')
                sql, args = conn.procedures[0]
                self.assertIn(expected, sql)
                self.assertEqual(args, (4, 'service note', 'FittingMES'))
                self.assertEqual(result['Status'], resulting_status)
                self.assertFalse(any('BEGIN TRANSACTION' in query for query, _ in conn.sql))
                self.assertEqual((conn.commits, conn.rollbacks), (1, 0))
        returned = FakeConnection()
        result = return_from_recondition(returned, 4)
        self.assertEqual((result['CurrentReconditionNo'], result['CurrentAge'], result['LifetimeAge']), (3, 0, 220))

    def test_status_actions_cover_retire_deny_and_reactivate(self):
        for state in ('RETIRED', 'DENIED', 'ACTIVE'):
            with self.subTest(state=state):
                conn = FakeConnection()
                result = set_mould_status(conn, 4, state, 'status reason')
                self.assertIn('sp_Mould_SetStatus', conn.procedures[0][0])
                self.assertEqual(conn.procedures[0][1], (4, state, 'status reason', 'FittingMES'))
                self.assertEqual(result['Status'], state)

    def test_invalid_values_reject_without_database_mutation(self):
        conn = FakeConnection()
        with self.assertRaisesRegex(ValueError, 'MouldID'):
            update_mould_info(conn, 'bad', 'Name')
        with self.assertRaisesRegex(ValueError, 'ACTIVE, RETIRED or DENIED'):
            set_mould_status(conn, 4, 'RECONDITION')
        with self.assertRaisesRegex(ValueError, 'Product Family'):
            register_mould(conn, 'Name', '', '01')
        self.assertEqual(conn.procedures, [])

    def test_sql_exception_rolls_back_and_does_not_commit(self):
        conn = FakeConnection()
        conn.fail = 'EXEC dbo.sp_Mould_SendToRecondition'
        with self.assertRaisesRegex(RuntimeError, 'simulated SQL failure'):
            send_to_recondition(conn, 4, 'note')
        self.assertEqual((conn.commits, conn.rollbacks), (0, 1))

    def test_page_renders_filters_authoritative_age_actions_and_histories(self):
        conn = FakeConnection()
        with patch('app.main.get_connection', return_value=conn):
            response = mould_page(request(), production_date=date(2026, 9, 27), mould_id=4)
        self.assertEqual(response.status_code, 200)
        page = response.body.decode()
        for text in ('M000001', 'Mould One', 'Product One', 'Lifetime Age', 'Status History',
                     'Recondition History', 'Usage / Production History', 'I0260901',
                     'Send to Recondition', 'DENIED', 'RETIRED'):
            self.assertIn(text, page)
        self.assertNotIn('name="mould_no"', page)
        self.assertIn('FROM dbo.vw_MouldList', '\n'.join(sql for sql, _ in conn.sql))
        self.assertEqual(conn.commits, 0)


if __name__ == '__main__':
    unittest.main()