# FittingMES --- PressMc → Mould → Production Design

**Status:** Design locked before SQL/UI implementation\
**Implementation order:** `PressMc` → `Mould` → `Production`

------------------------------------------------------------------------

## 1. Purpose

The Production module cannot be completed correctly until the system
knows:

1.  Which Press Machines exist.
2.  Which production line each Press Machine belongs to.
3.  Which Product Family / Product each Press Machine is capable of
    producing.
4.  Which physical Moulds exist.
5.  Which Product each Mould belongs to.
6.  Which Mould is installed/used on which Press for each production
    allocation.
7.  How many press cycles each Mould has accumulated over its lifetime
    and since its latest recondition.

Therefore the implementation order is fixed as:

``` text
[ PressMc ]
     ↓
Define available Press Machines,
Line assignment, and production capability
     ↓
[ Mould ]
     ↓
Register physical Mould assets,
product relation, status, age and recondition history
     ↓
[ Production ]
     ↓
Allocate Production Plan quantity to Press Machines
and select valid Moulds
```

Do not build Production around temporary/dummy Mould logic. Build the
real master data first.

------------------------------------------------------------------------

# 2. Tab: PressMc

## 2.1 Purpose

`PressMc` is the master/configuration page for the factory Press
Machines (`F1 ... Fxx`).

Press Machine must **not** be hard-coded as F1--F14 because machines may
later be:

-   added,
-   removed/disabled,
-   relocated from LINE1 to LINE2,
-   relocated from LINE2 to LINE1,
-   given different production capabilities.

The system must preserve historical Production records even when a
machine is later disabled or moved.

------------------------------------------------------------------------

## 2.2 Basic Press Machine information

Example:

``` text
Machine Code : F1
Machine Name : Press 1
Status       : ACTIVE
Current Line : LINE1
```

Required operations:

-   Add new Press Machine.
-   Edit machine information.
-   Activate / Disable machine.
-   Assign machine to LINE1 or LINE2.
-   Move a machine between lines without destroying historical records.
-   Configure the products that the machine is capable of producing.

Prefer disable/retire over physical deletion when the machine has
historical transactions.

------------------------------------------------------------------------

## 2.3 Press → Line relationship

Current production topology concept:

``` text
LINE1
 ├─ F1
 ├─ F2
 ├─ ...
 └─ Fx

LINE2
 ├─ Fy
 ├─ ...
 └─ Fxx
```

This assignment is configuration data and may change in the future.

It is also required later for OEE/time dependency:

``` text
LINE STOP
   ↓
all Press Machines belonging to that Line are affected

Press STOP
   ↓
only that Press is affected
and does NOT stop the Line
```

Therefore Press → Line is a directional production relationship that
must be stored explicitly.

------------------------------------------------------------------------

## 2.4 Press production capability

Each Press Machine can support:

-   one or many Product Families,
-   one or many Products inside each supported Product Family.

Example:

``` text
F1
├─ Special Ridge
│  ├─ Product 01 ✓
│  ├─ Product 02 ✓
│  └─ Product 03 ✓
│
├─ Prestige Common
│  ├─ Product 11 ✓
│  └─ Product 14 ✓
│
└─ NeuFit / NeuStile
   └─ Product 02 ✓
```

The PressMc UI should allow the user to configure capability using a
clear selection/check-box frame rather than manually typing codes.

Concept:

``` text
PRESS MACHINE: F1

Line: [ LINE1 ▼ ]

Allowed Products

[✓] Special Ridge
    [ ] 01 - ...
    [✓] 02 - ...
    [✓] 03 - ...

[✓] Prestige Common
    [✓] 11 - ...
    [ ] 12 - ...
    [✓] 14 - ...

[ ] NeuFit / NeuStile
    ...
```

The existing `ProductFamilyMaster` and `ProductCodeMaster` should be
used as the source of Product Family/Product choices.

------------------------------------------------------------------------

## 2.5 Why capability is mandatory

Production must never assume that every Press can use every
Product/Mould.

When Production is for:

``` text
ProductFamily = Special Ridge
ProductCode   = 02
```

only Press Machines configured to support:

``` text
Special Ridge / 02
```

should normally appear as valid choices.

The backend must also validate this rule on SAVE. UI filtering alone is
not sufficient.

