# FittingMES REJECT / Production Reconciliation Handoff

**Date:** 2026-10-07
**Project:** `D:\AI\FittingMES`
**Database:** SB23
**Status:** Production and Depallet REJECT FINAL workflows complete; Depallet manually verified

## Purpose and current state

The REJECT tab records detailed RAW transactions. Production and Depallet
each load, preview, edit, and save their own normalized FINAL
reconciliation. RAW and FINAL are intentionally independent.

```text
REJECT tab -> ProductionRejectEntry RAW
Production page LOAD -> saved ProductionRejectFinal
Production-page REJECT CAL -> fresh whole-Lot RAW browser preview
operator edits -> SAVE REJECT -> normalized FINAL snapshot
```

The implementation is complete in the current worktree. SQL migration
`025_production_reject_final.sql` and `026_depallet_reject_final.sql` have
been applied and verified on live SB23. Do not rerun them. This handoff
does not authorize any further database action.

## 1. RAW transactions and multi-shift behavior

`dbo.ProductionRejectEntry` remains the RAW/detail transaction source. A
RAW row retains its actual `ProductionDate`, `ShiftID`, `LineEquipmentID`,
`SourceEquipmentID`, `RejectReasonID`, and `Qty`.

`ProductionID` identifies the whole Production Lot. One ProductionID may
have RAW transactions from multiple transaction shifts; `ProductionLot.Shift`
does not restrict the transaction ShiftID. Saving Production FINAL never
rewrites, deletes, consolidates, or fabricates RAW rows.

Depallet retains its existing Shift/Lot matching behavior.

## 2. Standalone REJECT-tab CAL

The standalone `/reject/cal` page remains shift-specific. Its RAW query is
filtered by:

```text
ProductionDate + selected ShiftID + ProductionID
```

For Production workflow, the Lot is validated by ProductionID, selected
Production Date, and active status; its `ProductionLot.Shift` need not
equal the selected RAW transaction shift. The selected shift remains the
shift filter for CAL itself and is shown in the CAL heading and BACK TO
REJECT context. Depallet continues to require its existing Shift/Lot match.

Manual verification for ProductionID 13 / Lot `I11691001 · Angle Ridge`
on 2026-10-01:

```text
Shift 1: 23 qty / 5 entries
Shift 2: 10 qty / 2 entries
```

The Shift 2 total did not include Shift 1 transactions.

## 3. Production-page whole-Lot CAL

Production-page REJECT CAL is distinct from standalone REJECT-tab CAL.
It uses `ProductionID` as the Lot identity, validates RAW dates against
the authoritative active Lot date, groups RAW by `RejectReasonID`, and
aggregates across all shifts, Lines, and Sources. It has no ShiftID,
LineEquipmentID, or SourceEquipmentID filter.

CAL is read-only browser preview state. It replaces the editable Qty
values with fresh RAW grouped totals and updates Calculated Reject; it
does not write FINAL or change persisted Qty/Day.

## 4. Applicable reasons and FINAL schema

Applicable active reasons are selected dynamically using the existing
relationship and activity rules:

```text
ProductionLot.ProductFamilyID
 -> RejectReasonProductFamily
 -> active RejectReason
 -> active RejectCatalog and RejectSourceScope
```

`dbo.RejectReason` remains the sole authoritative reason master. FINAL
storage is normalized:

- `dbo.ProductionRejectFinal`: one header per ProductionID, enforced by
  `UNIQUE (ProductionID)`. There is no ShiftID in FINAL identity.
- `dbo.ProductionRejectFinalDetail`: reason-level rows, unique by
  `(ProductionRejectFinalID, RejectReasonID)`.

Every applicable reason receives a detail row, including zeros.
`RawQtyAtSave` records the fresh RAW quantity at SAVE time;
`FinalQty` records the operator-approved value. The header raw total is
the sum of the detail RawQtyAtSave values. Stale/non-applicable RAW
reason IDs block CAL and SAVE with an error; they are not ignored or
fabricated into FINAL details.

There are no Rxxx quantity columns, no mapping back to legacy R01-R24/R99,
and no `RejectReasonLegacyMap`.

## 5. Total, SAVE, LOAD, and Qty/Day semantics

```text
Total Wet Reject = CounterQty - CuringQty
Final Classified Reject = sum of saved/current FinalQty
Difference / Unclassified = Total Wet Reject - Final Classified Reject
```

Counter/Curing values are validated; invalid negative values and
`CuringQty > CounterQty` are not silently clamped and block SAVE.

- Normal page LOAD displays saved FINAL values if present, otherwise zero.
  It does not recalculate or overwrite FINAL from RAW.
- REJECT CAL replaces editable browser Qty values with fresh whole-Lot
  RAW totals. The operator may edit any Qty before SAVE.
