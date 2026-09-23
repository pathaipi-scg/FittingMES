# FittingMES Database Contract

**Project:** FittingMES\
**Database:** `SB23`\
**DBMS:** Microsoft SQL Server\
**Application:** FastAPI + Jinja2 + Bootstrap/JavaScript\
**Purpose:** Database contract and SQL semantics for the FittingMES
project.

> This document is the database contract for FittingMES.\
> Codex/developers must read this file before changing SQL, database
> access, data models, or workflows.\
> Inspect the actual database schema before making changes. Do not guess
> undocumented mappings or create duplicate tables.

------------------------------------------------------------------------

## 1. Core Design Rules

1.  `SB23` is the FittingMES source of truth for MES-entered production,
    depallet, reject, and material-usage data.
2.  Do not `DROP`, recreate, rename, or materially change existing
    database objects without explicit approval.
3.  Inspect the actual schema before writing migrations or application
    SQL.
4.  Do not invent columns, material mappings, PIS mappings, Angel
    mappings, GL accounts, cost centers, or external material codes.
5.  Keep master/configuration data separate from transaction data.
6.  Preserve historical records. Prefer `IsActive = 0` over deleting
    master rows that may already be referenced.
7.  External-system identifiers must not replace stable internal MES
    identifiers.
8.  Calculated values should normally be derived from source data rather
    than duplicated unless the contract explicitly requires persistence.
9.  Existing legacy objects such as `wetReject1` and `wetReject2` must
    not be altered or dropped unless explicitly approved.
10. When database semantics change, update this document in the same
    change.

------------------------------------------------------------------------

## 2. Main Database Objects

Known FittingMES tables:

-   `dbo.ProductCodeMaster`
-   `dbo.ProductFamilyMaster`
-   `dbo.MaterialProductMap`
-   `dbo.ProductionLot`
-   `dbo.ProductionLotHistory`
-   `dbo.ProductionData`
-   `dbo.Depallet`
-   `dbo.DepalletReject`
-   `dbo.RejectReasonMaster`
-   `dbo.DepalletPISLog`
-   `dbo.MaterialUsageMaster`
-   `dbo.DailyMaterialUsage`
-   `dbo.DailyMaterialUsageDetail`
-   `dbo.wetReject1` --- legacy; do not alter/drop
-   `dbo.wetReject2` --- legacy; do not alter/drop

Known views:

-   `dbo.vw_DailyMaterialUsage`
-   `dbo.vw_DailyMaterialUsageTotal`
-   `dbo.vw_DailyProductionQty`: production denominators from ProductionLot
    and ProductionData.
-   `dbo.vw_DailyMaterialUsageCalc`: shift RawQty, UsageType,
    QtyPer1000Counter, QtyPer1000Curing, CounterPerUnit.
-   `dbo.vw_DailyMaterialUsageTotalCalc`: ALL DAY RawQty, UsageType and the
    same three calculated rate columns, based on daily aggregated quantities.

The two calculation views join MaterialUsageMaster by MaterialUsageCode.
They return QtyPer1000Counter/QtyPer1000Curing only for MATERIAL, and
CounterPerUnit only for CONSUMABLE; other rates are NULL.
`app.usage.read_usage_context` consumes these views directly, using the
active master to retain all columns even before the first usage save.
-   `dbo.vw_DepalletSummary`
-   `dbo.vw_DepalletValidation`

Production planning is read from `dbo.P_ActivePlan` / `dbo.ActivePlan`.
The application must use the actual live plan source rather than a
static copy.

------------------------------------------------------------------------

## 3. Production Planning Source

### `dbo.ActivePlan`

Known definition:

``` sql
ALTER VIEW [dbo].[ActivePlan]
AS
SELECT TOP (100) PERCENT *
FROM dbo.P_ActivePlan
WHERE (company = 'CRTC')
  AND (Machine = 'SB2-3')
  AND (Plant = '30A1')
...
ORDER BY StartTime DESC, VersionNo DESC, Shift;
```

Important semantics:

-   Product/plan choices are read live from `dbo.P_ActivePlan`.
-   Production date used for lot numbering is based on the selected
    plan's `StartTime`, not the server's current date.
-   Default shift may come from the selected plan, but the operator can
    edit the shift and the selected value is stored with the lot.
-   Known PIS mapping from the selected plan:
    -   `plantCode` ← `Plant`
    -   `machineCode` ← `Machine`
    -   `operationCode` ← plan operation code
    -   `planWeek` ← `PlanWeek`
    -   `versionNo` ← `VersionNo`
    -   `planName` ← selected/saved plan