If an invalid combination is submitted, the system must reject/warn, for
example:

``` text
F5 cannot produce Special Ridge / Product 02.
```

------------------------------------------------------------------------

# 3. Tab: Mould

## 3.1 Purpose

Mould is a **physical asset**, not just a Product Type.

There can be multiple physical Moulds for exactly the same Product.

Example:

``` text
Special Ridge / Product 02 / ปิดชาย

M0001   ปิดชาย ชุด 1
M0002   ปิดชาย ชุด 2
M0003   ปิดชาย สำรอง
```

All three can produce the same Product but are three separate Mould
assets with independent age and recondition history.

------------------------------------------------------------------------

## 3.2 Mould numbering and name

The system can generate the Mould number.

Example:

``` text
M0001
M0002
M0003
...
```

But the operator must also be able to assign a human-friendly Mould
Name.

Example:

``` text
Mould No.   : M0001
Mould Name  : ปิดชาย ชุด 1
```

Therefore:

-   `MouldNo` = system-controlled unique identifier/number.
-   `MouldName` = operator-defined/display name.

Do not use the operator name as the primary identity of the Mould.

------------------------------------------------------------------------

## 3.3 Mould Product classification

Mould uses the same Product classification structure as Production.

A registered Mould must identify at least:

``` text
ProductFamily
ProductCode
```

Example:

``` text
Mould No.      : M0001
Mould Name     : ปิดชาย ชุด 1
Product Family : Special Ridge
Product        : 02 - ปิดชาย
```

The Product dropdown must be filtered by selected Product Family.

------------------------------------------------------------------------

# 4. Mould lifecycle

A newly registered Mould begins as a new physical Mould.

Conceptual lifecycle:

``` text
REGISTER NEW MOULD
       ↓
     ACTIVE
       ↓
used in Production
       ↓
Press cycles accumulate
       ↓
reaches maintenance/recondition point
       ↓
RECONDITION
       ↓
Recondition #1
       ↓
ACTIVE again
       ↓
more Production
       ↓
Recondition #2
       ↓
...
       ↓
eventually cannot be reconditioned
       ↓
RETIRED / DENIED
```

Exact operational status names can be finalized during implementation,
but the database must support this lifecycle.

------------------------------------------------------------------------

# 5. Mould age / Press cycle counting

The age of a Mould is based on the number of Press cycles in which that
physical Mould was used.

Example Production result:

``` text
Machine   Dispatch   Counter   Curing
F1        100        110       100
```

If Mould `M0001` was installed on F1 for that production entry:

``` text
M0001 usage = 110 press cycles
```

The Mould age uses **Counter**, not Dispatch and not Curing.

------------------------------------------------------------------------

## 5.1 Keep two age concepts

Do not permanently lose the lifetime history when a Mould is
reconditioned.

Keep at least:

``` text
LifetimePressCount
CyclePressCount
CurrentReconditionNo
```

Meaning:

-   `LifetimePressCount` = all press cycles since the Mould was first
    registered.
-   `CyclePressCount` = press cycles since the most recent recondition.
-   `CurrentReconditionNo` = 0 for new Mould, then 1, 2, 3, ...

Example:

``` text
New Mould
ReconditionNo = 0
Cycle = 0
Lifetime = 0

after 20,000 cycles
Cycle = 20,000
Lifetime = 20,000

Recondition #1
Cycle = 0
Lifetime = 20,000

after another 15,000 cycles
Cycle = 15,000
Lifetime = 35,000
ReconditionNo = 1
```

The lifetime history must remain traceable.

------------------------------------------------------------------------

# 6. Mould Usage transaction

Production should not merely overwrite a number in `MouldMaster`.

Every use of a Mould must create a transaction/history record.

Concept:

``` text
MouldUsage
------------------------------------------------
Production
PressProduction
Mould
Press Machine
Counter / PressCycles
ReconditionNoAtUse
Date/Time
```

Example:

``` text
Production I02690901
F1
M0001
Counter = 110
Recondition = 0
```

This becomes a Mould usage record of 110 cycles.

Benefits:

-   Mould age can be audited.
-   Historical usage can be traced.
-   Corrections to Production can be reconciled.
-   We can answer which Press used a Mould.
-   We can answer which Lot/Product used a Mould.
-   Recondition history can be checked against actual production usage.

