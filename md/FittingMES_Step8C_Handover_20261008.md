# FittingMES Step 8C Handover — 2026-10-08

## Purpose and evidence labels

This document hands off the completed September 2026 Shift-aware Press/Mould integration test and identifies proposed next work.

- **Verified** means recorded in the Step 8C execution register or confirmed by the Git/schema checks cited below.
- **Known limitation** means observed but not fully exercised or resolved.
- **Proposed** means a candidate for Step 9, not approved implementation scope.

Primary records:

- [Step 8C execution register](./FittingMES_Step8C_T07-T20_Execution_Register_2026-10-08.md)
- [Shift-aware Press/Mould design context](./FittingMES_Shift_Aware_Press_Mould_Design_Context_20261008.md)

## 1. Project status and Git working tree

**Verified at handover preparation:**

- Repository: `D:\AI\FittingMES`
- Branch: `main`
- Local `HEAD`: `e01a0ece6c915e011a9cf9f95406da95b2e73bb0`
- Locally available `origin/main` ref: the same SHA. No fetch was performed, so this does not assert the current remote state.
- The worktree was not clean. Existing modifications and untracked files were left untouched.

Existing modified files:

- `app/main.py`
- `app/press_production.py`
- `app/print_oee.py`
- `app/templates/production.html`
- `tests/test_log_cal_copy.cjs`
- `tests/test_press_production.py`
- `tests/test_print_oee.py`

Existing untracked files:

- `md/FittingMES_Shift_Aware_Press_Mould_Design_Context_20261008.md`
- `md/FittingMES_Step8C_T07-T20_Execution_Register_2026-10-08.md`
- `sql/027_shift_aware_press_production.sql`
- `sql/027_shift_aware_press_production_preflight.sql`
- `sql/027_shift_aware_press_production_rollback.sql`
- `tests/test_press_production_ui.cjs`
- `tests/test_shift_aware_press_migration.py`

This handover is a further untracked file. Do not discard or restore any of the listed work. No commit or push was made.

## 2. Migration 027 and live SB23 schema status

**Verified during the Step 8C live preflight; not re-queried while preparing this documentation:**

- Target connection was `DCDLGYF3\SQLEXPRESS`, database `SB23`.
- Migration 027 was already applied before Step 8C. The live schema had nullable `PressProduction.ShiftMasterID` (`bigint`), enabled/trusted FK `FK_PressProduction_ShiftMaster`, and enabled filtered unique index `UX_PressProduction_Production_Machine_ShiftActive`. The old unfiltered `UX_PressProduction_Production_Machine` index was absent.
- The filtered active-assignment key is `(ProductionID, MachineCode, ShiftMasterID)` for unreleased rows with a non-NULL Shift.
- All original 14 `PressProduction` rows retained `ShiftMasterID = NULL`; their historical Shift was not inferred or backfilled.
- The Step 8C run made no schema changes and ran no migrations.
- The migration, preflight, and rollback SQL files in `sql/` are artifacts. Do not execute them as part of resuming this handover.
- The preflight recorded the verified backup as available. A SQL permission limitation prevented `RESTORE VERIFYONLY`; require a separately confirmed restore/backup plan before any future migration or destructive operation.

The database skill read for the Step 8C work was `skill/DATABASE_ID_FIRST_DESIGN_SKILL.md`. Read and verify the skill path again before any future database, schema, migration, or data work.

## 3. Step 8C T01–T20 results and limitations

**Verified:** all tests have a recorded PASS result in the execution register. T07's original failure and successful retest are recorded separately. PASS does not mean every behavior was exercised without limitation.

