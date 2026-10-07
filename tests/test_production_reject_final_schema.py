import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "sql" / "025_production_reject_final.sql"


def table_definition(sql, name):
    match = re.search(
        rf"CREATE TABLE dbo\.{re.escape(name)}\s*\((.*?)\n    \);",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise AssertionError(f"CREATE TABLE dbo.{name} was not found")
    return match.group(1)


class ProductionRejectFinalSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.header = table_definition(cls.sql, "ProductionRejectFinal")
        cls.detail = table_definition(cls.sql, "ProductionRejectFinalDetail")

    def test_header_is_unique_per_production_id_and_keeps_audit_totals(self):
        self.assertIn("ProductionID bigint NOT NULL", self.header)
        self.assertIn("UNIQUE (ProductionID)", self.header)
        self.assertIn("FOREIGN KEY (ProductionID)", self.header)
        for column in (
            "ProductionDate date",
            "Remark nvarchar(1000)",
            "TotalWetRejectAtSave bigint",
            "RawTotalQtyAtSave bigint",
            "FinalClassifiedQtyAtSave bigint",
            "UnclassifiedQtyAtSave bigint",
            "CreatedAt datetime2(3)",
            "UpdatedAt datetime2(3)",
        ):
            with self.subTest(column=column):
                self.assertIn(column, self.header)
        self.assertNotIn("ShiftID", self.header)

    def test_detail_is_normalized_unique_and_nonnegative(self):
        self.assertIn("ProductionRejectFinalID bigint NOT NULL", self.detail)
        self.assertIn("RejectReasonID bigint NOT NULL", self.detail)
        self.assertIn("RawQtyAtSave bigint NOT NULL", self.detail)
        self.assertIn("FinalQty bigint NOT NULL", self.detail)
        self.assertIn("UNIQUE (ProductionRejectFinalID,RejectReasonID)", self.detail)
        self.assertIn("REFERENCES dbo.ProductionRejectFinal(ProductionRejectFinalID)", self.detail)
        self.assertIn("REFERENCES dbo.RejectReason(id)", self.detail)
        self.assertIn("RawQtyAtSave >= 0 AND FinalQty >= 0", self.detail)

    def test_creation_script_does_not_migrate_or_touch_legacy_reject_data(self):
        self.assertNotIn("WetRejectHistory", self.sql)
        self.assertNotIn("WetRejectReasonMaster", self.sql)
        self.assertNotIn("INSERT INTO dbo.WetReject", self.sql)
        self.assertNotIn("INSERT INTO dbo.ProductionRejectEntry", self.sql)
        self.assertNotIn("ShiftID", self.sql)
        self.assertIn("BEGIN TRANSACTION", self.sql)
        self.assertIn("ROLLBACK TRANSACTION", self.sql)


if __name__ == "__main__":
    unittest.main()
