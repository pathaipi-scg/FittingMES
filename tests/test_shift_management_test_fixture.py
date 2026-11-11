import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'tests' / 'sql' / 'shift_management_test_setup.sql'
SEED = ROOT / 'tests' / 'sql' / 'shift_management_test_seed_after_030.sql'
CLEANUP = ROOT / 'tests' / 'sql' / 'shift_management_test_cleanup.sql'
SQLSERVER_TESTS = (
    ROOT / 'tests' / 'integration' / 'test_migration_029_sqlserver.py',
    ROOT / 'tests' / 'integration' / 'test_logical_shift_reporting_sqlserver.py',
)


class ShiftManagementTestFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.setup = SETUP.read_text(encoding='utf-8')
        cls.seed = SEED.read_text(encoding='utf-8')
        cls.cleanup = CLEANUP.read_text(encoding='utf-8')

    def test_every_fixture_script_guards_database_before_writes(self):
        for script in (self.setup, self.seed, self.cleanup):
            guard = script.index("IF DB_NAME() <> N'SB23_TEST'")
            writes = re.search(
                r'\b(?:CREATE\s+TABLE|CREATE\s+INDEX|INSERT\s+INTO|UPDATE\s+'
                r'[\w.]+|DROP\s+(?:TABLE|VIEW|TRIGGER|INDEX))\b',
                script,
                re.IGNORECASE,
            )
            self.assertIsNotNone(writes)
            self.assertLess(guard, writes.start())

    def test_setup_requires_empty_database_and_has_synthetic_027_baseline(self):
        self.assertIn('FROM sys.objects WHERE is_ms_shipped = 0', self.setup)
        self.assertIn('FROM sys.synonyms', self.setup)
        self.assertIn('referenced_server_name IS NOT NULL', self.setup)
        self.assertIn('FK_PressProduction_ShiftMaster', self.setup)
        self.assertIn('UX_PressProduction_Production_Machine_ShiftActive', self.setup)
        self.assertIn("VALUES ('2026-01-01', '08:00')", self.setup)
        self.assertIn('Synthetic unresolved legacy row', self.setup)
        self.assertIn('Synthetic Shift 1 second period', self.setup)

    def test_post_030_seed_preserves_cross_cutoff_period_as_one_period(self):
        self.assertIn("CutoffTime = '07:00'", self.seed)
        self.assertIn("CONVERT(time(0), '04:00'), CONVERT(time(0), '08:00')", self.seed)
        self.assertIn("ProductionDateCutoffSnapshot = '07:00'", self.seed)
        self.assertIn('PeriodStartTimeSnapshot = fixture.StartTime', self.seed)
        self.assertIn('PeriodEndTimeSnapshot = fixture.EndTime', self.seed)
        self.assertNotRegex(self.seed, r'\b(?:DELETE|DROP)\b')

    def test_cleanup_is_database_scoped_and_does_not_drop_the_database(self):
        self.assertIn("IF DB_NAME() <> N'SB23_TEST'", self.cleanup)
        self.assertIn('DROP TABLE dbo.PressProduction', self.cleanup)
        self.assertIn('DROP TABLE dbo.ShiftPeriodVersion', self.cleanup)
        self.assertNotRegex(self.cleanup, r'\bDROP\s+DATABASE\b')
        self.assertNotRegex(self.cleanup, r'\b(?:INSERT|UPDATE|DELETE)\b')

    def test_fixture_has_no_live_database_or_linked_server_references(self):
        combined = '\n'.join((self.setup, self.seed, self.cleanup)).upper()
        self.assertNotIn('SB23]', combined)
        self.assertNotIn('PIS.', combined)
        self.assertNotIn('OPENQUERY', combined)
        self.assertNotIn('OPENDATASOURCE', combined)
        self.assertNotRegex(combined, r'\b(?:CREATE|ALTER)\s+DATABASE\b')

    def test_sqlserver_integration_connections_pin_database_and_instance(self):
        for path in SQLSERVER_TESTS:
            script = path.read_text(encoding='utf-8')
            self.assertIn('"DATABASE={SB23_TEST};"', script)
            self.assertIn('DB_NAME(), @@SERVERNAME', script)
            self.assertIn('"DCDLGYF3\\\\SQLEXPRESS"', script)
            self.assertIn('"10.28.254.3"', script)


if __name__ == '__main__':
    unittest.main()
