# FittingMES REJECT Module Requirements

**Status:** Authoritative implementation specification\
**Repository:** `D:\AI\FittingMES`

## 1. Core concept

The new **REJECT** tab is the **quantity-based sibling of LOGGER**.

-   LOGGER records detailed time events and feeds summaries through
    `LOG CAL`.
-   REJECT records detailed reject quantities and feeds summaries
    through `REJECT CAL`.
-   Do not reproduce the old Excel/paper matrix as the main web-entry
    UI.
-   Reuse the proven LOGGER interaction pattern and project architecture
    where appropriate.
-   Production and Depallet are separate UI workflow modes. The selected
    mode routes SAVE to its workflow-specific transaction table; it is not
    persisted on the transaction.

Operator flow after setting the header context:

`Qty -> Source -> Reject Reason -> SAVE`

Each SAVE creates one detailed row in exactly one of:

-   `dbo.ProductionRejectEntry`
-   `dbo.DepalletRejectEntry`

The table is the workflow owner. The same ProductionID may have entries
in both tables.

## 2. Production Date

`Production Date` is already the global FittingMES context above the
tabs.

**Do not add another Production Date selector inside REJECT.**

## 3. REJECT header context

Top of REJECT:

`REJECT | Shift | Reject Of | Line | Product / Lot`

Example:

``` text
REJECT   Shift: [1 v]   Reject Of: [Production v]   Line: [LINE1 v]   Product / Lot: [.... v]

Qty      Source          Reject Reason
[ 5 ]    [F3 v]          [R301 ... v]                                  [SAVE]
```

Header selections remain selected while multiple reject rows are added.

### Shift

REJECT selects a row from `dbo.ShiftMaster` and saves its ID:

-   `ShiftID -> ShiftMaster.id`

The business codes are `1` and `2`, displayed as Shift 1 and Shift 2.
Effective start times remain in `ProductionShiftRuleHistory`; do not
duplicate them in ShiftMaster. Resolve selected shifts by ShiftCode, never
by assuming generated IDs.

Existing `ProductionLot.Shift`, `Depallet.Shift`, `LoggerEvent.ShiftID`,
`EquipmentTimeEvent.ShiftID`, and `ProductionShiftRuleHistory.ShiftID`
remain unchanged. Production REJECT validates that the transaction
ShiftID is active but does not require it to match `ProductionLot.Shift`;
the ProductionID is the whole-Lot identity. Depallet retains its existing
Shift/Lot matching rule.

### Reject Of

-   Choices are `Production` and `Depallet`.
-   Default to `Production` whenever REJECT is initially opened.
-   This is UI routing state only. It is not a RejectReason attribute,
    applicability rule, saved value, flag, or master.
-   `Production` routes SAVE to `ProductionRejectEntry`.
-   `Depallet` routes SAVE to `DepalletRejectEntry`.

The selected mode does not require a Depallet run or DepalletID.

### Line

For `Reject of = Production`:

-   LINE1
-   LINE2

For `Reject of = Depallet`:

-   display LINE1 (DRY)
-   display LINE2 (DRY)

`(Dry)` is UI meaning only. Do not create duplicate dry-line equipment
masters just for this label.

### Product / Lot

Product/Lot is header context and is selected once for multiple reject
entries.

Use `ProductionID -> ProductionLot.ProductionID` as Product/Lot identity.
Production candidates must match the global Production Date and active /
valid ProductionLot context, but may remain selected when the transaction
Shift changes. For Production SAVE, the server validates that ShiftID is
active and that ProductionID belongs to the selected date and is active;
ProductionLot.Shift does not restrict the transaction Shift. Depallet
continues to require its existing selected Shift / Lot match. Reject lots
with NULL ProductFamilyID. ProductFamilyID and ProductCode are obtained
through ProductionLot; neither is copied into the new entry tables.
ProductFamilyID relationships use IDs, not family names or hardcoded
numeric IDs.

## 4. Source

Source is selected per reject entry and filtered by the selected Line.

For LINE1, show:

-   active Press machines configured to LINE1
-   LINE1 itself

For LINE2, show:

-   active Press machines configured to LINE2
-   LINE2 itself

Current configuration examples only:

-   F1-F5 currently belong to LINE1
-   F6 is currently Inactive
-   F7-F14 currently belong to LINE2

**Do not hard-code these assignments.**

The existing **PressMc/equipment master configuration is the single
source of truth for Press -\> Line and Active status**.

Do not create another Press-to-Line mapping for REJECT.

