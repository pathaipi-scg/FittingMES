# FittingMES -- Depallet Implementation Summary

**Status:** Completed and manually verified against SB23\
**Final Git commit:** `2c2af50` ---
`Finalize Depallet multi-run sequencing and reject validation`\
**Previous protected checkpoint:** `ba7f8e6`\
**Backup tag:** `backup-before-copilot-depallet`\
**Branch:** `main`\
**Git state after completion:** pushed to origin and working tree clean

------------------------------------------------------------------------

# 1. Purpose

The original Depallet workflow was redesigned from a
Production-Date-filtered, single-row workflow into a multi-run Depallet
workflow.

The completed design supports:

-   selecting Production Lots by Product Family → Product → Production
    Lot
-   showing historical and current curing balance
-   multiple Depallet runs for the same Production Lot
-   editing an earlier run without losing later runs
-   operator-controlled run sequence
-   run-specific Reject Detail
-   date-level Qty/Day reject totals
-   strict reject validation
-   optional Depallet Start/End time
-   Production Day cutoff rules, including times after midnight
-   historical Production Day rule lookup
-   concurrent/server-side protection against over-depalleting

------------------------------------------------------------------------

# 2. Production Lot Selection

The Depallet page uses cascading selection:

``` text
Production Date
      ↓
Product Family
      ↓
Product
      ↓
Production Lot
```

Production Lots with zero remaining curing or zero production remain
visible for historical context but are disabled for new Depallet work.

The authoritative curing balance is read from:

``` text
dbo.vw_DepalletCuringBalance
```

The live SB23 view was inspected and contains:

``` text
ProductionID
ProdDate
Shift
PlanName
MaterialCode
MaterialName
ProductCode
LotPrefix
LotNo
ProductionQty
DepalletQtyTotal
RemainingCuringQty
DepalletCount
FirstDepalletDate
LastDepalletDate
```

The view semantics verified in SB23 are:

``` text
ProductionQty = ProductionData.CuringQty

DepalletQtyTotal =
    historical Depallet quantity summed by ProductionID

RemainingCuringQty =
    MAX(ProductionQty - DepalletQtyTotal, 0)
```

The application does not independently reconstruct the historical curing
balance in the browser.

------------------------------------------------------------------------

# 3. Multi-Run Depallet

A Production Lot can be depalleted more than once.

Example:

``` text
Production Lot
Produced = 1,050

SEQ 1 / RUN 5 → Depallet 300
SEQ 2 / RUN 4 → Depallet 500

Total Depallet = 800
Remaining after both runs = 250
```

Each saved run is identified permanently by:

``` text
DepalletID
```

`DepalletID` is the identity of the run.

`RunSequence` controls the operator-visible chronological/working order
for the selected Depallet Date.

These are intentionally separate concepts:

``` text
DepalletID   = permanent run identity
RunSequence  = editable run order
```

Reject records and run data stay attached to the same `DepalletID` even
when sequence is changed.

------------------------------------------------------------------------

# 4. Run Sequence

Migration:

``` text
sql/008_depallet_run_sequence.sql
```

added `RunSequence`.

Existing rows were deterministically backfilled by:

``` text
DepalletDate
then DepalletID
```

The migration was verified as idempotent.

The database enforces a unique sequence within a Depallet Date:

``` text
(DepalletDate, RunSequence)
```

and sequence values must be positive.

New runs append using the selected date's next sequence:

``` text
MAX(RunSequence) + 1
```

The UI displays:

``` text
SEQ n / RUN DepalletID
```

and provides UP/DOWN controls.

Boundary controls are disabled:

-   first row cannot move UP
-   last row cannot move DOWN

Reordering is blocked when unsaved draft edits/new rows exist so unsaved
work is not silently lost.

------------------------------------------------------------------------

# 5. Editing Earlier Runs

Saved runs can be edited later by `DepalletID`.

If an earlier run changes, later runs are preserved but their displayed
before-run balance is recalculated.

Example verified manually:

Before edit:

``` text
RUN 4
Depallet = 600

RUN 5
Already Depalleted = 600
Remaining Curing   = 450
```

RUN 4 was edited:

``` text
RUN 4
Depallet = 500
```

After SAVE, RUN 5 automatically became:

``` text
Already Depalleted = 500
Remaining Curing   = 550
```

RUN 5's own Depallet Qty, Good Qty and Reject Detail were not changed.

This is the intended behavior.

------------------------------------------------------------------------

# 6. Before-Run Balance

For each run, `Already Depalleted` and `Remaining Curing` represent the
state immediately **before that run**.

For the selected ProductionID, the calculation considers:

1.  earlier Production/Depallet Dates
2.  lower `RunSequence` values on the selected date

It does not count the current run against itself.

