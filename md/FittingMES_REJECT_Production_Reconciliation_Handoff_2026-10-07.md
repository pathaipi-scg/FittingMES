# FittingMES --- REJECT / Production Reconciliation Handoff

**Date:** 2026-10-07\
**Project:** `D:\AI\FittingMES`\
**Database:** SB23\
**Status:** Design paused --- **do not implement the new Production
REJECT Final schema yet**

------------------------------------------------------------------------

## 1. Purpose of this handoff

This document records the decisions and investigation completed for the
new REJECT workflow so work can resume later without repeating the
design discussion.

The main objective is to connect the new **REJECT tab** to the
**Production page** while keeping detailed operator entries (RAW)
separate from the final Production reconciliation (FINAL).

The intended flow is:

``` text
REJECT tab
   |
   | detailed RAW entries
   v
dbo.ProductionRejectEntry
   |
   | REJECT CAL (whole Lot)
   v
Production page editable Qty
   |
   | operator may adjust quantities
   v
SAVE REJECT
   |
   v
New normalized FINAL reconciliation tables
```

------------------------------------------------------------------------

## 2. Current REJECT master is authoritative

There must be **one Reject Reason master only**.

The existing master already used by the REJECT tab is authoritative:

-   `dbo.RejectCatalog`
-   `dbo.RejectReason`
-   `dbo.RejectReasonProductFamily`
-   `dbo.RejectSourceScope`

The identity used by transaction/final data is:

``` text
RejectReasonID -> dbo.RejectReason.id
```

`dbo.RejectReason` already contains the R1xx/R2xx/R3xx definitions such
as:

-   `ReasonCode`
-   `ReasonNameTH`
-   `RejectCatalogID`
-   `RejectSourceScopeID`
-   `SortOrder`
-   `IsOther`
-   `IsActive`

Product applicability already comes from:

``` text
ProductionLot.ProductFamilyID
    -> RejectReasonProductFamily.ProductFamilyID
    -> RejectReasonProductFamily.RejectReasonID
    -> RejectReason.id
```

### Hard rules

Do **not**:

-   create another Reject Reason master;
-   create a Production-specific reason master;
-   duplicate Rxxx definitions into a new table;
-   store R201/R202/... as quantity columns;
-   hardcode a fixed number of reject reasons in the Production page.

All reject quantity storage must remain **row-based / normalized**.

Example:

``` text
FinalHeaderID | RejectReasonID | FinalQty
100           | 35             | 3
100           | 41             | 7
100           | 42             | 4
```

The R-code and Thai name are obtained by joining `dbo.RejectReason`.

------------------------------------------------------------------------

## 3. RAW source of truth

The RAW/detail transaction source is:

``` text
dbo.ProductionRejectEntry
```

Current RAW dimensions include:

``` text
ProductionDate
ShiftID
LineEquipmentID
SourceEquipmentID
RejectSourceScopeID
ProductionID
RejectReasonID
Qty
```

This is appropriate for detailed operator-entered transactions.

RAW must preserve:

-   Shift;
-   Line;
-   Source/Press;
-   Source Scope;
-   Reject Reason;
-   Qty;
-   Production Lot identity.

### Important rule

Production reconciliation edits must **never** rewrite, delete,
consolidate, or fabricate `ProductionRejectEntry` rows merely to make
RAW totals equal FINAL totals.

Example:

``` text
RAW R207 = 6
Operator FINAL R207 = 7
```

Both facts must remain distinguishable.

------------------------------------------------------------------------

## 4. Whole-Lot identity

Copilot traced the current repository model and found:

``` text
One active business Production Lot = one ProductionID
```

`ProductionID` is currently the relational identity used by:

-   `ProductionLot`;
-   `ProductionData`;
-   `ProductionRejectEntry`;
-   Production-page lot selection;
-   Production routes.

`LotNo` is a display/business number and must **not** be used as the
relational key for FINAL persistence.

### FINAL identity

The proposed FINAL identity is therefore:

``` text
one ProductionRejectFinal row per ProductionID
```

with:

``` sql
UNIQUE (ProductionID)
```

