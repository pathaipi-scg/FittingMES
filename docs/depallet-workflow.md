# Depallet Workflow

DEPALLET uses the shared Production Date as the date of depallet/packing activity. Production Lots remain eligible regardless of their Production Date. The Product Family -> Product -> Production Lot selector uses the existing active product master and actual lots from `dbo.vw_DepalletCuringBalance`, ordered by Production Date descending and then Run No. descending. Zero-production and zero-remaining lots remain visible but disabled.

The balance view is keyed by `ProductionID`. Its `ProductionQty` is ProductionData `CuringQty`; `DepalletQtyTotal` is the all-date Depallet sum; and `RemainingCuringQty` is the view's clamped remaining balance. The UI does not recalculate this selector balance. A ProductionID can have any number of Depallet runs on the selected Production Date, including repeated runs in the same shift and runs interleaved with other lots. Each run has its own `DepalletID`; saved runs are edited only by that ID and new runs are inserted rather than merged.

DEPALLET LOTS is a multi-row working table. The production Lot No., Product, Produced Qty, Already Depalleted and Remaining Curing are read-only. For saved runs, the balance columns show quantities immediately before that run, ordered by Production Date and then DepalletID; the run does not appear to consume itself twice. Shift, Start, End, Depallet Qty, Good Qty and Remark are editable. Start and End accept HH:mm. Their calendar date is derived from the selected shared Production Date and the `ProductionDayRuleHistory` cutoff effective for that date. Historical rules are never replaced and are resolved using the latest `EffectiveFromDate <= Production Date` with `RuleID` as tie-breaker. Existing NULL run times load blank and remain valid until an operator explicitly enters both times. Entering a Depallet Qty above the current allowable remaining amount displays a warning and clamps the input immediately.

SAVE DEPALLET submits all working rows to the batch endpoint. The server takes the shared transaction-owned ProductionLot writer lock, rereads the authoritative balance view by ProductionID for every row, accounts for that specific run's quantity when editing by DepalletID, validates the maximum, and commits all rows and their reject details in one transaction. Multiple rows may share ProductionID. A failure rolls the whole batch back. Existing historical over-depallet records are not changed; with a clamped remaining balance of zero, an existing run may remain unchanged or decrease but cannot increase.

One REJECT DETAIL frame follows the selected working row. Its R01-R24 quantities belong only to that transaction; inactive saved reasons remain read-only. Physical Reject Qty is `DepalletQty - GoodQty`; Classified Reject is the selected row's R01-R24 sum; Difference is Physical Reject Qty minus Classified Reject; and R99 is `max(Difference, 0)`. R99 remains server-derived. Qty/Day is read-only and aggregates each reject code across all transactions for the selected Depallet Date. Draft reject edits update the displayed day totals immediately and never affect the selected-row Classified Reject or Difference.

The GET `/lots/{production_id}/depallet` and POST `/lots/{production_id}/depallet` legacy endpoints remain available. Production, Usage, PROD API, REJECT API, and shared date navigation are unchanged. Migration `sql/007_depallet_run_times.sql` adds nullable `datetime2(3)` run-time columns only when missing; existing historical rows are not backfilled.

Validation uses isolated database doubles and local JavaScript tests:

- `.venv/Scripts/python.exe -m unittest discover -s tests`
- `node tests/test_family_ui.cjs`
- `node tests/test_depallet_ui.cjs`

The actual SB23 schema and historical production-day rule query must be verified before deploying to a database other than the one inspected for this implementation.