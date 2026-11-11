# Migration 029 Press interval SQL Server integration tests

These tests never create a database. The test connection hard-codes
`SB23_TEST` and refuses to continue unless
`FITTINGMES_029_TEST_AUTHORIZED=1` and dedicated test credentials are supplied.
When explicitly enabled, the suite creates only the minimal synthetic schema
in that database, applies Migration 029 there, and runs its DML and concurrency
tests. Normal Python test runs skip the integration suite.

## Migration identity and conditional deployment order

The original `028_depallet_dry_line_equipment.sql` is Migration 028 and is
already applied on SB23. Its live mapping/audit schema and four matching
audited Depallet row assignments were verified read-only. That deployed
identity must remain 028. The new Press interval migration was renumbered to
029 to resolve the filename collision; the new Shift Period/Cutoff migration
is 030 and logical reporting is 031.

| Order | Migration | Status from current schema |
|---|---|---|
| 027 | Shift-aware Press assignment | Fully applied |
| 028 | Depallet dry-line mapping | Fully applied |
| 029 | Press/Mould interval overlap enforcement | Not applied |
| 030 | Shift Period and effective-dated Production Date cutoff | Not applied |
| 031 | Logical Shift reporting identities and views | Not applied |

Before any deployment, run the matching read-only preflight and resolve every
reported mismatch. Apply 029, then 030, then 031. The 030 preflight requires
the 029 overlap trigger; the 031 preflight requires the versioned schema from
030. Do not rerun or renumber the deployed Depallet Migration 028. SB23 has no
discoverable migration-history ledger, so deployment records must retain
these identities in the DBA change record.

The 028 Depallet migration reassigned four original demo rows and retained
their original/new line IDs in its audit table. Do not edit those rows or run
its rollback as part of Shift testing. Current live catalog/data evidence and
the conditional deployment plan are in
[`shift_migration_deployment.md`](../../docs/shift_migration_deployment.md).

The configured connection reached `DCDLGYF3\SQLEXPRESS` / `SB23` as login
`sb23`, using SQL Server Express 2019. That login is a member of both
`db_owner` and `db_datawriter`, but it is not a server `dbcreator` or
`sysadmin`. `SB23_TEST` was not visible (`DB_ID` returned NULL), and free
volume space could not be queried because the login lacks `VIEW SERVER STATE`.
Do not use the application login to create the test database. A DBA must
confirm available storage, select isolated data/log paths, and create
`SB23_TEST` after explicit authorization.

Read-only inspection also found eight linked servers on the instance and a
`dbo.P_ActivePlan` synonym in both SB23 and
`SB23_TEST_ProductFamilyID`, targeting `PIS.dbo.vw_ActivePlan` through a
linked server. The existing `SB23_TEST_ProductFamilyID` contains application
tables and must not be used, copied, or modified for Shift Management tests.
The new test database must be created empty and contain no synonyms or
external dependencies.

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
IF DB_NAME() <> N'master'
    THROW 52927, 'Connect to master before provisioning the test login.', 1;
IF @@SERVERNAME <> N'DCDLGYF3\SQLEXPRESS'
    THROW 52928, 'Refusing test-login provisioning on an unexpected SQL Server instance.', 1;
IF DB_ID(N'SB23') IS NULL OR DB_ID(N'SB23_TEST') IS NULL
    THROW 52929, 'SB23 and SB23_TEST must both exist before provisioning.', 1;
IF SUSER_ID(N'FittingMES_ShiftTest') IS NOT NULL
    THROW 52930, 'The dedicated test login already exists; inspect it instead of reusing it.', 1;
IF EXISTS (
    SELECT 1 FROM [SB23].sys.database_principals
    WHERE name = N'FittingMES_ShiftTest'
)
    THROW 52931, 'The test login name is already present in SB23; do not alter SB23 permissions.', 1;

CREATE LOGIN [FittingMES_ShiftTest]
    WITH PASSWORD = '<set-through-the-DBA-secret-management-process>',
         CHECK_POLICY = ON,
         DEFAULT_DATABASE = [SB23_TEST];
GO
USE [SB23_TEST];
IF DB_NAME() <> N'SB23_TEST'
    THROW 52925, 'Create the test user only in SB23_TEST.', 1;