Do not guess missing plan fields.

------------------------------------------------------------------------

## 4. Product Family and Lot Rules

Four mutually exclusive product families are currently used:

  Family              Lot Prefix
  ------------------- ------------
  NeuFit / NeuStile   `B`
  Oriental            `B`
  Special Ridge       `I`
  Prestige Common     `I`

Known product codes:

### NeuFit / NeuStile

`01` Eaves, `02` Angle Ridge, `03` Angle Ridge End, `04` Angle HIP, `05`
Angle HIP End, `06` Verge, `07` Verge End, `08` Verge Seamless, `09`
Verge Seamless End, `10` Wall Ridge, `11` Wall Verge.

### Oriental

`12` Main, `13` TOP, `14` Eaves, `15` Angle Ridge, `16` Angle Ridge End,
`17` Angle HIP, `18` Angle HIP End, `19` Verge, `20` Verge End, `21`
Wall Ridge, `22` Wall Verge.

### Special Ridge

`01` ปิดจั่ว, `02` ปิดชาย, `03` หางมน, `04` 2 ทาง, `05` 3 ทาง, `06` 4 ทาง,
`07` ข้างผนัง, `08` โค้งผนัง E, `09` โค้งผนัง C.

### Prestige Common

`11` Angle Ridge, `12` Angle Ridge End, `13` Angle HIP, `14` Angle HIP
End, `15` Verge Seamless, `16` Verge Seamless End, `17` Wall Ridge, `18`
Wall Verge, `19` Verge, `20` Verge End.

Lot numbering rules:

-   Prefix is family-dependent (`B` or `I`).
-   Date portion is derived from the selected plan `StartTime`.
-   Running number resets monthly.
-   Running is family/product-aware.
-   Examples: `B006690901`, `B006690902`, `I02690901`.

Do not change the lot algorithm without verifying the existing
implementation and production workflow.

------------------------------------------------------------------------

## 5. Production Transaction Data

### `dbo.ProductionLot`

Represents the MES production lot and its selected plan/product context.

Important concepts used by the application include:

-   Production date
-   Shift
-   Lot number
-   Product/material code
-   Selected production plan and plan-related information

The exact schema must be inspected before modifying SQL. Do not infer
undocumented column names from this document.

### `dbo.ProductionData`

Stores operator-entered production quantities/times associated with a
production lot.

Current application concepts:

-   Start time
-   End time
-   Counter quantity
-   Curing quantity
-   Remark

Wet reject is derived as:

``` text
WetRejectQty = CounterQty - CuringQty
```

Wet reject percentage is a calculated display value and should be
derived from the authoritative production quantities.

For PIS production output, the current quantity source is `CuringQty`.

------------------------------------------------------------------------

## 6. Depallet

### `dbo.Depallet`

Stores depallet transaction/header information.

Current UI concepts include:

-   Depallet Date
-   Shift
-   Depallet Lot
-   Depallet Qty
-   Good Qty
-   Remark

### `dbo.DepalletReject`

Stores reject classification quantities for a depallet transaction.

Reject codes `R01` through `R24` are operator-entered classifications.
`R99` is calculated by the server.

Authoritative calculation:

``` text
PhysicalRejectQty   = DepalletQty - GoodQty
ClassifiedRejectQty = SUM(R01 ... R24)
Difference          = PhysicalRejectQty - ClassifiedRejectQty
R99                 = MAX(Difference, 0)
```

Rules:

-   Client-provided `R99` must not be trusted.
-   Server recalculates `R99`.
-   Save `R01`--`R24` exactly as entered.
-   If calculated `R99 > 0`, upsert the normalized R99 row.
-   If calculated `R99 = 0`, delete any stale R99 row.
-   If classified reject is greater than physical reject, saving is
    allowed with a warning; `R99 = 0`.
-   No PIS compensation logic should be invented.

### `dbo.RejectReasonMaster`

Master for reject reason codes.

Current active reject codes are `R01`--`R24` plus `R99`.

`R99` means "อื่นๆ / Other" and is special because its quantity is
calculated as described above.

### `dbo.DepalletPISLog`

Used for PIS-related depallet/reject integration logging. Keep
external-delivery state/logging separate from the source depallet/reject
transaction data.

Inspect the actual schema before implementing or changing PIS delivery
logic.

------------------------------------------------------------------------