**ShiftID must not be part of the FINAL identity.**

Shift, Source and Line remain RAW/detail dimensions only.

------------------------------------------------------------------------

## 5. Production RAW multi-shift behavior --- resolved

``` text
ProductionID = whole Production Lot identity
ShiftID      = actual Shift in which the RAW reject transaction occurred
```

Production RAW entries allow multiple transaction Shift IDs for one
ProductionID; `ProductionLot.Shift` does not restrict the actual Shift.

The Production workflow Lot selection does not filter out a valid Lot
when the transaction Shift changes; it remains subject to the selected
Production Date and active-Lot validation.

Depallet retains its previous Shift/Lot matching behavior.

Manual browser-to-database verification passed on 2026-10-07:

``` text
Production Date: 2026-10-01
Workflow: Production
ProductionID: 13
Lot: I11691001 · Angle Ridge
Line: LINE2
Source: F7

Shift 1 / F7 / R201 / Qty 3
Shift 2 / F7 / R201 / Qty 5
```

The Lot and compatible Source remained selected when changing Shift 1 to
Shift 2. The Shift 2 RAW entry saved and appeared alongside the Shift 1
entry after reload. After SAVE, Shift, workflow, Line, Lot and Source
remained selected, while Qty and Reject Reason were cleared.

The standalone REJECT CAL is also currently shift-specific.
Production-page REJECT CAL needs a separate whole-Lot aggregation
behavior.

------------------------------------------------------------------------

## 6. Meaning of Production Qty

On the Production page, each Reject Reason `Qty` means the quantity for
the **whole Lot**.

It must combine:

-   Shift 1 + Shift 2;
-   every Source/Press that produced that Lot;
-   every Line involved with that Lot;
-   all valid RAW entries for the selected `ProductionID`.

Example RAW:

``` text
ProductionID X / Shift 1 / F7  / R201 = 3
ProductionID X / Shift 1 / F10 / R201 = 2
ProductionID X / Shift 2 / F7  / R201 = 4
ProductionID X / Shift 2 / F10 / R201 = 1
```

Production REJECT CAL:

``` text
R201 Qty = 10
```

The Production whole-Lot CAL must therefore aggregate by:

``` text
ProductionID + RejectReasonID
```

and must **not** filter by:

-   ShiftID;
-   SourceEquipmentID;
-   LineEquipmentID.

It must still validate the selected Lot/date context so data from
another Lot/date cannot leak into the result.

------------------------------------------------------------------------

## 7. Production page workflow

### LOAD

For selected `ProductionID`:

1.  Load the selected Production Lot.
2.  Load `ProductFamilyID`.
3.  Load applicable active Reject Reasons from the existing REJECT
    master.
4.  Load the single `ProductionData` row for the same `ProductionID`.
5.  Calculate Total Wet Reject.
6.  Load saved FINAL reconciliation by `ProductionID`.
7.  If FINAL exists, show saved `FinalQty`.
8.  If FINAL does not exist, show zero Qty values.
9.  Calculate/display Qty/Day from saved FINAL data for the Production
    Date.
10. Do **not** automatically run RAW REJECT CAL on ordinary page load.

### REJECT CAL

`REJECT CAL` is read-only.

It must:

1.  use selected `ProductionID`;
2.  read **only** `dbo.ProductionRejectEntry`;
3.  include all shifts, Sources and Lines for that ProductionID;
4.  group by `RejectReasonID`;
5.  populate the editable Qty fields;
6.  update Calculated Reject;
7.  update Final Classified Reject based on current editable values;
8.  update Difference / Unclassified;
9.  perform **no DB write**;
10. leave the previously saved FINAL untouched;
11. leave persisted Qty/Day unchanged until SAVE.

### EDIT

After CAL, the operator may edit any applicable reason Qty.

Edits are browser/form state only until SAVE.

Example:

``` text
CAL:
R201 = 3
R207 = 6
R208 = 4
R212 = 8

Operator changes:
R201 = 3
R207 = 7
R208 = 4
R212 = 6
```

RAW remains unchanged.

### SAVE REJECT