This prevents the old problem where editing an existing row could
incorrectly consume its own quantity twice.

The cumulative server validation still uses the authoritative
curing-balance view under the transaction lock.

------------------------------------------------------------------------

# 7. Reordering Verified

Manual verification reordered the September 26 runs.

After moving RUN 5 above RUN 4:

``` text
SEQ 1 / RUN 5
Already Depalleted = 0
Remaining Curing   = 1,050
Depallet Qty       = 300
Good Qty           = 291

SEQ 2 / RUN 4
Already Depalleted = 300
Remaining Curing   = 750
Depallet Qty       = 500
Good Qty           = 474
```

The Reject data stayed with the correct `DepalletID`.

This verified that sequence controls order only; it does not move
ownership of the run's data.

------------------------------------------------------------------------

# 8. Depallet Quantity Protection

The UI prevents entering a Depallet quantity above the available
quantity.

Example verified:

``` text
Remaining Curing = 1,050
Input            = 1,051
```

The UI clamps/rejects the invalid value back to the maximum allowed
quantity.

The browser is not the only protection.

Server-side save validation rereads the current balance under the shared
transaction/application lock before committing.

For editing an existing same-date run, the allowable quantity accounts
for the current saved run so the row does not count against itself
twice.

Legacy over-depallet rows can remain unchanged or be reduced, but cannot
be increased further.

------------------------------------------------------------------------

# 9. Reject Model

For a Depallet run:

``` text
Total Reject = Depallet Qty - Good Qty
```

Reject codes `R01 ... R24` are operator-classified rejects.

`R99` is derived automatically as the remaining unclassified reject:

``` text
Classified Reject = SUM(R01 ... R24)

R99 =
    Total Reject - Classified Reject
```

The client does not submit R99 as an authoritative operator-entered
reject value.

The server derives R99 itself.

------------------------------------------------------------------------

# 10. Reject Validation

The completed validation enforces:

``` text
GoodQty <= DepalletQty
```

and:

``` text
SUM(R01 ... R24)
    <= DepalletQty - GoodQty
```

All quantities must be nonnegative.

The footer displays:

``` text
Total Reject
Classified Reject
Difference
R99
```

`R99` is read-only.

If Classified Reject exceeds Total Reject:

-   a clear error is displayed
-   R99 displays 0
-   SAVE is disabled in the browser
-   server-side validation independently rejects the request

If Good Qty exceeds Depallet Qty:

-   an error is displayed
-   SAVE is disabled
-   server-side validation also rejects it

------------------------------------------------------------------------

# 11. Reject Validation -- Manual Tests

The following real UI tests were performed.

### Case A

``` text
Depallet Qty      = 300
Good Qty          = 290
Total Reject      = 10
Classified Reject = 9
```

Expected/result:

``` text
Difference = 1
R99        = 1
SAVE       = enabled
```

Passed.

### Case B

``` text
Depallet Qty      = 300
Good Qty          = 290
Total Reject      = 10
Classified Reject = 11
```

Expected/result:

``` text
Difference = -1
R99        = 0
Error      = Classified Reject 11 exceeds Total Reject 10
SAVE       = disabled
```

Passed.

### Case C

``` text
Depallet Qty = 300
Good Qty     = 301
```

Expected/result:

``` text
Error = Good Qty 301 exceeds Depallet Qty 300
SAVE  = disabled
```

Passed.

### Case D

The data was changed back to a valid state.

Example:

``` text
Depallet Qty      = 300
Good Qty          = 291
Total Reject      = 9
Classified Reject = 9
Difference        = 0
R99               = 0
```

The error cleared immediately and SAVE became enabled again.

Passed.

------------------------------------------------------------------------

# 12. Reject Detail and Qty/Day

Reject Detail belongs to the selected `DepalletID`.

Changing the selected run changes the run-specific Reject Detail.

`Qty/Day` is different:

``` text
Qty/Day = aggregate reject quantity for the selected Depallet Date
```

It is informational and may include multiple runs on the same reporting
date.

`Qty/Day`:

-   is not submitted as the selected run's reject quantity
-   does not enter the selected run's Classified Reject calculation
-   does not enter the selected run's Difference calculation

A UI bug was found where dynamically rebuilt R01--R24 fields were
outside the main table event handler.

The fix added delegated Reject Detail input handling so edits:

1.  update the selected run's state
2.  recalculate the footer immediately
3.  keep Qty/Day separate

------------------------------------------------------------------------

# 13. Historical Reject Inconsistency Found

A read-only SB23 audit found one pre-existing inconsistent historical
row:

``` text
DepalletID = 3

Depallet Qty      = 2,120
Good Qty          = 2,100
Total Reject      = 20
R01–R24 total     = 42
R99               = 0
```

