# FittingMES Project Status — 2026-10-11

## Executive status

- Migration 028 was executed against live `DCDLGYF3\SQLEXPRESS / SB23` and its post-migration state was verified read-only against the saved pre-migration snapshot.
- Production and Depallet REJECT are separate workflows. Depallet uses the SQL-defined `LINE_DRY1` identity and active Press source choices.
- Production and Depallet navigation now have independent, tab-scoped remembered submenu destinations implemented with `sessionStorage`.
- Browser runtime verification of the latest submenu-memory behavior is pending. Do not treat its JavaScript regression tests as proof of browser runtime behavior.
- No live Reject SAVE test has been performed.

## Migration 028 — live SB23

### Verified results

- The migration completed successfully on `SB23`.
- `LINE_DRY1` is the active `DRY_LINE` EquipmentMaster identity with `EquipmentMaster.id = 17`.
- Exactly one active `DepalletLineEquipmentMap` row maps the existing active LINE(dry) main/submachine identities and instance 1 to EquipmentMaster ID 17.
- Four demo `DepalletRejectEntry` records were reassigned from legacy LINE2 ID 16 to dry-line ID 17.
- Four corresponding `DepalletRejectLineMigrationAudit` records preserve each entry's original and new line identity.
- The four Depallet entry rows' other values matched the pre-migration snapshot.
- `ProductionRejectEntry`, `ProductionData`, `PressProduction`, `LoggerEvent`, and `EquipmentTimeEvent` matched the pre-migration snapshot.
- Production LINE1/LINE2 EquipmentMaster identities and `EquipmentLineMap` also matched the snapshot.
- These read-only comparisons found no Production, OEE-input, LOGGER, downtime, or Press-production changes.

### Backup and rollback

- DBA-verified full COPY_ONLY backup with CHECKSUM:
  `C:\Program Files\Microsoft SQL Server\MSSQL15.SQLEXPRESS\MSSQL\Backup\SB23_Pre_Migration028_20261011_133747.bak`
- DBA reported successful `RESTORE VERIFYONLY WITH CHECKSUM`: “The backup set on file 1 is valid.”
- The controlled rollback script is `sql/028_depallet_dry_line_equipment_rollback.sql`.
- It restores audited Depallet demo rows to their recorded original `LineEquipmentID`, then removes migration audit/mapping and dry-line identity/schema changes.
- Rollback refuses if a non-audited Depallet entry references the dry-line identity or if audit/current data disagree. It does not delete Depallet Reject entries.
- Do not run rollback automatically. New Depallet records referencing DRY_LINE require review and explicit approval before rollback.
- No rollback or restore has been executed on live SB23.

## REJECT workflows

- Production REJECT uses Production LINE1/LINE2 and retains its Press-to-Line source filtering.
- Depallet REJECT uses the separate `LINE_DRY1` operation context.
- Depallet Press Source candidates are queried dynamically from `EquipmentMaster` where `EquipmentType='PRESS' AND IsActive=1`. The query does not use `EquipmentLineMap`.
- Source equipment IDs remain `EquipmentMaster.id`. The selected Press identifies product origin for quality traceability; it is not the operating Depallet machine.
- F6 is inactive in SQL and is excluded from the Depallet Source choices and server-side save validation.
- Depallet Reject persistence remains separate from Production Reject. The verified migration and application paths do not update Production quantities, OEE inputs, Press production, LOGGER, or downtime.
- No functional Reject SAVE test has been run against live SB23.

## Navigation

- PRODUCTION submenu: PRODUCTION, LOGGER, REJECT, USAGE.
- DEPALLET submenu: DEPALLET, REJECT.
- Production Reject and Depallet Reject remain distinct routes using `workflow=production` and `workflow=depallet`.
- The two main-menu groups store submenu destinations independently in `sessionStorage`. Defaults are Production and Depallet, respectively.
- Switching groups navigates to that group's remembered destination, uses the current Production Date, and carries only supported context for the destination workflow.
- Direct route state remains the source for the rendered active menu and submenu; the change is not a CSS-only highlight override.
- Automated regressions cover submenu memory, date/context handling, and Reject workflow separation.
- **Pending:** verify submenu-memory behavior in the actual browser, including switching groups and refreshing. Investigate any remaining URL/content/highlight mismatch during that verification.

## Changed files in this checkpoint

Application source and templates:

- `app/main.py`
- `app/reject.py`
- `app/reject_page.py`
- `app/templates/navigation.html`
- `app/templates/reject.html`

SQL migration and rollback:

- `sql/028_depallet_dry_line_equipment.sql`
- `sql/028_depallet_dry_line_equipment_rollback.sql`

Regression tests:

- `tests/test_depallet_dry_line_migration.py`
- `tests/test_family_ui.cjs`
- `tests/test_navigation.py`
- `tests/test_reject.py`
- `tests/test_reject_ui.cjs`

Documentation:

- `md/FittingMES_Project_Status_20261011.md`

No environment file, credential, backup, Excel lock file, temporary output, or Copilot session-state file is included.

## Tests and verification recorded

- Migration 028 isolated database rehearsal: first execution, four-row reassignment, repeated execution, rollback, and fixture restoration passed.
- Migration/Reject focused regression suite: 49 tests passed in the recorded pre-deployment validation.
- Reject Python regressions after the Source dropdown fix: 42 passed.
- Reject UI JavaScript regression after the Source dropdown fix: passed.
- Navigation Python regression: 12 passed.
- Navigation JavaScript regression, including remembered Production/Depallet routes and workflow-specific context: passed.
- `git diff --check`: passed after the recorded navigation/source changes; rerun before commit.
- Live post-migration database comparison: passed, including LINE_DRY1 ID 17, one active mapping, four reassigned demo entries, four audit rows, 13 active Presses, and F6 excluded.
- Read-only application verification after the Source dropdown fix: Depallet Source list matched active Presses and remained unchanged after Shift and Product/Lot selection. Production source filtering remained line-specific. Browser JavaScript errors: none.
- No SAVE test, live SQL write, migration rerun, or rollback was performed during those verifications.

## Running environment and limits

- Repository branch at checkpoint preparation: `main`.
- Configured Git remote: `origin` (`https://github.com/pathaipi-scg/FittingMES.git`).
- Last confirmed local application runtime: `http://127.0.0.1:1868`, started with `FittingMES.bat`.
- SQL connection uses the existing `.env` `SQL_SERVER=10.28.254.3`; verified identity was `DCDLGYF3\SQLEXPRESS / SB23`.
- Navigation submenu-memory changes have not yet been verified in a browser. Current server process may require a restart to ensure it serves the latest edited template.
- The worktree changes were uncommitted when this status document was prepared. Do not assume all changes originated in a single request; review each file before staging.

## Next-session instructions

1. Check branch, Git status, and the latest commit before making changes.
2. Start or restart FittingMES using the existing `FittingMES.bat` procedure if required; confirm the server on port 1868 is serving the latest template.
3. In one browser tab, select PRODUCTION > LOGGER, switch to DEPALLET > REJECT, then switch back to PRODUCTION and DEPALLET. Confirm each group returns to its own remembered submenu.
4. Refresh each route and directly open Production and Depallet routes, including both REJECT workflows. Check URL, content, main-menu active state, submenu active state, Production Date, and compatible lot context agree.
5. Investigate and correct any remaining navigation mismatch; do not accept a highlight-only fix.
6. Keep verification read-only unless a separately approved controlled Reject SAVE test is planned. Do not change live SB23 data, rerun Migration 028, or run rollback without explicit authorization.