| Test | Result | Summary |
|---|---|---|
| T01 | PASS | Created exactly the two approved TEST Lots; IDs and CREATE history are listed below. |
| T02 | PASS | Added the Shift 1 Press/Mould assignment. |
| T03 | PASS | Added the same Press/Mould in Shift 2 as a separate assignment ID. |
| T04 | PASS | Cross-Lot, same-Shift active Press conflict was rejected without unintended changes. |
| T05 | PASS | Cross-Lot, same-Shift active Mould conflict was rejected without unintended changes. |
| T06 | PASS | Edited Press while retaining the original `PressProductionID`. |
| T07 initial | FAIL | Mould edit failed with `Counter Qty is required to reconcile the existing Mould usage.` No partial change occurred. |
| T07 retest | PASS | After the user restarted the application, Mould 29→30 succeeded on the same assignment; quantities and usage were reconciled. |
| T08 | PASS | Shift edit retained the same assignment after dependency checks. |
| T09 | PASS | Invalid Curing quantity was rejected; valid quantities were saved. |
| T10 | PASS | RELEASE followed by re-ADD created a distinct episode ID and preserved history. |
| T11 | PASS | Conflicting UNDO RELEASE was rejected while the newer episode was active. |
| T12 | PASS | After releasing the newer episode, historical-episode guard rejected UNDO RELEASE of the older one. |
| T13 | PASS | Repeated historical episodes had separate IDs and timestamps. |
| T14 | PASS | Distinct Shift 1 and Shift 2 MANUAL downtime values were saved and verified. Initial attempt with missing quantities persisted no events; see known limitation. |
| T15 | PASS with limitation | LOG CAL read path and Shift isolation were checked; no matching source LOGGER categories existed for a positive import test. |
| T16 | PASS | Concurrent same-Shift allocation yielded one assignment; the competing request was rejected. |
| T17 | PASS | Invalid Curing operation was rejected with no partial writes. |
| T18 | PASS | All seven baseline fingerprints matched. |
| T19 | PASS with limitation | Five per-episode rows, Shift mapping, ambiguity exclusion, and no duplicate quantities/downtime were verified. Numerical OEE was not calculated because valid production Start/End times were absent. |
| T20 | PASS | Full LoggerEvent count and fingerprint matched the original baseline. |

Regression results recorded for the T07 fix: **9 focused tests passed, 581 Python tests passed, and 7 JavaScript test files passed.**

## 4. TEST Lots 19/20 and PPIDs 15–19

**Verified final TEST Lots** — retained and active as Lots:

| ProductionID | Plan | LotNo | Production date | Final Lot state |
|---:|---|---|---|---|
| 19 | MTS024 | `I11690902` | 2026-09-02 | Retained, active |
| 20 | MTS028 | `I11690903` | 2026-09-02 | Retained, active |

The two Lots were created through the existing application workflow. Their CREATE history IDs are 44 and 45 respectively.

**Verified final TEST assignment state:** all five test assignments were released; no active TEST assignments remain.

| PressProductionID | ProductionID | Assignment history |
|---:|---:|---|
| 15 | 19 | F8 / Shift 2 / Mould 30; Dispatch 75, Counter 100, Curing 80; released |
| 16 | 19 | F7 / Shift 2 / Mould 29; final Dispatch/Counter/Curing 1/1/1; released |
| 17 | 19 | Later F8 / Shift 2 / Mould 30 episode; released |
| 18 | 19 | F8 / Shift 1 / Mould 30; final Dispatch/Counter/Curing 1/1/1; released |
| 19 | 20 | F9 / Shift 1 / Mould 29; created by the one-winner concurrent allocation test; released at closeout |

MouldUsage history retained:

| MouldUsageID | PressProductionID | MouldID | UsageCycles |
|---:|---:|---:|---:|
| 10 | 15 | 30 | 100 |
| 11 | 18 | 30 | 1 |
| 12 | 16 | 29 | 1 |

MANUAL downtime history retained:

- EquipmentTimeEventIDs 57–62: PPID 18, F8 / Shift 1; Setup 11.5 minutes and Breakdown 3.5 minutes; other tracked categories 0.
- EquipmentTimeEventIDs 63–68: PPID 16, F7 / Shift 2; Setup 21.5 minutes and Breakdown 6.5 minutes; other tracked categories 0.
- No LoggerEvent rows were created.

## 5. Final counts and legacy integrity

**Verified final counts recorded at closeout:**

| Table | Final row count |
|---|---:|
| ProductionLot | 20 |
| ProductionLotHistory | 45 |
| PressProduction | 19 |
| MouldUsage | 12 |
| EquipmentTimeEvent | 68 |
| LoggerEvent | 10 |
| ProductionData | 13 |

The fingerprint calculation used the original method:

`json.dumps(data, sort_keys=True, default=str, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`

The same column selection/order, primary-key row order, and baseline row scope were used. Original records were compared separately from newly created TEST rows; LoggerEvent, EquipmentTimeEvent, and ProductionData were compared as full tables.