## 7. Material Usage Architecture

Material usage is **dynamic and row-based**.

Do **not**:

-   create one SQL column per material;
-   use Thai material names as database/application keys;
-   hard-code the current material list in Python, HTML, or JavaScript;
-   assume the current 16 active materials will remain fixed.

The active material list comes from:

``` text
dbo.MaterialUsageMaster
```

filtered by `IsActive = 1` and ordered by `SortOrder, MaterialUsageCode`.

------------------------------------------------------------------------

## 8. `dbo.MaterialUsageMaster`

Purpose: master/configuration list for materials shown on the FittingMES
**USAGE** page.

Actual schema confirmed on 2026-09-23:

  -----------------------------------------------------------------------
  Column                              Type / Meaning
  ----------------------------------- -----------------------------------
  `MaterialUsageCode`                 `varchar(30)`, primary key. Stable
                                      English coding key; camelCase; no
                                      spaces.

  `MaterialNameTH`                    `nvarchar`, Thai display name only.
                                      Never use as application key.

  `MaterialNameEN`                    `nvarchar`, English display name.
                                      May contain spaces.

  `Unit`                              `nvarchar`, local input/display
                                      unit.

  `SortOrder`                         `int`, unique display order.

  `APIFieldCode`                      `varchar`, reserved for future
                                      external API mapping. Leave `NULL`
                                      until authoritative mapping is
                                      known.

  `IsActive`                          `bit`, `1` active / `0` inactive.

  `CreatedAt`                         creation timestamp.

  `UpdatedAt`                         update timestamp.
  -----------------------------------------------------------------------

`UsageType` is `varchar(20) NOT NULL` with the valid classifications:
`MATERIAL` (material consumption), `RAW` (operational usage/loss), and
`CONSUMABLE` (production consumable units). It controls display behavior;
material codes and names never determine formulas.

The final live SB23 schema, confirmed by the database owner on 2026-09-23,
requires `UsageType` to be non-null. All 16 active records have valid
classifications.

Current master rows (the first ten are MATERIAL):

  MaterialUsageCode   MaterialNameTH     MaterialNameEN     Unit
  ------------------- ------------------ ------------------ ------
  `flyAsh`            เถ้าลอย             Fly Ash            kg
  `cementBody`        ปูนซีเมนต์ผสมตัว       Cement Body        kg
  `cementColor`       ปูนซีเมนต์ผสมสี        Cement Color       kg
  `sandBody`          ทรายผสมตัว          Sand Body          kg
  `sandColor`         ทรายผสมสี           Sand Color         kg
  `waterBaseSpray`    Water Base Spray   Water Base Spray   kg
  `mouldOil`          Mould Oil          Mould Oil          L
  `adva`              Adva               Adva               kg
  `baseColor`         สีพื้น                Base Color         kg
  `effectColor`       สีเหลือบ             Effect Color       kg

Six additional active configuration records are present:

| MaterialUsageCode | UsageType | Unit |
| --- | --- | --- |
| cementBatchUsed | RAW | Batch |
| cementBatchDiscarded | RAW | Batch |
| baseColorDiscarded | RAW | Bucket |
| effectColorDiscarded | RAW | Bucket |
| clothUsed | CONSUMABLE | Piece |
| screenUsed | CONSUMABLE | Sheet |

All 16 active records are configuration data, **not application schema**.
The application must not hard-code this list or hide the six newer records. Future
materials can be added/disabled without changing the table or
application structure.

`MaterialUsageCode` is the stable coding identity. External API material
numbers must not replace it.

------------------------------------------------------------------------

## 9. `dbo.DailyMaterialUsage`

Purpose: one material-usage header for one production date and shift.

Actual schema confirmed on 2026-09-23:

  -----------------------------------------------------------------------
  Column                              Meaning
  ----------------------------------- -----------------------------------
  `MaterialUsageID`                   `bigint IDENTITY`, primary key.

  `ReportDate`                        Production/report date.

  `Shift`                             Shift identifier. Current USAGE
                                      design uses Shift 1 and Shift 2.

  `Remark`                            Optional header remark.

  `CreatedAt`                         creation timestamp.

  `UpdatedAt`                         update timestamp.
  -----------------------------------------------------------------------

Database uniqueness:

``` text
ReportDate + Shift
```

There must be at most one usage header for a date/shift.

------------------------------------------------------------------------

## 10. `dbo.DailyMaterialUsageDetail`

Purpose: material quantities belonging to a `DailyMaterialUsage` header.