------------------------------------------------------------------------

# 7. Recondition history

Reconditioning must be stored as history, not just by changing the
current counter.

Concept:

``` text
MouldReconditionHistory

MouldID
ReconditionNo
ReconditionDate
BeforeCycleCount
LifetimeCountAtRecondition
Remark
```

After recondition:

``` text
CurrentReconditionNo += 1
CyclePressCount = 0
LifetimePressCount remains unchanged
```

Eventually the Mould can be marked as no longer usable:

``` text
RETIRED / DENIED
```

A retired/denied Mould must not be selectable for new Production, but
all old Production and usage history must remain available.

------------------------------------------------------------------------

# 8. Tab: Production

Production is implemented after PressMc and Mould because it consumes
both masters.

Existing flow remains:

``` text
Select Production Date
        ↓
Show Production Plans for that date
        ↓
Select Plan
        ↓
resolve Product Family / Product
        ↓
Generate/Create Production Lot
        ↓
open Press Production detail
```

------------------------------------------------------------------------

## 8.1 Production Plan → Production Lot

Example:

``` text
Plan:
Product = ครอบปิดชาย
Plan Qty = 300

Production Lot:
I02690901
ProductFamily = Special Ridge
ProductCode = 02
```

After the Lot exists, the operator allocates Plan quantity to Press
Machines.

------------------------------------------------------------------------

## 8.2 Press allocation is dynamic

Do **not** show fixed F1/F2/F3 rows as if every Press must be used.

The Press itself is a dropdown.

Example:

``` text
PRESS PRODUCTION — Lot I02690901

Machine   Dispatch   Mould                     Counter   Curing   Start   End
--------------------------------------------------------------------------------
[F1 ▼]    [100]      [M0001 / ปิดชาย 1 ▼]      [110]     [100]    [...]  [...]
[F2 ▼]    [ 80]      [M0002 / ปิดชาย 2 ▼]      [ 90]     [ 85]    [...]  [...]
[F3 ▼]    [120]      [M0003 / ปิดชาย 3 ▼]      [120]     [110]    [...]  [...]

                                                    [+ ADD PRESS]
```

The operator decides which Press Machines are actually used.

------------------------------------------------------------------------

# 9. Production validation sequence

For a Lot:

``` text
ProductFamily = Special Ridge
ProductCode   = 02
```

the system should determine valid choices as follows:

``` text
Production Lot Product
        ↓
PressMc Capability
        ↓
valid ACTIVE Press Machines
        ↓
operator selects Press
        ↓
active Moulds for the same Product
        ↓
valid Mould dropdown
```

At SAVE, validate again server-side:

``` text
Production Product
        │
        ├── Is selected Press capable of this Product?
        │
        ├── Is selected Mould for this Product?
        │
        ├── Is Mould ACTIVE/usable?
        │
        └── Is the Press/Mould combination allowed by the configured constraints?
```

Invalid combinations must not silently save.

------------------------------------------------------------------------

# 10. Dispatch / Counter / Curing meaning

Example:

``` text
Plan Qty = 300

F1 → Dispatch 100
F2 → Dispatch  80
F3 → Dispatch 120
-----------------
Total Dispatch = 300
```

Production results can differ from Dispatch:

``` text
Machine   Dispatch   Counter   Curing
-------------------------------------
F1        100        110       100
F2         80         90        85
F3        120        120       110
```

Interpretation:

-   `DispatchQty` = quantity allocated from Production Plan/Lot to that
    Press.
-   `CounterQty` = number of Press cycles/production counter.
-   `CuringQty` = resulting curing quantity.
-   Mould usage age is incremented from the applicable `CounterQty`.

The total Dispatch should be checked against the quantity available from
the Production Plan/Lot so that allocation cannot unintentionally exceed
the available quantity.

------------------------------------------------------------------------

# 11. Production data relationship

Target concept:

``` text
ProductionLot
     │
     ├── PressProduction F1
     │       ├── DispatchQty
     │       ├── CounterQty
     │       ├── CuringQty
     │       ├── Start / End
     │       └── Mould M0001
     │
     ├── PressProduction F2
     │       └── Mould M0002
     │
     └── PressProduction F3
             └── Mould M0003
```

