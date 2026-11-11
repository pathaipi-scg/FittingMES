# Shift Management Migration Review

## Database guidance

The applicable repository standard is
[`DATABASE_ID_FIRST_DESIGN_SKILL.md`](../skill/DATABASE_ID_FIRST_DESIGN_SKILL.md).
New relations use stable surrogate IDs; display codes are not relational keys,
and historical display values are retained as snapshots.

## Read-only SB23 evidence

Inspection used the existing application SQL connection and SELECT-only
queries. The connected database was confirmed as `SB23`. No migration,
DDL, DML, deployment, or service operation was performed. No migration ledger
table was found; `DepalletRejectLineMigrationAudit` was the only table matching
the migration/deployment name search.

| Migration | Classification | Supporting schema evidence |
|---|---|---|
| 027 — shift-aware Press assignment | Fully applied | `PressProduction.ShiftMasterID` is nullable `bigint`; enabled/trusted `FK_PressProduction_ShiftMaster` references `ShiftMaster(id)`; the unique filtered index has keys `(ProductionID, MachineCode, ShiftMasterID)` and filter `ReleasedAt IS NULL AND ShiftMasterID IS NOT NULL`. |
| 028 — Depallet dry-line mapping | Fully applied | `DepalletLineEquipmentMap` and `DepalletRejectLineMigrationAudit` have the migration's expected columns, PKs, unique constraints, and FKs. The equipment type check allows `DRY_LINE`. The active `LINE(dry)` main/submachine maps through one active `LINE_DRY1` equipment row. Four audit rows all match four existing reassigned entries; none are missing or mismatched. SB23 has 66 Depallet Reject rows, so the migration's original four-row prerequisite is historical and must not be rerun. |
| 029 — Press/Mould interval overlap enforcement | Not applied | The 027 filtered unique index is present. `IX_PressProduction_ActiveMachineInterval`, `IX_PressProduction_ActiveMouldInterval`, and `TR_PressProduction_PreventActiveIntervalOverlap` are absent. |
| 030 — Shift Period and cutoff versions | Not applied | `ShiftMasterVersion`, `ShiftPeriodMaster`, `ShiftPeriodVersion`, and `ProductionDateCutoffVersion` are absent; `PressProduction.ShiftPeriodID` and 030 snapshot columns are absent. |
| 031 — logical Shift reporting | Not applied | Logical reporting views and 031 columns (`DailyMaterialUsage.ShiftMasterID`, `LoggerEvent.ShiftMasterID`, reject Shift-code snapshots) are absent. |

`ProductionDayRuleHistory` contains the historical `08:00` rule effective
`2026-01-01`. Preserve that rule and all saved Production Dates; the new
`07:00` cutoff is prospective and effective-dated.

## SQL Server and test-database inspection

The existing application connection was used for SELECT-only catalog
inspection. It confirmed `DCDLGYF3\SQLEXPRESS`, SQL Server 2019 Express
`15.0.2000.5` RTM, with SB23 at compatibility level 150. SB23 and
`SB23_TEST_ProductFamilyID` are ONLINE, SIMPLE recovery, MULTI_USER and
writable. `SB23_TEST` was not present in the visible database catalog.

The current data/log files for SB23 are 264 MB / 8 MB; the existing
`SB23_TEST_ProductFamilyID` files are 200 MB / 8 MB. Both databases use the
same `C:\Program Files\Microsoft SQL Server\MSSQL15.SQLEXPRESS\MSSQL\DATA`
directory. These are allocated file sizes, not used-space measurements.
`sys.master_files` returned no rows to the application login, and the volume
space and server resource DMVs were denied with SQL Server error 300/297
(`VIEW SERVER STATE` denied). Available free disk, CPU and memory therefore
remain unverified. The proposed synthetic database allocation is 128 MB data
and 64 MB log (192 MB initially), with only a few synthetic rows; the DBA
must verify available capacity and choose approved paths before provisioning.
SQL Server Express shares instance CPU, memory and TempDB across SB23 and any
test database; a separate database is not resource isolation. Prefer a
separate test instance, or schedule concurrency tests outside production
peaks with DBA monitoring.

Eight linked servers are configured on the instance. `sys.sql_expression_dependencies`
reported no cross-database or cross-server module dependencies in SB23 or
`SB23_TEST_ProductFamilyID`, but each database has a synonym
`dbo.P_ActivePlan` targeting `PIS.dbo.vw_ActivePlan` through a linked server.
The existing `SB23_TEST_ProductFamilyID` also contains 49 tables, 14 views,
12 procedures and operational Shift/Press/Usage/LOGGER/REJECT objects. It is
not an empty isolated test database and must not be used or modified for this
work. Do not copy it or its synonym into `SB23_TEST`.

The proposed integration database must be a fresh, synthetic-only database
with no synonyms or external dependencies. Its initialization script refuses
to run unless `DB_NAME()` is exactly `SB23_TEST`, the database has no
user-created objects, and it has no synonyms or cross-database/server
dependencies. It creates the minimal 027-equivalent schema needed by
migrations 029-031, including the historical 08:00 rule and synthetic test
data. It does not execute or replay migrations 027/028, copy production
records, or create the unrelated Depallet mapping schema; the latter is not a
dependency of 029-031. The only Depallet source object created is the
synthetic `DepalletRejectEntry` table required by migration 031.

The Depallet status is also supported by the dated live deployment record in
[`FittingMES_Project_Status_20261011.md`](../md/FittingMES_Project_Status_20261011.md),
which records the successful Migration 028 execution and post-migration
read-only comparison. Its four audited demo-row changes are historical; do
not edit those rows or run the Depallet rollback as part of this work.