| Baseline data set | Scope | SHA-256 | Result |
|---|---|---|---|
| ProductionLot | Original rows 1–18 | `9f7eadfb47a009d7f2d4364fe09a9736dd66a3efd89c3d7a400dde3c1a479086` | Match |
| ProductionLotHistory | Original rows 1–43 | `6bc211511edf9bc36aff42af247d6d4383b06f9f887c93d6fa4d8546f58c5c02` | Match |
| PressProduction | Original rows 1–14 | `4f7dcd16ccbc1dd5e8e518e6f514591b87028d63531331c3320950d96a9b56ce` | Match |
| MouldUsage | Original rows 1–9 | `52f4ee9b1a00e4ec2bcd0d9472571d38c5295ca42f4fdd8ff633e827f049e4d9` | Match |
| EquipmentTimeEvent | Original rows 1–56 | `c23c1615953962c0949f45861daeab4a4a498e7251d0a14fec476dd1b6547f6e` | Match |
| LoggerEvent | Full table | `ece8b5d50b75bf3c6abe3c2a96a6a06bb718f74718e0c8dcfbfea86fd08732b8` | Match |
| ProductionData | Full table | `9da572c76287156e39cd6f1352c5701d62fa9d58d228c09a0799f22021deeda9` | Match |

**Verified:** the original 14 `PressProduction` records and all original `LoggerEvent` rows remained unchanged. Earlier digest differences for LoggerEvent, ProductionData, and original ProductionLot rows were false positives caused by using the default `ensure_ascii=True` instead of the original `ensure_ascii=False`; the corrected method matched all seven baselines.

## 6. T07 root cause and implemented fix

**Verified root cause:** the EDIT FITTING form does not submit quantity fields. The route populated absent optional values with `None`, while the update path only used persisted-value fallback when a key was absent. Existing MouldUsage reconciliation therefore received a missing CounterQty and rejected the Mould edit.

**Implemented and tested:**

- Route code includes optional fields only if submitted.
- Mould-only edit uses the locked, persisted PressProduction quantities as authoritative; it does not trust an arbitrary client CounterQty.
- Existing `MouldUsage` is reconciled in place from persisted CounterQty. The same `PressProductionID` is retained; identical edits do not inflate cycles or duplicate usage rows.
- Mould-only correction does not modify unrelated downtime.
- The transaction rolls back on failure, and existing Press/Shift dependency guards remain in force.

Relevant worktree changes are in [app/main.py](../app/main.py), [app/press_production.py](../app/press_production.py), and [tests/test_press_production.py](../tests/test_press_production.py). These changes were not committed in this handover.

## 7. Current Shift-aware Press/Mould business rules

**Verified design and implementation behavior:**

- Every Shift gets a separate PressProduction assignment row; changing Shift for an existing assignment through EDIT retains that row's ID, while RELEASE/re-ADD creates a new episode.
- Active Press and Mould conflicts are checked server-side for the same production date and Shift across Lots; different Shifts may reuse the resources.
- Mould availability and allocation are protected against concurrent conflicting requests.
- Resolve Shift through `ShiftMaster`/ShiftCode mapping; do not assume a ShiftMaster primary key equals the displayed Shift number.
- Legacy assignments with `ShiftMasterID = NULL` remain unknown. Never backfill or attribute them to a Shift by guessing.
- EDIT remains subject to conflict checks and dependent LOGGER/EquipmentTimeEvent history guards. RELEASE preserves history; UNDO RELEASE must respect active conflicts and newer historical episodes.
- Manual downtime is stored by ProductionID, equipment, Shift, time type, and source. Ambiguous repeated Lot/Press/Shift episodes block unsafe nonzero attribution; existing stored events are not copied or overwritten to resolve ambiguity.
- LOG CAL is a read/GET operation that fills only the selected row's Shift values in the client. Values are not persisted until the operator uses Save.
- PRINT OEE produces one row per assignment episode. Unknown or ambiguous Shift identity is not guessed and ambiguous downtime attribution is excluded. OEE formula changes are out of scope.
- Historical production cutoff was 08:00; the verified historical Shift starts were Shift 1 at 06:00 and Shift 2 at 19:00.

## 8. Known issues and untested behavior

### Known limitation: downtime SAVE can persist nothing

During T14, an attempted downtime submission without CounterQty and without an existing MouldUsage returned a success-shaped redirect but created no EquipmentTimeEvent rows. The UI also requires CounterQty, blocking an ordinary submission without it. The service calls `_save_manual_minutes` only when CounterQty is positive or an existing MouldUsage is present. The test proceeded through the application with 1/1/1 quantities, producing the verified downtime rows above.

This no-op/success response should be resolved deliberately; decide whether valid downtime may be saved independently of quantities or the application must show an explicit validation error. No behavior change was made in this handover.

### Known limitation: positive LOG CAL import not tested