SAVE persists the operator-approved FINAL quantities.

The intended semantics are:

``` text
RAW ProductionRejectEntry
    !=
FINAL Production reconciliation
```

SAVE should:

-   validate selected `ProductionID`;
-   load authoritative Lot/ProductFamily/date from DB;
-   validate every submitted `RejectReasonID`;
-   reject inactive/non-applicable reasons;
-   validate non-negative integer Qty;
-   recalculate Total Wet Reject server-side;
-   recalculate fresh whole-Lot RAW quantities for audit;
-   validate Final Classified Reject against Total Wet Reject;
-   upsert one FINAL header for the ProductionID;
-   replace/update the detail snapshot atomically;
-   never modify RAW rows.

### RE-CAL after SAVE

If FINAL already exists and the operator presses REJECT CAL:

-   fresh RAW totals replace the current editable fields;
-   saved FINAL in DB remains unchanged;
-   Qty/Day remains based on saved FINAL;
-   another SAVE is required to persist the newly displayed/edited
    values.

------------------------------------------------------------------------

## 8. Production UI

Preferred Production REJECT grid:

``` text
Code | Reject Reason | Qty | Qty/Day
R201 | ...           | [ ] | ...
R202 | ...           | [ ] | ...
R203 | ...           | [ ] | ...
```

`Code` and `Reject Reason` come dynamically from the existing
`RejectReason` master.

`Qty` is editable.

Buttons:

``` text
[SAVE REJECT] [REJECT CAL]
```

Do not continue using the label `SAVE WET REJECT` for the new FINAL
persistence semantics.

Summary should show:

``` text
Total Wet Reject
Calculated Reject
Final Classified Reject
Difference / Unclassified
Remark
```

No separate editable "Calculated Qty" and "Final Qty" columns are
required. REJECT CAL directly populates the editable Qty field.

------------------------------------------------------------------------

## 9. Qty/Day --- confirmed requirement

**Qty/Day must remain on the Production page.**

Meaning:

### Qty

``` text
Qty = FINAL/current editable quantity for this whole Lot
```

For CAL, it is initially populated from whole-Lot RAW totals.

### Qty/Day

``` text
Qty/Day =
SUM(saved FINAL FinalQty)
for the same Production Date
grouped by RejectReasonID
across all saved active Production Lots
```

Qty/Day should use **FINAL**, not RAW.

Reason:

-   Production operators can adjust CAL results before SAVE;
-   Qty/Day should represent approved/persisted Production quantities;
-   this preserves the legacy business meaning of a daily total based on
    persisted reject quantities.

Qty/Day is **derived display data**. Do not store a `QtyPerDay` field in
each detail row.

### Before current Lot is saved

-   current editable Qty may contain fresh CAL values;
-   current unsaved Lot contributes zero to persisted Qty/Day;
-   other saved Lots still contribute.

### After SAVE

-   the current Lot's saved FinalQty contributes to Qty/Day;
-   re-saving replaces the Lot's previous contribution, not duplicates
    it.

------------------------------------------------------------------------

## 10. Total Wet Reject and reconciliation totals

Business concepts:

``` text
Total Wet Reject
    = CounterQty - CuringQty
    for the selected whole ProductionID

Calculated Reject
    = SUM whole-Lot RAW ProductionRejectEntry Qty
    from the most recent REJECT CAL shown in the form

Final Classified Reject
    = SUM current editable/saved FINAL Qty

Difference / Unclassified
    = Total Wet Reject - Final Classified Reject
```

`ProductionData` has one row per `ProductionID`, so CounterQty/CuringQty
should not be summed across shifts.

### Important validation decision

Do **not** silently hide invalid Production data using:

``` text
max(CounterQty - CuringQty, 0)
```

The intended rule discussed is:

``` text
Total Wet Reject = CounterQty - CuringQty
```

If:

``` text
CuringQty > CounterQty
```

treat it as a Production-data inconsistency, show a clear validation
error, and block FINAL SAVE rather than silently converting the result
to zero.

This should be enforced when implementation resumes.

------------------------------------------------------------------------

## 11. Proposed FINAL schema direction

