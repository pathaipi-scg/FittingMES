# PIS production dry-run preview

No HTTP client, credentials, send action, schema change, or save-rule change is introduced.

## Confirmed sources

ProductionLot does not persist Plant, Machine or VersionNo. Lot creation stores ProdDate, PlanName, MaterialCode and PlanQty from the selected plan. Plan edits update the saved name/material/quantity. Shift is editable through Production save, so it is not used as a plan identity key.

The read-only resolver queries dbo.P_ActivePlan with the same installation scope as the existing Production plan reader: Company=CRTC, Plant=30A1, Machine=SB2-3, StartTime=selected date. It matches the saved date/name/material/quantity. Each plan field is mapped only if all candidate rows agree. It never selects the newest version arbitrarily. Missing candidates or conflicting values remain null. This is recovery from the currently available plan source, not proof of the original historical version. A deleted or revised historical source cannot be reconstructed from the lot schema.

| PIS field | Source |
| --- | --- |
| productionDate / outputDetails.effectiveDate | ProductionLot.ProdDate |
| shiftCode | ProductionLot.Shift, saved string preserved |
| plantCode / machineCode | Matching P_ActivePlan.Plant / Machine |
| operationCode | Matching P_ActivePlan.OperationCode |
| planWeek / versionNo | Matching P_ActivePlan.PlanWeek / VersionNo |
| planName | ProductionLot.PlanName |
| dateTimeStart / dateTimeEnd | ProductionData.ProductionStartTime / ProductionEndTime, time-only values preserved |
| materialCode / lotNo | ProductionLot.MaterialCode / LotNo |
| gross0 / outputDetails.count | ProductionData.CuringQty |
| item remark / output remark | ProductionData.Remark |
| outputDetails.statusCode | Requested constant Curing |
| followPlan | null: no confirmed field or equivalent |

Live cursor metadata confirms ActivePlan StartTime is a date and no EndTime or followPlan column exists. No calendar week, timestamp, timezone, overnight duration or follow-plan rule is inferred. The datetime wire format and shift type still need future PIS contract validation; READY FOR PIS PREVIEW only describes mapping availability, not send readiness.

The reference supplies empty resources/itemDetails/itemInputs/itemProperties and blank operator/tool/lock/reason fields. They are structural placeholders, not invented measurements. The payload builder accepts multiple records sharing date, shift, plant and machine, but no SEND ALL action is implemented. Wet Reject uses the existing Counter minus Curing calculation. NOT SENT remains display-only.

## Live read-only example: ProductionID 2

Captured from MSSQL during verification. The lot currently has ProdDate 2026-09-14. Its Depallet date is a separate field and is not used here.

```json
{
  "productionDate": "2026-09-14",
  "shiftCode": "1",
  "plantCode": "30A1",
  "machineCode": "SB2-3",
  "operatorName": "",
  "resources": [],
  "productionItems": [
    {
      "operationCode": "a",
      "dateTimeStart": "09:27:13",
      "dateTimeEnd": "00:28:31",
      "planWeek": "2026W34",
      "planName": "MTS033",
      "versionNo": "01",
      "followPlan": null,
      "remark": "",
      "itemDetails": [],
      "itemOutputs": [
        {
          "materialCode": "ZCB30005STDA000A11",
          "lotNo": "B006690902",
          "gross0": 1790,
          "tool": "",
          "remark": "",
          "outputDetails": [
            {
              "statusCode": "Curing",
              "lockProdOrderNo": "",
              "reasonCode": "",
              "reasonCode2": "",
              "effectiveDate": "2026-09-14",
              "lockId": "",
              "count": 1790,
              "remark": ""
            }
          ]
        }
      ],
      "itemInputs": [],
      "itemProperties": []
    }
  ]
}
```