Mould use then generates/maintains the corresponding usage history:

``` text
PressProduction
       ↓
MouldUsage
       ↓
Mould age
```

------------------------------------------------------------------------

# 12. Relationship with Equipment/OEE design

The earlier Equipment design remains valid and should not be replaced by
the PressMc/Mould work.

Equipment model:

``` text
PRESS LEVEL
F1...Fxx
→ Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other

LINE LEVEL
LINE1 / LINE2
→ Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other
```

Both Press and Line can later receive PLC events:

``` text
F1 PLC     ──┐
F2 PLC     ──┤
...           ├── EquipmentTimeEvent → OEE
LINE1 PLC  ──┤
LINE2 PLC  ──┘
```

`PressMc` machine/line configuration should therefore remain compatible
with:

``` text
EquipmentMaster
EquipmentLineMap
EquipmentTimeEvent
```

Do not create a second conflicting definition of F1/F2/etc. if
`EquipmentMaster` is already the canonical equipment master.

------------------------------------------------------------------------

# 13. Existing SQL direction

The database work already started contains/anticipates tables such as:

``` text
EquipmentMaster
EquipmentLineMap
EquipmentTimeEvent
MouldMaster
MouldRecondition...
MouldUsage
PressProduction
```

Before creating additional tables, inspect the exact current schema,
keys, indexes and foreign keys and extend/reuse these tables where
appropriate.

Existing Product masters are already available:

``` text
ProductFamilyMaster
ProductCodeMaster
```

These should remain the canonical Product classification used by:

-   Production Lot
-   Press capability
-   Mould registration
-   Production validation

Avoid duplicating Product definitions into separate Mould-only or
Press-only masters.

------------------------------------------------------------------------

# 14. SQL work to do next

The next implementation task is SQL for **PressMc**, before UI coding.

Required SQL capability:

``` text
Equipment/Press Master
        │
        ├── LINE assignment
        │
        └── Product Capability
              ├── ProductFamily
              └── ProductCode
```

Likely logical relationship:

``` text
PressMachine
    │
    ├── EquipmentLineMap
    │
    └── PressProductCapability
             ↓
      ProductCodeMaster
```

After PressMc schema is verified:

``` text
1. Complete PressMc SQL
2. Build PressMc UI
3. Test Add/Edit/Disable/Move Line/Capability
4. Complete Mould SQL
5. Build Mould UI
6. Test Register/Recondition/Retire
7. Modify Production SQL
8. Build Production Press allocation UI
9. Add Press/Mould validation
10. Add MouldUsage + age update/reconciliation
11. Later integrate EquipmentTimeEvent/OEE and PLC
```

------------------------------------------------------------------------

# 15. Important rules locked for implementation

1.  **Press is selected dynamically in Production.** F1...Fxx are not
    fixed Production rows.
2.  **Press Machines can move between LINE1 and LINE2.**
3.  **Press Machines can be added or disabled.**
4.  **Each Press has configurable Product capability.**
5.  **Capability can include multiple Product Families and multiple
    Products.**
6.  **Production must prevent invalid Press/Product combinations.**
7.  **A Mould is an individual physical asset.**
8.  **Mould No. is system-generated; Mould Name can be entered by the
    operator.**
9.  **Multiple Moulds can belong to the same Product.**
10. **Production selects a specific physical Mould.**
11. **Mould age is based on Press Counter usage.**
12. **Every Mould use must remain historically traceable.**
13. **Recondition resets the current-cycle count, not lifetime
    history.**
14. **Recondition number increases over the Mould lifetime.**
15. **Retired/Denied Moulds remain in history but cannot be selected for
    new Production.**
16. **ProductFamilyMaster/ProductCodeMaster remain the common Product
    masters.**
17. **Backend validation is mandatory even when dropdowns are
    filtered.**
18. **LINE stop affects Presses on that Line; a single Press stop does
    not stop the Line.**
19. **Press/Line time events remain separate from Production
    quantity/Mould usage transactions.**
20. **Design for future PLC input without requiring a database
    redesign.**

------------------------------------------------------------------------

# 16. Final implementation sequence