The architecture is approved **in principle**, but migration has not
been created.

### Header

Proposed concept:

``` text
dbo.ProductionRejectFinal
-------------------------
id
Rectime
UpdatedAt
ProductionID
ProductionDate
TotalWetRejectAtSave
RawTotalQtyAtSave
FinalClassifiedQtyAtSave
UnclassifiedQtyAtSave
Remark
```

Key relationship:

``` text
ProductionID -> dbo.ProductionLot.ProductionID
```

Recommended uniqueness:

``` text
UNIQUE (ProductionID)
```

No `ShiftID` in FINAL identity.

### Detail

Proposed concept:

``` text
dbo.ProductionRejectFinalDetail
-------------------------------
id
Rectime
ProductionRejectFinalID
RejectReasonID
RawQtyAtSave
FinalQty
```

Relationships:

``` text
ProductionRejectFinalID
    -> dbo.ProductionRejectFinal.id

RejectReasonID
    -> dbo.RejectReason.id
```

Recommended uniqueness:

``` text
UNIQUE (ProductionRejectFinalID, RejectReasonID)
```

### Naming correction

Use:

``` text
RawQtyAtSave
RawTotalQtyAtSave
```

rather than `CalculatedQtyAtSave`, because SAVE should read fresh RAW
values from DB and those values may differ from what the operator saw
when REJECT CAL was pressed earlier.

Example:

``` text
10:00 CAL showed R207 = 6
10:02 another RAW entry is added
10:03 operator presses SAVE while form still shows 6
fresh RAW at SAVE = 7
```

The saved audit value should mean:

``` text
RawQtyAtSave = 7
FinalQty = 6
```

It must not falsely imply the operator saw 7 during CAL.

------------------------------------------------------------------------

## 12. Zero-row design

Copilot recommended storing one FINAL detail row for every applicable
active Reject Reason, including zero values, so the saved snapshot
preserves the complete applicable reason set.

Reasons:

-   distinguishes "reason considered and zero" from "reason absent";
-   preserves the ProductFamily reason snapshot at save time;
-   preserves `RawQtyAtSave` even when operator FinalQty is zero;
-   makes reload deterministic.

This recommendation was not rejected, but should be reconfirmed
immediately before migration implementation.

------------------------------------------------------------------------

## 13. R99 / R199 / R299 / R399

Do not reuse legacy R99 semantics.

Legacy R99 was a calculated remainder.

New:

``` text
R199
R299
R399
```

are real catalog-specific `RejectReason` master records (`IsOther=1`).

Therefore:

-   do not map R199/R299/R399 to R99;
-   do not create a fake new R99;
-   do not use R99 for Difference/Unclassified.

Difference/Unclassified is a calculated summary:

``` text
Total Wet Reject - Final Classified Reject
```

------------------------------------------------------------------------

## 14. Legacy WET REJECT / API direction

The old system contains:

-   `dbo.WetReject`
-   `dbo.WetRejectReasonMaster`
-   `dbo.WetRejectHistory`
-   legacy R01-R24/R99 behavior
-   old REJECT API/PIS mapping.

These are **not constraints** for the new architecture.

Do not:

-   create R201 -\> R01 mappings;
-   create `RejectReasonLegacyMap`;
-   strip digits from R2xx to produce legacy codes;
-   force new FINAL data into `WetReject`.

The REJECT API will be redesigned later around the new model.

Legacy tables should not be dropped/altered yet unless explicitly
approved during cutover.

------------------------------------------------------------------------

## 15. Test data / migration policy

All REJECT/WET REJECT transaction data entered during this development
period is test data.

Therefore:

-   no reject transaction-data migration is required;
-   do not over-engineer compatibility for test transactions;
-   later cleanup/reinitialization of reject test transaction data is
    acceptable only after explicit approval.

This does **not** mean unrelated FittingMES production/master data is
disposable.

Protect all unrelated real data.

------------------------------------------------------------------------

## 16. Current REJECT Source/session-context behavior --- preserve it

The REJECT Source/session-context behavior is part of the current
workflow and must be preserved.

Known affected files:

``` text
app/templates/reject.html
tests/test_reject.py
tests/test_reject_ui.cjs
```

Do not reset/revert this work.

Current browser behavior is intended to remember in `sessionStorage`:

``` text
Shift
Reject Of
Line
Product / Lot
Source
```

Do not remember:

``` text
Qty
Reject Reason
edit mode
```

After SAVE:

-   context remains;
-   Qty clears;
-   Reject Reason clears;
-   Source remains if still compatible.

The browser compatibility bug caused by `select.options.some(...)` was
fixed using:

``` javascript
Array.from(select.options).some(...)
```

and the UI test mock was adjusted to behave like a non-Array
`HTMLOptionsCollection`.

------------------------------------------------------------------------

## 17. Current REJECT page behavior

REJECT currently supports bidirectional Source ↔ Reject Reason
compatibility:

-   selecting Source filters Reject Reasons;
-   selecting Reject Reason filters compatible Sources;
-   exactly one compatible Source may auto-select;
-   multiple compatible Sources remain a choice;
-   incompatible prior Source is cleared.

Do not hardcode press ranges or IDs.

The current REJECT page keeps detailed saved entries with fields such
as:

``` text
Source
Line
Shift
Product / Lot
Code
Reject Reason
Qty
```

This remains the RAW/detail workflow.

------------------------------------------------------------------------

## 18. Known example used during testing

Example Production Lot:

``` text
I11691001 · Angle Ridge
```

Example RAW entries observed:

``` text
R212 = 8
R207 = 6
R208 = 4
R201 = 3
```

RAW total:

``` text
21
```

These are test values only.

They were useful to validate CAL and Source persistence but must not be
treated as production history.

------------------------------------------------------------------------

## 19. Current tests/status before pause

Reported focused tests during recent REJECT work:

``` text
node tests/test_reject_ui.cjs
python -m unittest discover -s tests -p "test_reject*.py"
git diff --check
```

Latest REJECT verification after the multi-shift RAW change:

``` text
72 Python tests passed
REJECT UI test passed
git diff --check passed
```

A broader Python suite run found unrelated Mould test failures and is not
claimed as passing.

No new FINAL migration has been created or run.

No FINAL reconciliation implementation has been made.

------------------------------------------------------------------------

## 20. Expected implementation direction when work resumes

Likely new files (names not yet final):

``` text
sql/025_production_reject_final.sql
sql/025_production_reject_final_rollback.sql

app/production_reject_final.py
or
app/reject_reconciliation.py
```

Likely existing files to touch:

``` text
app/main.py
app/reject.py
app/reject_summary.py
app/templates/production.html
tests/test_production.py
tests/test_reject.py
tests/test_reject_ui.cjs
md/REJECT_MODULE_REQUIREMENTS.md
```

Do not assume migration number `025` if repository numbering has changed
by the time work resumes; verify first.

------------------------------------------------------------------------

## 21. Required implementation tests later

At minimum test:

1.  Production reason rows come dynamically from ProductFamily -\>
    RejectReason mapping.
2.  No Rxxx quantity columns/hardcoding.
3.  Production CAL reads only `ProductionRejectEntry`.
4.  Depallet rows are excluded.
5.  Whole-Lot CAL includes Shift 1 + Shift 2.
6.  Whole-Lot CAL includes all Source machines and Lines for the
    ProductionID.
7.  CAL groups by `RejectReasonID`.
8.  CAL performs no DB write.
9.  Existing FINAL loads instead of silently recalculating RAW.
10. Operator can edit Qty after CAL.
11. SAVE stores FINAL header/detail transactionally.
12. SAVE never changes RAW.
13. Re-CAL after SAVE does not overwrite saved FINAL.
14. Invalid/non-applicable RejectReasonID is rejected.
15. Final Classified Reject \> Total Wet Reject is rejected.
16. `CuringQty > CounterQty` is treated as invalid/inconsistent data,
    not silently clamped.
17. Qty/Day is derived from saved FINALs for the Production Date.
18. Unsaved current Lot does not change persisted Qty/Day.
19. Re-save replaces current Lot contribution rather than duplicating
    it.
