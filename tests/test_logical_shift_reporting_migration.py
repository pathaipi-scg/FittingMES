import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'sql' / '031_logical_shift_reporting.sql'
PREFLIGHT = ROOT / 'sql' / '031_logical_shift_reporting_preflight.sql'
ROLLBACK = ROOT / 'sql' / '031_logical_shift_reporting_rollback.sql'


class LogicalShiftReportingMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION.read_text(encoding='utf-8')
        cls.preflight = PREFLIGHT.read_text(encoding='utf-8')
        cls.rollback = ROLLBACK.read_text(encoding='utf-8')

    def test_migration_is_guarded_and_requires_029_snapshots(self):
        self.assertIn("DB_NAME() = N'SB23_TEST'", self.migration)
        self.assertIn("SESSION_CONTEXT(N'FittingMES_031_TestRun')", self.migration)
        self.assertIn("DayStartTime = '08:00'", self.migration)
        self.assertIn("CutoffTime = '07:00'", self.migration)
        self.assertIn("TR_PressProduction_PreventActiveIntervalOverlap", self.migration)
        self.assertIn("Migration 030 logical Shift snapshots are required.", self.migration)
        self.assertIn("OBJECT_ID(N'dbo.ShiftMasterVersion', N'U')", self.migration)
        self.assertIn("COL_LENGTH(N'dbo.ProductionLot', N'ShiftMasterID')", self.migration)
        self.assertIn("COL_LENGTH(N'dbo.ProductionLot', N'ShiftCodeSnapshot')", self.migration)

    def test_reporting_schema_keeps_stable_ids_and_legacy_snapshots(self):
        self.assertIn('ShiftMasterID bigint NULL', self.migration)
        self.assertIn('ShiftCodeSnapshot varchar(10) NULL', self.migration)
        self.assertIn('FK_DailyMaterialUsage_ShiftMaster', self.migration)
        self.assertIn('FK_LoggerEvent_ShiftMaster', self.migration)
        self.assertIn('UX_DailyMaterialUsage_Date_ShiftMaster', self.migration)
        self.assertIn('COALESCE(L.ShiftMasterID, historical.ShiftMasterID, current_shift.id)',
                      self.migration)
        self.assertNotRegex(self.migration, r'UPDATE\s+dbo\.(?:ProductionLot|LoggerEvent|DailyMaterialUsage)')

    def test_new_views_aggregate_by_master_and_preserve_legacy_key(self):
        for view_name in ('vw_DailyProductionQtyLogical',
                          'vw_DailyMaterialUsageLogical',
                          'vw_DailyMaterialUsageCalcLogical'):
            self.assertIn(f'CREATE VIEW dbo.{view_name}', self.migration)
        self.assertNotIn('ALTER VIEW dbo.vw_DailyProductionQty', self.migration)
        self.assertNotIn('CREATE OR ALTER VIEW dbo.vw_DailyProductionQty', self.migration)
        self.assertIn('GROUP BY ReportDate, ShiftMasterID, LegacyShiftKey', self.migration)
        self.assertIn('P.ShiftMasterID = U.ShiftMasterID', self.migration)
        self.assertNotRegex(self.migration, r'GROUP BY\s+[^;]*ShiftPeriodID')

    def test_preflight_is_read_only_and_checks_historical_cutoff(self):
        self.assertIn("SESSION_CONTEXT(N'FittingMES_031_TestRun')", self.preflight)
        self.assertIn("DayStartTime = '08:00'", self.preflight)
        self.assertIn("OBJECT_ID(N'dbo.ShiftPeriodMaster', N'U')", self.preflight)
        self.assertIn("TR_PressProduction_PreventActiveIntervalOverlap", self.preflight)
        self.assertIn("CutoffTime = '07:00'", self.preflight)
        self.assertNotRegex(self.preflight, r'\b(?:INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|EXEC)\b')
        self.assertIn('COUNT_BIG(*) AS DuplicateCount', self.preflight)
        self.assertNotIn('AS RowCount', self.preflight)

    def test_rollback_refuses_to_discard_new_logical_identity(self):
        self.assertIn('Rollback 031 would discard saved logical Shift identity or snapshots.',
                      self.rollback)
        self.assertIn('BEGIN TRANSACTION', self.rollback)
        self.assertIn('ROLLBACK TRANSACTION', self.rollback)


if __name__ == '__main__':
    unittest.main()
