import sqlite3
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from app.main import read_plans, mark_used, choose_plan, production_page
from app.lots import insert_lot, update_lot, require_available
from test_production import PLAN, LOT, DAY, request


class QueryCursor:
    """Execute the production window query against an isolated in-memory SQL fixture."""
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, *params):
        self.cursor.execute(sql, tuple(p.isoformat() if isinstance(p, date) else p for p in params))
        return self

    @property
    def description(self):
        return self.cursor.description

    def fetchall(self):
        names = [column[0] for column in self.description]
        result = []
        for row in self.cursor.fetchall():
            result.append(tuple(date.fromisoformat(value) if name == 'StartTime' else value
                                for name, value in zip(names, row)))
        return result


class EffectivePlanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute("ATTACH DATABASE ':memory:' AS dbo")
        self.db.execute("""CREATE TABLE dbo.P_ActivePlan (
            Company TEXT, Plant TEXT, Machine TEXT, StartTime TEXT, Shift TEXT,
            PlanName TEXT, MaterialCode TEXT, MaterialName TEXT, PlanCount INTEGER, VersionNo TEXT)""")
        for version in ('1', '3', '2', '9', '10'):
            self.add(version)
        self.add('99', company='OTHER')
        self.add('99', day='2026-09-22')
        self.cursor = QueryCursor(self.db.cursor())

    def add(self, version, company='CRTC', day='2026-09-21'):
        self.db.execute("INSERT INTO dbo.P_ActivePlan VALUES (?,?,?,?,?,?,?,?,?,?)",
            (company, '30A1', 'SB2-3', day, 'D', 'Plan 1',
             'CODE' + version, 'Product version ' + version, int(version) * 100, version))

    def latest(self):
        return read_plans(self.cursor, DAY)[0]

    def test_sql_returns_only_highest_numeric_version_per_date_name(self):
        plans = read_plans(self.cursor, DAY)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]['VersionNo'], '10')
        self.assertEqual(plans[0]['StartTime'], DAY)
        self.assertEqual(plans[0]['MaterialCode'], 'CODE10')
        self.assertEqual(plans[0]['MaterialName'], 'Product version 10')
        self.assertEqual(plans[0]['PlanCount'], 1000)
        self.assertEqual(read_plans(self.cursor, date(2026, 9, 22))[0]['VersionNo'], '99')

    def test_used_status_ignores_saved_older_material_and_version(self):
        plan = mark_used([self.latest()], [dict(LOT, VersionNo='1')])[0]
        self.assertEqual(plan['used_by'], LOT['LotNo'])
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            choose_plan([plan], plan['selection_id'])
        self.assertIsNone(mark_used([plan], [LOT], LOT['ProductionID'])[0]['used_by'])

    def test_old_version_selection_is_rejected(self):
        old = self.latest()
        self.add('11')
        with self.assertRaisesRegex(ValueError, 'changed'):
            choose_plan(read_plans(self.cursor, DAY), old['selection_id'])

    def test_information_and_edit_resolve_latest_version(self):
        conn = MagicMock()
        latest = self.latest()
        with patch('app.main.get_connection', return_value=conn), patch('app.main.read_lots', return_value=[LOT]), patch('app.main.read_plans', return_value=[latest]):
            response = production_page(request(), production_id=7, edit=True, production_date=DAY)
        self.assertEqual(response.status_code, 200)
        current = response.context['current']
        self.assertEqual((current['MaterialCode'], current['MaterialName'], current['PlanQty'], current['VersionNo']),
                         ('CODE10', 'Product version 10', 1000, '10'))
        self.assertEqual(current['LotNo'], LOT['LotNo'])
        self.assertEqual(response.context['edit_plans'][0]['VersionNo'], '10')
        self.assertIsNone(response.context['edit_plans'][0]['used_by'])
        self.assertIn('Plan Version', response.body.decode())
        conn.commit.assert_not_called()

    def test_create_uses_effective_fields(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(0,), ('06',), ('NeuFit / NeuStile','06'), None, (1,), (8,)]
        insert_lot(conn, self.latest(), '06', 'B066909', 1, product_family='NeuFit / NeuStile')
        args = next(call.args for call in cursor.execute.call_args_list
                    if 'INSERT INTO dbo.ProductionLot\n' in call.args[0])
        self.assertEqual(args[1:6], (DAY, 'D', 'Plan 1', 'CODE10', 'Product version 10'))
        self.assertEqual(args[-2:], (1000, 'NeuFit / NeuStile'))

    def test_plan_change_uses_effective_fields(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value
        cursor.description = [(key,) for key in LOT]
        cursor.fetchall.return_value = [tuple(LOT.values())]
        cursor.fetchone.side_effect = [(0,), None]
        update_lot(conn, 7, self.latest())
        args = next(call.args for call in cursor.execute.call_args_list
                    if 'UPDATE dbo.ProductionLot' in call.args[0])
        self.assertEqual(args[1:], ('Plan 1', 'CODE10', 'Product version 10', 1000, 7))

    def test_backend_duplicate_check_uses_business_identity(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (LOT['LotNo'],)
        with self.assertRaisesRegex(ValueError, 'already assigned'):
            require_available(cursor, self.latest())
        args = cursor.execute.call_args.args
        self.assertEqual(args[1:], (DAY, 'Plan 1', 0))
        self.assertNotIn('VersionNo', args[0])

    def test_create_and_save_reject_old_version_before_writing(self):
        old = self.latest()
        self.add('11')
        for action in ('create', 'save'):
            with self.subTest(action=action):
                conn = MagicMock()
                with patch('app.main.get_connection', return_value=conn), patch('app.main.read_lots', return_value=[LOT] if action == 'save' else []), patch('app.main.read_plans', return_value=read_plans(self.cursor, DAY)), patch('app.main.insert_lot') as insert, patch('app.main.update_lot') as update:
                    response = production_page(request(), old['selection_id'], production_date=DAY,
                        create=action == 'create', save=action == 'save',
                        production_id=7 if action == 'save' else None, running_no=1)
                self.assertEqual(response.status_code, 400)
                insert.assert_not_called()
                update.assert_not_called()