EquipmentMaster receives an additive `id bigint IDENTITY(1,1)` with a
UNIQUE candidate key for new FKs. Keep EquipmentCode as its existing
clustered primary key and preserve all legacy EquipmentCode relationships.
New REJECT entries use LineEquipmentID and SourceEquipmentID referencing
EquipmentMaster.id. Do not change legacy procedures, PressMc behavior, or
EquipmentLineMap relationships.

RejectReason.SourceScope is read through its database relationship to
RejectSourceScope. PRESS reasons offer active Press sources mapped to the
selected Line; LINE reasons offer the selected Line itself. LINE denotes
the attribution level, not necessarily the physical cause. For Depallet
display only, LINE1/LINE2 may be labeled `(DRY)`; stored identity remains
the corresponding equipment ID.

## 5. Entry fields

Each entry requires only:

-   Qty
-   Source
-   Reject Reason
-   SAVE

Qty is reject quantity, not minutes.

Use server-side validation, not browser validation alone.

## 6. REJECT ENTRIES

Saved entries appear below from the table corresponding to the selected
workflow, following LOGGER's proven list/edit pattern where practical.

Conceptual columns:

``` text
Select | Source | Line | Shift | Product / Lot | Code | Reject Reason | Qty
```

Investigate and reuse LOGGER's Select/Edit/Cancel behavior where
appropriate.

## 7. No Before Primer / After Primer selector

Do **not** add a separate `Before Primer / After Primer` selector.

The reject reasons and database-configured SourceScope describe the
attribution level. `Reject Of` remains a UI routing choice: Production
SAVE writes to `ProductionRejectEntry`; Depallet SAVE writes to
`DepalletRejectEntry`. It is not a saved transaction attribute or
reason-applicability rule.

## 8. Fitting ReasonCode namespaces

Existing tile/API reason codes `R01-R98` are already reserved/used by
the tile system.

Fitting uses separate namespaces:

-   `R1xx` = Special Ridge / ครอบพิเศษ
-   `R2xx` = Prestige
-   `R3xx` = NeuFit / NeuStile + Oriental
-   `x99` = อื่นๆ for that catalog

Unused numbers remain reserved for future additions.

## 9. Special Ridge / ครอบพิเศษ

  Code   Reject Reason                    SourceScope
  ------ -------------------------------  -----------
  R101   เนื้อแหว่งใต้ครอบ                PRESS
  R102   ครอบแตกบิ่น                       PRESS
  R103   ขอบแหว่ง                          PRESS
  R104   ครอบมีรอยขีด                      PRESS
  R105   ผิวปูดบวม                         PRESS
  R106   ร้าวแก้มครอบ                      PRESS
  R107   ร้าวใต้ครอบ                       PRESS
  R108   ร้าวคอครอบ                        PRESS
  R109   ร้าวจานครอบ                       PRESS
  R110   ร้าวทะลุตัวครอบ                   PRESS
  R111   ร้าวท้ายครอบ                      PRESS
  R112   ร้าวผิวครอบ                       PRESS
  R113   ร้าวหัวครอบ                       PRESS
  R114   สีเป็นเม็ด                        LINE
  R115   สีเป็นฟอง                         LINE
  R116   สี Salary ไม่เต็ม                 LINE
  R117   สีด้าน                            LINE
  R118   ปูนติดโมล                         PRESS
  R119   สีถลอก                            LINE
  R120   สีปูด                             LINE
  R121   สีหยด                             LINE
  R122   สีไหล/ เยิ้ม                      LINE
  R123   สีพอง                             LINE
  R124   แกะงานแตก                         LINE
  R125   หัวครอบแตก                        PRESS
  R126   รถยกชนแตก                         LINE
  R127   ยกชน Rack                         LINE
  R199   อื่นๆ                             LINE

R128-R198 remain available.