``` text
NOW
 │
 ▼
SQL — PressMc / capability / line assignment
 │
 ▼
TAB — PressMc
 │
 ▼
SQL — Mould lifecycle / usage / recondition
 │
 ▼
TAB — Mould
 │
 ▼
SQL — Production allocation + Mould relation
 │
 ▼
TAB — Production
 │
 ▼
Production validation + Mould age
 │
 ▼
Equipment Time / OEE
 │
 ▼
PLC integration
```

**Current immediate next step:** inspect the existing `EquipmentMaster`,
`EquipmentLineMap`, Product master and related keys, then implement the
missing Press Product Capability SQL without duplicating existing
structures.

# CURRENT SQL IMPLEMENTATION STATUS — 2026-09-26

COMPLETED

1. EquipmentMaster
   - PRESS: F1-F14
   - LINE: LINE1, LINE2
   - EquipmentMaster is canonical equipment master

2. EquipmentLineMap
   Current mapping:
   F1-F7   -> LINE1
   F8-F14  -> LINE2

   Mapping is configurable.
   Press can later be moved between LINE1/LINE2 from PressMc UI.

3. PressProductCapability
   CREATED

   Columns:
   PressEquipmentCode
   ProductFamily
   ProductCode
   IsActive
   CreatedAt
   UpdatedAt

   FK:
   PressEquipmentCode -> EquipmentMaster.EquipmentCode
   (ProductFamily, ProductCode)
       -> ProductCodeMaster(ProductFamily, ProductCode)

   Purpose:
   Defines which Product(s) each Press Machine can produce.

   IMPORTANT:
   Capability rows are intentionally not populated yet.
   They will be configured by operator through PressMc UI.

4. Product Masters
   ProductFamilyMaster = canonical Product Family master
   ProductCodeMaster   = canonical Product master

5. VERIFIED CURRENT LINE ASSIGNMENT

   F1  -> LINE1
   F2  -> LINE1
   F3  -> LINE1
   F4  -> LINE1
   F5  -> LINE1
   F6  -> LINE1
   F7  -> LINE1

   F8  -> LINE2
   F9  -> LINE2
   F10 -> LINE2
   F11 -> LINE2
   F12 -> LINE2
   F13 -> LINE2
   F14 -> LINE2

NEXT STEP

Build PressMc UI using the EXISTING SQL above.

DO NOT recreate:
- EquipmentMaster
- EquipmentLineMap
- PressProductCapability

PressMc UI must support:
- Add Press
- Edit Press name
- Enable/Disable Press
- Move Press between LINE1/LINE2
- Configure ProductFamily/ProductCode capability

IMPORTANT — PRESS MACHINE HISTORY

Press Machine configuration is historical / effective-dated.

NEVER physically delete a Press Machine that has existed in the system.
NEVER overwrite its historical Line assignment.

Moving Press:
- Close the current Line assignment.
- Insert a new Line assignment history row.

Removing Press from production:
- Close its current Line assignment.
- Set EquipmentMaster.IsActive = 0.
- Preserve all historical records.

Adding Press:
- Insert a new EquipmentMaster record.
- Insert its initial Line assignment.

F1-F14 are only the currently installed Press machines.
The number of Press machines is dynamic.

Historical Production, Mould Usage, Equipment Time Events and OEE
must continue to resolve the Press and its Line assignment as they
existed at the time of production.

# SQL IMPLEMENTATION UPDATE – PRESSMC
Updated: 2026-09-26

This section records SQL work completed after the previous
CURRENT SQL IMPLEMENTATION STATUS section.

============================================================
1. PRESS MACHINE IS NOT FIXED TO F1-F14
============================================================

F1-F14 are only the current Press machines.

The system must support:

- Add new Press machine
- Rename Press machine
- Enable / Disable Press machine
- Assign Press to LINE1 or LINE2
- Move Press between LINE1 and LINE2
- Remove Press from current production line without deleting history
- Re-assign an old Press later
- Configure which ProductFamily / ProductCode each Press can produce

IMPORTANT:

Never physically DELETE Press configuration just because a machine
is removed from service or moved to another line.

Historical configuration must remain available.


============================================================
2. CURRENT PRESS / LINE CONFIGURATION
============================================================

Current Press machines:

F1  -> LINE1
F2  -> LINE1
F3  -> LINE1
F4  -> LINE1
F5  -> LINE1
F6  -> LINE1
F7  -> LINE1

F8  -> LINE2
F9  -> LINE2
F10 -> LINE2
F11 -> LINE2
F12 -> LINE2
F13 -> LINE2
F14 -> LINE2

Current LINE equipment:

LINE1
LINE2

Both LINE1 and LINE2 are stored in EquipmentMaster
with EquipmentType = 'LINE'.

Press machines are stored in EquipmentMaster
with EquipmentType = 'PRESS'.


============================================================
3. EQUIPMENT LINE HISTORY
============================================================

The original EquipmentLineMap represents CURRENT line assignment.

Historical line assignment support has now been added.

Initial current mappings were migrated into line history.

Example initial history:

F1 -> LINE1
F2 -> LINE1
...
F7 -> LINE1

F8 -> LINE2
...
F14 -> LINE2

Initial migrated records use:

ChangeType = INITIAL
ChangedBy  = SYSTEM

The design supports keeping:

- EffectiveFrom
- EffectiveTo
- ChangeType
- Remark
- ChangedBy

A Press therefore has only one CURRENT line assignment,
but can have many historical line assignments.


============================================================
4. PRESS LINE MOVE TEST – VERIFIED
============================================================

A controlled SQL transaction test was performed with:

F3 : LINE1 -> LINE2

Result during transaction:

PreviousLine = LINE1
CurrentLine  = LINE2
Result       = MOVE

History correctly became:

Old history:
F3 / LINE1
EffectiveTo = move timestamp

New history:
F3 / LINE2
ChangeType  = MOVE
EffectiveTo = NULL

The test transaction was then ROLLBACK.

After rollback:

F3 CurrentLine returned to LINE1.

Only the original INITIAL history remained.

Therefore line movement + historical recording behavior
has been verified successfully.


============================================================
5. EQUIPMENT STATUS HISTORY
============================================================

Press machine active/inactive state is also historical.

Initial EquipmentMaster status was migrated into status history.

Current F1-F14:

IsActive = 1

Initial migrated history uses:

ChangeType = INITIAL
ChangedBy  = SYSTEM

This allows future operations such as:

ACTIVE
    ->
machine removed from service
    ->
INACTIVE
    ->
machine returned later
    ->
ACTIVE

without deleting the machine identity or its old history.


============================================================
6. PRESS PRODUCT CAPABILITY
============================================================

Existing table:

dbo.PressProductCapability

Columns verified:

- PressEquipmentCode varchar(20)
- ProductFamily varchar(30)
- ProductCode varchar(2)
- IsActive bit
- CreatedAt datetime2
- UpdatedAt datetime2

Primary Key:

(
    PressEquipmentCode,
    ProductFamily,
    ProductCode
)

Foreign Keys verified:

PressEquipmentCode
    -> EquipmentMaster.EquipmentCode

(ProductFamily, ProductCode)
    -> ProductCodeMaster(ProductFamily, ProductCode)

Existing product lookup index:

(ProductFamily, ProductCode, IsActive)

This table represents CURRENT capability.


============================================================
7. PRESS PRODUCT CAPABILITY HISTORY
============================================================

Added:

dbo.PressProductCapabilityHistory

Purpose:

Never lose previous Press/Product compatibility configuration.

History records include:

- PressEquipmentCode
- ProductFamily
- ProductCode
- IsActive
- ChangeType
- Remark
- ChangedBy
- ChangedAt

Supported ChangeType:

- INITIAL
- ENABLE
- DISABLE

Capability must NOT be physically deleted when unchecked.

Instead:

IsActive = 0

and a DISABLE history record is created.

If enabled again later:

IsActive = 1

and an ENABLE history record is created.


============================================================
8. STORED PROCEDURE
============================================================

Added:

dbo.sp_SetPressProductCapability

Purpose:

Safely Add / Enable / Disable a Press/Product capability.

Parameters:

@PressEquipmentCode
@ProductFamily
@ProductCode
@IsActive
@Remark
@ChangedBy

The procedure validates:

1. PressEquipmentCode exists
2. EquipmentType must be PRESS
3. ProductFamily/ProductCode exists
4. Existing state is checked before update

Behavior:

Never registered before
    -> INSERT capability
    -> History = INITIAL

