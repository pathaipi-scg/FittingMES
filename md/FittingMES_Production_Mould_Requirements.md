# FittingMES -- Production & Mould Requirements

**Status:** Design / Requirements locked for next development phase\
**Scope:** `PRODUCTION` tab + new `MOULD` tab\
**Context:** Continue after Depallet multi-run/reject work is completed.

------------------------------------------------------------------------

## 1. Main Objective

The Production module must support the real production structure of the
fitting/coating process:

1.  Select a production plan for the selected Production Date.
2.  Create a Production Lot from the plan.
3.  Dispatch the planned quantity to individual presses (`F1 ... Fxx`).
4.  Assign a physical mould to each press production.
5.  Record press production quantities (`Counter`, `Curing`, etc.).
6.  Record production time/OEE independently for:
    -   each Press (`F1 ... Fxx`)
    -   `LINE1`
    -   `LINE2`
7.  Track every physical mould's usage/lifetime from press counter
    cycles.
8.  Support mould reconditioning cycles and final retirement/deny.
9.  Design the database so Manual entry now and PLC input later use the
    same underlying model.

------------------------------------------------------------------------

# PART A -- PRODUCTION TAB

## 2. Production Plan → Production Lot Workflow

Target workflow:

``` text
Select Production Date
        ↓
Show all Production Plans for that date
        ↓
Operator selects one Plan row
        ↓
System checks information required to create Lot
        │
        ├─ Plan data is sufficient
        │       ↓
        │   Auto determine Product Family / Product
        │
        └─ Plan data is insufficient
                ↓
        Operator selects additional dropdowns
        Product Family / Product
                ↓
        Auto Generate Lot No.
                ↓
        CREATE PRODUCTION LOT
                ↓
        Open Production Detail
```

Example:

``` text
Plan:
Prestige Common xxx
Plan Qty = 3,000

→ Product Family = Prestige Common
→ Product = 02
→ Lot Prefix = I
→ Generated Lot = I02690901
```

Selected-plan area should be approximately:

``` text
SELECTED PLAN
----------------------------------------------------
Product        : XXXXX
Plan Qty       : 3,000

Product Family : [ Prestige Common ▼ ]
Product        : [ 02 - xxxxxxxxx ▼ ]

Lot No.        : [ I02690901 ]   ← Auto/Preview

                         [ CREATE PRODUCTION LOT ]
```

The existing Lot numbering rule remains separate from Mould numbering.

------------------------------------------------------------------------

## 3. Dispatch Production Plan Qty to Presses

A Production Plan/Lot quantity can be split among several presses.

Example:

``` text
Plan / Lot Product : ครอบปิดชาย
Plan Qty           : 300

F1 → Dispatch 100 pcs
F2 → Dispatch  80 pcs
F3 → Dispatch 120 pcs
                    ---
Total Dispatch     300 pcs
```

Validation:

``` text
SUM(DispatchQty for the Production Plan/Lot)
    <= quantity available from the Plan
```

The system must prevent over-dispatching the remaining plan quantity.

`DispatchQty` belongs to each Press Production row, not only to the
Production Lot header.

------------------------------------------------------------------------

## 4. Press Production Result

Each press (`F1 ... Fxx`) has its own production result.

Example:

``` text
Machine | Dispatch | Counter | Curing
--------------------------------------
F1      |   100    |   110   |  100
F2      |    80    |    90   |   85
F3      |   120    |   120   |  110
--------------------------------------
TOTAL   |   300    |   320   |  295
```

Important:

-   `Dispatch` = quantity assigned from the production plan to that
    press.
-   `Counter` = number of actual press cycles.
-   `Curing` = production quantity reaching the defined curing/output
    stage.
-   Counter is **not required to equal Dispatch or Curing**.
-   Counter is important because it is also the basis for physical mould
    usage/lifetime.

Press production should contain production quantities only, while
detailed time records are stored separately as Equipment Time Events.

Conceptual structure:

``` text
PressProduction
------------------------------------------------
PressProductionID
ProductionID
MachineCode
DispatchQty
CounterQty
CuringQty
...
```

------------------------------------------------------------------------

## 5. Mould Selection in Press Production

Each Press Production must allow the operator to select the physical
mould being used.

After Product is known, the Mould dropdown must show only suitable
registered moulds for that Product.

Example:

``` text
Machine | Dispatch | Mould                         | Counter | Curing
----------------------------------------------------------------------
F1      |   100    | M000001 | ปิดชายตัว 1        |   110   | 100
F2      |    80    | M000004 | ตัวสำรอง            |    90   |  85
F3      |   120    | M000007 | งานเร็ว             |   120   | 110
```

Mould dropdown should normally exclude moulds that are:

-   for another Product
-   under recondition
-   denied/retired
-   otherwise unavailable

A physical Mould ID is the identity used by the database. `MouldName` is
only a human-friendly name.

### Future-proof requirement: mould change during the same Press Production

The database should not assume that one press can use only one mould for
an entire lot.

Example:

``` text
F1 / Production Lot X

08:00–12:00 → M000001 → 400 cycles
12:30–16:00 → M000002 → 350 cycles
```

Therefore the long-term data model should support Mould Assignment/Usage
segments, even if the first UI version normally selects one mould per
press row.

------------------------------------------------------------------------

# PART B -- PRESS AND LINE TIME / OEE

## 6. Two Independent Equipment Levels

Production time is not recorded only for `F1 ... Fxx`.

There are two independent equipment levels:

### PRESS LEVEL

``` text
F1  → Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other
F2  → Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other
F3  → ...
...
Fxx → ...
```

### LINE LEVEL

``` text
LINE1 → Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other
LINE2 → Run / Setup / Changeover / Idle / Clean / SMDT / Breakdown / Other
```

A Press event and a Line event are different real events.

Example:

-   F1 Changeover may mean changing the mould on F1.
-   LINE1 Changeover may mean changing color or line/process setup.

They must not be merged into the same event.

------------------------------------------------------------------------

## 7. Equipment-Based Time Model

Do **not** design the time database as Press-only.

Use a generic Equipment model from the beginning.

Concept:

``` text
EquipmentMaster
--------------------------------
EquipmentCode | EquipmentType
F1            | PRESS
F2            | PRESS
...
F14           | PRESS
LINE1         | LINE
LINE2         | LINE
```

All equipment uses the same TimeType set:

``` text
RUN
SETUP
CHANGEOVER
IDLE
CLEAN
SMDT
BREAKDOWN
OTHER
```

Conceptual event table:

``` text
EquipmentTimeEvent
----------------------------------------------------------------
ProductionID
EquipmentCode
EquipmentType
StartTime
EndTime
TimeType
Duration
SourceType
Remark
```

Example:

``` text
Equipment | Type  | TimeType    | Start | End   | Source
---------------------------------------------------------
F1        | PRESS | Run         | ...   | ...   | MANUAL
F1        | PRESS | Changeover  | ...   | ...   | MANUAL
F2        | PRESS | Breakdown   | ...   | ...   | MANUAL

LINE1     | LINE  | Run         | ...   | ...   | MANUAL
LINE1     | LINE  | Changeover  | ...   | ...   | MANUAL
LINE1     | LINE  | Breakdown   | ...   | ...   | MANUAL

LINE2     | LINE  | Setup       | ...   | ...   | MANUAL
```

------------------------------------------------------------------------

## 8. Manual Now, PLC Later

Manual input and PLC input must use the same conceptual time model.

`SourceType` must support at least:

``` text
MANUAL
PLC
SYSTEM
```

Phase 1 can allow operators to enter summarized time manually:

``` text
F1

Run           320 min
Setup          20 min
Changeover     15 min
Idle           10 min
Clean          15 min
SMDT            0 min
Breakdown      25 min
Other           5 min
```

Conceptually:

``` text
F1 | Run        | 320 | MANUAL
F1 | Setup      |  20 | MANUAL
F1 | Changeover |  15 | MANUAL
F1 | Idle       |  10 | MANUAL
F1 | Clean      |  15 | MANUAL
F1 | Breakdown  |  25 | MANUAL
F1 | Other      |   5 | MANUAL
```

Later PLC integration can produce actual event rows:

``` text
ProductionID | Equipment | StartTime | EndTime | TimeType
----------------------------------------------------------
123          | F1        | 08:00     | 09:20   | Run
123          | F1        | 09:20     | 09:35   | Breakdown
123          | F1        | 09:35     | 10:10   | Run
123          | F1        | 10:10     | 10:25   | Changeover
```

PLC concept:

``` text
PLC F1 Running = 1
        ↓
Start RUN event

PLC F1 Running = 0
        ↓
Close RUN event
Start STOP event

Operator/MES
        ↓
Classify STOP
Setup / Changeover / Idle / Clean /
SMDT / Breakdown / Other
```

The same concept also applies to PLCs for `LINE1` and `LINE2`.

``` text
F1 PLC     ──┐
F2 PLC     ──┤
...           ├──> EquipmentTimeEvent ──> OEE
LINE1 PLC  ──┤
LINE2 PLC  ──┘
```

------------------------------------------------------------------------

## 9. Press ↔ Line Mapping and Dependency

Presses must be mapped to their production line.

Current conceptual mapping:

``` text
F1 ─┐
F2 ─┤
... ├── LINE1
F7 ─┘

F8  ─┐
...  ├── LINE2
F14 ─┘
```

The exact machine mapping should be maintained as master/configuration
data rather than hard-coded if possible.

### Dependency is one-way

A Line stop always affects all Presses connected to that Line.

``` text
LINE1 STOP
   ↓
F1 STOP
F2 STOP
F3 STOP
...
F7 STOP
```

But a single Press stop does not stop the Line:

``` text
F3 STOP
   ↓
F3 affected only

LINE1 can still RUN
F1, F2, F4 ... F7 can still RUN
```

Therefore:

``` text
LINE → PRESS
```

is the production dependency.

It is **not**:

``` text
PRESS → LINE
```

### Do not duplicate Line events into Press event data

If LINE1 has a 25-minute breakdown, keep it as a LINE1 event.

Do not create fake duplicate Breakdown rows for F1--F7.

The Press ↔ Line mapping should be used later when calculating effective
press availability/OEE.

### Overlap must not be double-counted

Example:

``` text
F3 Breakdown : 13:00–13:40
LINE1 Stop   : 13:10–13:25
```

Elapsed stopped time is not simply:

``` text
40 + 15 = 55 min   ← WRONG
```

The OEE/effective-time calculation must handle overlapping Press and
Line events without double-counting time.

------------------------------------------------------------------------

## 10. Target Production UI

After selecting/creating the Production Lot, the main Production area
should conceptually contain:

``` text
PRESS PRODUCTION
------------------------------------------------------------------------------------------------
MC | Dispatch | Mould | Counter | Curing | Start | End | Run | Setup | Chg | Idle | Clean | BD...
------------------------------------------------------------------------------------------------
F1 |   ...    | ...   |   ...   |  ...   | ...   | ... | ... | ...   | ... | ...  | ...   | ...
F2 |   ...    | ...   |   ...   |  ...   | ...   | ... | ... | ...   | ... | ...  | ...   | ...
F3 |   ...    | ...   |   ...   |  ...   | ...   | ... | ... | ...   | ... | ...  | ...   | ...
...
```

and a separate Line section:

``` text
LINE PRODUCTION / LINE TIME
--------------------------------------------------------------------------------
Equipment | Run | Setup | Changeover | Idle | Clean | SMDT | Breakdown | Other
--------------------------------------------------------------------------------
LINE1     | ... | ...   | ...        | ...  | ...   | ...  | ...       | ...
LINE2     | ... | ...   | ...        | ...  | ...   | ...  | ...       | ...
```