Therefore:

``` text
Accounted Qty = 2,142
```

which exceeds Depallet Qty by 22.

This historical record was deliberately **not automatically corrected**.

When opened, the new UI detects the inconsistency, displays the
validation error and prevents SAVE until the data is corrected.

------------------------------------------------------------------------

# 14. Optional Start / End Time

Migration:

``` text
sql/007_depallet_run_times.sql
```

added:

``` text
StartDateTime datetime2(3) NULL
EndDateTime   datetime2(3) NULL
```

Times are optional.

Legacy Depallet rows remain valid with:

``` text
StartDateTime = NULL
EndDateTime   = NULL
```

The operator enters only:

``` text
HH:mm
```

The calendar date is resolved by the server using the historical
Production Day rule.

------------------------------------------------------------------------

# 15. Production Day Rule

Production does not necessarily change day at midnight.

The existing history table is:

``` text
dbo.ProductionDayRuleHistory
```

with the relevant fields:

``` text
RuleID
EffectiveFromDate
DayStartTime
Remark
CreatedAt
```

For a selected Production Date, the effective rule is resolved using:

``` text
EffectiveFromDate <= selected Production Date
```

ordered by:

``` text
EffectiveFromDate DESC
RuleID DESC
```

This is important because historical records must use the Production Day
cutoff that was effective at that time, not today's cutoff.

If the factory changes the day start in the future, for example:

``` text
08:00 → 08:30
```

the old rule remains in history and old Production/Depallet dates
continue to resolve correctly.

------------------------------------------------------------------------

# 16. After-Midnight Time Handling

For the verified September 26 rule:

``` text
Production Day Start = 08:00
```

a clock time before 08:00 belongs to the following calendar date while
remaining part of Production Date September 26.

Example:

``` text
Production Date = 2026-09-26
Time entered    = 01:00

Stored datetime = 2026-09-27 01:00
```

This was verified directly against raw SB23 datetime values.

------------------------------------------------------------------------

# 17. Real Cross-Midnight Verification

The final SQL verification returned:

``` text
DepalletID  DepalletDate  Seq  ProductionID  StartDateTime              EndDateTime                Depallet  Good
5           2026-09-26    1    3             2026-09-26 22:00:00.000    2026-09-27 00:15:00.000    300       291
4           2026-09-26    2    3             2026-09-27 01:00:00.000    2026-09-27 03:00:00.000    500       474
```

This confirms both required cases:

### RUN 5

``` text
Production Date = 26/09/2026
Start           = 22:00 on 26/09
End             = 00:15 on 27/09
```

Cross-midnight storage is correct.

### RUN 4

``` text
Production Date = 26/09/2026
Start           = 01:00
End             = 03:00
```

Both timestamps are correctly stored on calendar date 27/09 while the
reporting/Production Date remains 26/09.

This is intentional.

------------------------------------------------------------------------

# 18. Server-Side Concurrency / Transaction Protection

Batch saves use the existing transaction-owned Production Lot
application lock.

The save process:

-   locks the active Production Lot
-   locks matching Depallet rows as required
-   rereads the authoritative curing balance
-   validates all quantities
-   validates rejects
-   commits the complete batch only when valid
-   rolls back the complete batch if validation fails

This prevents two application writers from independently consuming the
same remaining curing balance.

Reorder operations also run under the transaction lock.

Because `(DepalletDate, RunSequence)` is unique, reordering uses
temporary safe sequence values before assigning the final dense
sequence.

------------------------------------------------------------------------

# 19. Compatibility

Legacy/single-run routes were retained where practical.

The compatibility GET route supports:

``` text
depallet_id
```

so a specific saved run can be opened directly.

Example concept:

``` text
/depallet?...&production_id=5&depallet_id=3
```

------------------------------------------------------------------------

# 20. Database Changes

Two migrations were introduced during the completed redesign:

``` text
sql/007_depallet_run_times.sql
sql/008_depallet_run_sequence.sql
```

### 007

Adds optional:

``` text
StartDateTime
EndDateTime
```

### 008

Adds:

``` text
RunSequence
```

and the required sequence constraints/index behavior.

No change was made to the fundamental `dbo.vw_DepalletCuringBalance`
calculation during this work.

------------------------------------------------------------------------

# 21. Main Files Changed During the Depallet Work

The Depallet redesign touched, across its development commits, files
including:

``` text
app/depallet.py
app/main.py
app/templates/depallet.html
app/templates/navigation.html
app/templates/production.html
app/templates/usage.html

docs/depallet-workflow.md
md/DATABASE.md
md/SB23_Depallet_Change_Summary.md

sql/007_depallet_run_times.sql
sql/008_depallet_run_sequence.sql

tests/test_depallet.py
tests/test_depallet_ui.cjs
tests/test_family_ui.cjs
tests/test_navigation.py
tests/test_prod_api.py
tests/test_usage.py
```

