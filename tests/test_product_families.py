import unittest
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from starlette.requests import Request

from app.products import lot_prefix, read_families, read_mapping, require_product, selected_product, confirm_mapping
from app.lots import insert_lot, next_running_no


class SqliteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, *params):
        self.cursor.execute(sql, tuple(value.isoformat() if isinstance(value, date) else value
                                       for value in params))
        return self

    def fetchone(self):
        return self.cursor.fetchone()


class ProductFamilyTests(unittest.TestCase):
    def test_family_read_and_prefix_use_surrogate_id_and_master_attribute(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(7, 'Family A', 'B')]
        self.assertEqual(read_families(cursor), [
            dict(ProductFamilyID=7, ProductFamily='Family A', LotPrefixLetter='B')])
        cursor.fetchone.return_value = ('B',)
        self.assertEqual(lot_prefix(cursor, 7, '06', date(2026, 9, 21)), 'B066909')
        self.assertIn('ProductFamilyID=?', cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1:], (7,))
        with self.assertRaisesRegex(ValueError, 'valid Product Family ID'):
            lot_prefix(cursor, 'Family A', '06', date(2026, 9, 21))
        cursor.fetchone.return_value = None
        with self.assertRaisesRegex(ValueError, 'not available'):
            lot_prefix(cursor, 7, '06', date(2026, 9, 21))

    def test_selection_requires_one_family_scoped_product(self):
        self.assertEqual(selected_product([('7', ''), ('8', '06')]), (8, '06'))
        for choices in ([], [('7', ''), ('8', '')], [('7', '06'), ('8', '06')]):
            with self.subTest(choices=choices), self.assertRaisesRegex(ValueError, 'exactly one'):
                selected_product(choices)
        with self.assertRaisesRegex(ValueError, 'Product Family ID'):
            selected_product([('Family A', '06')])

    def test_missing_family_master_rows_do_not_create_choices(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        self.assertEqual(read_families(cursor), [])

    def test_product_validation_uses_composite_surrogate_key(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        with self.assertRaisesRegex(ValueError, 'not available'):
            require_product(cursor, 7, '06')
        self.assertIn('ProductFamilyID=? AND pcm.ProductCode=?', cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1:], (7, '06'))

    def test_mapping_read_preserves_unresolved_null_family(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (None, '06')
        self.assertIsNone(read_mapping(cursor, 'PREFIX'))
        cursor.fetchone.return_value = (7, '06')
        self.assertEqual(read_mapping(cursor, 'PREFIX'), (7, '06'))
        self.assertIn('SELECT ProductFamilyID,ProductCode', cursor.execute.call_args.args[0])

    def test_new_mapping_persists_id_and_display_snapshot(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(0,), ('Family A',), None, ('Family A',)]
        self.assertEqual(confirm_mapping(conn, 'PREFIX', 7, '06'), (7, '06'))
        insert = next(call.args for call in cursor.execute.call_args_list
                      if 'INSERT INTO dbo.MaterialProductMap' in call.args[0])
        self.assertIn('ProductFamilyID,ProductFamily,ProductCode', insert[0])
        self.assertEqual(insert[1:], ('PREFIX', 7, 'Family A', '06'))
        conn.commit.assert_called_once()

    def test_explicit_confirmation_resolves_legacy_null_mapping_without_history(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(0,), ('Family A',), (None, '06', None), ('Family A',)]
        unresolved_cursor = MagicMock()
        unresolved_cursor.fetchone.return_value = (None, '06')
        self.assertIsNone(read_mapping(unresolved_cursor, 'PREFIX'))
        self.assertEqual(confirm_mapping(conn, 'PREFIX', 7, '06'), (7, '06'))
        update = next(call.args for call in cursor.execute.call_args_list
                      if 'UPDATE dbo.MaterialProductMap SET' in call.args[0])
        self.assertEqual(update[1:], (7, 'Family A', '06', 'PREFIX'))
        self.assertFalse(any('MaterialProductMapHistory' in call.args[0]
                             for call in cursor.execute.call_args_list))
        conn.commit.assert_called_once()

    def test_mapping_change_keeps_historical_name_and_id_snapshots(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(0,), ('06',), (3, '16', 'Old Family'), ('Family B',)]
        self.assertEqual(confirm_mapping(conn, 'PREFIX', 8, '06', edit=True), (8, '06'))
        history = next(call.args for call in cursor.execute.call_args_list
                       if 'INSERT INTO dbo.MaterialProductMapHistory' in call.args[0])
        self.assertEqual(history[1:], ('PREFIX', 3, 'Old Family', '16', 8, 'Family B', '06'))
        update = next(call.args for call in cursor.execute.call_args_list
                      if 'UPDATE dbo.MaterialProductMap SET' in call.args[0])
        self.assertEqual(update[1:], (8, 'Family B', '06', 'PREFIX'))

    def test_concurrent_conflicting_confirmation_is_not_overwritten(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [
            (0,), ('Family A',), (3, '06', 'Family B'), ('Family A',)]
        with self.assertRaisesRegex(ValueError, 'another session'):
            confirm_mapping(conn, 'PREFIX', 7, '06')
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        self.assertFalse(any('UPDATE dbo.MaterialProductMap SET' in call.args[0]
                             for call in cursor.execute.call_args_list))

    def test_same_value_edit_does_not_insert_history(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [
            (0,), ('Family A',), (7, '06', 'Family A'), ('Family A',)]
        self.assertEqual(confirm_mapping(conn, 'PREFIX', 7, '06', edit=True), (7, '06'))
        self.assertFalse(any('MaterialProductMapHistory' in call.args[0]
                             for call in cursor.execute.call_args_list))
        self.assertFalse(any('UPDATE dbo.MaterialProductMap SET' in call.args[0]
                             for call in cursor.execute.call_args_list))
        conn.commit.assert_called_once()

    def test_mapping_update_failure_rolls_back_history(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [
            (0,), ('Family B',), (3, '16', 'Old Family'), ('Family B',)]

        def fail_update(sql, *args):
            if 'UPDATE dbo.MaterialProductMap SET' in sql:
                raise RuntimeError('mapping update failed')

        cursor.execute.side_effect = fail_update
        with self.assertRaisesRegex(RuntimeError, 'mapping update failed'):
            confirm_mapping(conn, 'PREFIX', 8, '06', edit=True)
        self.assertTrue(any('INSERT INTO dbo.MaterialProductMapHistory' in call.args[0]
                            for call in cursor.execute.call_args_list))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_edit_mode_renders_saved_id_selection_and_cancel(self):
        from app.main import production_page
        request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})
        plan = dict(selection_id='plan-id', StartTime=date(2026, 9, 21), Shift='D',
                    PlanName='Plan 1', MaterialCode='12345678XX',
                    MaterialName='Product brown', PlanCount=3600)
        families = [dict(ProductFamilyID=8, ProductFamily='Family B', LotPrefixLetter='I')]
        products = [dict(ProductFamilyID=8, ProductFamily='Family B',
                         ProductCode='06', ProductName='Product six')]
        with patch('app.main.get_connection', return_value=MagicMock()), \
             patch('app.main.read_lots', return_value=[]), \
             patch('app.main.read_shift_rules', return_value=[]), \
             patch('app.main.read_plans', return_value=[plan]), \
             patch('app.main.read_families', return_value=families), \
             patch('app.main.product_selection_context',
                   return_value=dict(products=products, product_previews={})), \
             patch('app.main.read_mapping', return_value=(8, '06')):
            response = production_page(request, 'plan-id', production_date=date(2026, 9, 21),
                                      mapping_edit=True)
        body = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="mapping_edit" value="true"', body)
        self.assertIn('value="06" selected', body)
        self.assertIn('>CANCEL</a>', body)

    def test_mapping_edit_confirmation_returns_to_mapped_product_preview(self):
        from app.main import production_page
        request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})
        plan = dict(selection_id='plan-id', StartTime=date(2026, 9, 21), Shift='D',
                    PlanName='Plan 1', MaterialCode='12345678XX',
                    MaterialName='Product brown', PlanCount=3600)
        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = ('Family B', 'Product six')
        with patch('app.main.get_connection', return_value=conn), \
             patch('app.main.read_lots', return_value=[]), \
             patch('app.main.read_shift_rules', return_value=[]), \
             patch('app.main.read_plans', return_value=[plan]), \
             patch('app.main.read_families', return_value=[
                 dict(ProductFamilyID=8, ProductFamily='Family B', LotPrefixLetter='I')]), \
             patch('app.main.confirm_mapping', return_value=(8, '06')) as confirm, \
             patch('app.main.read_mapping', return_value=(8, '06')), \
             patch('app.main.lot_prefix', return_value='I066909'), \
             patch('app.main.next_running_no', return_value=1):
            response = production_page(request, 'plan-id', confirm=True, mapping_edit=True,
                                       production_date=date(2026, 9, 21),
                                       product_choices=[('8', '06')])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['product_family_id'], 8)
        self.assertEqual(response.context['product_family'], 'Family B')
        self.assertEqual(response.context['product_code'], '06')
        self.assertNotIn('name="mapping_edit" value="true"', response.body.decode())
        confirm.assert_called_once()

    def test_forward_migration_uses_surrogate_scoped_keys_and_preserves_snapshots(self):
        sql = Path('sql/023_product_family_id.sql').read_text()
        self.assertIn('ProductFamilyID int IDENTITY(1,1) NOT NULL', sql)
        self.assertIn('PRIMARY KEY CLUSTERED (ProductFamilyID,ProductCode)', sql)
        self.assertIn('FOREIGN KEY (ProductFamilyID,ProductCode)', sql)
        self.assertIn('OldProductFamilyID int NULL, NewProductFamilyID int NULL', sql)
        self.assertIn('ProductFamilyID IS NULL', sql)
        self.assertIn('CK_ProductFamilyMaster_LotPrefixLetter', sql)
        self.assertIn('Latin1_General_100_BIN2', sql)
        self.assertIn('DATALENGTH(pf.ProductFamily)', sql)
        self.assertIn("EXEC sys.sp_executesql N'", sql)
        self.assertIn('THROW 52304', sql)
        self.assertIn('THROW 52305', sql)
        self.assertIn('THROW 52306', sql)
        self.assertIn('#PF_PreMigrationSnapshots', sql)
        self.assertNotIn('DELETE FROM', sql.upper())
        self.assertIn('BEGIN TRY', sql)
        self.assertIn('BEGIN TRANSACTION', sql)

    def test_rollback_refuses_to_rekey_changed_display_snapshots(self):
        sql = Path('sql/023_product_family_id_rollback.sql').read_text()
        self.assertIn('dbo.MaterialProductMap m', sql)
        self.assertIn('dbo.ProductionLot l', sql)
        self.assertIn('Rollback stopped: family snapshots differ', sql)
        self.assertIn('WHERE ProductFamily=@ProductFamily AND ProductCode=@ProductCode', sql)
        self.assertIn('ON pcm.ProductFamily=m.ProductFamily AND pcm.ProductCode=m.ProductCode', sql)
        drops = sql.rfind('ALTER TABLE dbo.ProductionLot DROP COLUMN ProductFamilyID;')
        self.assertGreaterEqual(drops, 0)
        self.assertNotIn('ProductFamilyID', sql[drops + len(
            'ALTER TABLE dbo.ProductionLot DROP COLUMN ProductFamilyID;'):])

    def test_next_running_number_scopes_family_month_and_legacy_rows(self):
        database = sqlite3.connect(':memory:')
        self.addCleanup(database.close)
        database.execute("ATTACH DATABASE ':memory:' AS dbo")
        database.execute('''CREATE TABLE dbo.ProductionLot (
            ProductFamilyID INTEGER,ProductCode TEXT,SequenceMonth TEXT,
            LotPrefix TEXT,RunningNo INTEGER,IsActive INTEGER)''')
        database.executemany('INSERT INTO dbo.ProductionLot VALUES (?,?,?,?,?,?)', [
            (1, '06', '2026-09-01', 'B066909', 1, 1),
            (1, '06', '2026-09-01', 'B066909', 2, 1),
            (3, '06', '2026-09-01', 'I066909', 1, 1),
            (3, '06', '2026-09-01', 'I066909', 2, 0),
            (None, '06', '2026-09-01', 'B006909', 1, 1),
            (None, '06', '2026-09-01', 'B006909', 2, 1),
        ])
        cursor = SqliteCursor(database.cursor())
        self.assertEqual(next_running_no(
            cursor, product_family_id=1, product_code='06', plan_date=date(2026, 9, 21)), 3)
        self.assertEqual(next_running_no(
            cursor, product_family_id=3, product_code='06', plan_date=date(2026, 9, 21)), 2)
        self.assertEqual(next_running_no(
            cursor, product_family_id=1, product_code='06', plan_date=date(2026, 10, 1)), 1)
        self.assertEqual(next_running_no(cursor, 'B006909'), 3)

    def test_new_lot_rejects_unresolved_family_before_insert(self):
        conn = MagicMock()
        plan = dict(StartTime=date(2026, 9, 21), Shift='1', PlanName='Plan',
                    MaterialCode='12345678XX', MaterialName='Product', PlanCount=10)
        with self.assertRaisesRegex(ValueError, 'valid Product Family ID'):
            insert_lot(conn, plan, '06', 'I066909', 1)
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        self.assertFalse(any('INSERT INTO dbo.ProductionLot' in call.args[0]
                             for call in conn.cursor.return_value.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
