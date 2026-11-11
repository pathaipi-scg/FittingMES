import os
import unittest

import pyodbc

from app.database import env_bool, get_sql_driver


AUTHORIZED = os.getenv("FITTINGMES_031_TEST_AUTHORIZED") == "1"


def _odbc_value(value):
    return "{" + value.replace("}", "}}") + "}"


def _connect_test_database():
    server = os.getenv("SQL_SERVER", "").strip()
    username = os.getenv("SQL_TEST_USER", "").strip()
    password = os.getenv("SQL_TEST_PASS", "")
    if not server or not username or not password:
        raise RuntimeError(
            "Set SQL_SERVER and dedicated SQL_TEST_USER/SQL_TEST_PASS credentials."
        )
    connection_string = (
        f"DRIVER={{{get_sql_driver()}}};"
        f"SERVER={_odbc_value(server)};"
        "DATABASE={SB23_TEST};"
        f"UID={_odbc_value(username)};"
        f"PWD={_odbc_value(password)};"
        f"Encrypt={'yes' if env_bool('SQL_ENCRYPT', False) else 'no'};"
        f"TrustServerCertificate={'yes' if env_bool('SQL_TRUST_SERVER_CERTIFICATE', True) else 'no'};"
    )
    connection = pyodbc.connect(connection_string, timeout=5)
    cursor = connection.cursor()
    cursor.execute("""
        SELECT DB_NAME(), @@SERVERNAME,
               CAST(CONNECTIONPROPERTY('local_net_address') AS nvarchar(128))
    """)
    database_name, server_name, local_address = cursor.fetchone()
    if (
        database_name != "SB23_TEST"
        or server_name != "DCDLGYF3\\SQLEXPRESS"
        or local_address != "10.28.254.3"
    ):
        connection.close()
        raise RuntimeError(
            "Refusing logical Shift integration tests unless connected to "
            "SB23_TEST on DCDLGYF3\\SQLEXPRESS (10.28.254.3)."
        )
    return connection


@unittest.skipUnless(
    AUTHORIZED,
    "Set FITTINGMES_031_TEST_AUTHORIZED=1 only for an approved isolated SB23_TEST database.",
)
class LogicalShiftReportingSqlServerTests(unittest.TestCase):
    def setUp(self):
        self.connection = _connect_test_database()
        self.cursor = self.connection.cursor()

    def tearDown(self):
        self.connection.close()

    def test_versioned_logical_shift_views_and_identity_columns_exist(self):
        self.cursor.execute("""
            SELECT
                OBJECT_ID(N'dbo.vw_DailyProductionQtyLogical', N'V'),
                OBJECT_ID(N'dbo.vw_DailyMaterialUsageLogical', N'V'),
                OBJECT_ID(N'dbo.vw_DailyMaterialUsageCalcLogical', N'V'),
                COL_LENGTH(N'dbo.DailyMaterialUsage', N'ShiftMasterID'),
                COL_LENGTH(N'dbo.LoggerEvent', N'ShiftMasterID'),
                COL_LENGTH(N'dbo.ProductionRejectEntry', N'ShiftCodeSnapshot'),
                COL_LENGTH(N'dbo.DepalletRejectEntry', N'ShiftCodeSnapshot')
        """)
        self.assertTrue(all(value is not None for value in self.cursor.fetchone()))

    def test_logical_production_view_preserves_daily_totals_without_duplication(self):
        self.cursor.execute("""
            WITH SourceTotals AS (
                SELECT lot.ProdDate AS ReportDate,
                       SUM(CONVERT(bigint,data.CounterQty)) AS CounterQty,
                       SUM(CONVERT(bigint,data.CuringQty)) AS CuringQty,
                       COUNT_BIG(*) AS LotCount
                FROM dbo.ProductionLot AS lot
                JOIN dbo.ProductionData AS data
                  ON data.ProductionID=lot.ProductionID
                WHERE lot.IsActive=1
                GROUP BY lot.ProdDate
            ),
            LogicalTotals AS (
                SELECT ReportDate,SUM(CounterQty) AS CounterQty,
                       SUM(CuringQty) AS CuringQty,SUM(LotCount) AS LotCount
                FROM dbo.vw_DailyProductionQtyLogical
                GROUP BY ReportDate
            )
            SELECT COUNT_BIG(*)
            FROM SourceTotals AS source
            FULL OUTER JOIN LogicalTotals AS logical
              ON logical.ReportDate=source.ReportDate
            WHERE source.ReportDate IS NULL OR logical.ReportDate IS NULL
               OR source.CounterQty<>logical.CounterQty
               OR source.CuringQty<>logical.CuringQty
               OR source.LotCount<>logical.LotCount
        """)
        self.assertEqual(self.cursor.fetchone()[0], 0)

    def test_multiple_scheduled_periods_share_one_logical_report_group(self):
        self.cursor.execute("""
            SELECT TOP (1) lot.ProdDate,assignment.ShiftMasterID
            FROM dbo.PressProduction AS assignment
            JOIN dbo.ProductionLot AS lot
              ON lot.ProductionID=assignment.ProductionID
             AND lot.IsActive=1
            WHERE assignment.ShiftMasterID IS NOT NULL
              AND assignment.ShiftPeriodID IS NOT NULL
            GROUP BY lot.ProdDate,assignment.ShiftMasterID
            HAVING COUNT(DISTINCT assignment.ShiftPeriodID)>1
            ORDER BY lot.ProdDate,assignment.ShiftMasterID
        """)
        candidate = self.cursor.fetchone()
        if candidate is None:
            self.skipTest("SB23_TEST has no production date with assignments in multiple periods of one Shift.")
        self.cursor.execute("""
            SELECT COUNT_BIG(*)
            FROM dbo.vw_DailyProductionQtyLogical
            WHERE ReportDate=? AND ShiftMasterID=?
        """, candidate[0], candidate[1])
        self.assertEqual(self.cursor.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
