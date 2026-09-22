import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv


# ---------------------------------------------------------
# Load .env from project root
# D:\AI\FittingMES\.env
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


def get_sql_driver() -> str:
    """
    SQL_DRIVER=AUTO:
        Prefer ODBC Driver 17 for SQL Server.
        Fall back to Driver 18 / Native Client / SQL Server.
    """

    configured = os.getenv("SQL_DRIVER", "AUTO").strip()

    if configured.upper() != "AUTO":
        return configured

    installed = pyodbc.drivers()

    preferred = [
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "SQL Server Native Client 11.0",
        "SQL Server",
    ]

    for driver in preferred:
        if driver in installed:
            return driver

    raise RuntimeError(
        "No supported SQL Server ODBC driver found. "
        f"Installed drivers: {installed}"
    )


def get_connection():
    server = os.getenv("SQL_SERVER", "").strip()
    database = os.getenv("SQL_DB", "").strip()
    username = os.getenv("SQL_USER", "").strip()
    password = os.getenv("SQL_PASS", "")
    driver = get_sql_driver()

    encrypt = env_bool("SQL_ENCRYPT", False)
    trust_cert = env_bool(
        "SQL_TRUST_SERVER_CERTIFICATE",
        True,
    )

    if not server:
        raise RuntimeError("SQL_SERVER is not configured")

    if not database:
        raise RuntimeError("SQL_DB is not configured")

    if not username:
        raise RuntimeError("SQL_USER is not configured")

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt={'yes' if encrypt else 'no'};"
        f"TrustServerCertificate={'yes' if trust_cert else 'no'};"
    )

    return pyodbc.connect(
        connection_string,
        timeout=5,
    )


def test_connection():
    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                @@SERVERNAME AS ServerName,
                DB_NAME() AS DatabaseName,
                CAST(SERVERPROPERTY('InstanceName') AS nvarchar(128))
                    AS InstanceName,
                GETDATE() AS SqlServerTime
            """
        )

        row = cursor.fetchone()

        return {
            "connected": True,
            "driver": get_sql_driver(),
            "server": row.ServerName,
            "instance": row.InstanceName,
            "database": row.DatabaseName,
            "sql_server_time": str(row.SqlServerTime),
        }

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        result = test_connection()

        print()
        print("FittingMES MSSQL Connection Test")
        print("--------------------------------")
        print(f"Connected : {result['connected']}")
        print(f"Driver    : {result['driver']}")
        print(f"Server    : {result['server']}")
        print(f"Instance  : {result['instance']}")
        print(f"Database  : {result['database']}")
        print(f"SQL Time  : {result['sql_server_time']}")
        print()

    except Exception as exc:
        print()
        print("FittingMES MSSQL Connection FAILED")
        print("----------------------------------")
        print(type(exc).__name__)
        print(str(exc))
        print()
        raise