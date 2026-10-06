# Fitting REJECT workflow

The Fitting REJECT page is the quantity-entry sibling of LOGGER. Its
global Production Date comes from the shared navigation. The page context
selects Shift, workflow, active Line, and an active Product / Lot; each
saved row records Qty, Source, Reject Reason, and the selected
workflow-specific table.

## Workflow ownership

- `Production` inserts and edits only `dbo.ProductionRejectEntry`.
- `Depallet` inserts and edits only `dbo.DepalletRejectEntry`.
- Reject Of is page routing state and is not persisted.
- The legacy Wet Reject and Depallet reject interfaces remain unchanged.
- REJECT CAL has its own page and reads only the selected workflow table;
  its quantities are not combined with legacy totals.

## Authoritative configuration

- Shift options use active `dbo.ShiftMaster` rows. Lot matching uses
  `ShiftCode` against `ProductionLot.Shift`; generated Shift IDs have no
  business meaning.
- Product family comes from the selected `ProductionLot.ProductFamilyID`.
  Active reasons are filtered through `dbo.RejectReasonProductFamily`.
- `RejectReason.RejectSourceScopeID` and its `RejectSourceScopeCode`
  control both Source-to-Reason directions.
- Active Press-to-Line membership comes from
  `dbo.vw_PressMcPressList`; active equipment and relational IDs come
  from `dbo.EquipmentMaster`.
- Server-side validation repeats the date, shift, lot, family, reason,
  scope, line, source, and quantity checks before insert or edit.

## Validation

Run focused checks with:

```powershell
.\.venv\Scripts\python.exe tests\test_reject.py -v
node tests\test_reject_ui.cjs
```

The REJECT detail and CAL features do not change PIS/API behavior, legacy
reject tables, or the existing Production and Depallet summary values.