Existing inactive capability enabled
    -> IsActive = 1
    -> History = ENABLE

Existing active capability disabled
    -> IsActive = 0
    -> History = DISABLE

Requested state already equals current state
    -> no duplicate history record


============================================================
9. PRESS PRODUCT CAPABILITY TEST – VERIFIED
============================================================

Controlled transaction test:

Press:
F3

Product:
ProductFamily = Special Ridge
ProductCode   = 02

Command:

sp_SetPressProductCapability
IsActive = 1

During transaction the current capability correctly showed:

F3
Special Ridge
02
IsActive = 1

History correctly showed:

ChangeType = INITIAL
ChangedBy  = SQL TEST
Remark     = Test PressMc capability

The transaction was then ROLLBACK.

Verification after rollback:

PressProductCapability
    -> ZERO F3 test rows

PressProductCapabilityHistory
    -> ZERO F3 test rows

Therefore:

Current capability write
+
Capability history write
+
Transaction rollback

have all been verified successfully.


============================================================
10. PRESSMC UI DATA MODEL
============================================================

The PressMc tab must NOT hard-code F1-F14.

Press list must come from SQL:

EquipmentMaster
WHERE EquipmentType = 'PRESS'

The UI must support future machines such as:

F15
F16
...
or other Press codes.

For each selected Press the UI needs to show:

- Press Code
- Press Name
- Active / Inactive
- Current Line
- Product capability


Product capability UI should be grouped by ProductFamily.

Concept:

F3
|
+-- Current Line : LINE1
|
+-- NeuFit / NeuStile
|   +-- [ ] Product 01
|   +-- [ ] Product 02
|   +-- ...
|
+-- Oriental
|   +-- ...
|
+-- Prestige Common
|   +-- ...
|
+-- Special Ridge
    +-- [ ] Product 01
    +-- [x] Product 02
    +-- ...


Product list must come from ProductCodeMaster.

Checkbox state must come from PressProductCapability.

Do NOT hard-code ProductFamily or ProductCode in the UI.


============================================================
11. IMPORTANT PRODUCTION VALIDATION RULE
============================================================

PressProductCapability will later be used by the Production tab.

When Production Product is already known:

ProductFamily + ProductCode

the system must only allow Press machines capable of producing
that Product.

After Press is selected, Mould selection must also be validated
against:

1. Production Product
2. Press capability
3. Mould ProductFamily/ProductCode
4. Mould active/status condition

Therefore the final Production relationship is:

Production Plan / Lot
        |
        v
ProductFamily + ProductCode
        |
        +-------------------------+
        |                         |
        v                         v
Compatible Press             Compatible Mould
        |                         |
        +------------+------------+
                     |
                     v
              Press Production


============================================================
12. CURRENT SQL STATUS
============================================================

VERIFIED:

[OK] EquipmentMaster supports dynamic PRESS machines
[OK] LINE1 / LINE2 exist as LINE equipment
[OK] Current Press -> Line mapping exists
[OK] Historical Press -> Line design implemented
[OK] F3 LINE1 -> LINE2 move tested
[OK] Move rollback tested
[OK] Equipment active/inactive history implemented
[OK] PressProductCapability exists
[OK] Composite Product FK verified
[OK] PressProductCapabilityHistory added
[OK] sp_SetPressProductCapability added
[OK] Capability transaction test passed
[OK] Capability rollback test passed


============================================================
13. NEXT SQL STEP
============================================================

Build PressMc UI query/view.

For a selected Press, SQL must return ALL active products from
ProductCodeMaster and LEFT JOIN the Press capability.

Expected output concept:

PressCode
ProductFamily
ProductCode
ProductName
ProductNameTH
CanProduce

Example:

F3 | NeuFit / NeuStile | 01 | ... | ... | 0
F3 | NeuFit / NeuStile | 02 | ... | ... | 0
F3 | Special Ridge     | 01 | ... | ... | 0
F3 | Special Ridge     | 02 | ... | ... | 1

This dataset will directly drive the Product capability
checkboxes on the [PressMc] tab.

After this SQL layer is complete:

NEXT:
1. Build [PressMc] tab
2. Build [Mould] tab
3. Extend [Production] tab for Press + Mould dispatch
