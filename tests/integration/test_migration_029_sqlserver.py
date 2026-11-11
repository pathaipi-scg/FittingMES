import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
import re
import threading
import unittest
import uuid

import pyodbc

from app.database import env_bool, get_sql_driver


ROOT = Path(__file__).resolve().parents[2]
SETUP_SQL = ROOT / "tests" / "sql" / "029_press_production_interval_overlap_test_setup.sql"
MIGRATION_SQL = ROOT / "sql" / "029_press_production_interval_overlap.sql"
ROLLBACK_SQL = ROOT / "sql" / "029_press_production_interval_overlap_rollback.sql"
AUTHORIZED = os.getenv("FITTINGMES_029_TEST_AUTHORIZED") == "1"


def _batches(script):
    return [
        batch.strip()
        for batch in re.split(r"(?im)^\s*GO\s*$", script)
        if batch.strip()
    ]


def _run_script(connection, path):
    cursor = connection.cursor()
    for batch in _batches(path.read_text(encoding="utf-8")):
        cursor.execute(batch)
    return cursor


def _odbc_value(value):
    return "{" + value.replace("}", "}}") + "}"


def _connect_test_database(autocommit=False):
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
    connection = pyodbc.connect(
        connection_string, timeout=5, autocommit=autocommit
    )
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
            "Refusing SQL Server integration tests unless connected to "
            "SB23_TEST on DCDLGYF3\\SQLEXPRESS (10.28.254.3)."
        )
    cursor.execute("""
        EXEC sys.sp_set_session_context
            @key=N'FittingMES_029_TestRun',
            @value=N'1',
            @read_only=1
    """)
    return connection


def _production_id():
    return 1_000_000_000 + uuid.uuid4().int % 1_000_000_000