Press quantity and mould data belong to the Press Production rows.

Time data should ultimately be backed by Equipment Time Events, not by
permanently storing only summary columns.

------------------------------------------------------------------------

# PART C -- NEW MOULD TAB

## 11. Purpose of MOULD Tab

Add a new top-level tab:

``` text
PRODUCTION | USAGE | DEPALLET | MOULD | PROD API | REJECT API
```

The Mould tab is used to:

-   register new physical moulds
-   give each mould a permanent system number
-   allow operators to give moulds their own names
-   associate a mould with its Product Family/Product
-   show current usage age
-   show lifetime usage
-   record reconditioning
-   control mould status
-   view usage history
-   retire/deny moulds without deleting their history

------------------------------------------------------------------------

## 12. Mould Identity

Separate three concepts:

### `MouldID`

Internal database primary key.

### `MouldNo`

Permanent system-generated running number.

Example:

``` text
M000001
M000002
M000003
...
```

The system generates this number automatically.

Once registered, `MouldNo` should not normally be editable.

### `MouldName`

Human-friendly name entered by the operator.

Example:

``` text
M000001 | ปิดชายตัว 1
M000002 | ตัวสำรอง
M000003 | งานเร็ว
```

`MouldName` may be editable later without changing the identity or
historical records.

Database relationships must use `MouldID`, not `MouldName`.

------------------------------------------------------------------------

## 13. Mould Product Classification

Moulds follow the same Product classification concept used by
Production.

There are 4 Product Family/Type groups, and the Product is selected
within the appropriate family/type.

When registering a mould:

``` text
MOULD REGISTER

Product Family : [ Special Ridge ▼ ]
Product        : [ 02 | ปิดชาย ▼ ]

Mould No.      : [ M000001 ]       ← Auto
Mould Name     : [ ปิดชายตัว 1 ]   ← Operator input

Status         : NEW

                         [ REGISTER MOULD ]
```

Once Production Product is known, the system can automatically filter
compatible moulds.

------------------------------------------------------------------------

## 14. Mould Master -- Conceptual Fields

Conceptual schema:

``` text
MouldMaster
------------------------------------------------
MouldID
MouldNo                 -- Auto running, unique
MouldName               -- Operator-defined
ProductFamilyID
ProductID
Status
RegisterDate
CurrentReconditionNo
CurrentAge
LifetimeAge
...
```

`CurrentAge` and `LifetimeAge` may eventually be calculated/maintained
from transactions; the authoritative history must not depend only on
editable summary values.

------------------------------------------------------------------------

# PART D -- MOULD USAGE / AGE

## 15. Press Counter Is Mould Usage

When a mould is installed in a Press, every actual press cycle
contributes to mould wear.

Example:

``` text
F1
Dispatch = 100
Counter  = 110
Curing   = 100
```

Mould usage is:

``` text
110 cycles
```

not:

``` text
100 Dispatch
100 Curing
```

Therefore:

``` text
Mould Usage = Press Counter attributable to that mould
```

Even an unsuccessful press cycle still physically uses the mould.

------------------------------------------------------------------------

## 16. Every Mould Usage Must Be Historical

Do not store only one accumulated counter in `MouldMaster`.

Every production usage must be traceable.

Conceptual table:

``` text
MouldUsage
--------------------------------------------------------------------------------
UsageID
MouldID
ProductionID
PressProductionID
MachineCode
UsageCycles
ReconditionNo
UsageDate
SourceType
...
```

Example:

``` text
UsageID | Mould | Production | Press | Cycles | Date       | RC Cycle
----------------------------------------------------------------------
1       | 101   | 123        | F1    | 110    | 26/09/26   | 0
2       | 101   | 130        | F3    | 200    | 27/09/26   | 0
3       | 101   | 145        | F2    | 180    | 28/09/26   | 0
```

Current usage:

``` text
110 + 200 + 180 = 490 cycles
```

This history must allow answering:

-   Which Production Lots used this mould?
-   Which Press used it?
-   When was it used?
-   How many cycles did it run?
-   Which recondition cycle was active at that time?
-   What is its current age?
-   What is its lifetime total usage?

------------------------------------------------------------------------

## 17. Save/Update Must Not Double-Count Mould Usage

This is a critical implementation rule.

Example:

1.  Operator saves F1 Counter = 110.
2.  Later corrects Counter from 110 → 115.

The system must **not** do:

``` text
Mould age = 110 + 115 = 225   ← WRONG
```

It must update/reconcile the usage transaction so the production
contributes:

``` text
115 cycles
```

Mould usage updates must therefore be idempotent/reconcilable against
the Press Production or Mould Assignment record.

------------------------------------------------------------------------

# PART E -- MOULD RECONDITION LIFECYCLE

## 18. New Mould

On first registration:

``` text
Status               = NEW
CurrentReconditionNo = 0
CurrentAge            = 0
LifetimeAge           = 0
```

After it starts being used, it becomes active.

------------------------------------------------------------------------

## 19. Recondition

When the mould reaches its maintenance/recondition age, it can be sent
for reconditioning.

Example before first recondition:

``` text
Mould             M000001
Recondition No.   0
Current Age       18,500
Lifetime Usage    18,500
```

After Recondition #1:

``` text
Recondition No.   1
Current Age       0
Lifetime Usage    18,500
```

Important:

**Only Current Age resets. Lifetime Usage never resets.**

After another 15,000 cycles:

``` text
Recondition No.   1
Current Age       15,000
Lifetime Usage    33,500
```

After Recondition #2:

``` text
Recondition No.   2
Current Age       0
Lifetime Usage    33,500
```

This allows later analysis of mould life between reconditions.

------------------------------------------------------------------------

## 20. Recondition History

Do not store only the current recondition number.

Every recondition must have history.

Concept:

``` text
MouldReconditionHistory
---------------------------------------------------------------------------
ID
MouldID
ReconditionNo
SentDate
ReturnDate
UsageBeforeRecondition
Remark
...
```

Example:

``` text
RC#1 → 18,500 cycles before recondition
RC#2 → 15,000 cycles before recondition
RC#3 → 12,800 cycles before recondition
```

This makes deterioration and mould life trends analyzable later.

------------------------------------------------------------------------

## 21. Mould Status / End of Life

Conceptual lifecycle:

``` text
NEW
 ↓
ACTIVE
 ↓
RECONDITION
 ↓
ACTIVE
 ↓
RECONDITION
 ↓
ACTIVE
 ↓
...
 ↓
DENIED / RETIRED
```

Final terminology (`DENIED`, `RETIRED`, or both) can be finalized during
implementation.

A retired/denied mould:

-   cannot be selected for new Production
-   should not appear in the normal active Mould dropdown
-   must **not** be deleted from the database
-   retains all Production Usage history
-   retains all Recondition history
-   retains Lifetime Usage

------------------------------------------------------------------------

# PART F -- RELATIONSHIP OF THE WHOLE SYSTEM

## 22. Overall Data Relationship

``` text
Production Plan
      │
      ▼
Production Lot
      │
      ├─────────────────────────────────────────────┐
      │                                             │
      ▼                                             ▼
PRESS PRODUCTION                              LINE TIME
      │                                      LINE1 / LINE2
      │
      ├─ F1
      │   ├─ Dispatch Qty
      │   ├─ Counter / Curing
      │   ├─ Mould Assignment
      │   └─ Equipment Time Events
      │
      ├─ F2
      │   ├─ Dispatch Qty
      │   ├─ Counter / Curing
      │   ├─ Mould Assignment
      │   └─ Equipment Time Events
      │
      └─ Fxx ...
```

Mould side:

``` text
MouldMaster
     │
     ├── MouldUsage
     │       ├── Production Lot
     │       ├── Press
     │       ├── Counter cycles
     │       └── Recondition cycle
     │
     └── MouldReconditionHistory
             ├── RC#1
             ├── RC#2
             ├── RC#3
             └── ...
```