## 10. Prestige

  Code   Reject Reason                              SourceScope
  ------ -----------------------------------------  -----------
  R201   ร้าวผิวตัวกระเบื้อง                         PRESS
  R202   ร้าวรางลิ้นหงาย                             PRESS
  R203   ร้าวล่างรางลิ้นคว่ำ                         PRESS
  R204   ร้าวล่างตัวครอบ                             PRESS
  R205   ร้าวชายกระเบื้อง                            PRESS
  R206   ร้าวเขื่อนรางลิ้นหงาย                       PRESS
  R207   ร้าวเขื่อนรางลิ้นคว่ำ                       PRESS
  R208   บิ่นแหว่ง                                   PRESS
  R209   ผิวครอบปูดบวม                               PRESS
  R210   ผิวครอบไม่เรียบ                             PRESS
  R211   ขอบไม่คม / ขอบไม่เรียบ                     PRESS
  R212   รูพรุน                                      PRESS
  R213   แตกรูตะปู                                   PRESS
  R214   ผ้าขาด/ติดผ้า/เนื้อแหว่งใต้ครอบ           PRESS
  R215   ปูนติดโมล                                   PRESS
  R216   สี Salary ไม่เต็ม                           LINE
  R217   สีเป็นเม็ด                                  LINE
  R218   สีพอง                                      LINE
  R219   สีหนา                                      LINE
  R220   สีไหล/ เยิ้ม                                LINE
  R221   สีหยด                                      LINE
  R222   สีปูด                                       LINE
  R223   ครอบบาง/น้ำหนักเบา                         PRESS
  R224   ยกชน Rack                                  LINE
  R225   รถยกชน                                     LINE
  R299   อื่นๆ                                       LINE

R226-R298 remain available.

## 11. NeuFit / NeuStile + Oriental

NeuFit / NeuStile and Oriental share one reject catalog.

  Code   Reject Reason                    SourceScope
  ------ -------------------------------  -----------
  R301   ร้าวผิวตัวกระเบื้อง                PRESS
  R302   ร้าวอกรับน้ำ                       PRESS
  R303   ร้าวสันเขื่อน                      PRESS
  R304   เป็นครีบ                           PRESS
  R305   คราบน้ำ                            PRESS
  R306   ร้าวรางลิ้นหงาย                   PRESS
  R307   ร้าวชายกระเบื้อง                  PRESS
  R308   ร้าวล่างรางลิ้นคว่ำ               PRESS
  R309   ร้าวขอเกาะ                        PRESS
  R310   ร้าวล่างตัวครอบ                   PRESS
  R311   บิ่นแหว่ง / แตกบิ่น                PRESS
  R312   ปูนติดโมลบน                       PRESS
  R313   โก่งแอ่น                           PRESS
  R314   รูพรุน                             PRESS
  R315   ผิวปูดบวม/ผิวระเบิด               PRESS
  R316   ขอบไม่คม                          PRESS
  R317   แต่งผิวไม่เรียบ                   PRESS
  R318   แตกรูตะปู                         PRESS
  R319   แบบชนในไลน์ผลิต                  LINE
  R320   สีไม่เต็มแผ่น                     LINE
  R321   สีนอง / สีแตก                     LINE
  R322   เนื้อแหว่งใต้ครอบ                 PRESS
  R323   กระเบื้อง / ครอบแฉะ               PRESS
  R399   อื่นๆ                             LINE

R324-R398 remain available.

## 12. Reason applicability

Product/Lot determines the applicable reason catalog through
`ProductionLot.ProductFamilyID` and ID-based
`RejectReasonProductFamily` rows. The selected ProductionID is the lot
identity; do not copy ProductCode or ProductFamilyID into either entry
table.

Do **not** implement business rules using numeric comparisons such as
`ReasonCode >= R216`.

Each reason has exactly one approved SourceScope, stored through the
database relationship `RejectReason.RejectSourceScopeID ->
RejectSourceScope.id`. The database is authoritative. The complete
approved mapping is in Sections 9-11; all SourceScope assignments are
approved and final.
Do not infer SourceScope from a reason code, range, name, or family.

Preserve bidirectional filtering:

-   Source first: filter reasons by ProductFamilyID and the selected
    source's configured type/scope.
-   Reason first: read its database SourceScope; PRESS offers active
    Presses mapped to the selected Line, while LINE offers that Line.
-   SAVE revalidates family applicability, SourceScope, equipment type,
    source-to-Line mapping, and active equipment status on the server.

Reject Of does not restrict reason applicability.

## 13. Standalone REJECT CAL

Keep the existing reject frames/summary areas in **Production** and
**Depallet**.

Pattern:

`REJECT detail -> REJECT CAL -> Production/Depallet reject summary`

This mirrors:

`LOGGER detail -> LOG CAL -> Production summary`

### Production REJECT CAL

The standalone `/reject/cal` page reads only `dbo.ProductionRejectEntry`,
matching:

-   global Production Date
-   relevant Shift
-   relevant Product/Lot/Production context
Calculate/load the Shift-specific Production REJECT summary.

### Depallet REJECT CAL

Read only `dbo.DepalletRejectEntry`, matching:

-   global Production Date
-   relevant Shift
-   relevant Product/Lot/Depallet context
Calculate/load the Depallet/Dry Reject summary.

Neither workflow uses a DepalletID owner relationship. A Depallet-side
reject belongs to the selected Product/Lot context, not a specific
Depallet run.