@unittest.skipUnless(
    AUTHORIZED,
    "Set FITTINGMES_029_TEST_AUTHORIZED=1 only after SB23_TEST is DBA-created and approved.",
)
class Migration029SqlServerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        connection = _connect_test_database(autocommit=True)
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT OBJECT_ID(N'dbo.PressProduction', N'U')")
            if cursor.fetchone()[0] is None:
                _run_script(connection, SETUP_SQL)

            cursor.execute(
                "SELECT OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR')"
            )
            if cursor.fetchone()[0] is None:
                _run_script(connection, MIGRATION_SQL)

            cursor.execute("""
                SELECT
                    OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR'),
                    (SELECT COUNT(*) FROM sys.indexes
                     WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
                       AND name=N'IX_PressProduction_ActiveMachineInterval'),
                    (SELECT COUNT(*) FROM sys.indexes
                     WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
                       AND name=N'IX_PressProduction_ActiveMouldInterval')
            """)
            trigger_id, press_index_count, mould_index_count = cursor.fetchone()
            if not trigger_id or press_index_count != 1 or mould_index_count != 1:
                raise RuntimeError("SB23_TEST is not in the expected Press interval Migration 029 state.")
        finally:
            connection.close()

    def setUp(self):
        self.connection = _connect_test_database()
        self.cursor = self.connection.cursor()
        self._test_production_ids = []

    def tearDown(self):
        self.connection.rollback()
        self.connection.close()
        self._cleanup_lots(self._test_production_ids)

    def _add_lot(self, production_date=date(2026, 11, 7)):
        production_id = _production_id()
        self.cursor.execute(
            "INSERT INTO dbo.ProductionLot (ProductionID, LotNo, ProdDate, IsActive) "
            "VALUES (?, ?, ?, 1)",
            production_id, f"TEST028_{production_id}", production_date,
        )
        self._test_production_ids.append(production_id)
        return production_id

    def _add_assignment(
        self, production_id, machine, mould, start, end, shift=1
    ):
        self.cursor.execute("""
            INSERT INTO dbo.PressProduction
                (ProductionID, MachineCode, MouldID, ShiftMasterID,
                 ProductionStartTime, ProductionEndTime)
            OUTPUT INSERTED.PressProductionID
            VALUES (?, ?, ?, ?, ?, ?)
        """, production_id, machine, mould, shift, start, end)
        return int(self.cursor.fetchone()[0])

    @staticmethod
    def _cleanup_lots(production_ids):
        if not production_ids:
            return
        connection = _connect_test_database()
        try:
            cursor = connection.cursor()
            placeholders = ",".join("?" for _ in production_ids)
            cursor.execute(
                f"DELETE FROM dbo.PressProduction WHERE ProductionID IN ({placeholders})",
                *production_ids,
            )
            cursor.execute(
                f"DELETE FROM dbo.ProductionLot WHERE ProductionID IN ({placeholders})",
                *production_ids,
            )
            connection.commit()
        finally:
            connection.close()

    def _assert_database_error(self, code, operation):
        with self.assertRaises(pyodbc.Error) as raised:
            operation()
        self.assertIn(str(code), str(raised.exception))

    def test_adjacent_press_and_mould_intervals_are_allowed(self):
        production_id = self._add_lot()
        self._add_assignment(
            production_id, "F_SEQ", 91001,
            datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16),
        )
        self._add_assignment(
            production_id, "F_SEQ", 91001,
            datetime(2026, 11, 7, 16), datetime(2026, 11, 8, 1),
        )

    def test_overlapping_press_interval_is_rejected(self):
        production_id = self._add_lot()
        self._add_assignment(
            production_id, "F_PRESS_OVERLAP", 92001,
            datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16),
        )
        self._assert_database_error(
            52937,
            lambda: self._add_assignment(
                production_id, "F_PRESS_OVERLAP", 92002,
                datetime(2026, 11, 7, 15), datetime(2026, 11, 7, 18),
            ),
        )

    def test_overlapping_mould_interval_is_rejected_on_another_press(self):
        production_id = self._add_lot()
        self._add_assignment(
            production_id, "F_MOULD_A", 93001,
            datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16),
        )
        self._assert_database_error(
            52937,
            lambda: self._add_assignment(
                production_id, "F_MOULD_B", 93001,
                datetime(2026, 11, 7, 15), datetime(2026, 11, 7, 18),
            ),
        )

    def test_cross_midnight_sequential_boundary_is_allowed_in_one_production_day(self):
        production_id = self._add_lot()
        self._add_assignment(
            production_id, "F_OVERNIGHT", 94001,
            datetime(2026, 11, 7, 16), datetime(2026, 11, 8, 1),
        )
        self._add_assignment(
            production_id, "F_OVERNIGHT", 94001,
            datetime(2026, 11, 8, 1), datetime(2026, 11, 8, 4),
        )

    def test_actual_overlap_is_rejected_across_production_dates(self):
        first_production_id = self._add_lot(date(2026, 11, 6))
        second_production_id = self._add_lot(date(2026, 11, 7))
        self._add_assignment(
            first_production_id, "F_CROSS_DATE", 94003,
            datetime(2026, 11, 6, 23), datetime(2026, 11, 7, 9),
        )
        self._assert_database_error(
            52937,
            lambda: self._add_assignment(
                second_production_id, "F_CROSS_DATE", 94004,
                datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 10),
            ),
        )

    def test_unrelated_updates_to_historical_unresolved_and_overlapping_rows_work(self):
        self.cursor.execute("""
            UPDATE dbo.PressProduction
            SET DispatchQty=DispatchQty+1,
                DowntimeMinutes=ISNULL(DowntimeMinutes,0)+1,
                Remark=N'Unrelated synthetic update'
            WHERE ProductionID IN (990001, 990002)
        """)

    def test_relevant_update_cannot_leave_historical_active_interval_invalid(self):
        self._assert_database_error(
            52936,
            lambda: self.cursor.execute("""
                UPDATE dbo.PressProduction
                SET ProductionStartTime='2026-09-03T08:00:00'
                WHERE ProductionID=990001
            """),
        )

    def test_unresolved_historical_resource_still_blocks_new_same_day_allocation(self):
        production_id = self._add_lot(date(2026, 9, 3))
        self._assert_database_error(
            52937,
            lambda: self._add_assignment(
                production_id, "F_LEGACY_INVALID", 94002,
                datetime(2026, 9, 3, 8), datetime(2026, 9, 3, 12),
            ),
        )

    def _concurrent_insert_worker(self, barrier, production_id, machine, mould,
                                  start, end, application_locks=False):
        connection = _connect_test_database()
        cursor = connection.cursor()
        try:
            barrier.wait(timeout=15)
            for attempt in range(2):
                try:
                    if application_locks:
                        for resource in sorted((
                            f"FittingMES.PressMachine.{machine}",
                            f"FittingMES.PressMould.{mould}",
                        )):
                            cursor.execute("""
                                DECLARE @result int;
                                EXEC @result=sys.sp_getapplock
                                    @Resource=?, @LockMode='Exclusive',
                                    @LockOwner='Transaction', @LockTimeout=10000;
                                SELECT @result
                            """, resource)
                            if cursor.fetchone()[0] < 0:
                                raise RuntimeError(
                                    "Test writer could not acquire application lock."
                                )
                    self._add_assignment_on(
                        cursor, production_id, machine, mould, start, end
                    )
                    connection.commit()
                    return "committed"
                except pyodbc.Error as exc:
                    connection.rollback()
                    message = str(exc)
                    if "1205" in message and attempt == 0:
                        continue
                    if "52937" in message:
                        return "blocked"
                    if "1205" in message:
                        return "deadlock-unresolved"
                    return f"unexpected:{message}"
            return "retry-exhausted"
        finally:
            connection.close()

    @staticmethod
    def _add_assignment_on(cursor, production_id, machine, mould, start, end):
        cursor.execute("""
            INSERT INTO dbo.PressProduction
                (ProductionID, MachineCode, MouldID, ShiftMasterID,
                 ProductionStartTime, ProductionEndTime)
            VALUES (?, ?, ?, 1, ?, ?)
        """, production_id, machine, mould, start, end)

    def _concurrent_results(self, barrier, args):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self._concurrent_insert_worker, barrier, *item)
                for item in args
            ]
            return [future.result(timeout=30) for future in futures]

    def test_concurrent_direct_inserts_do_not_commit_overlapping_rows(self):
        production_id = self._add_lot()
        self.connection.commit()
        barrier = threading.Barrier(2)
        results = self._concurrent_results(barrier, [
            (production_id, "F_DIRECT_RACE", 95001,
             datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16), False),
            (production_id, "F_DIRECT_RACE", 95001,
             datetime(2026, 11, 7, 9), datetime(2026, 11, 7, 17), False),
        ])
        self.assertEqual(results.count("committed"), 1, results)
        self.assertEqual(results.count("blocked"), 1, results)
        self.cursor.execute("""
            SELECT COUNT(*) FROM dbo.PressProduction
            WHERE ProductionID=? AND MachineCode=N'F_DIRECT_RACE'
        """, production_id)
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_application_locks_serialize_concurrent_insert_requests(self):
        production_id = self._add_lot()
        self.connection.commit()
        barrier = threading.Barrier(2)
        results = self._concurrent_results(barrier, [
            (production_id, "F_APP_RACE", 96001,
             datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16), True),
            (production_id, "F_APP_RACE", 96001,
             datetime(2026, 11, 7, 9), datetime(2026, 11, 7, 17), True),
        ])
        self.assertEqual(results.count("committed"), 1, results)
        self.assertEqual(results.count("blocked"), 1, results)

    def test_concurrent_direct_updates_leave_no_overlapping_pair(self):
        production_ids = [self._add_lot(), self._add_lot()]
        press_ids = [
            self._add_assignment(
                production_ids[0], "F_UPDATE_A", 97001,
                datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 10),
            ),
            self._add_assignment(
                production_ids[1], "F_UPDATE_B", 97002,
                datetime(2026, 11, 7, 10), datetime(2026, 11, 7, 12),
            ),
        ]
        self.connection.commit()
        barrier = threading.Barrier(2)

        def update_worker(press_id):
            connection = _connect_test_database()
            cursor = connection.cursor()
            try:
                barrier.wait(timeout=15)
                for attempt in range(2):
                    try:
                        cursor.execute("""
                            UPDATE dbo.PressProduction
                            SET MachineCode=N'F_UPDATE_SHARED', MouldID=97999,
                                ProductionStartTime='2026-11-07T08:00:00',
                                ProductionEndTime='2026-11-07T12:00:00'
                            WHERE PressProductionID=?
                        """, press_id)
                        connection.commit()
                        return "committed"
                    except pyodbc.Error as exc:
                        connection.rollback()
                        message = str(exc)
                        if "1205" in message and attempt == 0:
                            continue
                        if "52937" in message:
                            return "blocked"
                        if "1205" in message:
                            return "deadlock-unresolved"
                        return f"unexpected:{message}"
                return "retry-exhausted"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(update_worker, press_ids))
        self.assertEqual(results.count("committed"), 1, results)
        self.assertEqual(results.count("blocked"), 1, results)
        self.cursor.execute("""
            SELECT COUNT(*) FROM dbo.PressProduction
            WHERE MachineCode=N'F_UPDATE_SHARED'
              AND ProductionStartTime='2026-11-07T08:00:00'
              AND ProductionEndTime='2026-11-07T12:00:00'
        """)
        self.assertEqual(self.cursor.fetchone()[0], 1)

    def test_rollback_refuses_when_sequential_active_identity_exists(self):
        production_id = self._add_lot()
        self._add_assignment(
            production_id, "F_ROLLBACK", 98001,
            datetime(2026, 11, 7, 8), datetime(2026, 11, 7, 16),
        )
        self._add_assignment(
            production_id, "F_ROLLBACK", 98001,
            datetime(2026, 11, 7, 16), datetime(2026, 11, 8, 1),
        )
        self._assert_database_error(
            52924,
            lambda: _run_script(self.connection, ROLLBACK_SQL),
        )

    def test_successful_rollback_script_can_be_rolled_back_as_a_test(self):
        connection = _connect_test_database(autocommit=True)
        cursor = connection.cursor()
        try:
            cursor.execute("BEGIN TRANSACTION")
            _run_script(connection, ROLLBACK_SQL)
            cursor.execute("""
                SELECT
                    OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR'),
                    (SELECT COUNT(*) FROM sys.indexes
                     WHERE object_id=OBJECT_ID(N'dbo.PressProduction')
                       AND name=N'UX_PressProduction_Production_Machine_ShiftActive')
            """)
            trigger_id, old_index_count = cursor.fetchone()
            self.assertIsNone(trigger_id)
            self.assertEqual(old_index_count, 1)
        finally:
            cursor.execute("IF XACT_STATE() <> 0 ROLLBACK TRANSACTION")
            cursor.execute("""
                SELECT OBJECT_ID(N'dbo.TR_PressProduction_PreventActiveIntervalOverlap', N'TR')
            """)
            self.assertIsNotNone(cursor.fetchone()[0])
            connection.close()


if __name__ == "__main__":
    unittest.main()
