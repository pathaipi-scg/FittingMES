# FittingMES Final Handover — 2026-10-09

## Project status

The approved Shift-aware Press/Mould, Step 9, and PRINT OEE implementation
is complete and pushed to `origin/main`.

- Implementation commit: `745bf985348d6f3356fb7b09212989631e10dca7`
- Branch: `main`
- Python regression suite: **614 passed**
- JavaScript regression suites: **7 passed**
- Focused regression results: PRINT OEE **21 passed**, Press Production
  **91 passed**, LOGGER guide **10 passed**
- `git diff --check`: **passed**

The handover itself is maintained as a separate documentation-only change.

## Completed implementation and business rules

- ADD FITTING stores a separate PressProduction assignment for each saved
  Shift. Press and Mould availability is scoped to Production Date + Shift
  across Lots; server-side validation and transaction locks remain
  authoritative.
- EDIT FITTING retains the existing PressProductionID and actual saved Shift.
  Legacy assignments with unknown Shift remain unknown; do not infer Shift 1.
- RELEASE MOULD preserves assignment history. UNDO RELEASE checks for later
  or conflicting Press/Mould assignments.
- One row-level SAVE persists production quantities and manual downtime.
  Downtime can be saved with CounterQty NULL, zero, or omitted and without
  MouldUsage; it does not create dummy quantities or MouldUsage. Omitted
  quantity values are preserved. MANUAL event summaries are idempotent.
- Manual downtime uses the established identity
  `ProductionID + EquipmentCode + ShiftID + TimeType + SourceType`.
  Ambiguous repeated Press/Shift episodes are not assigned downtime
  speculatively.
- LOG CAL remains a GET-only guide operation. It does not persist data until
  the operator uses SAVE.
- PRINT OEE derives production Start/End from the parent Lot's
  `ProductionData`, then allocates the Lot interval to each saved Shift using
  effective configured Shift boundaries. The Production Day cutoff is
  separate from Shift boundaries. Approved OEE formulas remain unchanged.

## Database and migration status

Migration 027 was already applied to live SB23 before Step 8C, as recorded in
the Step 8C handover. Existing legacy PressProduction rows retained NULL
ShiftMasterID and remain unknown. No migration was run during Step 9 or this
closeout. The migration, read-only preflight, and guarded rollback scripts
are committed artifacts only; do not execute them when resuming.

No live SB23 data was modified during final OEE investigation or this
closeout. The F9 finding below came from SELECT-only inspection.

## Final PRINT OEE verification and F9 exception

The final numerical values supplied for release were:

| Press / Shift | Result |
|---|---:|
| F7 / Shift 1 | OEE 51.01% |
| F7 / Shift 2 | OEE 66.67% |
| F8 / Shift 1 | OEE 50.00% |
| F9 / Shift 2 | Setup 995 minutes; excluded because allocated time is 480 minutes |
| All Day | OEE 54.81% |

The Lot interval 08:00–03:00 next day allocates 660 minutes to Shift 1 and
480 minutes to Shift 2 under the configured boundaries.

F9 Shift 2 has one directly stored MANUAL Setup value of 995 minutes. It
exceeds the allocated 480-minute interval by 515 minutes. SELECT-only
investigation found no duplicate event identity or repeated F9 Press/Shift
episode contributing to the total. The value is reported as an inconsistency;
it is not clamped or corrected automatically. Have the responsible operator
verify the original downtime record before any correction through the
approved application workflow.

### Browser/runtime discrepancy

During final Git review, the shared localhost PRINT OEE page for
2026-09-03 still displayed “Invalid production time” and unavailable OEE
ratios, even though the updated source and numerical fixtures use parent Lot
times. The page appears to be served by an older running build. The server
was not restarted during the implementation review. On a future approved
session, start the application deliberately and verify that the displayed
report reflects the committed source; do not treat the stale page as
validation of the new implementation.

## Outstanding issues and recommended next steps

1. Confirm the running/deployed application uses the pushed commit, then
   verify PRINT OEE for Production Date 2026-09-03 with a read-only review.
2. Ask the data owner to verify F9 Shift 2 Setup against the original record.
   Do not clamp 995 to 480; change the stored value only if the source record
   confirms an entry error and the user authorizes that correction.
3. Decide the expected interpretation for a single production run that
   straddles the 08:00 Production Day cutoff before changing or certifying
   that edge case.
4. Retain the unknown-Shift and ambiguous-episode safeguards. Do not create
   additional TEST Lots or repeat Step 8C T01–T20.
5. Before any future database or migration work, read the database skill,
   confirm target/environment and backup/restore readiness, and obtain
   explicit authorization for the exact operation.

## Important files, skills, and documentation

- Skills:
  - [DATABASE_ID_FIRST_DESIGN_SKILL.md](../skill/DATABASE_ID_FIRST_DESIGN_SKILL.md)
  - [FittingMES_LOGGER_Bidirectional_SKILL.md](../skill/FittingMES_LOGGER_Bidirectional_SKILL.md)
- Design and handover:
  - [Shift-aware Press/Mould design context](./FittingMES_Shift_Aware_Press_Mould_Design_Context_20261008.md)
  - [Step 8C handover](./FittingMES_Step8C_Handover_20261008.md)
  - [Step 8C execution register](./FittingMES_Step8C_T07-T20_Execution_Register_2026-10-08.md)
  - [Step 9 implementation report](./FittingMES_Step9_Implementation_Report.md)
- Implementation:
  - `app/press_production.py`, `app/main.py`
  - `app/templates/production.html`
  - `app/print_oee.py`
- Regression tests:
  - `tests/test_press_production.py`
  - `tests/test_press_production_ui.cjs`
  - `tests/test_print_oee.py`
  - `tests/test_logger_summary.py`
  - `tests/test_log_cal_copy.cjs`
  - `tests/test_shift_aware_press_migration.py`
- Migration artifacts (not to be executed without approval):
  - `sql/027_shift_aware_press_production_preflight.sql`
  - `sql/027_shift_aware_press_production.sql`
  - `sql/027_shift_aware_press_production_rollback.sql`

## Fresh-session resume instructions

1. Open the repository and read this handover, the Step 8C handover/register,
   the Shift-aware design context, and the Step 9 report.
2. Read `DATABASE_ID_FIRST_DESIGN_SKILL.md` before any database-related work;
   read the LOGGER bidirectional skill before changing LOGGER behavior.
3. Check the branch, HEAD, and Git status. Preserve unrelated user changes.
   The implementation checkpoint is
   `745bf985348d6f3356fb7b09212989631e10dca7` on `main`.
4. Run focused tests for the changed area, then the full Python and seven
   JavaScript regression suites if preparing a new change.
5. Treat SB23 as read-only unless the user explicitly approves a specific
   write. Do not rerun Migration 027, modify historical rows, or create TEST
   Lots.
6. Resolve the stale-server OEE discrepancy by an explicitly authorized
   application start/restart and read-only verification; do not infer live
   correctness from fixture results alone.