CREATE USER [FittingMES_ShiftTest] FOR LOGIN [FittingMES_ShiftTest];
ALTER ROLE [db_owner] ADD MEMBER [FittingMES_ShiftTest];
GO
USE [SB23];
IF EXISTS (
    SELECT 1 FROM sys.database_principals
    WHERE sid = SUSER_SID(N'FittingMES_ShiftTest')
)
    THROW 52926, 'The test login must not be mapped into SB23.', 1;
GO
```

The test principal needs schema DDL and DML rights only in the isolated
database to create synthetic fixtures and run rollback tests.

## Setup and execution

The runner installs
[`029_press_production_interval_overlap_test_setup.sql`](../sql/029_press_production_interval_overlap_test_setup.sql)
if the minimal schema is absent. It seeds only synthetic historical rows:
one unresolved active row and one overlapping pair. The runner then sets a
session marker and applies the same Migration 029 script. The migration and
rollback guards accept `SB23_TEST` only when that marker is present.

### Combined synthetic baseline for Migrations 029-031

For the full Shift Management rehearsal, provision a fresh `SB23_TEST` and
use the combined baseline instead of the 029-only setup above:

1. As a DBA, create `SB23_TEST` on approved data/log paths. Use a dedicated
   login mapped only to `SB23_TEST`; do not map it to SB23 or grant it server
   roles. The test login needs DDL/DML rights inside the isolated database
   because the gated runner applies schema migrations there.
2. Connect to `SB23_TEST` and run
   [`shift_management_test_setup.sql`](../sql/shift_management_test_setup.sql).
   It refuses to run outside that exact database or over existing user
   objects, synonyms, or cross-database/server dependencies. It creates a
   small synthetic 027-equivalent baseline and test rows; it does not apply or
   copy migrations 027/028 or any production records. The Depallet mapping
   schema from 028 is not required by 029-031; the fixture provides only the
   `DepalletRejectEntry` source table used by 031.
3. Keep the 029 authorization variable unset until the database and test login
   are approved. Then run the 029 integration suite as documented below; it
   detects the prebuilt fixture and applies Migration 029. The expected
   synthetic legacy overlap and missing-time rows are intentionally retained.
4. In a separate approved `SB23_TEST` session, set the Migration 030 session
   marker, run its read-only preflight, and apply 030. Run
   [`shift_management_test_seed_after_030.sql`](../sql/shift_management_test_seed_after_030.sql)
   to attach the generated period/version snapshots to the synthetic lots.
   The fixture includes Shift 1's adjacent periods and Shift 2's
   `04:00-08:00` period with a `07:00` cutoff snapshot; it does not split that
   period. Then run the 031 preflight and migration in an approved session with
   the 031 marker, and run the gated logical-reporting tests.
5. To remove the synthetic schema after collecting results, connect to
   `SB23_TEST` and run
   [`shift_management_test_cleanup.sql`](../sql/shift_management_test_cleanup.sql).
   This removes fixture tables and 029-031 objects only; it does not drop the
   database. The setup, seed, and cleanup scripts have not been executed.

From the repository root in PowerShell, after the DBA creates the database and
the test login is provisioned. The runner reads `SQL_SERVER` from the existing
configuration and uses the dedicated `SQL_TEST_USER`/`SQL_TEST_PASS` values:

```powershell
$env:SQL_SERVER = '10.28.254.3'
$env:SQL_TEST_USER = 'FittingMES_ShiftTest'
$env:SQL_TEST_PASS = '<retrieve-from-secret-management>'
$env:FITTINGMES_029_TEST_AUTHORIZED = '1'
python -m pytest tests/integration/test_migration_029_sqlserver.py -v
```

Unset the opt-in immediately afterward:

```powershell
Remove-Item Env:FITTINGMES_029_TEST_AUTHORIZED
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
    @key=N'FittingMES_029_TestRun',
    @value=N'1',
    @read_only=1;
GO
:r <repository-root>\sql\029_press_production_interval_overlap_rollback.sql
```

The rollback script refuses to run while active sequential rows share a
ProductionID/Press/Shift key. The integration suite tests both that refusal and
a successful rollback whose DDL is then reverted by the test transaction.

To remove only the test schema, connect to `SB23_TEST` in SSMS and execute
[`029_press_production_interval_overlap_test_cleanup.sql`](../sql/029_press_production_interval_overlap_test_cleanup.sql).
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
