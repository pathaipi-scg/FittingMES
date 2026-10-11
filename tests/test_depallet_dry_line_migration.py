import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "sql" / "028_depallet_dry_line_equipment.sql").read_text(
    encoding="utf-8"
)
ROLLBACK = (
    ROOT / "sql" / "028_depallet_dry_line_equipment_rollback.sql"
).read_text(encoding="utf-8")


class DepalletDryLineMigrationTests(unittest.TestCase):
    def test_mapping_table_uses_id_first_identity_and_required_timestamp(self):
        definition = re.search(
            r"CREATE TABLE dbo\.DepalletLineEquipmentMap\s*\((.*?)\n    \);",
            MIGRATION,
            re.DOTALL,
        ).group(1)
        self.assertRegex(
            definition,
            r"id bigint IDENTITY\(1,1\) NOT NULL\s+"
            r"CONSTRAINT PK_DepalletLineEquipmentMap PRIMARY KEY",
        )
        self.assertRegex(
            definition,
            r"Rectime datetime NOT NULL\s+"
            r"CONSTRAINT DF_DepalletLineEquipmentMap_Rectime DEFAULT \(GETDATE\(\)\)",
        )
        self.assertIn(
            "FOREIGN KEY (EquipmentID)\n"
            "                REFERENCES dbo.EquipmentMaster(id)",
            definition,
        )
        self.assertIn("UNIQUE (MainMachineMcId,SubMcId,InstanceNo)", definition)

    def test_migration_allows_distinct_dry_line_without_touching_line_map(self):
        self.assertIn(
            "CHECK (EquipmentType IN ('LINE','PRESS','DRY_LINE'))", MIGRATION
        )
        self.assertIn("EquipmentType='DRY_LINE'", MIGRATION)
        self.assertIn("Equipment=N'LINE(dry)'", MIGRATION)
        self.assertIn("Machine=N'LINE(dry)'", MIGRATION)
        self.assertIn("McId=@MainMachineId", MIGRATION)
        self.assertIn("sub_machine.McId", MIGRATION)
        self.assertNotIn("EquipmentLineMap", MIGRATION)
        self.assertIn("SET LineEquipmentID=@DryLineId", MIGRATION)
        self.assertIn("WHERE LineEquipmentID=@LegacyLineId", MIGRATION)
        self.assertNotIn("UPDATE dbo.ProductionRejectEntry", MIGRATION)
        self.assertNotIn("ProductionData", MIGRATION)
        self.assertNotIn("PressProduction", MIGRATION)
        self.assertNotIn("LoggerEvent", MIGRATION)
        self.assertNotIn("EquipmentTimeEvent", MIGRATION)

    def test_seed_is_dynamic_and_does_not_use_opaque_equipment_ids(self):
        self.assertIn("sub_machine.No BETWEEN 1 AND main_machine.No", MIGRATION)
        self.assertIn("CONCAT('LINE_DRY',sub_machine.No)", MIGRATION)
        self.assertNotRegex(MIGRATION, r"EquipmentID\s*=\s*\d+")
        self.assertNotRegex(MIGRATION, r"(?:McId|SubMcId)\s*=\s*[0-9]+")

    def test_repeated_execution_is_a_validated_noop(self):
        self.assertIn("IF OBJECT_ID(N'dbo.DepalletLineEquipmentMap', N'U') IS NULL", MIGRATION)
        self.assertIn(
            "WHERE NOT EXISTS (\n"
            "        SELECT 1\n"
            "        FROM dbo.EquipmentMaster AS equipment WITH",
            MIGRATION,
        )
        self.assertIn("WHERE mapping.IsActive<>1 OR mapping.EquipmentID<>equipment.id", MIGRATION)
        self.assertIn("sp_getapplock", MIGRATION)
        self.assertNotIn("already exists; migration refused", MIGRATION)

    def test_inconsistent_states_fail_explicitly(self):
        for code in (
            52806, 52807, 52808, 52810, 52817, 52820, 52823, 52825,
            52826, 52829, 52831,
        ):
            self.assertIn(f"THROW {code}", MIGRATION)

    def test_demo_reassignment_is_limited_and_idempotent(self):
        self.assertIn("DepalletRejectLineMigrationAudit", MIGRATION)
        self.assertIn("CONSTRAINT UQ_DepalletRejectLineMigrationAudit_Entry", MIGRATION)
        self.assertIn("@TotalDepalletCount <> 4", MIGRATION)
        self.assertIn("@LegacyLineCount=4 AND @DryLineCount=0", MIGRATION)
        self.assertIn("@LegacyLineCount=0 AND @DryLineCount=4", MIGRATION)
        self.assertIn("IF @@ROWCOUNT <> 4", MIGRATION)
        self.assertIn("EquipmentCode='LINE2' AND EquipmentType='LINE'", MIGRATION)
        self.assertEqual(
            MIGRATION.count("SET LineEquipmentID=@DryLineId"),
            1,
        )

    def test_rollback_preserves_historical_rows(self):
        self.assertIn("Rollback refused", ROLLBACK)
        self.assertIn("DepalletRejectEntry", ROLLBACK)
        self.assertIn("DepalletRejectLineMigrationAudit", ROLLBACK)
        self.assertIn("SET LineEquipmentID=audit.OriginalLineEquipmentID", ROLLBACK)
        self.assertNotIn("DELETE FROM dbo.DepalletRejectEntry", ROLLBACK)
        self.assertIn("DROP TABLE dbo.DepalletRejectLineMigrationAudit", ROLLBACK)
        self.assertIn("DROP TABLE dbo.DepalletLineEquipmentMap", ROLLBACK)


if __name__ == "__main__":
    unittest.main()
