# Production workflow

## Plans
The page reads dbo.P_ActivePlan for CRTC / 30A1 / SB2-3 and the selected StartTime date. The existing ActivePlan view is unchanged.
ROW_NUMBER selects the highest numeric VersionNo per StartTime + PlanName. Plan assignment remains date + PlanName. USED plans are visible/disabled; stale source tokens are rejected server-side. Plan replacement is restricted to the saved date.

## Explicit product identity and confirmation
Product identity is ProductFamily + ProductCode. Four compact selectors are shown when a MaterialPrefix has no family-confirmed mapping. Selecting a product clears the other three selectors. The server also requires exactly one selection and validates it against the active master pair.
Confirm stores MaterialPrefix + ProductFamily + ProductCode. A NULL-family legacy map is NOT used automatically: only an explicit operator confirmation can resolve it. Concurrent conflicting confirmations are rejected.
There is no inference from MaterialCode, MaterialName, Thai descriptions or a legacy ProductCode.
After confirmation, the saved mapping resolves automatically on future visits. Existing lots are never rebuilt from current mappings.

## Prefixes and sequences
| Family | Letter | Available product codes |
| --- | --- | --- |
| NeuFit / NeuStile | B | 01-11 (11 existing factory master rows) |
| Oriental | B | 12-22 (11 existing factory master rows) |
| Special Ridge | I | None supplied/loaded |
| Prestige Common | I | None supplied/loaded |

Existing master ProductGroup explicitly identifies NeuFit/Oriental. Migration preserves their codes, names, Thai names and active flags; it introduces no guessed products for the other families.
New format: letter + two-digit ProductCode + Buddhist YY + MM + two-digit running number. Example: NeuFit 06 on 2026-09-22 starts B06690901.
The exact printable prefix identifies the sequence for that product and calendar month. The page suggests historical MAX + 1 from persisted ProductionLot records, including voided Lots; skipped numbers are never reused. Operators may choose a two-ASCII-digit suffix from 01 to 99 greater than historical MAX, including a deliberate skipped number. At MAX 99 the sequence is exhausted.
UI previews are advisory; creation re-derives the product prefix and selected plan date, then revalidates the confirmed mapping, plan availability, historical MAX and duplicate LotNo inside the serialized lot transaction. The transaction-owned application lock serializes competing CREATE LOT requests.
ProductionID is always the transaction identity. Exact LotNo duplicates are rejected even when the matching record is voided.
VOID is latest-only within the saved sequence; voided records and history remain and consume their running numbers.
Unresolved legacy lots retain their exact old LotPrefix/LotNo/RunningNo and latest-only legacy-prefix VOID checks. Their running numbers also remain consumed. They do not participate in a guessed family sequence. Later historical-family reconciliation requires explicit review and must not silently renumber lots.

## Migration 003 applied
Apply migrations in version order. Do not rerun migration 001 after 003: 003 replaces its old global lot/sequence indexes.
003_product_families.sql adds:
- ProductFamilyMaster containing only the four names and B/I letters.
- Composite ProductCodeMaster primary key (ProductFamily,ProductCode).
- Nullable ProductFamily on MaterialProductMap and ProductionLot, with composite foreign keys.
- Persisted SequenceMonth derived from ProdDate.
- Active family-aware lot and running uniqueness; separate legacy NULL-family indexes.
It does not backfill families on maps/lots or rename/renumber lots. It is rerunnable and reports unresolved rows.

Unresolved records preserved:
- MaterialPrefix ZCB30005, code 06.
- ProductionID 1: B006690901, code 06.
- ProductionID 2: B006690902, code 06.

Before/after comparisons verified all original values in MaterialProductMap (1 row), ProductionLot (2 rows), ProductionData (1 row), and ProductionLotHistory (3 rows) unchanged. No user mapping confirmation was performed by the agent.

## Stored lot and production data
ProductionLot permanently retains ProductFamily, ProductCode, LotPrefix, RunningNo, LotNo and Shift. A new lot defaults Shift from the effective plan. Reopening and plan changes do not overwrite stored Shift.
ProductionData is one-to-one by ProductionID. Operator saves Shift, start/end time, whole nonnegative Counter/Curing quantities and optional Remark. Curing cannot exceed Counter. Wet reject quantity and percentage are derived client/server-side, not persisted; zero counter is safe.
History records CREATE, PLAN_CHANGE, VOID and PRODUCTION_SAVE atomically with their respective writes.
The compact UI, splitter/collapse persistence, custom Plan dropdown, reusable lot status bar, and input/calculated sections remain.
No PIS API, material usage, downtime, depallet or reject-detail functions are implemented.

## Universal Press and Mould availability
ADD FITTING and EDIT FITTING use the same production-time availability rule for every equipment-master Press and physical Mould. Each assignment boundary uses its explicitly saved PressProduction timestamp when present, otherwise the corresponding ProductionData Lot boundary. Lot clock values are resolved against the effective Production Day rule; clocks before that day's start belong to the following calendar date. A missing effective start is unresolved and blocks allocation, while a missing effective end is treated as ongoing.

Availability uses half-open full-datetime intervals `[start, end)`: two active assignments conflict only when their intervals overlap. Thus a previous assignment ending exactly when another begins does not block reuse. Press eligibility still requires an active PRESS master row and Product capability; Mould eligibility still requires an ACTIVE physical Mould compatible with the Lot Product. Released assignments and inactive Lots do not occupy equipment. Server validation repeats eligibility and overlap checks inside the existing SQL Server transaction and uses transaction-owned application locks keyed by resource identity, including across Production Dates. EDIT excludes only its own PressProductionID.

Historical PressProduction intervals are interpreted using their explicit assignment boundaries and then the Lot ProductionData fallbacks. If a historical assignment cannot be resolved, it is treated as a conflict rather than as free equipment. No migration or historical data rewrite is part of this rule.

The original F12 issue came from the prior dropdown and save checks treating any active assignment on the same Production Date and Shift (including legacy assignments with unknown Shift) as occupied. Those checks never compared Start/End times, so an 08:00-16:00 assignment incorrectly blocked a back-to-back 16:00-01:00 assignment.

## Validation
- .venv\\Scripts\\python.exe -m unittest discover -s tests
- node tests/test_family_ui.cjs
57 Python tests passed. All inline JavaScript passed syntax validation. The isolated JavaScript test checks all 16 family-to-family selection directions and preview updates.
Live smoke checks used read-only page loads; no test lots or ProductionData rows were created. Browser visual verification was unavailable.
