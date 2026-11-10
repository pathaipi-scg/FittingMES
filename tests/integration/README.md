# Migration 028 SQL Server integration tests

These tests never create a database. The test connection hard-codes
`SB23_TEST` and refuses to continue unless
`FITTINGMES_028_TEST_AUTHORIZED=1` and dedicated test credentials are supplied.
When explicitly enabled, the suite creates only the minimal synthetic schema
in that database, applies Migration 028 there, and runs its DML and concurrency
tests. Normal Python test runs skip the integration suite.

The configured connection reached `DCDLGYF3\SQLEXPRESS` / `SB23` as login
`sb23`, using SQL Server Express 2019. That login is a member of both
`db_owner` and `db_datawriter`, but it is not a server `dbcreator` or
`sysadmin`. `SB23_TEST` was not visible (`DB_ID` returned NULL), and free
volume space could not be queried because the login lacks `VIEW SERVER STATE`.
Do not use the application login to create the test database. A DBA must
confirm available storage, select isolated data/log paths, and create
`SB23_TEST` after explicit authorization.

## Database creation (DBA only, after authorization)

Run on the SQL Server instance in an SSMS window connected to `master`. Replace
the path placeholders with DBA-approved paths on a volume with sufficient free
space. This command has **not** been run:

```sql
IF DB_ID(N'SB23_TEST') IS NOT NULL
    THROW 52920, 'SB23_TEST already exists; refusing to reuse it.', 1;

CREATE DATABASE [SB23_TEST]
ON PRIMARY (
    NAME = N'SB23_TEST',
    FILENAME = N'<approved-data-path>\SB23_TEST.mdf',
    SIZE = 128MB,
    MAXSIZE = 2GB,
    FILEGROWTH = 64MB
)
LOG ON (
    NAME = N'SB23_TEST_log',
    FILENAME = N'<approved-log-path>\SB23_TEST_log.ldf',
    SIZE = 64MB,
    MAXSIZE = 1GB,
    FILEGROWTH = 64MB
);
```

Create a dedicated SQL login and grant it access only to `SB23_TEST`; do not
reuse `sb23`. Store its password in the local process environment, not source
control or a command-line argument:

```sql
CREATE LOGIN [FittingMES_028_Test]
    WITH PASSWORD = '<set-through-the-DBA-secret-management-process>',
         CHECK_POLICY = ON;
GO
USE [SB23_TEST];
CREATE USER [FittingMES_028_Test] FOR LOGIN [FittingMES_028_Test];
ALTER ROLE [db_owner] ADD MEMBER [FittingMES_028_Test];
GO
```

The test principal needs schema DDL and DML rights only in the isolated
database to create synthetic fixtures and run rollback tests.

## Setup and execution

The runner installs
[`028_press_production_interval_overlap_test_setup.sql`](../sql/028_press_production_interval_overlap_test_setup.sql)
if the minimal schema is absent. It seeds only synthetic historical rows:
one unresolved active row and one overlapping pair. The runner then sets a
session marker and applies the same Migration 028 script. The migration and
rollback guards accept `SB23_TEST` only when that marker is present.

From the repository root in PowerShell, after the DBA creates the database and
the test login is provisioned. The runner reads `SQL_SERVER` from the existing
configuration and uses the dedicated `SQL_TEST_USER`/`SQL_TEST_PASS` values:

```powershell
$env:SQL_TEST_USER = 'FittingMES_028_Test'
$env:SQL_TEST_PASS = '<retrieve-from-secret-management>'
$env:FITTINGMES_028_TEST_AUTHORIZED = '1'
python -m pytest tests/integration/test_migration_028_sqlserver.py -v
```

Unset the opt-in immediately afterward:

```powershell
Remove-Item Env:FITTINGMES_028_TEST_AUTHORIZED
Remove-Item Env:SQL_TEST_USER
Remove-Item Env:SQL_TEST_PASS
```

The suite covers adjacent same-key intervals, Press and Mould overlap
rejection, cross-midnight adjacency within one Production Day, unresolved
historical rows, unrelated versus allocation-relevant updates, concurrent
direct INSERT/UPDATE, application-lock serialization, and rollback guards.
Concurrent direct-SQL tests accept either an overlap rejection or SQL Server
deadlock error 1205 for a losing transaction, then verify that no overlapping
pair committed. This is not a claim that mixed application/direct writers are
deadlock-free.

## Rollback and cleanup

The integration tests roll back ordinary fixtures and clean up rows committed
by their concurrency cases. The synthetic seed rows and the test schema remain
in `SB23_TEST`. The rollback integration test verifies the rollback script
inside a transaction and rolls that test transaction back; it does not leave
the old unique index installed.

For a manual schema rollback, connect to `SB23_TEST` in SSMS, enable SQLCMD
Mode, and run in the same query window/session:

```sql
EXEC sys.sp_set_session_context
    @key=N'FittingMES_028_TestRun',
    @value=N'1',
    @read_only=1;
GO
:r <repository-root>\sql\028_press_production_interval_overlap_rollback.sql
```

The rollback script refuses to run while active sequential rows share a
ProductionID/Press/Shift key. The integration suite tests both that refusal and
a successful rollback whose DDL is then reverted by the test transaction.

To remove only the test schema, connect to `SB23_TEST` in SSMS and execute
[`028_press_production_interval_overlap_test_cleanup.sql`](../sql/028_press_production_interval_overlap_test_cleanup.sql).
It refuses to run in any database other than `SB23_TEST`.

To remove the entire test database, first verify all test results have been
collected and connect to `master`:

```sql
IF DB_NAME() <> N'master'
    THROW 52921, 'Connect to master before dropping SB23_TEST.', 1;
IF DB_ID(N'SB23_TEST') IS NULL
    THROW 52922, 'SB23_TEST does not exist.', 1;

ALTER DATABASE [SB23_TEST] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
DROP DATABASE [SB23_TEST];
```

Do not run the production rollback script against SB23 as part of this test
workflow. In either database, rollback is refused if sequential active rows
share a ProductionID/Press/Shift key; those rows must not be deleted to force
rollback.

## Writer-access findings and limitations

Read-only metadata exposed these principals:

- `sb23`: the configured FittingMES connection login; its database user is in
  `db_owner` and `db_datawriter`, and `HAS_PERMS_BY_NAME` confirmed INSERT,
  UPDATE, CONTROL, and ALTER on `dbo.PressProduction`.
- `sa`: the only visible server `sysadmin`; it can bypass database-level
  restrictions.
- `qa`: a database user with no membership in `db_owner`, `db_datawriter`, or
  `db_ddladmin`, and no explicit database/object write grants were visible.

No explicit `PressProduction` DML grants or write modules were found. The
server denied `VIEW SERVER STATE`, so active sessions and all application
connections could not be enumerated. Multiple applications using the `sb23`
credential cannot be distinguished from this metadata.

Preventing direct writers requires more than the trigger: the current
application itself issues direct table DML and its login is `db_owner`. A
genuine restriction would require moving writes behind a controlled stored
procedure or equivalent writer that takes the resource locks before DML, then
removing direct INSERT/UPDATE rights from the application principal. `sa`
remains an administrative bypass. Until that is implemented or SQL Server
concurrency testing validates the mixed-writer behavior, no deadlock-free
claim is made.
