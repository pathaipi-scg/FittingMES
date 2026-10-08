# FittingMES Step 9 Implementation Report

**Date:** 2026-10-09<br>
**Database:** SB23 (LIVE; Step 9B/9C fixtures were isolated; subsequent F9 investigation was SELECT-only)<br>
**Scope:** Step 9A status record, deterministic Step 9B and Step 9C validation

## Summary

- Step 9A independent downtime saving was completed in the preceding task.
- Step 9B positive LOGGER guide behavior was validated with isolated fixtures.
- Step 9C numerical PRINT OEE behavior was validated with isolated fixtures.
- Step 9B/9C fixture validation used no live SB23 reads or writes. A later
  read-only F9 investigation queried SB23; it made no data changes.
- No migrations, TEST Lots, server operations, or LOGGER schema/master
  changes were performed.
- A subsequent approved PRINT OEE correction changed the time source and
  Shift allocation in `app/print_oee.py`; the approved OEE formulas were not
  changed.

## Step 9A — Independent Downtime Saving

**PASS — recorded from the completed Step 9A implementation and user-provided
results:**

- Independent MANUAL downtime save accepts NULL, zero, or omitted CounterQty
  without requiring MouldUsage.
- The downtime-only action leaves quantities and MouldUsage untouched.
- Blank quantity fields are treated as omitted, preserving persisted values.
- Repeated saves update the existing MANUAL summary identity rather than
  inserting duplicate rows.
- Shift isolation, ambiguity protection, transaction rollback, and
  operator-visible validation are retained.
- The completed Step 9A validation recorded 89 focused tests and 592 Python
  tests passing, along with UI and LOG CAL JavaScript regressions passing.

Step 9A was not rewritten as part of this work.

## Step 9B — Positive LOG CAL Validation

**PASS — deterministic fixtures and read-only route checks:**

| Requirement | Evidence |
|---|---|
| Correct LOGGER source selection | The guide fixture uses active `Fitting_MainMachine` mapping, F-machine instance, authoritative stop IDs, and LOGGER events filtered by ProductionDate, McId, and McInstanceNo. |
| Production Date / Press / Shift isolation | Decoy events for another date and F instance are excluded. The guide route derives Lot date and equipment from the requested PressProduction row; each UI row has its own guide URL and selected Shift. |
| Category mapping | SETUP, CHANGEOVER, IDLE, CLEAN, SMDT, and BREAKDOWN are verified from their LOGGER StopId mappings. |
| Zero-value replacement | Fixture values of zero replace the existing client input values; present-zero events retain `present: true`. |
| No automatic persistence on LOG CAL | UI fixture observes only the row-specific guide fetch, with no POST or Save operation. The guide route is GET-only and executes read-only queries. |
| Persistence after operator SAVE | An isolated route-to-service test saves the populated values to MANUAL EquipmentTimeEvent identities for the selected Shift. |
| No LoggerEvent modifications | The fixture LoggerEvent collection remains unchanged through guide read and Production SAVE; persistence is verified through MANUAL EquipmentTimeEvent rows while quantities and MouldUsage remain unchanged. |
| Multiple Press Production row isolation | Two rows with different Lot/date, Press, and Shift are exercised independently; clicking one leaves the other row unchanged. |
| Existing LOGGER bidirectional rules | LOGGER UI, page, service, and classification tests remain in the full regression suite; no LOGGER implementation files were changed. |

The focused `test_logger_summary.py` suite passed 10 tests. The expanded
`test_log_cal_copy.cjs` fixture passed. The guide-to-SAVE route integration
test passed as part of the 91-test Press Production suite.

## Step 9C — Numerical PRINT OEE Validation

**PASS — deterministic calculation and report-context fixtures:**

- **Shift 1 fixture:** 09:00–13:00, 240 planned minutes, 30 minutes of
  attributed loss, 210 runtime minutes, Counter 84, Curing 70, speed 0.4.
  Expected and verified: Availability 0.875, Performance 1, Quality 5/6,
  OEE approximately 0.7291666666666667.
- **Shift 2 fixture:** 21:00–02:00 across midnight, 300 planned minutes,
  30 minutes of attributed loss, 270 runtime minutes, Counter 108, Curing 90,
  speed 0.4. Expected and verified: Availability 0.9, Performance 1,
  Quality 5/6, OEE 0.75.
