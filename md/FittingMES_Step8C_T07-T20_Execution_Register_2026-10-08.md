# FittingMES Step 8C T07-T20 Execution Register

**Recorded:** 2026-10-08<br>
**Database:** `DCDLGYF3\SQLEXPRESS` / `SB23`<br>
**Application:** `http://127.0.0.1:1868`<br>
**Production Date:** 2026-09-02
**Status:** T01-T20 executed. T07 passed on retest after the original failure. T18 and T20 integrity checks passed; closeout released all remaining TEST assignments and retained both TEST Lots.

## Required context read

- `skill/DATABASE_ID_FIRST_DESIGN_SKILL.md`
- `md/FittingMES_Shift_Aware_Press_Mould_Design_Context_20261008.md`

No database schema changes or migrations were performed.

## Preserved T01-T07 history

| Test | Result | Recorded operation and identifiers |
|---|---|---|
| T01 | PASS | Created Lot A, ProductionID 19, LotNo `I11690902`, MTS024, CREATE history 44; and Lot B, ProductionID 20, LotNo `I11690903`, MTS028, CREATE history 45. |
| T02 | PASS | Added PPID 15 for ProductionID 19, Press F7, MouldID 29, Shift 1. |
| T03 | PASS | Added PPID 16 for ProductionID 19, Press F7, MouldID 29, Shift 2. |
| T04 | PASS | Cross-Lot same-Shift Press conflict rejected; no unintended data changes. |
| T05 | PASS | Cross-Lot same-Shift Mould conflict rejected; no unintended data changes. |
| T06 | PASS | Edited PPID 15 Press F7 to F8, retaining PPID 15, MouldID 29, Shift 1. |
| T07 initial | FAIL | After saving Dispatch 75, Counter 100, Curing 80 on PPID 15, EDIT Mould 29 to 30 failed with `Counter Qty is required to reconcile the existing Mould usage.` No partial database change occurred. |
| T07 retest | PASS | After the user restarted FittingMES, edited PPID 15 MouldID 29 to 30 through EDIT FITTING. PPID 15 stayed the same; quantities 75/100/80 were preserved; MouldUsageID 10 was updated in place to MouldID 30, UsageCycles 100. |
| T08 | PASS | Edited PPID 15 from Shift 1 to Shift 2 after confirming no dependent LOGGER or EquipmentTimeEvent history. PPID 15 and quantities remained unchanged. |
| T09 | PASS | Curing 101 against Counter 100 was rejected with no data changes; valid 75/100/80 values were saved and verified. No downtime rows were created. |
| T10 | PASS | Released PPID 15, then re-added F8/MouldID 30/Shift 2 as new PPID 17. PPID 15 retained its history; PPID 17 is a separate active episode. |
| T11 | PASS | Attempted UNDO RELEASE for PPID 15 while PPID 17 was active. The application rejected the request because F8 already had an active assignment for the date/shift. No database changes occurred. |
| T12 | PASS | Released PPID 17, retried UNDO RELEASE on PPID 15, and confirmed the historical-episode guard rejected it with `MOULD_ALREADY_REASSIGNED`; PPID 15 remained released. |
| T13 | PASS | Verified distinct historical F8/MouldID 30/Shift 2 episodes PPID 15 and 17; both are released and retain separate IDs/timestamps. |
| T14 | PASS | Saved distinct MANUAL downtime values: PPID 18/F8/Shift 1 Setup 11.5 and Breakdown 3.5; PPID 16/F7/Shift 2 Setup 21.5 and Breakdown 6.5. IDs 57-68. |
| T15 | PASS | LOG CAL GETs returned no matching LOGGER events. Clicking Shift 1 LOG CAL changed only that row's client-side fields; Shift 2 fields and persisted MANUAL rows remained unchanged. |
| T16 | PASS | Two concurrent app requests for F9/MouldID 29/Shift 1 produced exactly one assignment, PPID 19 on Lot 20; the competing Lot 19 allocation was rejected. |
| T17 | PASS | Curing 2 against Counter 1 on PPID 16 was rejected; quantities, MouldUsageID 12, downtime IDs 63-68, and counts were unchanged. |
| T18 | PASS | All seven original-table fingerprints matched the recorded baseline after live testing. |
| T19 | PASS with limitation | PRINT OEE showed one row per each of five episodes, correct Shift mapping, no duplicated counts/downtime, and excluded ambiguous repeated episodes. All rows lacked valid production times, so OEE ratios were not calculated. |
| T20 | PASS | Full LoggerEvent count and SHA-256 matched the original baseline; no LoggerEvent writes occurred. |

