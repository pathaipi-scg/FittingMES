# Depallet entry

DEPALLET has its own `/depallet` page between PRODUCTION and USAGE. The shared Production Date selects active production lots whose ProdDate matches that date and the Depallet record for each ProductionID/date pair. Direct access defaults to today. Production no longer loads or renders Depallet inputs; its save, edit and void workflows are unchanged.

The compact lot grid shows the production Lot No., saved/default Shift, editable Depallet Qty, Good Qty and Remark, and read-only physical Reject Qty. The summary uses PhysicalRejectQty from the existing reader/calculation, not the classified-plus-R99 total. The production Lot No. remains the row label; an existing independent Depallet LotNo is retained in the submitted data.

Selecting a lot by its link, row or input displays its vertical reject detail. Selection updates the URL and retains the shared date. Summary inputs and reject drafts remain in memory while switching rows. Only the selected row and its reject detail are associated with the save form. Active R01-R24 names and ordering come from RejectReasonMaster; saved inactive manual reasons remain read-only and retained. R99 appears only in reject detail, with its master-provided name and a read-only value.

The page reuses the existing live calculation preview and the authoritative server `summary`, `validate` and `save_depallet` functions. PhysicalRejectQty = DepalletQty - GoodQty; ClassifiedRejectQty sums R01-R24; DifferenceQty = PhysicalRejectQty - ClassifiedRejectQty; R99 = max(DifferenceQty, 0). Client R99 is ignored. Manual quantities are not adjusted. Positive R99 is upserted, and stale zero R99 is deleted. Classified quantities above physical rejects are allowed, with R99 zero and the existing warning.

SAVE DEPALLET posts to the unchanged `/lots/{production_id}/depallet` endpoint, then reloads that lot through its existing GET endpoint with `depallet_date`. The selected lot and Production Date remain on DEPALLET. Failed saves preserve inputs. A committed save whose reload fails blocks another save until a successful selected-lot reload. RELOAD SELECTED LOT explicitly replaces that lot's draft with saved values.

The existing date-keyed reader and endpoints remain available for older clients and deep links, including independent Depallet dates. Duplicate records for one ProductionID/date are rejected. Repeated saves update the existing record. Header and reject changes commit together or roll back together under the existing lot writer lock. There are no schema, view, PIS, ProductionLot or ProductionData write changes.

Validation uses isolated database doubles and mocked HTTP calls, never live production records or external services:

- `.venv/Scripts/python.exe -m unittest discover -s tests`
- `node tests/test_family_ui.cjs`
- `node tests/test_depallet_ui.cjs`
