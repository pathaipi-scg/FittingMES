# Depallet entry

Depallet Input appears below Calculated Data on the existing Production page. Active reject reasons are loaded from RejectReasonMaster in SortOrder; Thai names remain database-provided Unicode text.

The selected ProductionLot supplies ProductionID, default LotNo, stored Shift and product/material context. Shift is stored on ProductionLot in this application, not ProductionData. Editing the Depallet Lot does not rename the Production Lot.

Depallet Date initially follows the selected Production Date but is independently editable. Changing it loads the record for that ProductionID/date, or new defaults. It does not move a previously saved dated record. Save updates the existing record for that pair; pre-existing duplicate records are reported rather than selected arbitrarily.

Saving requires nonnegative integer quantities and Depallet Qty = Good Qty + Reject Qty. Zero quantity has a zero reject percentage. The existing validation view supplies persisted totals. Header and reject changes commit together or all roll back; the existing application writer lock serializes concurrent saves. Blank/zero rejects have no rows. Previously saved inactive reasons remain visible read-only and are retained in totals.

Messages use the existing generic lot status bar. Saving does not reload the page. No schema changes, PIS calls, PIS-log writes or ProductionLot/ProductionData updates are introduced.

Validation commands:

- `.\.venv\Scripts\python.exe -m unittest discover -s tests`
- `node tests/test_family_ui.cjs` (also validates all inline JavaScript syntax)
- `node tests/test_depallet_ui.cjs`

Tests use in-memory database doubles; they do not create live records.