20. Existing REJECT Source-session-context tests remain passing.
21. Production Shift-independent Lot entry is tested for Lots spanning
    shifts, and Depallet Shift/Lot matching remains unchanged.
22. Zero-row snapshot behavior is tested if retained.

------------------------------------------------------------------------

## 22. Open items to resolve first when resuming

The Production RAW multi-shift Shift/Lot restriction is resolved and
manually verified; it is no longer an open item.

### Open item 1 --- zero FINAL detail rows

Current design recommendation is to store zero rows for all applicable
reasons.

Confirm this immediately before schema implementation.

### Open item 2 --- concurrency/history

Before implementation, inspect existing project conventions for:

-   concurrent Production saves;
-   audit/history tables/triggers;
-   whether FINAL revisions/history are required.

Do not invent an authentication/user-audit model if the application does
not already have one.

### Open item 3 --- legacy Production section cutover

The current Production page still uses legacy WET REJECT context
(`WetReject`, `WetRejectReasonMaster`, legacy R99 logic).

Plan the UI/service cutover carefully so the new Final workflow does not
accidentally write both old and new systems.

------------------------------------------------------------------------

## 23. Recommended first action when resuming Production reconciliation

Do **not** immediately ask Copilot to code.

First ask it to:

1.  read this handoff;
2.  run `git status --short`;
3.  confirm the Source/session-context and multi-shift RAW work is
    present, whether committed or uncommitted;
4.  verify no new migration number conflicts exist;
5.  treat Production multi-shift RAW entry as resolved and preserve the
    separate Depallet Shift/Lot behavior;
6.  return a short implementation plan for whole-Lot Production
    reconciliation;
7.  make no changes until that plan is approved.

Suggested resume prompt:

``` text
Read the REJECT / Production Reconciliation handoff MD first.

Do not implement yet.

Verify the current repository state against the handoff:
- git status --short
- REJECT Source-session-context work
- confirmed Production multi-shift RAW REJECT behavior
- latest SQL migration number
- current ProductionLot / ProductionData model
- preserve Depallet Shift/Lot behavior
- current Production legacy WET REJECT integration

Then return a concise implementation plan for the approved architecture:

ProductionRejectEntry RAW
    -> whole-Lot REJECT CAL by ProductionID + RejectReasonID
    -> editable Production Qty
    -> SAVE REJECT
    -> normalized ProductionRejectFinal + Detail

Hard requirements:
- existing RejectReason master only
- row-based RejectReasonID storage
- one FINAL per ProductionID
- no ShiftID in FINAL identity
- Qty combines all shifts/sources/lines for the ProductionID
- Qty/Day comes from saved FINALs for the Production Date
- no legacy Rxxx mapping
- no Rxxx quantity columns
- no RAW mutation from FINAL edits
- Total Wet Reject = CounterQty - CuringQty
- CuringQty > CounterQty must be treated as invalid, not silently clamped
- preserve current REJECT Source/session-context and multi-shift RAW work

Do not modify files or DB until the implementation plan is reviewed.
No commit/push/reset/revert.
```

------------------------------------------------------------------------

## 24. Pause point

Production RAW multi-shift Lot entry is implemented and manually
verified. Work remains paused at the **Production FINAL reconciliation
architecture/design stage**. Do not begin FINAL implementation until
separately requested and approved.

The latest Copilot investigation confirmed:

-   `ProductionID` is the current whole-Lot relational identity;
-   one `ProductionData` row exists per ProductionID;
-   Production whole-Lot CAL should aggregate RAW by ProductionID
    without Shift/Source/Line filters;
-   FINAL should be one header per ProductionID;
-   Qty/Day should be derived from saved FINAL quantities for the
    Production Date;
-   Production RAW entries may use multiple ShiftIDs for one ProductionID;
-   Production Lot selection does not become Shift-bound, while Depallet
    retains its previous Shift/Lot behavior;
-   the Production RAW multi-shift flow passed manual browser-to-database
    verification as documented in Section 5.

**No implementation of the new FINAL schema has been approved or
performed yet.**
