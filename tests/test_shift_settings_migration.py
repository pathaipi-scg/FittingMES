import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'sql' / '030_shift_period_cutoff.sql'
ROLLBACK = ROOT / 'sql' / '030_shift_period_cutoff_rollback.sql'
PREFLIGHT = ROOT / 'sql' / '030_shift_period_cutoff_preflight.sql'


class ShiftSettingsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION.read_text(encoding='utf-8')
        cls.rollback = ROLLBACK.read_text(encoding='utf-8')
        cls.preflight = PREFLIGHT.read_text(encoding='utf-8')

    def test_version_tables_follow_database_id_first_columns_and_audit_fields(self):
        for table in ('ShiftMasterVersion', 'ShiftPeriodMaster',
                      'ShiftPeriodVersion', 'ProductionDateCutoffVersion'):
            self.assertRegex(
                self.migration,
                rf'CREATE TABLE dbo\.{table}\s*\(\s*id bigint IDENTITY\(1,1\)',
            )
            self.assertRegex(
                self.migration,
                rf'Rectime datetime NOT NULL CONSTRAINT DF_{table}_Rectime DEFAULT \(GETDATE\(\)\)',
            )
        for field in ('VersionNumber', 'OldValue', 'NewValue', 'ChangedAt',
                      'ChangedBy nvarchar(256) NULL', 'EffectiveFromDate', 'EffectiveToDate'):
            self.assertIn(field, self.migration)

    def test_press_snapshots_are_nullable_for_legacy_rows(self):
        self.assertIn('ShiftPeriodID bigint NULL', self.migration)
        self.assertIn('ShiftMasterVersionID bigint NULL', self.migration)
        self.assertIn('ShiftPeriodVersionID bigint NULL', self.migration)
        self.assertIn('ShiftCodeSnapshot varchar(10) NULL', self.migration)
        self.assertIn('ProductionDateCutoffSnapshot time(0) NULL', self.migration)
        self.assertNotRegex(self.migration, r'UPDATE\s+dbo\.PressProduction')

    def test_seed_data_is_database_resolved_and_migration_is_guarded(self):
        self.assertIn("IF DB_NAME() <> N'SB23'", self.migration)
        self.assertIn("DB_NAME() = N'SB23_TEST'", self.migration)
        self.assertIn("SESSION_CONTEXT(N'FittingMES_030_TestRun')", self.migration)
        self.assertIn("WHERE ShiftCode = '1'", self.migration)
        self.assertIn("WHERE ShiftCode = '2'", self.migration)
        self.assertIn("VALUES\n        (@shift1, N'1'", self.migration)
        self.assertIn("N'07:00 Asia/Bangkok'", self.migration)

    def test_rollback_refuses_to_drop_referenced_snapshots(self):
        self.assertIn('Rollback refused: production rows reference versioned configuration.',
                      self.rollback)
        self.assertIn('BEGIN TRANSACTION', self.rollback)
        self.assertIn('ROLLBACK TRANSACTION', self.rollback)

    def test_preflight_requires_027_029_and_preserves_cutoff_history(self):
        self.assertIn("SESSION_CONTEXT(N'FittingMES_030_TestRun')", self.preflight)
        self.assertIn("COL_LENGTH(N'dbo.PressProduction', N'ShiftMasterID')", self.preflight)
        self.assertIn("Migration 029 is not applied", self.preflight)
        self.assertIn("dbo.TR_PressProduction_PreventActiveIntervalOverlap", self.preflight)
        self.assertIn("EffectiveFromDate = '2026-01-01'", self.preflight)
        self.assertIn("DayStartTime = '08:00'", self.preflight)
        self.assertIn('pp.ProductionStartTime IS NULL OR pp.ProductionEndTime IS NULL',
                      self.preflight)
        self.assertNotRegex(self.preflight, r'\b(?:INSERT|UPDATE|DELETE|MERGE|ALTER|DROP)\b')


if __name__ == '__main__':
    unittest.main()