## Migration identity and deployment order

The two former 028 filenames represented different work. Preserve the
deployed Depallet migration as 028. Renumber only the unapplied Press interval
migration to 029; the unapplied Shift Period/Cutoff and logical reporting
migrations are 030 and 031. Their preflight, rollback, test, authorization
marker, and error references use the corrected identities.

1. Re-run the 027 and Depallet 028 schema checks during the DBA change review;
   do not reapply either migration.
2. Run the read-only 029 preflight. Resolve all invalid active intervals,
   missing timestamps, and cross-ProductionDate Press/Mould overlaps before
   considering 029.
3. Apply 029, then verify its trigger and both interval indexes.
4. Run the read-only 030 preflight; confirm the 08:00 historical rule and
   existing Shift masters, then apply 030.
5. Run the read-only 031 preflight; confirm the 030 versioned periods,
   cutoff versions, and 07:00 initial cutoff, then apply 031.
6. Verify each migration's resulting catalog objects and run post-deployment
   report reconciliation before enabling the application paths.

This is a conditional order, not deployment authorization. The current schema
shows 029/030/031 are absent, but no database migration-history ledger exists.
Record the DBA's preflight results and applied identities in the change record.

## Isolated SQL Server test plan

No database has been created or modified for this plan. Tests must run only
after explicit authorization and DBA provisioning.

1. After approval, ask the DBA to provision a fresh `SB23_TEST` using approved
   data/log paths and a dedicated login. Grant that login DDL/DML only in
   `SB23_TEST`; do not map it to SB23, reuse the application login, or grant it
   server roles. Verify the login cannot write to SB23 and that the fresh
   database contains no synonyms, external tables or cross-database/server
   references. The eight instance linked servers must not be referenced by
   test objects.
2. Run
   [`shift_management_test_setup.sql`](../tests/sql/shift_management_test_setup.sql)
   only after verifying the connection's current database is `SB23_TEST`. The
   script creates an empty-database-only synthetic 027-equivalent baseline,
   including test rows for legacy missing timestamps, an existing overlap,
   two sequential Shift 1 periods, a Shift 2 period crossing the 07:00 cutoff,
   and small Usage/OEE/LOGGER/REJECT inputs. It does not copy production data
   or execute historical migrations 027/028.
3. Run the read-only 029 preflight first and retain its expected synthetic
   unresolved/overlap findings. The 029 integration runner then applies 029
   to `SB23_TEST` and runs the gated interval tests. The 030 preflight should
   confirm the synthetic 08:00 history and report the intentionally unresolved
   legacy interval; do not repair that row. Apply 030 only in an authorized
   test session. Run
   [`shift_management_test_seed_after_030.sql`](../tests/sql/shift_management_test_seed_after_030.sql)
   to attach the synthetic period/version snapshots, then run the 031
   preflight and apply 031 in a separate authorized test session. The seeding
   script assigns the Shift 2 `04:00-08:00` period without splitting it at
   `07:00`.
4. For 029, test overlapping and touching Press intervals and Mould intervals;
   same-Shift sequential assignments on reused Press/Mould resources; and
   overlaps crossing ProductionDate midnight. Use concurrent sessions for
   conflicting inserts/updates, assert that no conflicting pair commits, and
   accept/document SQL Server deadlock 1205 for a losing mixed-writer
   transaction.
5. For 030, create and version Shift/period/cutoff configuration with future
   effective dates. Verify enabled-period overlap rejection, allowed gaps,
   periods crossing the 07:00 cutoff, and preservation of old configuration
   versions. Verify saved lot/assignment identities, timestamps, Production
   Dates, and snapshots do not change after later configuration edits.
6. For 031 and the application reports, compare source totals with logical
   groups: multiple periods of one Shift produce one ShiftMasterID group;
   Usage quantities and OEE inputs are counted once; OEE rates are recomputed
   from aggregated quantities and times; REJECT quantities and LOGGER durations
   are not duplicated; PRINT/API groupings retain historical display snapshots;
   legacy NULL identities remain readable.
7. Test rollback refusal after data references versioned IDs/snapshots and
   after sequential Press assignments exist. The 029 rollback cannot restore
   the old unique index while sequential active rows conflict. The 030/031
   rollback scripts must not discard referenced configuration or reporting
   identity. Do not run the Depallet 028 rollback; it concerns historical
   Depallet entries and is outside this rehearsal.

The existing gated integration tests cover Migration 029 and three logical
reporting schema/quantity checks. They do not yet automate every 030/031
configuration, Usage/OEE, REJECT, LOGGER, PRINT or API scenario; retain those
as explicit SQL/application integration cases rather than treating the
read-only view checks as complete coverage. To reset only the synthetic schema,
use
[`shift_management_test_cleanup.sql`](../tests/sql/shift_management_test_cleanup.sql)
from `SB23_TEST`; it removes the test views, migration objects and fixture
tables but does not drop the database. Test setup, seeding and cleanup have
not been executed.

Migration 029 rollback is refused when sequential active assignments share a
Lot/Press/Shift key, and concurrency can expose deadlock 1205 for mixed
writers. Migration 030 rollback is refused after assignments or lots reference
versioned configuration, or after configuration history advances beyond the
initial version. Migration 031 rollback is refused after saved logical Shift
IDs or snapshots exist. Test successful rollbacks only on a pristine disposable
baseline before adding those references; do not use rollback to erase
historical production identities.