T07 precondition created MouldUsageID 10 for PPID 15, MouldID 29, ReconditionNo 0, UsageCycles 100. The save created no EquipmentTimeEvent rows. No EquipmentTimeEvent IDs or LoggerEvent IDs were created for the test Lots.

## T07 root cause and code change

The EDIT FITTING form posts `production_date`, `shift_code`, `machine_code`, and `mould_id`; it does not include quantity, time, remark, or downtime fields. The route nevertheless added those optional fields to the backend data dictionary with `None` values. The update logic only fell back to the persisted PressProduction values when a key was absent. Consequently, CounterQty remained `None` and existing MouldUsage reconciliation rejected the edit.

Changes made for this fix:

- `app/main.py`: include an optional value only when that form field was actually submitted.
- `app/press_production.py`: for a Mould-only edit, retain persisted DispatchQty, CounterQty, and CuringQty from the locked PressProduction row; reconcile MouldUsage UsageCycles from persisted CounterQty; do not write manual downtime during the Mould-only correction.
- `tests/test_press_production.py`: cover omitted form values, persisted CounterQty authority, same PPID and quantity preservation, Mould conflict, rollback, idempotent usage reconciliation, and existing Press/Shift dependency guards.

MouldUsage is updated in place; no duplicate usage row or cumulative cycle increment is introduced.

## Regression results

- Focused regression set: **9 passed**. The set included existing LOGGER and EquipmentTimeEvent Press/Shift dependency-protection tests.
- Full Python suite: **581 passed**.
- Full JavaScript suite: **7 test files passed**.
- Pylance: no diagnostics in `tests/test_press_production.py`; the two changed application modules had only unused-symbol warnings.
- A pre-fix focused run reproduced both the route's `CounterQty: None` payload and the backend acceptance of a client CounterQty of 999 for a Mould-only correction. Both regressions pass after the fix.

## Pre-continuation read-only live recheck

This is the pre-live-continuation snapshot, taken after the source/regression review and before the post-restart T07-T11 operations below.

The configured application database connection returned exactly `DCDLGYF3\SQLEXPRESS` and `SB23`. The existing application returned HTTP 200 on port 1868.

### Fingerprint method

Fingerprints were recalculated using the original serialization:

`json.dumps(data, sort_keys=True, default=str, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`

Rows were selected with the same full-table column order (`SELECT *`), ordered by each table's primary key, and scoped to the original baseline rows for tables that gained new TEST rows: first 18 ProductionLot rows, first 43 ProductionLotHistory rows, first 14 PressProduction rows, and first 9 MouldUsage rows. LoggerEvent, EquipmentTimeEvent, and ProductionData were compared as full tables. Datetimes use the same `default=str` conversion. The previous calculation omitted `ensure_ascii=False`, escaping Thai and other non-ASCII characters and producing false-positive digest differences.

| Entity | State at this pre-continuation snapshot |
|---|---|
| Lot A | ProductionID 19, `I11690902`, MTS024, 2026-09-02, ProductFamilyID 3 / ProductCode 11, active |
| Lot B | ProductionID 20, `I11690903`, MTS028, 2026-09-02, ProductFamilyID 3 / ProductCode 11, active |
| PPID 15 | ProductionID 19, F8, Shift 1, MouldID 29, Dispatch 75, Counter 100, Curing 80, active |
| PPID 16 | ProductionID 19, F7, Shift 2, MouldID 29, quantities NULL, active |
| MouldUsageID 10 | PPID 15, MouldID 29, ReconditionNo 0, UsageCycles 100 |
| Lot 19/20 EquipmentTimeEvent rows | 0 |
| Active database requests | 0 at the time of the DMV check |

Recorded-baseline fingerprint comparison:

| Data set | Baseline rows / current total rows | Result |
|---|---:|---|
| ProductionLot original rows | 18 / 20 | Match: `9f7eadfb47a009d7f2d4364fe09a9736dd66a3efd89c3d7a400dde3c1a479086` |
| ProductionLotHistory original rows | 43 / 45 | Match: `6bc211511edf9bc36aff42af247d6d4383b06f9f887c93d6fa4d8546f58c5c02` |
| PressProduction original rows 1-14 | 14 / 16 | Match: `4f7dcd16ccbc1dd5e8e518e6f514591b87028d63531331c3320950d96a9b56ce` |
| MouldUsage original rows 1-9 | 9 / 10 | Match: `52f4ee9b1a00e4ec2bcd0d9472571d38c5295ca42f4fdd8ff633e827f049e4d9` |
| EquipmentTimeEvent full table | 56 / 56 | Match: `c23c1615953962c0949f45861daeab4a4a498e7251d0a14fec476dd1b6547f6e` |
| LoggerEvent full table | 10 / 10 | Match: `ece8b5d50b75bf3c6abe3c2a96a6a06bb718f74718e0c8dcfbfea86fd08732b8` |
| ProductionData full table | 13 / 13 | Match: `9da572c76287156e39cd6f1352c5701d62fa9d58d228c09a0799f22021deeda9` |

The previously reported LoggerEvent, ProductionData, and original ProductionLot digest differences were false positives caused by the omitted `ensure_ascii=False` option. All seven fingerprints now match the recorded baseline. No row-level differences were found, so there are no changed primary keys, columns, or values to report.

## Server code-load verification

The user restarted FittingMES after the prior code-load check. The replacement application was confirmed running on port 1868 and returned HTTP 200. T07 was executed only after that restart; the application was not restarted or stopped by the assistant.

## T07-T20 continuation status

| Test | Result |
|---|---|
| T07 retest | PASS |
| T08 | PASS |
| T09 | PASS |
| T10 | PASS |
| T11 | PASS |
| T12-T20 | PASS; see detailed outcomes below. T19 numerical OEE remains uncalculated because production start/end times are absent. |

## Writes and closeout

Permanent SB23 writes recorded for T01-T20:

- ProductionLot 19 and 20 creation, including history IDs 44 and 45.
- PressProduction assignments PPID 15 and 16.
- EDIT of PPID 15 from F7 to F8.
- Dispatch/Counter/Curing save on PPID 15 (75/100/80), creating MouldUsageID 10.
- T07 EDIT of PPID 15 from MouldID 29 to 30; MouldUsageID 10 updated in place, UsageCycles remained 100.
- T08 EDIT of PPID 15 from Shift 1 to Shift 2.
- T09 valid quantity save on PPID 15 (75/100/80); the preceding invalid curing attempt was rejected without writes.
- T10 RELEASE of PPID 15 and ADD of a new F8/MouldID 30/Shift 2 episode, PPID 17.
- T12 RELEASE of PPID 17. The subsequent UNDO RELEASE attempt for PPID 15 was rejected by the historical-episode guard and made no further changes.
- T14 ADD of PPID 18 (Lot 19/F8/MouldID 30/Shift 1), followed by quantity 1/1/1 and MANUAL downtime saves on PPID 18 and PPID 16. These generated MouldUsageIDs 11 and 12 and EquipmentTimeEventIDs 57-68.
- T16 concurrent ADD generated PPID 19 on Lot 20/F9/MouldID 29/Shift 1; the competing request was rejected.
- Closeout RELEASE of PPID 16, PPID 18, and PPID 19. PPID 15 and PPID 17 had already been released.

The first T14 save attempt with quantity fields omitted returned a success redirect but persisted no downtime; the UI's required Counter field had also prevented its form submit. The service saves manual downtime only when CounterQty is positive or the assignment already has MouldUsage. The authorized application workflow was then used with Dispatch/Counter/Curing = 1/1/1 on PPID 18 and PPID 16. No direct SQL data writes were made.

### T12-T20 verification details

