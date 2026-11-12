import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'sql' / '029_press_production_interval_overlap.sql'
PREFLIGHT = ROOT / 'sql' / '029_press_production_interval_overlap_preflight.sql'
ROLLBACK = ROOT / 'sql' / '029_press_production_interval_overlap_rollback.sql'
TEST_SETUP = ROOT / 'tests' / 'sql' / '029_press_production_interval_overlap_test_setup.sql'
TEST_CLEANUP = ROOT / 'tests' / 'sql' / '029_press_production_interval_overlap_test_cleanup.sql'
SQLSERVER_TEST = ROOT / 'tests' / 'integration' / 'test_migration_029_sqlserver.py'


class PressProductionIntervalMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION.read_text(encoding='utf-8')
        cls.preflight = PREFLIGHT.read_text(encoding='utf-8')
        cls.rollback = ROLLBACK.read_text(encoding='utf-8')

    def test_press_interval_migration_uses_unapplied_029_identity(self):
        self.assertTrue((ROOT / 'sql' / '028_depallet_dry_line_equipment.sql').exists())
        self.assertFalse((ROOT / 'sql' / '028_press_production_interval_overlap.sql').exists())
        self.assertEqual(MIGRATION.name, '029_press_production_interval_overlap.sql')
        self.assertIn("Migration 029 may only be applied", self.migration)
        self.assertIn("SESSION_CONTEXT(N'FittingMES_029_TestRun')", self.migration)

    def test_preflight_is_read_only_and_reports_existing_invalid_or_overlapping_rows(self):
        self.assertIn("SESSION_CONTEXT(N'FittingMES_029_TestRun')", self.preflight)
        self.assertIn('pp.ProductionStartTime IS NULL', self.preflight)
        self.assertIn('pp.ProductionEndTime IS NULL', self.preflight)
        self.assertIn('second_assignment.ProductionStartTime IS NULL', self.preflight)
        self.assertIn('first_assignment.ProductionStartTime < second_assignment.ProductionEndTime',
                      self.preflight)
        self.assertNotRegex(
            self.preflight,
            r'\b(?:INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|MERGE)\b',
        )
        self.assertNotIn('second_lot.ProdDate = first_lot.ProdDate', self.preflight)

    def test_preflight_separates_invalid_intervals_real_overlaps_and_null_candidates(self):
        invalid_start = self.preflight.index('AS MissingStartTime')
        actual_overlap = self.preflight.index(
            "N'Valid actual interval overlap' AS Finding"
        )
        null_candidate = self.preflight.index(
            "N'Potential conflict caused by NULL interval endpoint' AS Finding"
        )
        self.assertLess(invalid_start, actual_overlap)
        self.assertLess(actual_overlap, null_candidate)
        self.assertIn('AS MissingEndTime', self.preflight)
        self.assertIn('AS NonPositiveInterval', self.preflight)
        self.assertIn('first_assignment.ProductionStartTime IS NOT NULL',
                      self.preflight)
        self.assertIn('first_assignment.ProductionEndTime IS NOT NULL',
                      self.preflight)
        self.assertIn('second_assignment.ProductionStartTime IS NOT NULL',
                      self.preflight)
        self.assertIn('second_assignment.ProductionEndTime IS NOT NULL',
                      self.preflight)
        self.assertIn('AS OverlapStartTime', self.preflight)
        self.assertIn('AS OverlapEndTime', self.preflight)
        self.assertIn(
            'second_assignment.PressProductionID > first_assignment.PressProductionID',
            self.preflight,
        )
        self.assertIn('first_assignment.ProductionStartTime IS NULL',
                      self.preflight[null_candidate:])
        self.assertIn('first_assignment.ProductionEndTime IS NULL',
                      self.preflight[null_candidate:])

    def test_migration_replaces_identity_unique_index_with_interval_indexes(self):
        self.assertIn('DROP INDEX UX_PressProduction_Production_Machine_ShiftActive',
                      self.migration)
        self.assertIn('CREATE INDEX IX_PressProduction_ActiveMachineInterval',
                      self.migration)
        self.assertIn('CREATE INDEX IX_PressProduction_ActiveMouldInterval',
                      self.migration)
        self.assertNotRegex(
            self.migration,
            r'CREATE\s+UNIQUE\s+INDEX\s+UX_PressProduction_Production_Machine_ShiftActive',
        )
        self.assertIn("IF DB_NAME() <> N'SB23'", self.migration)
        self.assertIn('BEGIN TRANSACTION', self.migration)
        self.assertIn('ROLLBACK TRANSACTION', self.migration)
        self.assertNotRegex(
            self.migration,
            r'\bUPDATE\s+dbo\.PressProduction\b|\bDELETE\s+FROM\s+dbo\.PressProduction\b',
        )

    def test_trigger_serializes_and_blocks_cross_date_press_or_mould_overlap(self):
        self.assertIn('TR_PressProduction_PreventActiveIntervalOverlap', self.migration)
        self.assertIn('AFTER INSERT, UPDATE', self.migration)
        self.assertIn('DECLARE @changed TABLE', self.migration)
        self.assertIn('EXCEPT', self.migration)
        self.assertIn('JOIN @changed AS c ON c.PressProductionID = i.PressProductionID',
                      self.migration)
        self.assertIn('OR i.ProductionEndTime IS NULL', self.migration)
        self.assertIn('sys.sp_getapplock', self.migration)
        self.assertIn('ORDER BY ResourceName', self.migration)
        self.assertNotIn('existing_lot.ProdDate = new_lot.ProdDate', self.migration)
        self.assertIn('actual datetime interval.', self.migration)
        self.assertIn('new_assignment.MachineCode = existing_assignment.MachineCode',
                      self.migration)
        self.assertIn('new_assignment.MouldID = existing_assignment.MouldID',
                      self.migration)
        self.assertIn('new_assignment.ProductionStartTime\n                      < existing_assignment.ProductionEndTime',
                      self.migration)
        self.assertIn('existing_assignment.ProductionStartTime\n                      < new_assignment.ProductionEndTime',
                      self.migration)
        self.assertIn('existing_assignment.ReleasedAt IS NULL', self.migration)
        self.assertIn('new_assignment.ReleasedAt IS NULL', self.migration)
        self.assertIn('Mixed writers can deadlock', self.migration)
        self.assertIn('does not guarantee deadlock-free writes', self.migration)

    def test_rollback_refuses_to_recreate_identity_unique_index_after_sequential_rows(self):
        self.assertIn('HAVING COUNT_BIG(*) > 1', self.rollback)
        self.assertIn('sequential active assignments share a Lot/Press/Shift key',
                      self.rollback)
        self.assertIn('CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive',
                      self.rollback)
        self.assertIn('DROP TRIGGER dbo.TR_PressProduction_PreventActiveIntervalOverlap',
                      self.rollback)
        self.assertNotRegex(
            self.rollback,
            r'\bUPDATE\s+dbo\.PressProduction\b|\bDELETE\s+FROM\s+dbo\.PressProduction\b',
        )

    def test_test_database_bypass_requires_explicit_session_marker(self):
        for script in (self.migration, self.rollback):
            self.assertIn("DB_NAME() = N'SB23_TEST'", script)
            self.assertIn("SESSION_CONTEXT(N'FittingMES_029_TestRun')", script)
        setup = TEST_SETUP.read_text(encoding='utf-8')
        cleanup = TEST_CLEANUP.read_text(encoding='utf-8')
        integration = SQLSERVER_TEST.read_text(encoding='utf-8')
        self.assertIn("DB_NAME() <> N'SB23_TEST'", setup)
        self.assertIn("DB_NAME() <> N'SB23_TEST'", cleanup)
        self.assertIn('FITTINGMES_029_TEST_AUTHORIZED', integration)
        self.assertIn('"DATABASE={SB23_TEST};"', integration)
        self.assertNotRegex(integration, r'\bCREATE\s+DATABASE\b')


if __name__ == '__main__':
    unittest.main()