- **Production-day cutoff and Shift allocation:** with an 08:00 day-start
  rule, a 05:00–07:00 Lot interval maps both endpoints to the following
  calendar date. With configured Shift 2 ending at 06:00, the allocated
  overlap is 60 minutes; the Production Day cutoff is not treated as a Shift
  boundary.
- **SMDT:** for the Shift 1 four-hour interval and 30 minutes in the five
  standard loss categories, the existing residual calculation returns
  210 minutes.
- **Downtime attribution:** the query scopes events to MANUAL source, matching
  ProductionID, Press, and ShiftCode; SMDT is excluded from the OEE loss sum
  to avoid counting residual SMDT as another loss category.
- **Repeated episodes and ambiguity:** two same-Press/Shift episode fixtures
  flagged ambiguous are excluded from OEE and summary totals.
- **Released history:** the report-context fixture retains a released
  assignment row, and the report query has no active-only `ReleasedAt IS NULL`
  restriction.
- **Numerical summaries:** Shift 1 and Shift 2 summaries match the expected
  values above; only eligible episodes contribute to totals.
- **Formula integrity:** OEE implementation/formula files were not changed
  during Step 9B/9C.

The focused `test_print_oee.py` suite passed 21 tests after the Lot-time source
and Shift-overlap correction.

## Final PRINT OEE verification and known F9 exception

**PASS — final verification values supplied for this release:**

| Press / Shift | OEE / status |
|---|---:|
| F7 / Shift 1 | 51.01% |
| F7 / Shift 2 | 66.67% |
| F8 / Shift 1 | 50.00% |
| F9 / Shift 2 | Setup 995 minutes; exceeds the 480-minute allocated interval and is excluded |
| All Day | 54.81% |

The PRINT OEE calculation now takes production Start/End from the parent
Production Lot's `ProductionData`, then intersects that interval with the
effective configured Shift boundaries. For the 08:00–03:00 cross-midnight
Lot interval, the deterministic regression tests verify Shift 1 = 660
minutes and Shift 2 = 480 minutes. PressProduction Start/End values are not
required.

F9 Shift 2's 995-minute Setup is retained as a known data exception. It
exceeds the allocated 480 minutes, is reported as an inconsistency, and does
not produce valid OEE ratios. It was not clamped or corrected automatically.

The shared localhost PRINT OEE page was also read without interaction on
2026-10-09. It still showed `Invalid production time` and unavailable OEE
ratios for the listed rows, rather than the final values above. The server
was not restarted; therefore those values are recorded as the supplied final
verification, while the currently running page appears not to reflect the
updated Lot-time implementation.

## Final Validation

**PASS**

- Full Python unittest suite: **614 tests passed**.
- All seven JavaScript regression files passed.
- Focused suites: LOGGER guide 10 passed; PRINT OEE 21 passed; Press Production
  91 passed.
- Python compilation passed for the relevant application and test modules.
- `git diff --check` passed.

**FAIL**

- None in the final validation runs.

**BLOCKED**

- A single production run that straddles the 08:00 production-day cutoff has
  no approved expected interpretation in this scope. No cutoff-crossing
  behavior was changed; define the desired business rule before altering or
  certifying that case.

**NOT TESTED**

- Live SB23 behavior and live source LOGGER rows; all validation used
  deterministic in-memory fixtures as required.
- Real-browser end-to-end interaction; the LOG CAL client behavior was
  validated with the existing Node JavaScript harness.
- A positive LOGGER event spanning multiple category rows with duplicate
  production master mappings; the fixture uses the verified unique active
  machine mapping and authoritative StopType rows.

## Git Scope and Preservation

The working tree was already dirty at the start of Step 9B/9C. The final
scope includes the Shift-aware Press Production implementation, Step 8C
preflight/migration artifacts and documentation, Step 9 regression fixtures,
and the PRINT OEE parent-Lot-time correction. The follow-up OEE correction
changed `app/print_oee.py` and `tests/test_print_oee.py`; the OEE formulas were
preserved. No unrelated application changes or live database changes were
made. This report accompanies the approved final Git changes.