- **T12:** Before release, PPID 17 had no quantities, MouldUsage, Lot 19 EquipmentTimeEvent, or matching F8/Shift 2 LoggerEvent dependency. RELEASE PPID 17 succeeded. UNDO RELEASE PPID 15 returned `MOULD_ALREADY_REASSIGNED: this Mould is already assigned to another Press.` PPID 15 remained released; PressProduction stayed 17, MouldUsage 10, EquipmentTimeEvent 56, LoggerEvent 10. No unintended state change.
- **T13:** Lot 19's F8/MouldID 30/Shift 2 episodes were PPID 15 (created 17:49:22, released 18:22:23) and PPID 17 (created 18:22:55, released 18:31:56). Each retained a distinct PressProductionID.
- **T14:** PPID 18 was created as F8/MouldID 30/Shift 1. PPID 18 saved 1/1/1 and MouldUsageID 11 (1 cycle); PPID 16 saved 1/1/1 and MouldUsageID 12 (1 cycle). MANUAL events 57-62 are F8/Shift 1 (SETUP 11.5, BREAKDOWN 3.5; other categories 0); events 63-68 are F7/Shift 2 (SETUP 21.5, BREAKDOWN 6.5; other categories 0). No LoggerEvent was created.
- **T15:** LOG CAL for PPID 18 and PPID 16 returned no present LOGGER categories for 2026-09-02. The Shift 1 button changed only the PPID 18 browser inputs; PPID 16's Shift 2 inputs remained 21.5/6.5. Persisted EquipmentTimeEvent values and LoggerEvent count 10 were unchanged. There were no source LOGGER events with which to demonstrate a positive import.
- **T16:** Independent concurrent requests targeted Lot 19 and Lot 20 with F9/MouldID 29/Shift 1. Lot 20 succeeded as PPID 19; exactly one target assignment existed. A local CP1252 output error obscured the concurrent losing response text; a follow-up request for Lot 19 was explicitly rejected with the active-Press conflict and made no changes.
- **T17:** The UI rejected Curing 2 against Counter 1 on PPID 16 (`Curing Qty cannot exceed Counter Qty`). PPID 16 remained 1/1/1; MouldUsageID 12 stayed at 1 cycle; downtime IDs 63-68 remained unchanged; counts did not change.
- **T18:** Recalculated all seven fingerprints using `json.dumps(data, sort_keys=True, default=str, separators=(',', ':'), ensure_ascii=False).encode('utf-8')`, `SELECT *`, primary-key ordering, and original row scopes. Original ProductionLot 1-18, ProductionLotHistory 1-43, PressProduction 1-14, MouldUsage 1-9, EquipmentTimeEvent 1-56, full LoggerEvent, and full ProductionData all match the baseline hashes listed above.
- **T19:** PRINT OEE for 2026-09-02 contained exactly five assignment rows: PPID 16 (Shift 2), PPIDs 15/17 (Shift 2), PPID 18 (Shift 1), and PPID 19 (Shift 1). Counts were shown once per episode: PPID 15 has 100/80; PPID 17 is null. Downtime totals were 28.00 for F7/Shift 2 and 15.00 for F8/Shift 1, each appearing once. PPIDs 15/17 were flagged `Ambiguous Press/Shift downtime` and excluded from summaries. All rows were excluded from OEE calculations for invalid production time; shift/all-day summary counts remained zero and OEE was `-`.
- **T20:** LoggerEvent remains 10 rows with SHA-256 `ece8b5d50b75bf3c6abe3c2a96a6a06bb718f74718e0c8dcfbfea86fd08732b8`.

### Final state and closeout

Both Lots remain active and retained: ProductionID 19 / `I11690902` / MTS024 and ProductionID 20 / `I11690903` / MTS028. All five TEST assignments are released: PPIDs 15-19. No active TEST assignments remain. MouldUsageIDs 10, 11, and 12 and EquipmentTimeEventIDs 57-68 remain as permanent test history. Current counts are PressProduction 19, MouldUsage 12, EquipmentTimeEvent 68, LoggerEvent 10, and ProductionLotHistory 45.

Final baseline fingerprints for all seven data sets match; the original 14 PressProduction rows and full LoggerEvent table are unchanged. The FittingMES server was left running. No schema changes, migrations, master-data edits, LoggerEvent modifications, source edits, commits, or pushes were performed during this continuation.
