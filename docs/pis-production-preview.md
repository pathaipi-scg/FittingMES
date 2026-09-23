# PIS production previews: DRY RUN / NO PIS SEND

PREVIEW PROD uses only the selected lot for inspection. PREVIEW ALL PROD includes every active lot for the selected date, even when measurements or mappings are missing. Grouping is productionDate + trimmed shiftCode + trimmed plantCode + trimmed machineCode. Each group is one separate ProdOrders request body; no batch wrapper is added. Group keys are sorted and items are ordered by start time and lot number. No send endpoint, HTTP client, credentials, schema change or save-rule change is introduced. Future real production sending must be SEND ALL PROD only.

## Sources and transformations

- ProductionLot.ProdDate supplies productionDate and effectiveDate.
- ProductionLot.Shift supplies the saved Production shift, as a trimmed string.
- ProductionLot.PlanName, MaterialCode and LotNo supply the corresponding trimmed PIS strings.
- ProductionData.CuringQty supplies gross0 and outputDetails.count; zero stays zero, missing stays null.
- ProductionData.Remark supplies item and output remarks, trimmed; missing/blank remains null.
- ProductionData.Start/End times are combined with ProductionLot.ProdDate as factory-local values. End advances one calendar day only when earlier than Start. Equal times remain on the same day. Both format as YYYY-MM-DDTHH:mm without UTC conversion or timezone suffix. Seconds are dropped after comparing the saved times. Missing times remain null; if Start is missing, End uses the lot date and the missing Start is flagged.
- P_ActivePlan supplies Plant, Machine, OperationCode, PlanWeek and VersionNo. The read-only resolver uses the existing installation scope Company=CRTC, Plant=30A1, Machine=SB2-3 and date. It matches saved date, trimmed plan name/material and plan quantity. Only values shared by every matching candidate are accepted, after trimming.

ProductionLot does not persist Plant, Machine or VersionNo. Source resolution cannot prove the original historical plan version if that source changed or disappeared. No CB plant/machine/material/version defaults are substituted.

## Readiness

Per-lot field mappings distinguish required missing values, unresolved mappings and optional remarks. Per-request-group readiness checks date, shift, plant, machine, operation, plan week/name/version, start/end, material, lot and CuringQty. Missing required values do not prevent inspection or silently exclude lots.

followPlan is calculated independently for each lot as ProductionData.CuringQty >= the saved ProductionLot.PlanQty. CounterQty and ActivePlan quantities are not used in this calculation. Missing either source produces null and required-source diagnostics. Existing lot save validation and database constraints permit zero PlanQty, so saved zero participates in the comparison. itemDetails, itemInputs, itemProperties and resources remain empty arrays; no downtime/tasks/properties are invented. These omissions are displayed. READY FOR PIS PREVIEW describes the currently agreed preview fields, not authorization or readiness to send to PIS.

## Generated examples

These are synthetic regression-fixture examples, not live MSSQL records:

- [Selected-lot PREVIEW PROD](preview-prod-example.json)
- [PREVIEW ALL PROD request group with two lots](preview-all-prod-group-example.json), including an overnight item.

Validation: python -m unittest discover -s tests; node tests/test_family_ui.cjs; node tests/test_depallet_ui.cjs.
