import os
import unittest
from decimal import Decimal

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

    def test_usage_and_production_inputs_aggregate_once_across_shift_periods(self):
        self.cursor.execute("""
            SELECT lot.ProdDate,lot.ShiftMasterID
            FROM dbo.ProductionLot AS lot
            WHERE lot.ProductionID=990010
        """)
        production_date, shift_master_id = self.cursor.fetchone()
        self.cursor.execute("""
            SELECT SUM(CounterQty),SUM(CuringQty),SUM(LotCount),COUNT_BIG(*)
            FROM dbo.vw_DailyProductionQtyLogical
            WHERE ReportDate=? AND ShiftMasterID=?
        """, production_date, shift_master_id)
        self.assertEqual(tuple(self.cursor.fetchone()), (300, 240, 2, 1))

        self.cursor.execute("""
            SELECT ShiftMasterID,RawQty,CounterQty,CuringQty,LotCount,
                   QtyPer1000Counter,QtyPer1000Curing
            FROM dbo.vw_DailyMaterialUsageCalcLogical
            WHERE MaterialUsageID=990001
        """)
        usage = self.cursor.fetchone()
        self.assertIsNotNone(usage)
        self.assertEqual(usage[0], shift_master_id)
        self.assertEqual(Decimal(str(usage[1])), Decimal("12.500"))
        self.assertEqual(tuple(usage[2:5]), (300, 240, 2))
        self.assertEqual(Decimal(str(usage[5])), Decimal("41.667"))
        self.assertEqual(Decimal(str(usage[6])), Decimal("52.083"))

    def test_oee_inputs_are_aggregated_across_periods_before_rates(self):
        self.cursor.execute("""
            SELECT SUM(assignment.CounterQty),SUM(assignment.CuringQty),
                   SUM(DATEDIFF_BIG(SECOND,assignment.ProductionStartTime,
                                    assignment.ProductionEndTime))/60.0,
                   SUM(ISNULL(assignment.DowntimeMinutes,0))
            FROM dbo.PressProduction AS assignment
            WHERE assignment.ProductionID IN (990010,990011)
              AND assignment.ShiftMasterID=(
                  SELECT ShiftMasterID FROM dbo.ProductionLot
                  WHERE ProductionID=990010)
        """)
        counter, curing, actual_minutes, downtime = self.cursor.fetchone()
        self.assertEqual((counter, curing), (300, 240))
        self.assertEqual(Decimal(str(actual_minutes)), Decimal("600.000000"))
        self.assertEqual(Decimal(str(downtime)), Decimal("0.00"))

        availability = (Decimal(str(actual_minutes)) - Decimal(str(downtime))) / Decimal(str(actual_minutes))
        quality = Decimal(curing) / Decimal(counter)
        performance = Decimal(counter) / (Decimal("1") * (Decimal(str(actual_minutes)) - Decimal(str(downtime))))
        self.assertEqual(availability, Decimal("1"))
        self.assertEqual(quality, Decimal("0.8"))
        self.assertEqual(performance, Decimal("0.5"))
        self.assertEqual(availability * quality * performance, Decimal("0.40"))

    def test_reject_and_logger_inputs_are_not_duplicated_by_period_count(self):
        self.cursor.execute("""
            SELECT lot.ProdDate,lot.Shift
            FROM dbo.ProductionLot AS lot
            WHERE lot.ProductionID=990010
        """)
        production_date, shift_code = self.cursor.fetchone()
        self.cursor.execute("""
            SELECT SUM(RejectQty),COUNT_BIG(*)
            FROM dbo.ProductionRejectEntry
            WHERE ProductionDate=? AND Shift=?
        """, production_date, shift_code)
        self.assertEqual(tuple(self.cursor.fetchone()), (5, 1))
        self.cursor.execute("""
            SELECT SUM(DurationMin),COUNT_BIG(*)
            FROM dbo.LoggerEvent
            WHERE ProductionDate=?
        """, production_date)
        self.assertEqual(tuple(self.cursor.fetchone()), (15, 1))
        self.cursor.execute("""
            SELECT SUM(RejectQty),COUNT_BIG(*)
            FROM dbo.DepalletRejectEntry
            WHERE ProductionDate=? AND Shift=?
        """, production_date, shift_code)
        self.assertEqual(tuple(self.cursor.fetchone()), (7, 1))

    def test_cutoff_and_historical_production_dates_remain_preserved(self):
        self.cursor.execute("""
            SELECT
                (SELECT DayStartTime FROM dbo.ProductionDayRuleHistory
                 WHERE EffectiveFromDate='2026-01-01'),
                (SELECT CutoffTime FROM dbo.ProductionDateCutoffVersion
                 WHERE EffectiveFromDate=(SELECT MIN(EffectiveFromDate)
                                          FROM dbo.ProductionDateCutoffVersion)),
                (SELECT ProdDate FROM dbo.ProductionLot WHERE ProductionID=990001),
                (SELECT ProductionDateCutoffSnapshot
                 FROM dbo.ProductionLot WHERE ProductionID=990012),
                (SELECT PeriodStartTimeSnapshot FROM dbo.PressProduction
                 WHERE ProductionID=990012)
        """)
        historical_start, cutoff, historical_date, saved_cutoff, period_start = self.cursor.fetchone()
        self.assertEqual(str(historical_start), "08:00:00")
        self.assertEqual(str(cutoff), "07:00:00")
        self.assertEqual(str(historical_date), "2026-09-03")
        self.assertEqual(str(saved_cutoff), "07:00:00")
        self.assertEqual(str(period_start), "04:00:00")


if __name__ == "__main__":
    unittest.main()
