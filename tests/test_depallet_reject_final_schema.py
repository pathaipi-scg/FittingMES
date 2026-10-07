import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sql" / "026_depallet_reject_final.sql"


def table_definition(sql, name):
    match = re.search(
        rf"CREATE TABLE dbo\.{re.escape(name)}\s*\((.*?)\n    \);",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise AssertionError(f"CREATE TABLE dbo.{name} was not found")
    return match.group(1)


class DepalletRejectFinalSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.raw = table_definition(cls.sql, "DepalletRejectEntry")
        cls.header = table_definition(cls.sql, "DepalletRejectFinal")
        cls.detail = table_definition(cls.sql, "DepalletRejectFinalDetail")

    def test_raw_entry_is_run_keyed_with_nullable_source(self):
        self.assertIn("SourceEquipmentID bigint NULL", self.raw)
        self.assertIn("FOREIGN KEY (SourceEquipmentID) REFERENCES dbo.EquipmentMaster(id)", self.raw)
        self.assertIn("FOREIGN KEY (LineEquipmentID) REFERENCES dbo.EquipmentMaster(id)", self.raw)
        self.assertIn("ADD DepalletID '", self.sql)
        self.assertIn("QUOTENAME(@DepalletIDType) + N' NOT NULL;'", self.sql)
        self.assertIn("FOREIGN KEY (DepalletID) REFERENCES dbo.Depallet(DepalletID)", self.sql)
        self.assertIn("ON dbo.DepalletRejectEntry (DepalletID,ShiftID)", self.sql)
        self.assertIn("SourceEquipmentID,RejectReasonID", self.sql)

    def test_final_header_is_unique_per_depallet_run(self):
        self.assertIn("UNIQUE (DepalletID)", self.sql)
        self.assertNotIn("UNIQUE (ProductionID)", self.header)
        self.assertIn("FOREIGN KEY (DepalletID)", self.sql)
        self.assertIn("ADD DepalletID '", self.sql)
        self.assertIn("ProductionID bigint NOT NULL", self.header)
        self.assertIn("TotalRejectAtSave bigint NOT NULL", self.header)
        self.assertIn("RawTotalQtyAtSave bigint NOT NULL", self.header)
        self.assertIn("FinalClassifiedQtyAtSave bigint NOT NULL", self.header)
        self.assertIn("UnclassifiedQtyAtSave bigint NOT NULL", self.header)

    def test_detail_is_reason_normalized_and_unique(self):
        self.assertIn("RejectReasonID bigint NOT NULL", self.detail)
        self.assertIn("UNIQUE (DepalletRejectFinalID,RejectReasonID)", self.detail)
        self.assertIn("REFERENCES dbo.RejectReason(id)", self.detail)
        self.assertIn("RawQtyAtSave bigint NOT NULL", self.detail)
        self.assertIn("FinalQty bigint NOT NULL", self.detail)
        self.assertIn("RawQtyAtSave >= 0 AND FinalQty >= 0", self.detail)

    def test_migration_does_not_touch_production_or_legacy_reject_data(self):
        self.assertNotIn("ProductionRejectEntry", self.sql)
        self.assertNotIn("ProductionRejectFinal", self.sql.replace(
            "DepalletRejectFinal", ""
        ))
        self.assertNotIn("dbo.DepalletReject ", self.sql)
        self.assertNotIn("UNKNOWN", self.sql)
        self.assertIn(
            "@DepalletIDType IS NULL OR @DepalletIDType NOT IN (N'int',N'bigint')",
            self.sql,
        )
        self.assertIn("DB_NAME() <> N'SB23'", self.sql)


if __name__ == "__main__":
    unittest.main()
