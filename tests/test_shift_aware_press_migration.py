import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "sql" / "027_shift_aware_press_production.sql"
PREFLIGHT_PATH = ROOT / "sql" / "027_shift_aware_press_production_preflight.sql"
ROLLBACK_PATH = ROOT / "sql" / "027_shift_aware_press_production_rollback.sql"
CONTEXT_PATH = ROOT / "md" / "FittingMES_Shift_Aware_Press_Mould_Design_Context_20261008.md"


class ShiftAwarePressMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.preflight = PREFLIGHT_PATH.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK_PATH.read_text(encoding="utf-8")
        cls.context = CONTEXT_PATH.read_text(encoding="utf-8")

    def test_migration_preserves_unknown_shift_for_legacy_rows(self):
        self.assertRegex(self.migration, r"ADD ShiftMasterID bigint NULL")
        self.assertIn(
            "FOREIGN KEY (ShiftMasterID) REFERENCES dbo.ShiftMaster(id)",
            self.migration,
        )
        self.assertNotRegex(
            self.migration,
            r"\bUPDATE\s+dbo\.PressProduction\b",
        )
        self.assertNotIn("@Shift1MasterID", self.migration)
        self.assertNotIn("ShiftCode 1 is required", self.migration)

    def test_migration_does_not_read_or_change_equipment_time_events(self):
        self.assertNotRegex(
            self.migration,
            r"\bdbo\.EquipmentTimeEvent\b",
        )

    def test_active_filtered_key_allows_released_and_unknown_shift_rows(self):
        self.assertIn(
            "ON dbo.PressProduction (ProductionID, MachineCode, ShiftMasterID)",
            self.migration,
        )
        self.assertIn(
            "WHERE ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL",
            self.migration,
        )
        self.assertIn(
            "DROP INDEX UX_PressProduction_Production_Machine",
            self.migration,
        )

    def test_migration_checks_expected_old_key_and_runs_transactionally(self):
        self.assertIn("UX_PressProduction_Production_Machine", self.migration)
        self.assertIn("BEGIN TRANSACTION", self.migration)
        self.assertIn("BEGIN CATCH", self.migration)
        self.assertIn("ROLLBACK TRANSACTION", self.migration)
        self.assertIn("IF DB_NAME() <> N'SB23'", self.migration)
        self.assertIn("HAVING COUNT_BIG(*) > 1", self.migration)

    def test_new_column_referencing_ddl_runs_in_later_dynamic_batches(self):
        add_column = self.migration.index("ADD ShiftMasterID bigint NULL")
        begin_transaction = self.migration.index("BEGIN TRANSACTION")
        foreign_key_batch = self.migration.index(
            "EXEC sys.sp_executesql N'\n        ALTER TABLE dbo.PressProduction"
        )
        drop_old_index = self.migration.index(
            "DROP INDEX UX_PressProduction_Production_Machine"
        )
        filtered_index_batch = self.migration.index(
            "EXEC sys.sp_executesql N'\n        CREATE UNIQUE INDEX "
            "UX_PressProduction_Production_Machine_ShiftActive"
        )
        commit_transaction = self.migration.index("COMMIT TRANSACTION")

        self.assertLess(begin_transaction, add_column)
        self.assertLess(add_column, foreign_key_batch)
        self.assertLess(foreign_key_batch, drop_old_index)
        self.assertLess(drop_old_index, filtered_index_batch)
        self.assertLess(filtered_index_batch, commit_transaction)
        self.assertIn("FOREIGN KEY (ShiftMasterID)", self.migration)
        self.assertIn("ShiftMasterID IS NOT NULL", self.migration)

        dynamic_batches = re.findall(
            r"EXEC\s+sys\.sp_executesql\s+N'((?:''|[^'])*)';",
            self.migration,
            re.IGNORECASE | re.DOTALL,
        )
        self.assertEqual(len(dynamic_batches), 2)
        dynamic_sql = "\n".join(batch.replace("''", "'") for batch in dynamic_batches)
        self.assertRegex(
            dynamic_sql,
            r"ALTER TABLE dbo\.PressProduction\s+ADD CONSTRAINT "
            r"FK_PressProduction_ShiftMaster\s+FOREIGN KEY \(ShiftMasterID\)",
        )
        self.assertRegex(
            dynamic_sql,
            r"CREATE UNIQUE INDEX UX_PressProduction_Production_Machine_ShiftActive"
            r"[\s\S]*ShiftMasterID[\s\S]*WHERE ReleasedAt IS NULL"
            r" AND ShiftMasterID IS NOT NULL",
        )

        outer_batch = re.sub(
            r"EXEC\s+sys\.sp_executesql\s+N'((?:''|[^'])*)';",
            "",
            self.migration,
            flags=re.IGNORECASE | re.DOTALL,
        )
        self.assertNotRegex(
            outer_batch,
            r"(?is)ALTER TABLE dbo\.PressProduction\s+ADD CONSTRAINT "
            r"FK_PressProduction_ShiftMaster[\s\S]*?ShiftMasterID",
        )
        self.assertNotRegex(
            outer_batch,
            r"(?is)CREATE UNIQUE INDEX "
            r"UX_PressProduction_Production_Machine_ShiftActive[\s\S]*?ShiftMasterID",
        )

    def test_preflight_is_read_only_and_reports_unknown_shift_assignments_and_events(self):
        self.assertIn("ActiveAssignmentCount", self.preflight)
        self.assertIn("COUNT(DISTINCT pp.ProductionID)", self.preflight)
        self.assertIn("AS TotalRows", self.preflight)
        self.assertNotIn("AS RowCount", self.preflight)
        self.assertIn("Shift2TimeEventID", self.preflight)
        self.assertIn("MatchingShift1TimeEventID", self.preflight)
        self.assertIn("Shift1NaturalKeyCollisionCount", self.preflight)
        self.assertIn("NonzeroOrNullLinkedShift2ManualEventCount", self.preflight)
        self.assertIn("PressProduction rows with unknown Shift", self.preflight)
        self.assertIn("WHERE ShiftMasterID IS NULL", self.preflight)
        self.assertNotIn("Exactly one active ShiftMaster row with ShiftCode 1 is required", self.preflight)
        self.assertNotRegex(
            self.preflight,
            r"\b(?:INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|MERGE)\b",
        )

    def test_rollback_refuses_to_discard_explicit_assignment_shift_data(self):
        self.assertIn("WHERE ShiftMasterID IS NOT NULL", self.rollback)
        self.assertIn("restore a pre-migration backup instead", self.rollback)
        self.assertIn("GROUP BY ProductionID, MachineCode", self.rollback)
        self.assertIn(
            "CREATE UNIQUE INDEX UX_PressProduction_Production_Machine",
            self.rollback,
        )
        self.assertIn("BEGIN TRANSACTION", self.rollback)
        self.assertIn("ROLLBACK TRANSACTION", self.rollback)
        self.assertNotRegex(
            self.rollback,
            r"\bDELETE\s+FROM\s+dbo\.PressProduction\b",
        )
        self.assertNotRegex(
            self.rollback,
            r"\b(?:UPDATE|DELETE)\s+dbo\.EquipmentTimeEvent\b",
        )

    def test_context_captures_edit_and_unknown_legacy_shift_rules(self):
        self.assertIn("DEMO data", self.context)
        self.assertIn("แม้กรอก Counter/Curing แล้ว", self.context)
        self.assertIn("UPDATE `PressProductionID` เดิม", self.context)
        self.assertIn("คง `ShiftMasterID = NULL`", self.context)
        self.assertIn("ห้าม migration กำหนด Shift", self.context)
        self.assertIn("18 MANUAL `EquipmentTimeEvent` rows", self.context)


if __name__ == "__main__":
    unittest.main()