The standalone REJECT CAL and Production-page FINAL SAVE are separate
operations. Standalone CAL is read-only and does not populate the
Production page's editable whole-Lot FINAL form.

Keep the standalone Production and Depallet REJECT CAL pages.

### Production-page whole-Lot FINAL reconciliation

The Production page uses `dbo.ProductionRejectFinal` and
`dbo.ProductionRejectFinalDetail`; it no longer uses the legacy WetReject
master or transaction tables for its Production REJECT entry area.

-   One FINAL header is keyed uniquely by ProductionID, without ShiftID.
-   Applicable active RejectReason rows are selected dynamically through
    RejectReasonProductFamily.
-   Ordinary page LOAD displays saved FinalQty values, or zeros if no
    FINAL exists. LOAD does not calculate RAW.
-   REJECT CAL reads ProductionRejectEntry for the authoritative Lot
    ProductionDate and ProductionID, groups by RejectReasonID, and
    includes all transaction shifts, Sources, and Lines.
-   CAL only updates browser form state. SAVE validates the fresh
    ProductionData wet total and fresh RAW audit totals, then atomically
    replaces the complete applicable-reason detail snapshot.
-   Qty/Day is derived from saved FINAL detail for active Production Lots
    on the Production Date.
-   RAW rows and legacy WetReject tables are never changed by FINAL SAVE.

## 14. Paper/Excel relationship

The paper form uses:

-   reject reasons vertically
-   F machines/products horizontally
-   quantities at intersections
-   separate shift/process context

The web UI preserves the information, not the wide matrix layout.

Set context once:

`Shift + Reject Of + Line + Product/Lot`

Then repeatedly enter:

`Qty + Source + Reject Reason -> SAVE`

Reject Of defaults to Production and routes SAVE to the corresponding
workflow table; it is never persisted.

## 15. Existing implementation and legacy isolation

Use the inspected implementation as context, but do not replace or modify
legacy reject behavior. The new Fitting REJECT workflow is independent of:

-   RejectReasonMaster
-   WetRejectReasonMaster
-   WetReject
-   wetReject1
-   wetReject2
-   WetRejectHistory
-   Depallet
-   DepalletReject
-   RejectPISLog / Reject API
-   Production reject behavior
-   Depallet reject detail behavior
-   PressMc/equipment configuration
-   ProductionLot/ProductFamilyID/ProductCode
-   LOGGER

All listed legacy objects and existing API/PIS behavior remain unchanged.
New Fitting REJECT uses its own reason masters, applicability mapping, and
workflow-specific detail tables. PIS/API integration is out of scope for
the first implementation.

## 16. Existing test data

The new Fitting REJECT catalogs use R1xx/R2xx/R3xx, including R199/R299/
R399. These are separate from legacy R01-R24/R99. Preserve all legacy
reject objects and behavior; do not repurpose or backfill legacy records
into the new workflow.

## 17. API considerations

Reject API/PIS integration is outside the first implementation phase.
Do not modify the existing Reject API, its payload construction, its logs,
or legacy R01-R24/R99 behavior. New R199/R299/R399 remain separate from
legacy R99.

## 18. Data-model minimum dimensions

### Mandatory columns for every new table

Every new table, including lookup and mapping tables, uses:

```sql
id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
Rectime datetime NOT NULL DEFAULT (GETDATE())
```

Use UNIQUE constraints for business uniqueness; do not use composite
primary keys instead of the required identity. Do not substitute int,
datetime2, SYSDATETIME(), or GUID for these base columns.

### REJECT-owned masters and mapping

-   `RejectCatalog`: `id`, `Rectime`, unique `CatalogCode`, display name,
    `IsActive`. Seed catalog codes R1, R2, R3.
-   `RejectSourceScope`: `id`, `Rectime`, unique `SourceScopeCode`,
    display name, `IsActive`. Seed PRESS and LINE.
-   `RejectReason`: `id`, `Rectime`, unique `ReasonCode`, `RejectCatalogID`,
    `ReasonNameTH`, `SortOrder`, `RejectSourceScopeID`, `IsOther`,
    `IsActive`. FKs use IDs, not ReasonCode.
-   `RejectReasonProductFamily`: `id`, `Rectime`, `RejectReasonID`,
    `ProductFamilyID`; UNIQUE `(RejectReasonID, ProductFamilyID)`.
    ProductFamilyID references `ProductFamilyMaster.ProductFamilyID`.

All seed relationships resolve IDs from their authoritative unique business
codes/values and verify exactly one match; never hardcode opaque IDs.