No matching source LOGGER categories existed for the test date. Read behavior and Shift isolation were verified, but no positive import was demonstrated. LoggerEvent was not modified.

### Known limitation: PRINT OEE with actual production times not tested

All five assignment rows lacked valid production Start/End times, so numerical OEE ratios were not calculated. The report's row identity, Shift mapping, ambiguity handling, and duplicate prevention were checked; this is not a numerical OEE validation.

## 9. Proposed next work — Step 9

No authoritative Step 9 specification was found in the reviewed `md/` materials. The items below are **proposals**, not approved scope:

1. Decide and document the intended downtime-save contract for assignments with missing CounterQty and no MouldUsage. Add explicit validation/feedback or support the appropriate independent downtime path; test that the UI response matches persisted outcome.
2. Exercise a positive LOG CAL import using a controlled fixture or isolated test database with known LOGGER inputs. Do not modify SB23 LoggerEvent to manufacture test data.
3. Validate PRINT OEE with controlled, valid Start/End times and known expected results in tests or an isolated database. Keep OEE formulas unchanged unless separately approved.
4. Add or retain regression coverage for unknown legacy Shift, ambiguous episode downtime, conflict serialization, and error atomicity as these cases are touched.
5. Only after Step 9 scope and environment are approved, schedule any live SB23 operation separately. Step 8C's permission to create the two Lots does not authorize new TEST data or unrelated writes.

## 10. Exact files and functions to inspect next

Suggested inspection order:

1. [app/press_production.py](../app/press_production.py)
   - `save_press_production`
   - `_save_manual_minutes`
   - `release_press_production`
   - `undo_release_press_production`
2. [app/main.py](../app/main.py)
   - `save_press_production_route_action`
   - `save_press_production_change`
   - `undo_release_press_production_change`
   - `read_press_logger_guide`
3. [app/templates/production.html](../app/templates/production.html)
   - Per-assignment ADD/EDIT form, required Counter field, downtime inputs, and LOG CAL client-side behavior.
4. [app/print_oee.py](../app/print_oee.py)
   - `calculate_oee_row`
   - `_query_rows`
   - `read_print_oee_context`
   - `summarize`
5. Tests:
   - [tests/test_press_production.py](../tests/test_press_production.py): Mould-only edit, persisted CounterQty authority, rollback, dependency protection, downtime ambiguity, and concurrency.
   - [tests/test_print_oee.py](../tests/test_print_oee.py): per-episode rows, Shift mapping, ambiguity, and OEE eligibility.
   - [tests/test_log_cal_copy.cjs](../tests/test_log_cal_copy.cjs) and [tests/test_press_production_ui.cjs](../tests/test_press_production_ui.cjs): row-specific LOG CAL/UI behavior.
   - [tests/test_shift_aware_press_migration.py](../tests/test_shift_aware_press_migration.py): migration artifact/preflight safeguards; tests do not authorize execution.

## 11. SB23 safety restrictions

- Read and verify the applicable database skill before any database, SQL, migration, or data task.
- Verify server, database, live schema, active writers/transactions, and a usable backup before any approved operation.
- Treat SB23 as read-only unless the user separately authorizes the exact write operation and scope. No direct data mutation, migrations, schema changes, master-data edits, backfill, cleanup, or additional TEST data under this handover.
- Use existing application workflows for any specifically approved future operational writes; do not create, edit, or delete LoggerEvent records.
- Do not change LOGGER behavior or OEE formulas as an incidental part of Step 9.
- Stop on unexpected differences, unsafe dependencies, or uncertain state. Preserve committed Lot and test history; do not automatically repair or roll back.
- Do not restart or stop the user's application without authorization. The application had been left running after Step 8C; check before use and do not assume it remains available.
- No commit or push without a separate instruction.

## 12. Fresh-session resume instructions

1. Open `D:\AI\FittingMES` and read this handover, the execution register, and the Shift-aware design context.
2. Check `git status --short`, branch, and `HEAD`. Preserve the pre-existing modified and untracked files; do not restore or clean them.
3. Before any database work, locate and read `skill/DATABASE_ID_FIRST_DESIGN_SKILL.md`, verify its path, and report that it was read.
4. Treat the recorded Step 8C final state as history, not permission for new writes. Confirm the exact server/database and current schema read-only before any separately approved live operation.
5. Confirm the desired Step 9 scope and test environment with the user before implementation or database activity. Prefer isolated automated fixtures for untested positive LOGGER/OEE cases.
6. Do not repeat T01–T20 writes, create Lots, or alter existing TEST history.