- SAVE re-reads authoritative Lot/ProductFamily/date, active applicable
  reasons, ProductionData, and fresh whole-Lot RAW. It validates and
  atomically upserts the header and replaces the complete detail snapshot.
- Re-CAL after SAVE shows fresh RAW values in the browser but does not
  alter saved FINAL or Qty/Day unless SAVE REJECT is pressed again.
- Refresh/F5 after an unsaved CAL restores saved FINAL values; calculated
  RAW preview returns to `—`.
- Qty/Day is derived from `ProductionRejectFinalDetail.FinalQty` across
  active Production Lots for the selected date, grouped by RejectReasonID.
  It is not stored as a separate field. Re-saving a Lot replaces that
  Lot’s contribution rather than duplicating it.

Production FINAL SAVE never modifies `ProductionRejectEntry` or legacy
`WetReject` data.

## 6. Production REJECT layout

The Production reason list is dynamically split into exactly three
contiguous display groups, preserving master/display ordering. Group sizes
are rebalanced from the current applicable reason count (for 26 Prestige
reasons: 9 / 9 / 8). Each table shows:

```text
Code | Reject Reason | Qty | Qty/Day
```

All three tables are inside one form; each applicable RejectReasonID has
one Qty input, and CAL, manual editing, totals, and SAVE cover all groups.
The template contains no hardcoded R201-R299 reason list.

## 7. Manually verified ProductionID 13 reconciliation

Target:

```text
Production Date: 2026-10-01
ProductionID: 13
Lot: I11691001 · Angle Ridge
ProductFamily: Prestige
Total Wet Reject: 180
```

RAW comprises seven individual transactions across Shift 1 and Shift 2:

```text
R201 = 8 (Shift 1 = 3, Shift 2 = 5)
R202 = 5
R204 = 2
R207 = 6
R208 = 4
R212 = 8
RAW total = 33
```

The initial FINAL save created one header and 26 applicable detail rows:

```text
RawTotalQtyAtSave = 33
FinalClassifiedQtyAtSave = 33
UnclassifiedQtyAtSave = 147
TotalWetRejectAtSave = 180
```

The operator then edited R201 from RAW 8 to FINAL 10 and saved. Read-only
database verification confirmed the existing header was updated, not
duplicated:

```text
RawTotalQtyAtSave = 33
FinalClassifiedQtyAtSave = 35
UnclassifiedQtyAtSave = 145
TotalWetRejectAtSave = 180
R201 RawQtyAtSave = 8; FinalQty = 10
Qty/Day R201 = 10
```

All seven RAW rows remained intact; detail raw sum was 33, detail FINAL
sum was 35, and there were no duplicate header/reason keys.

Critical re-CAL/refresh browser verification:

1. After saving FINAL 35, REJECT CAL displayed fresh RAW R201 = 8 and
   Calculated Reject = 33.
2. The operator did not save that preview.
3. Browser refresh restored saved FINAL R201 = 10, Final Classified
   Reject = 35, Difference / Unclassified = 145, Qty/Day R201 = 10, and
   Calculated Reject = `—`.

This confirms RAW preview and persisted FINAL remain separate.

## 8. Existing REJECT Source/session context

Preserve the existing browser `sessionStorage` behavior for Shift,
Reject Of, Line, Product/Lot, and compatible Source. Qty, Reject Reason,
and edit mode are not remembered. SAVE retains compatible context and
clears Qty/Reason. EDIT uses the saved row’s actual fields; CANCEL restores
normal remembered context. The browser compatibility fix uses
`Array.from(select.options).some(...)`.

## 9. Migration and legacy boundary

`sql/025_production_reject_final.sql` creates the normalized Production
FINAL tables. `sql/026_depallet_reject_final.sql` creates the normalized
Depallet FINAL tables, adds exact DepalletID identity to
`DepalletRejectEntry`, and allows nullable Depallet Source. Both
migrations were deployed to SB23 and verified. Migration 026 preflight
found zero rows in the old DepalletRejectEntry table; it was recreated
as designed. No legacy reject-data migration/backfill was performed.
Do not rerun either migration.

Legacy `WetReject`, `WetRejectReasonMaster`, legacy R01-R24/R99 behavior,
and legacy REJECT API/PIS code remain separate and are not rewritten by
this implementation. A future API redesign/cutover may be considered as
a separate approved project; it is not a blocker for the verified
Production FINAL workflow.

## 10. Regression verification

The original Production-only checkpoint's focused results (before the
Depallet implementation) were:

```text
test_reject*.py: 76 passed
test_production_reject_final*.py: 24 passed
test_wet_reject.py: 28 passed
test_depallet*.py: 58 passed
node tests/test_reject_ui.cjs: passed
git diff --check: passed
```