Actual schema confirmed on 2026-09-23:

  -----------------------------------------------------------------------
  Column                              Meaning
  ----------------------------------- -----------------------------------
  `MaterialUsageDetailID`             `bigint IDENTITY`, primary key.

  `MaterialUsageID`                   Parent usage header.

  `MaterialUsageCode`                 Material key referencing
                                      `MaterialUsageMaster`.

  `Qty`                               `decimal(18,3)`, raw usage quantity
                                      stored by MES.

  `SourceType`                        Identifies source/type of the
                                      quantity. Do not invent values
                                      without defining them.

  `Remark`                            Optional detail remark.

  `CreatedAt`                         creation timestamp.

  `UpdatedAt`                         update timestamp.
  -----------------------------------------------------------------------

Database uniqueness:

``` text
MaterialUsageID + MaterialUsageCode
```

There must be at most one row for each material within a usage header.

------------------------------------------------------------------------

## 11. Material Usage Calculation Rules

`DailyMaterialUsageDetail.Qty` stores the raw material quantity.

Production `Counter` and `Curing` quantities must **not** be duplicated
into the material-usage tables merely for calculation. They come from
FittingMES production data.

### Shift calculation

For each active `MATERIAL` record (calculated by SQL):

``` text
UsagePer1000Counter = RawQty * 1000 / ShiftCounter
UsagePer1000Curing  = RawQty * 1000 / ShiftCuring
```

If the denominator is zero, return `NULL` / no calculated value. Do not
divide by zero.

### ALL DAY calculation

First aggregate the raw material quantity for the same
`MaterialUsageCode` across Shift 1 and Shift 2:

``` text
TotalRawQty = Shift1RawQty + Shift2RawQty
```

Then aggregate production quantities for the whole selected production
date:

``` text
For MATERIAL only:
AllDayPer1000Counter = TotalRawQty * 1000 / TotalCounter
AllDayPer1000Curing  = TotalRawQty * 1000 / TotalCuring
```

**Do not** calculate ALL DAY by adding Shift 1 and Shift 2 normalized
`/1000` values.

For `RAW`, raw quantities remain editable per shift and ALL DAY shows the
SQL total raw quantity. All calculated rate cells display `-`.

For `CONSUMABLE`, SQL exposes `CounterPerUnit`: shift CounterQty / raw Qty,
and ALL DAY total CounterQty / total raw Qty. The views use `NULLIF` on the
usage quantity denominator and return `decimal(18,3)`. Display these values
in a dedicated **Counter / Unit** row. Do not show Qty/1000 rates for these
columns. MATERIAL and RAW show `-` in Counter / Unit cells.

Neither Python nor JavaScript recomputes these calculations. Zero/null
SQL results retain their existing display semantics (zero versus `-`).
Calculated values should be derived, not persisted, unless this contract
is explicitly changed.

------------------------------------------------------------------------

## 12. Material Usage Views

Known existing views:

-   `dbo.vw_DailyMaterialUsage`
-   `dbo.vw_DailyMaterialUsageTotal`
-   `dbo.vw_DailyProductionQty`: production denominators from ProductionLot
    and ProductionData.
-   `dbo.vw_DailyMaterialUsageCalc`: shift RawQty, UsageType,
    QtyPer1000Counter, QtyPer1000Curing, CounterPerUnit.
-   `dbo.vw_DailyMaterialUsageTotalCalc`: ALL DAY RawQty, UsageType and the
    same three calculated rate columns, based on daily aggregated quantities.

The two calculation views join MaterialUsageMaster by MaterialUsageCode.
They return QtyPer1000Counter/QtyPer1000Curing only for MATERIAL, and
CounterPerUnit only for CONSUMABLE; other rates are NULL.
`app.usage.read_usage_context` consumes these views directly, using the
active master to retain all columns even before the first usage save.

Before changing these views, inspect their current SQL definitions.

Do not assume their current formulas are correct merely from their
names. Reconcile them with the calculation rules in this document and
the final approved Excel/business formula.

------------------------------------------------------------------------

## 13. USAGE Page Contract

Target navigation:

``` text
PRODUCTION | USAGE | PROD API | REJECT API
```

The USAGE page uses the same selected **Production Date** as the other
FittingMES pages.

Target page structure:

1.  Production lots for the selected Production Date
2.  Shift 1 raw material usage input
3.  Shift 1 calculated values
4.  Shift 2 raw material usage input
5.  Shift 2 calculated values
6.  ALL DAY calculated values