Equipment/OEE side:

``` text
EquipmentMaster
      │
      ├── PRESS: F1 ... Fxx
      │
      └── LINE: LINE1 / LINE2
               │
               ▼
        EquipmentTimeEvent
               │
      RUN / SETUP / CHANGEOVER /
      IDLE / CLEAN / SMDT /
      BREAKDOWN / OTHER
               │
               ▼
              OEE
```

------------------------------------------------------------------------

# PART G -- IMPORTANT RULES TO LOCK BEFORE CODING

## 23. Locked Requirements

1.  Production Plan quantity can be dispatched across multiple Presses.
2.  Each Press has its own `Dispatch`, `Counter`, `Curing`, Mould, and
    time/OEE data.
3.  A physical Mould is registered once and reused over many Production
    Lots.
4.  System generates permanent `MouldNo`.
5.  Operator can independently enter/edit `MouldName`.
6.  Mould identity/history uses `MouldID`, never the editable name.
7.  Production Product determines which Moulds are selectable.
8.  Press `Counter` is the basis of Mould usage/lifetime.
9.  Every Mould usage must be historically traceable.
10. Editing/resaving production Counter must not double-count Mould age.
11. Recondition resets `CurrentAge`, but never resets `LifetimeAge`.
12. Every Recondition cycle has its own history.
13. Retired/Denied moulds remain in historical data but cannot be used
    for new Production.
14. Database should support changing Mould during one Press Production
    in the future.
15. Press Time and Line Time are independent real equipment events.
16. LINE1 and LINE2 have the same TimeTypes as Presses.
17. Line stop affects mapped Presses; Press stop does not stop the Line.
18. Line events must not be copied into fake Press events.
19. OEE calculations must handle Press/Line time overlap without
    double-counting.
20. Manual, PLC, and System-generated time data must fit the same
    underlying model.
21. Future PLC support includes both `F1 ... Fxx` PLCs and `LINE1/LINE2`
    PLCs.
22. Do not hard-wire the database design to manual entry only; Manual is
    Phase 1 input into the future-compatible model.

------------------------------------------------------------------------

# PART H -- SUGGESTED DEVELOPMENT ORDER

To reduce risk, implement in this order:

``` text
1. Confirm existing Production Plan / Product / Lot schema
        ↓
2. Add Equipment Master + Press ↔ Line mapping
        ↓
3. Add Mould Master / Mould Register tab
        ↓
4. Add Mould Recondition + status lifecycle
        ↓
5. Add Press Production Dispatch + Mould assignment
        ↓
6. Add Mould Usage tied safely to Press Counter
        ↓
7. Add Manual Press Time entry
        ↓
8. Add Manual LINE1 / LINE2 Time entry
        ↓
9. Add validation / totals / overlap rules
        ↓
10. Verify historical queries and OEE-ready summaries
        ↓
11. Later connect Press PLC + Line PLC using SourceType = PLC
```

Before modifying the live database, inspect the existing FittingMES
schema and reuse existing Product Family, Product, Production Plan,
Production Lot, and other relevant master keys where appropriate. Do not
create duplicate master concepts merely because the names in this design
document differ.

------------------------------------------------------------------------

## 24. Key Principle

The intended architecture is:

``` text
PLAN → LOT → PRESS PRODUCTION → PHYSICAL MOULD
                  │                    │
                  │                    └→ USAGE / AGE / RECONDITION
                  │
                  └→ EQUIPMENT TIME
                         ↑
                 MANUAL / PLC / SYSTEM

LINE1 / LINE2 ─────────→ EQUIPMENT TIME
```

The Production screen is therefore not only a place to enter production
quantity. It is the connection point between:

-   Production Plan / Lot
-   Press allocation
-   Physical Mould
-   Press output
-   Mould lifetime
-   Press time/OEE
-   Line time/OEE
-   future PLC data

The schema must preserve those concepts separately while allowing them
to be analyzed together.