The full Python suite ran 519 tests and retained three unrelated Mould
failures: two Production Date rendering assertions in
`test_mould_page_accepts_missing_empty_and_valid_navigation_date` and one
`mould_redirect()` unexpected `navigation` keyword argument in
`test_mould_redirect_preserves_filters_and_omits_invalid_or_empty_date`.
No unrelated Mould code was changed.

## Current pause point

Production multi-shift RAW entry, shift-specific standalone REJECT CAL,
whole-Lot Production-page REJECT CAL, editable/saved FINAL reconciliation,
three-column dynamic reason layout, Qty/Day, and re-CAL/refresh separation
are implemented and manually verified. There is no remaining Production
FINAL implementation step in this block. Any future legacy API/PIS
redesign or broader cutover requires a separate request and review.

## 10. Depallet REJECT RAW / CAL / FINAL

The exact Depallet-run identity is `dbo.Depallet.DepalletID`. `ProductionID`
identifies the underlying Lot only; a Lot may have multiple runs.
`RunSequence` is the ordering value displayed as `SEQ n`, never the RUN
identity. The REJECT tab's Depallet Product / Lot selector is populated
from existing Depallet runs for the selected shared Production Date. Each
run remains a separate option keyed by DepalletID, with both that ID and
its ProductionID submitted. There is no separate Depallet Run selector.
REJECT and REJECT CAL RUN labels use the actual DepalletID.

Production RAW Source is required and its behavior is unchanged. Depallet
RAW Source is optional: SQL NULL means the machine was not identified.
No placeholder EquipmentMaster record is used. Line, Shift, ProductionID,
DepalletID, applicable reason/scope, and Qty remain validated.

`DepalletRejectEntry` is immutable RAW detail. Depallet CAL reads fresh
RAW for the exact selected DepalletID and groups by RejectReasonID; both
known-Source and NULL-Source entries are included. CAL only replaces
browser quantities and does not write FINAL. SAVE REJECT atomically
upserts the single `DepalletRejectFinal` header keyed by DepalletID and
replaces only that header's normalized reason details. Re-saving a run
does not duplicate its FINAL or affect another run's FINAL. RAW is never
rewritten by FINAL save. Load shows saved FinalQty and leaves Calculated
Reject at `—` until CAL is performed.

Depallet Total Reject remains `DepalletQty - GoodQty`.
Final Classified Reject is the selected run's saved/current FinalQty sum;
Difference / Unclassified is Total Reject less that sum. Qty/Day sums
saved FINAL detail quantities by RejectReasonID across Depallet runs on
the selected Depallet Date, while the current-run quantities remain
isolated by DepalletID.

The Depallet page's compact REJECT header contains the selected Lot/RUN,
Remark, SAVE REJECT, REJECT CAL, and the four summaries. Its reason grid
uses the existing RejectReason/ProductFamily mapping and preserves
master order while dynamically splitting the applicable reasons into
three contiguous balanced groups:

```text
Code | Reject Reason | Qty | Qty/Day
```

SAVE DEPALLET remains the separate operational batch action beside
DEPALLET LOTS; it saves Depallet operational row values and is not the
FINAL reject action. Legacy `WetReject`, `dbo.DepalletReject`, and
legacy API/PIS behavior were not redesigned. Retiring or redesigning
legacy APIs remains separate future work.

## 11. Depallet manual verification and run isolation

Manual verification was completed for Production Date `2026-10-01`,
Lot `I11691001 · Angle Ridge`, DepalletID / RUN 7, Shift 1, LINE2 (DRY),
with Source intentionally blank:

```text
RAW: R201=3, R208=2, R222=8, R223=41; total=54
Total Reject=500
After CAL: Calculated Reject=54, Final Classified Reject=54,
           Difference / Unclassified=446
CAL did not persist FINAL.
After SAVE REJECT and reload: Calculated Reject=—,
  Final Classified Reject=54, Difference / Unclassified=446
  Qty and Qty/Day: R201=3, R208=2, R222=8, R223=41
```

Automated mock-backed coverage also uses RUN 71 and RUN 72 sharing one
ProductionID. It verifies each run's CAL excludes the other's RAW,
saving/re-saving one FINAL leaves the other run's header/details unchanged,
current-run Qty is isolated, and daily Qty/Day aggregates saved FINAL
across runs. Schema coverage verifies FINAL uniqueness by DepalletID, not
ProductionID. No test data was inserted into SB23.

All current REJECT/Depallet transaction data is test data, not real
production data. No legacy reject-data migration is required.

## 12. Current focused verification

```text
test_reject*.py: 79 passed
test_depallet*.py: 67 passed
node tests/test_reject_ui.cjs: passed
node tests/test_depallet_ui.cjs: passed
git diff --check: passed
```

These are focused code/test-double checks, not new database verification.
Production RAW multi-shift behavior and Production CAL/FINAL/SAVE/Qty/Day
remain complete and unchanged. No unrelated Mould changes are part of
this implementation.