The production-lot section can resemble the PROD API lot table, but **no
lot radio selection is required** for USAGE.

Horizontal material columns must be generated dynamically:

``` sql
SELECT ...
FROM dbo.MaterialUsageMaster
WHERE IsActive = 1
ORDER BY SortOrder, MaterialUsageCode;
```

Do not hard-code `flyAsh`, `cementBody`, etc. as HTML/Python/JavaScript
fields.

------------------------------------------------------------------------

## 14. Shared Production Date

FittingMES should ultimately have **one shared Production Date
selector** at the top of the application rather than an independent date
selector on every tab.

The selected date should carry across:

``` text
PRODUCTION
USAGE
PROD API
REJECT API
```

Changing tabs should not require the operator to reselect the date.

Database queries for each page must use the selected production date
according to that page's transaction semantics.

------------------------------------------------------------------------

## 15. PIS Production API Mapping

PIS production integration uses:

``` text
POST /api/v1/ProdOrders
GET  /api/v2/OutputDetails
POST /api/v1/OutputDetails/ChangeStatus
```

Current FittingMES PROD API is dry-run/preview oriented. External
sending must remain disabled until mappings and payloads are verified.

Important operational rule:

> PIS production must not be treated as an arbitrary one-lot send
> workflow.

Actual SEND must send **all eligible production lots for the selected
day**, grouped as required. A one-lot payload may be generated for
dry-run preview only.

Current preview modes:

-   `PREVIEW PROD` --- selected single lot, dry run only.
-   `PREVIEW ALL PROD` --- all eligible lots for the selected day.
-   Future actual action: one `SEND ALL PIS`.

Grouping key for all-production requests:

``` text
productionDate + shiftCode + plantCode + machineCode
```

Each group becomes one `ProdOrders` request containing multiple
`productionItems`. Do not invent an additional wrapper around multiple
groups.

Known top-level fields:

``` text
productionDate
shiftCode
plantCode
machineCode
operatorName
resources[]
productionItems[]
```

Known production item fields:

``` text
operationCode
dateTimeStart
dateTimeEnd
planWeek
planName
versionNo
followPlan
remark
itemDetails[]
itemOutputs[]
itemInputs[]
itemProperties[]
```

Known mappings:

-   `productionDate` ← `ProductionLot.ProdDate`
-   `shiftCode` ← saved `ProductionLot.Shift`
-   `plantCode` ← matching ActivePlan `Plant`
-   `machineCode` ← matching ActivePlan `Machine`
-   `operationCode` ← matching ActivePlan operation
-   `planWeek` ← matching ActivePlan `PlanWeek`
-   `planName` ← saved selected plan
-   `versionNo` ← matching ActivePlan `VersionNo`
-   `dateTimeStart` / `dateTimeEnd` ← production date + saved
    ProductionData times
-   If End time is earlier than Start time, End belongs to the next
    calendar day.
-   `materialCode` ← production lot material code
-   `lotNo` ← production lot number
-   output `gross0` ← `CuringQty`
-   output detail `count` ← `CuringQty`
-   output detail `statusCode` = `Curing`

`followPlan` rule:

``` text
followPlan = true  when CuringQty >= selected PlanQty
followPlan = false when CuringQty <  selected PlanQty
```

`PlanQty` is the quantity from the selected production plan.

Do not guess unresolved PIS fields.

------------------------------------------------------------------------

## 16. PIS Production Preview Table

The PROD API page is read-only with respect to production source data.

Known table information includes:

-   Production Date
-   Shift
-   Start
-   End
-   Plan
-   Version
-   Material Code
-   Lot No.
-   Product
-   Plan Qty
-   Counter
-   Curing
-   Wet Reject
-   Remark
-   Local status

`Plan Qty` should appear immediately before `Counter`.

------------------------------------------------------------------------

## 17. Reject API vs Production API

Do not assume reject sending follows the same batching rule as
production sending.

-   Production PIS: actual sending is all eligible production lots for
    the selected day/grouping.
-   Reject PIS: individual lot sending is supported; an all-reject
    action may send individual lots.

Keep the workflows separate.

------------------------------------------------------------------------

## 18. Angel / Material Usage External API

Angel integration is **not implemented yet**.

The authoritative Angel Material Master belongs to another system/server
and FittingMES has not yet seen the complete authoritative list of
material codes.

Therefore:

-   Do not guess Angel Material Number.
-   Do not guess Angel UOM.
-   Do not guess GL Account.
-   Do not guess Cost Center.
-   Do not guess Sloc.
-   Do not guess approver/requester usernames.
-   Do not copy CB/tile examples into SB23 as if they were FittingMES
    values.
-   Keep `MaterialUsageMaster.APIFieldCode` `NULL` until an
    authoritative mapping is confirmed.

The future architecture should keep external mapping separate from the
internal `MaterialUsageCode`.

Conceptually:

``` text
MaterialUsageMaster
        |
        v
Future Angel Mapping
        |
        v
Angel API
```

An external mapping change must not require changing historical
FittingMES usage records.

Future delivery logging should also be separate from source usage
transactions.

------------------------------------------------------------------------

## 19. External API Example vs Authoritative Data

Existing Angel/Auto GI documents contain example structures and mappings
from another process/site.

They are useful for understanding the expected API shape, but **they are
not authoritative SB23 material master data**.

Known conceptual Angel fields include:

``` text
InterfaceID
Approve1
Approve2
CreateBy
RequestDateTime
CompanyCode
CompanyID
DocumentRemark
EST_PL_ITEM[]
```

Item concepts include:

``` text
Item_Number
Item_Status
Cost_Center
GL_Account
Material_Number
Quantity
Material_Plant
Material_PlantID
GI_Quantity
Plan_Delivery_Day
Unit_Price
CurrencyNo
UOM
UseForPlantID
```

Do not populate these from guesses. Wait for the authoritative
FittingMES/SB23 mapping.

------------------------------------------------------------------------

## 20. Application/SQL Development Guardrails

Before any Codex task involving database access:

1.  Read this `DATABASE.md`.
2.  Read the relevant workflow document in `docs/`.
3.  Inspect the actual current SQL schema/definition.
4.  Reuse existing tables/views when they already represent the required
    concept.
5.  Do not create a similarly named replacement table merely because the
    current schema was not inspected.
6.  Do not modify unrelated tables/views.
7.  Do not add external send routes/buttons unless explicitly requested.
8.  Do not send requests to PIS/Angel during preview-only work.
9.  Add/update tests for changed database behavior.
10. Update this document if semantics change.

Suggested instruction for Codex:

> Read `docs/DATABASE.md` first and treat it as the database contract.
> Inspect the actual existing schema and relevant workflow docs before
> making changes. Reuse existing database objects. Do not infer
> undocumented mappings, create duplicate tables, change unrelated
> schema, or enable external API sending unless explicitly requested.

------------------------------------------------------------------------

## 21. Known Environment

Current deployment context:

``` text
Project: D:\AI\FittingMES
Database: SB23
SQL Server: DCDLGYF3\SQLEXPRESS
Server: 10.28.254.3
Runtime: Python 3.11
Web: FastAPI
Current web port: 1868
```

Secrets and credentials belong in `.env` and must not be committed to
Git or copied into this document.

Known PIS configuration variables are environment-based. Never put
usernames/passwords in source code or documentation.

------------------------------------------------------------------------

## 22. What This Document Does Not Authorize

This document does **not** authorize a developer to:

-   change production data semantics;
-   drop legacy objects;
-   alter lot numbering;
-   enable PIS sending;
-   enable Angel sending;
-   create guessed external mappings;
-   copy material codes from another plant;
-   replace dynamic material rows with fixed columns;
-   persist calculated values unnecessarily;
-   modify tables outside the requested task.

When required information is unknown, stop at the mapping/configuration
boundary and leave the unknown value unresolved rather than inventing
it.

------------------------------------------------------------------------

## 23. Current Status Snapshot --- 2026-09-23

At the time of this document:

-   Production entry and depallet workflows exist.
-   Material usage tables already exist in `SB23`.
-   `MaterialUsageMaster` contains the initial 10 active FittingMES
    usage materials.
-   `DailyMaterialUsage` and `DailyMaterialUsageDetail` are currently
    the intended transaction structure for the USAGE page.
-   PROD API supports dry-run preview, including single-lot preview and
    all-production preview.
-   Actual PIS production send is not yet enabled in FittingMES.
-   Angel material codes/mappings are not yet known and must not be
    guessed.
-   The planned USAGE page has not yet been implemented.
-   A shared Production Date selector across application tabs is
    planned.

------------------------------------------------------------------------

**Maintenance rule:** whenever a database object, field meaning,
calculation, or external mapping is changed, update this document so it
remains the authoritative SQL/database context for FittingMES.