Not every file above was changed in the final commit; this list records
files involved across the Depallet redesign/history.

------------------------------------------------------------------------

# 22. Automated Verification History

During development, the test suite increased as functionality was added.

Reported milestones included:

``` text
163 Python tests passed
168 Python tests passed
177 Python tests passed
180 Python tests passed
```

The final reject-validation work reported:

``` text
Python: 180 tests passed
test_depallet_ui.cjs: passed
test_family_ui.cjs: passed
git diff --check: clean
editor diagnostics: clean
```

Live SB23 verification was also performed manually after the automated
tests.

------------------------------------------------------------------------

# 23. Important Git History

### Protected checkpoint before continuation

``` text
ba7f8e6
WIP: checkpoint before continuing Depallet redesign
```

Backup tag:

``` text
backup-before-copilot-depallet
```

Both were pushed to GitHub before another coding agent continued the
work.

### Multi-run + Production Day time handling

``` text
a5da914
Complete Depallet multi-run and production-day time handling
```

### Operator-controlled sequence

``` text
5680eb0
Add operator-controlled Depallet run sequencing
```

### Final reject validation

``` text
2c2af50
Finalize Depallet multi-run sequencing and reject validation
```

This final commit was pushed successfully.

After the final push:

``` text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

------------------------------------------------------------------------

# 24. Manual Test Data / Caution

During final manual verification, real SB23 rows were saved/edited.

At the end of the documented September 26 test, the relevant rows were:

``` text
SEQ 1 / RUN 5
ProductionID = 3
Depallet Qty = 300
Good Qty     = 291
Start        = 2026-09-26 22:00
End          = 2026-09-27 00:15

SEQ 2 / RUN 4
ProductionID = 3
Depallet Qty = 500
Good Qty     = 474
Start        = 2026-09-27 01:00
End          = 2026-09-27 03:00
```

These rows were used for live verification of:

-   multi-run save
-   editing an earlier run
-   downstream balance recalculation
-   sequence reordering
-   reject ownership
-   cross-midnight datetime handling

Do not blindly delete or rewrite these records later without first
confirming whether they are test data or have subsequently become part
of required operational history.

------------------------------------------------------------------------

# 25. Completed Functional Checklist

The following behavior was verified:

``` text
[x] Cascading Family → Product → Production Lot selection
[x] Remaining Curing from authoritative view
[x] Zero-balance/zero-production lots visible but disabled
[x] Multiple runs for the same Production Lot
[x] Permanent DepalletID per run
[x] Editable RunSequence
[x] UP/DOWN reorder
[x] Reject data remains attached to DepalletID after reorder
[x] Edit earlier run
[x] Later run before-balance recalculates correctly
[x] No double-counting of current run during edit
[x] Over-depallet protection
[x] Good Qty <= Depallet Qty validation
[x] Classified Reject <= Total Reject validation
[x] R99 derived automatically
[x] Invalid data disables SAVE
[x] Server independently validates browser data
[x] Reject Detail is run-specific
[x] Qty/Day is date aggregate and separate from run calculation
[x] Optional Start/End time
[x] Historical Production Day cutoff lookup
[x] After-midnight calendar-date resolution
[x] Cross-midnight Start/End
[x] Transaction/concurrency protection
[x] Live SB23 SAVE verification
[x] Automated Python/JavaScript tests
[x] Final code committed and pushed
```

------------------------------------------------------------------------

# 26. Current Status

**Depallet is considered functionally complete for this development
phase.**

The current baseline is:

``` text
main @ 2c2af50
```

Future work should treat the completed Depallet behavior as protected
functionality.

When developing Production, Mould, Usage, API, or OEE features, avoid
changing Depallet schema/logic unless the change is explicitly required
and regression-tested.

------------------------------------------------------------------------

## 27. Short Mental Model

If the full document is forgotten, remember Depallet this way:

``` text
Production Lot
      │
      │ authoritative curing balance
      ▼
Depallet Date
      │
      ├── SEQ 1 / RUN DepalletID
      ├── SEQ 2 / RUN DepalletID
      ├── SEQ 3 / RUN DepalletID
      └── ...
             │
             ├── Depallet Qty
             ├── Good Qty
             ├── R01...R24
             ├── derived R99
             ├── optional Start/End
             └── Reject Detail belongs to DepalletID

RunSequence = operator-controlled order
DepalletID  = permanent identity

ProductionDayRuleHistory
      ↓
converts HH:mm to correct real calendar datetime

vw_DepalletCuringBalance
      ↓
protects cumulative curing balance

Server transaction lock
      ↓
protects concurrent writes
```
