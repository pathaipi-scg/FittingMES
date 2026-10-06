import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "sql" / "024_reject_module.sql"
ROLLBACK_PATH = ROOT / "sql" / "024_reject_module_rollback.sql"
REQUIREMENTS_PATH = ROOT / "md" / "REJECT_MODULE_REQUIREMENTS.md"


def _canonical_reasons():
    document = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    sections = (
        ("## 9. Special Ridge", "R1"),
        ("## 10. Prestige", "R2"),
        ("## 11. NeuFit / NeuStile + Oriental", "R3"),
    )
    reasons = []
    for heading, catalog_code in sections:
        start = document.index(heading)
        end = document.find("\n## ", start + len(heading))
        section = document[start:] if end < 0 else document[start:end]
        for line in section.splitlines():
            match = re.match(
                r"^\s*(R\d{3})\s{2,}(.+?)\s{2,}(PRESS|LINE)\s*$",
                line,
            )
            if match:
                reasons.append(
                    (catalog_code, match.group(1), match.group(2).strip(), match.group(3))
                )
    return reasons


def _migration_reason_seed(sql):
    match = re.search(
        r"INSERT INTO @ReasonSeed\s*\([^;]+?\)\s*VALUES(.*?);",
        sql,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("Reason seed block was not found")
    pattern = re.compile(
        r"\('([^']+)','([^']+)',N'((?:''|[^'])*)','(PRESS|LINE)',([01])\)"
    )
    return [
        (catalog, code, name.replace("''", "'"), scope)
        for catalog, code, name, scope, _is_other in pattern.findall(match.group(1))
    ]


def _table_definition(sql, table_name):
    match = re.search(
        rf"CREATE TABLE dbo\.{re.escape(table_name)}\s*\((.*?)\n    \);",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise AssertionError(f"CREATE TABLE dbo.{table_name} was not found")
    return match.group(1)


class RejectSchemaMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION_PATH.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK_PATH.read_text(encoding="utf-8")

    def test_canonical_reason_seed_is_complete_and_exact(self):
        canonical = _canonical_reasons()
        seeded = _migration_reason_seed(self.migration)
        self.assertEqual(len(canonical), 78)
        self.assertEqual(len(seeded), 78)
        self.assertEqual(seeded, canonical)
        self.assertEqual(len({reason[1] for reason in seeded}), 78)
        self.assertEqual(
            {code for _catalog, code, _name, _scope in seeded if code.endswith("99")},
            {"R199", "R299", "R399"},
        )
        self.assertEqual(
            {code for _catalog, code, _name, scope in seeded if code == "R319" and scope == "LINE"},
            {"R319"},
        )
        self.assertFalse(
            any(re.fullmatch(r"R(?:0[1-9]|1[0-9]|2[0-4]|99)", code) for _, code, _, _ in seeded)
        )

    def test_all_new_tables_follow_mandatory_identity_and_rectime_standard(self):
        tables = (
            "ShiftMaster",
            "RejectCatalog",
            "RejectSourceScope",
            "RejectReason",
            "RejectReasonProductFamily",
            "ProductionRejectEntry",
            "DepalletRejectEntry",
        )
        for table_name in tables:
            with self.subTest(table=table_name):
                definition = _table_definition(self.migration, table_name)
                self.assertRegex(
                    definition,
                    rf"\bid bigint IDENTITY\(1,1\) NOT NULL\s+CONSTRAINT PK_{table_name} PRIMARY KEY",
                )
                self.assertRegex(
                    definition,
                    rf"\bRectime datetime NOT NULL\s+CONSTRAINT DF_{table_name}_Rectime DEFAULT \(GETDATE\(\)\)",
                )

    def test_equipment_master_id_is_additive_and_preserves_code_primary_key(self):
        self.assertIn(
            "ALTER TABLE dbo.EquipmentMaster\n        ADD id bigint IDENTITY(1,1) NOT NULL;",
            self.migration,
        )
        self.assertIn(
            "CONSTRAINT UQ_EquipmentMaster_id UNIQUE (id)",
            self.migration,
        )
        self.assertIn("EquipmentCode", self.migration)
        self.assertIn("EquipmentCode key.", self.migration)
        self.assertNotRegex(self.migration, r"DROP\s+CONSTRAINT\s+PK_EquipmentMaster")
        self.assertNotRegex(self.migration, r"DROP\s+COLUMN\s+EquipmentCode")
        self.assertNotRegex(self.migration, r"ALTER\s+TABLE\s+dbo\.EquipmentLineMap")
        self.assertNotRegex(
            self.migration,
            r"DROP\s+CONSTRAINT\s+FK_(?:EquipmentLine|EquipmentStatus|EquipmentTime|PressProduct|PressProduction)",
        )
        self.assertIn("IF COL_LENGTH(N'dbo.EquipmentMaster', N'id') IS NOT NULL", self.migration)

    def test_shift_seed_uses_business_codes_not_generated_ids(self):
        self.assertIn(
            "INSERT INTO dbo.ShiftMaster (ShiftCode,ShiftName,IsActive)\n"
            "    VALUES ('1',N'Shift 1',1),('2',N'Shift 2',1);",
            self.migration,
        )
        self.assertNotRegex(
            self.migration,
            r"INSERT\s+INTO\s+dbo\.ShiftMaster\s*\([^)]*\bid\b",
        )
        self.assertNotRegex(self.migration, r"ShiftMaster\.id\s*=\s*[12]\b")

    def test_catalog_scope_family_and_other_seed_counts_are_guarded(self):
        self.assertIn("('R1',N'Special Ridge',1)", self.migration)
        self.assertIn("('R2',N'Prestige',1)", self.migration)
        self.assertIn("('R3',N'NeuFit / NeuStile + Oriental',1)", self.migration)
        self.assertIn("VALUES ('PRESS',N'PRESS',1),('LINE',N'LINE',1);", self.migration)
        self.assertIn("('R1','Special Ridge')", self.migration)
        self.assertIn("('R2','Prestige')", self.migration)
        self.assertIn("('R3','NeuFit / NeuStile')", self.migration)
        self.assertIn("('R3','Oriental')", self.migration)
        self.assertIn("HAVING COUNT(pf.ProductFamilyID) <> 1", self.migration)
        self.assertIn("(SELECT COUNT(*) FROM dbo.RejectReasonProductFamily) <> 102", self.migration)
        self.assertNotRegex(self.migration, r"ProductFamilyID\s*=\s*\d+")

    def test_new_entry_tables_are_workflow_owned_and_use_id_relationships(self):
        forbidden = (
            r"\bRejectOf\b",
            r"\bRejectOfID\b",
            r"\bDepalletID\b",
            r"\bProductCode\b",
            r"\bProductFamilyID\b",
            r"\bProductFamily\b",
            r"\bEquipmentCode\b",
            r"\bReasonCode\b",
            r"\bSourceScope\b",
            r"\bShift\b",
        )
        expected_foreign_keys = (
            r"FOREIGN KEY \(ShiftID\) REFERENCES dbo\.ShiftMaster\(id\)",
            r"FOREIGN KEY \(LineEquipmentID\) REFERENCES dbo\.EquipmentMaster\(id\)",
            r"FOREIGN KEY \(SourceEquipmentID\) REFERENCES dbo\.EquipmentMaster\(id\)",
            r"FOREIGN KEY \(RejectSourceScopeID\) REFERENCES dbo\.RejectSourceScope\(id\)",
            r"FOREIGN KEY \(ProductionID\) REFERENCES dbo\.ProductionLot\(ProductionID\)",
            r"FOREIGN KEY \(RejectReasonID\) REFERENCES dbo\.RejectReason\(id\)",
        )
        for table_name in ("ProductionRejectEntry", "DepalletRejectEntry"):
            with self.subTest(table=table_name):
                definition = _table_definition(self.migration, table_name)
                for pattern in forbidden:
                    self.assertNotRegex(definition, pattern)
                for pattern in expected_foreign_keys:
                    self.assertRegex(definition, pattern)
                self.assertIn("CHECK (Qty > 0)", definition)
                self.assertNotRegex(definition, r"\bUNIQUE\b")

    def test_reason_and_family_relationships_use_ids_not_business_codes(self):
        reason = _table_definition(self.migration, "RejectReason")
        mapping = _table_definition(self.migration, "RejectReasonProductFamily")
        self.assertIn("ReasonCode varchar(10) NOT NULL", reason)
        self.assertIn("UNIQUE (ReasonCode)", reason)
        self.assertIn("FOREIGN KEY (RejectCatalogID) REFERENCES dbo.RejectCatalog(id)", reason)
        self.assertIn(
            "FOREIGN KEY (RejectSourceScopeID) REFERENCES dbo.RejectSourceScope(id)",
            reason,
        )
        self.assertIn("RejectReasonID bigint NOT NULL", mapping)
        self.assertIn("ProductFamilyID int NOT NULL", mapping)
        self.assertIn("UNIQUE (RejectReasonID,ProductFamilyID)", mapping)
        self.assertIn("FOREIGN KEY (RejectReasonID) REFERENCES dbo.RejectReason(id)", mapping)
        self.assertIn(
            "FOREIGN KEY (ProductFamilyID) REFERENCES dbo.ProductFamilyMaster(ProductFamilyID)",
            mapping,
        )
        self.assertNotRegex(self.migration, r"FOREIGN KEY\s*\(\s*ReasonCode\s*\)")

    def test_non_pk_indexes_support_cal_and_common_filters(self):
        expected = (
            "IX_RejectReason_SourceCatalogActive",
            "IX_RejectReasonProductFamily_Family",
            "IX_ProductionRejectEntry_CAL",
            "IX_ProductionRejectEntry_ProductionID",
            "IX_ProductionRejectEntry_LineDate",
            "IX_ProductionRejectEntry_SourceDate",
            "IX_ProductionRejectEntry_Reason",
            "IX_DepalletRejectEntry_CAL",
            "IX_DepalletRejectEntry_ProductionID",
            "IX_DepalletRejectEntry_LineDate",
            "IX_DepalletRejectEntry_SourceDate",
            "IX_DepalletRejectEntry_Reason",
        )
        for index_name in expected:
            with self.subTest(index=index_name):
                self.assertIn(f"CREATE INDEX {index_name}", self.migration)

    def test_rollback_is_scoped_to_new_schema_and_equipment_id(self):
        for object_name in (
            "ProductionRejectEntry",
            "DepalletRejectEntry",
            "RejectReasonProductFamily",
            "RejectReason",
            "RejectSourceScope",
            "RejectCatalog",
            "ShiftMaster",
            "EquipmentMaster",
            "UQ_EquipmentMaster_id",
        ):
            self.assertIn(object_name, self.rollback)
        for legacy_name in (
            "WetReject",
            "WetRejectHistory",
            "WetRejectReasonMaster",
            "DepalletReject",
            "RejectReasonMaster",
            "wetReject1",
            "wetReject2",
            "EquipmentLineMap",
            "ProductionLot",
            "LoggerEvent",
            "EquipmentTimeEvent",
            "ProductionShiftRuleHistory",
        ):
            with self.subTest(legacy=legacy_name):
                self.assertNotRegex(
                    self.rollback,
                    rf"(?<![A-Za-z0-9_])(?:dbo\.)?{re.escape(legacy_name)}(?![A-Za-z0-9_])",
                )
        self.assertIn("another object still references EquipmentMaster.id", self.rollback)

    def test_migration_is_transactional_and_contains_no_legacy_reject_writes(self):
        self.assertIn("SET XACT_ABORT ON", self.migration)
        self.assertIn("BEGIN TRANSACTION", self.migration)
        self.assertIn("BEGIN CATCH", self.migration)
        self.assertIn("ROLLBACK TRANSACTION", self.migration)
        self.assertNotRegex(
            self.migration,
            r"(?:CREATE|ALTER|DROP)\s+(?:TABLE|VIEW|PROCEDURE)\s+dbo\.(?:WetReject|DepalletReject|RejectReasonMaster|WetRejectReasonMaster|wetReject1|wetReject2)\b",
        )


if __name__ == "__main__":
    unittest.main()