### Shared ShiftMaster

`ShiftMaster` has `id`, `Rectime`, unique `ShiftCode`, `ShiftName`, and
`IsActive`. Seed business codes `1` and `2` with display names Shift 1 and
Shift 2; generated IDs are opaque. Start times remain in
`ProductionShiftRuleHistory`. Existing shift columns are not migrated.
New entries reference `ShiftMaster.id`.

### Workflow-specific detail tables

`ProductionRejectEntry` and `DepalletRejectEntry` have aligned structures:

-   `id`, `Rectime`
-   `ProductionDate` (`date`): transaction/query dimension, not relational
    identity
-   `ShiftID`
-   `LineEquipmentID`
-   `SourceEquipmentID`
-   `RejectSourceScopeID`: validated transaction-time scope ID
-   `ProductionID`
-   `RejectReasonID`
-   `Qty` with CHECK `Qty > 0`
-   only approved audit/edit/void fields

Foreign keys:

-   `ShiftID -> ShiftMaster.id`
-   `LineEquipmentID` and `SourceEquipmentID -> EquipmentMaster.id`
-   `RejectSourceScopeID -> RejectSourceScope.id`
-   `ProductionID -> ProductionLot.ProductionID`
-   `RejectReasonID -> RejectReason.id`

ProductionID is the Product/Lot relational identity. ProductCode and
ProductFamilyID are derived through ProductionLot and are not copied to
these tables. Validate ProductFamily applicability through
`ProductionLot.ProductFamilyID -> RejectReasonProductFamily`. On Production
SAVE, validate the authoritative ProductionDate, active Lot, ProductFamily,
and active transaction Shift independently; do not require the selected
transaction Shift to equal `ProductionLot.Shift`. Depallet retains its
Shift/Lot validation.

ProductionRejectEntry and DepalletRejectEntry are the workflow owners.
Reject Of is not persisted. Do not add RejectOf, DepalletID, ProductCode,
ProductFamilyID, EquipmentCode, ReasonCode, SourceScope text, or Shift
text to either entry table. The same ProductionID may have rows in both.

### EquipmentMaster additive ID

Add `EquipmentMaster.id bigint IDENTITY(1,1)` with a UNIQUE candidate key
for new REJECT foreign keys. Keep `EquipmentCode` as its existing clustered
primary key. Do not migrate its nine existing EquipmentCode FKs, change
stored procedure interfaces, change PressMc behavior, or change
EquipmentLineMap relationships. Existing modules continue using
EquipmentCode; new REJECT rows use EquipmentMaster.id.

### Textual relational keys

There are zero new textual relational FKs. Business codes and display
names are not relational identity. Historical snapshots, if included, are
display-only and never used for joins, validation, or business rules.

## 19. LOGGER is the implementation reference

Before implementation, inspect LOGGER end-to-end:

-   routes/controllers/services
-   templates
-   header context
-   Shift handling
-   SAVE
-   entry list
-   Select/Edit/Cancel
-   server validation
-   PRG/redirect behavior
-   date navigation
-   tests
-   LOG CAL integration
-   DB transaction patterns

REJECT should feel like a native sibling of LOGGER.

## 20. Implementation phase status and safety

The read-only investigation, live safety audit, and design review are
complete. This document is the authoritative implementation specification.
Do not revise approved architecture during implementation without review.

### Safety

-   Do not execute migrations or schema/data-changing SQL against SB23
    without separate explicit authorization.
-   Migration and rollback files must be reviewed before any execution.
-   Do not modify unrelated application behavior or legacy reject code.
-   Do not commit or push.
-   Do not reset/clean unrelated worktree changes.
-   Do not edit pre-023 migrations.

Implementation must follow this specification, the database ID-first
standard, and the approved migration/rollback/test review process. No
migration may be run against SB23 without separate explicit authorization.

## 21. Target workflow

``` text
Global Production Date
        |
        v
REJECT TAB
Shift -> Reject Of (default Production) -> Line -> Product/Lot
                           |
                           v
                  Qty -> Source -> Reason -> SAVE
                           |
             +-------------+-------------+
             |                           |
             v                           v
 ProductionRejectEntry          DepalletRejectEntry
                           |
             +-------------+-------------+
             |                           |
             v                           v
     Production REJECT CAL       Depallet REJECT CAL
             |                           |
             v                           v
     Production summary          Depallet reject summary
```

Reject Of routes the save and is not persisted. Production and Depallet
CAL read only their corresponding detail tables. Report any implementation
blocker rather than silently changing the approved design.
