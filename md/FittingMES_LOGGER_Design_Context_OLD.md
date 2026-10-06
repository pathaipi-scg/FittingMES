# FittingMES LOGGER --- Master & Transaction Design Context

**Status:** Design agreed; live Master validation and implementation are
still pending.\
**Purpose:** Source of truth for future Copilot/Codex sessions so the
LOGGER hierarchy, Cause shortcut behavior, and SMDT/BD rules are not
reinterpreted.

## 1. Objective

Add a `LOGGER` page to FittingMES for manual machine-stop event logging.

Target navigation:

`PRODUCTION | LOGGER | USAGE | DEPALLET | PROD API | REJECT API | PressMc | Mould | PRINT PROD | PRINT OEE`

Operator entry:

`STOP | START | MIN | Machine | Sub / Related M/C | Type | Sub Type | Cause | M/E/O | Note | SAVE`

LOGGER is separate from `EquipmentTimeEvent`, `ProductionData`, and
`ProductionLot`.

## 2. Stop Types

Main Stop Types currently intended:

1.  `RUN`
2.  `SETUP`
3.  `CHGOVER`
4.  `IDLE`
5.  `CLEAN`
6.  `SMDT`
7.  `BD`

Examples of Sub Stop Types gathered from the factory:

-   CHGOVER: เปลี่ยน Color, เปลี่ยน Mould, เปลี่ยนผ้าตะแกรง
-   IDLE: ไม่มีแผนผลิต, ทดลองผลิต, ที่กองเต็ม, ไม่มีแบบ, ไฟฟ้าดับ/น้ำประปาไม่ไหล,
    ครอบไม่แห้งรอแกะ, อื่นๆ
-   CLEAN: Clean ระหว่างผลิต, Clean หลังผลิต
-   SMDT: ผู้รับเหมาทำไม่ทัน, Forklift เสีย/วิ่งไม่ทัน, วัตถุดิบหมด, รอแบบ, อื่นๆ,
    ปรับตั้งระหว่างผลิต where configured
-   BD: `--`

Database IDs are authoritative. Do not hard-code assumed
StopId/SubStopId values until verified from the live Master.

## 3. Existing Master Tables

Use these existing Master tables:

-   `dbo.Fitting_MainMachine`
-   `dbo.Fitting_SubMachine`
-   `dbo.Fitting_StopType`
-   `dbo.Fitting_SubStopType`
-   `dbo.Fitting_Cause`

Master tables help operator selection. They are not LOGGER
transaction/history tables.

## Master Philosophy

All `Fitting_*` tables are editable reference/configuration Masters.

A future Master maintenance page will allow authorized employees to add,
edit, and deactivate these mappings. Master values populate operator
dropdowns and Cause shortcuts; they are not historical transactions.

`LoggerEvent` stores the final operator-confirmed values. Snapshot fields
preserve the historical display meaning of those values even if Master
descriptions are edited later. Later Master edits must not rewrite
historical `LoggerEvent` rows.

Referenced Master rows should normally be deactivated with `IsActive`
rather than deleted. Active Master rows normally populate new LOGGER
dropdowns.

`Fitting_Cause` is an editable shortcut/reference mapping. A Cause row
must not be rejected merely because `Cause.McId` differs from the owner
`McId` of `Cause.SubMcId`. The Cause values help the UI find or suggest
selectable options, but they do not impose a strict parent-child
ownership rule by themselves.

`DIRECT_SUB`, `RELATED_MAIN`, and `RELATED_SUB` describe the final
operator-confirmed LOGGER selection. They describe the normalized
transaction hierarchy, not Cause validity.

## 4. MainMachine

Examples include SANDMIX, MIXER, CABLE CAR, Robot, LINE, LINE(dry), and
F.

`Fitting_MainMachine.No` is the instance count.

Example: `Machine = F, No = 14` generates `F1 ... F14`.

The transaction stores the Main Machine Master ID plus the selected
instance number. It does not require 14 separate Master rows.

`Fitting_MainMachine.Relate = 1` means that Main Machine type is
eligible to participate as a Related Main Machine for another machine's
downtime. It does not make that machine the downtime subject.

## 5. SubMachine and IsRelated

`Fitting_SubMachine` contains physical sub-equipment and proxy rows used
to represent Related Main Machines.

Physical examples include Mould, ผ้า/ตะแกรง, ถ้วยจ่าย, ชุดจ่ายปูน, ชุดรับแบบ,
ชุดเสิร์ฟ, Hydraulic Pump, Press Cylinder, Control System, แบบ, Other,
ชุดวาง Product, Color Spray, Clear Coat, Conv, Gripper, Arm.

Proxy-style rows may include SANDMIX, MIXER, CABLE CAR, Robot, LINE,
LINE(dry), and F.

Agreed semantics for `Fitting_SubMachine.IsRelated`:

-   `IsRelated = 0`: physical SubMachine
-   `IsRelated = 1`: proxy for a Related Main Machine

For a proxy:

`Fitting_SubMachine.McId -> Fitting_MainMachine.McId`

The proxy identifies the Related Main Machine type. A proxy `SubMcId` is
used for resolution only and is **never stored as
`LoggerEvent.SubMcId`**.

Instance generation:

-   physical SubMachine: use `Fitting_SubMachine.No`
-   Related Main Machine proxy: resolve `McId` and use
    `Fitting_MainMachine.No`

Do not use the proxy row's `No` as the Related Main Machine instance
count.

## 6. One Operator Dropdown

Keep exactly one operator-facing dropdown:

`Sub / Related M/C`

Do not expose the backend hierarchy as multiple operator dropdowns
unless the design is explicitly changed later.

Backend normalized option kinds:

-   `DIRECT_SUB` --- example `F1 -> Mould1`
-   `RELATED_MAIN` --- example `F1 -> LINE1`
-   `RELATED_SUB` --- example `F1 -> LINE1 -> Conv3`

For `RELATED_SUB`, the one dropdown may display `LINE1 / Conv3`.

The operator does not need to see the technical option kind.

## 7. Canonical Transaction Semantics

These meanings are fixed:

### LoggerEvent.McId + McInstanceNo

The machine whose downtime is being logged.

### LoggerEvent.RelatedMcId + RelatedMcInstanceNo

Another Main Machine related to or causing that downtime.

### LoggerEvent.SubMcId + SubMcInstanceNo

A physical `Fitting_SubMachine` only.

**Absolute rule:** `LoggerEvent.SubMcId` must never contain the
`SubMcId` of an `IsRelated = 1` proxy.

## 8. Canonical Examples

### F1 -\> Mould1

-   `McId = F McId`
-   `McInstanceNo = 1`
-   `RelatedMcId = NULL`
-   `RelatedMcInstanceNo = NULL`
-   `SubMcId = Mould physical SubMcId`
-   `SubMcInstanceNo = 1`
-   kind = `DIRECT_SUB`

Snapshots: - Machine = F1 - Related = NULL - Sub = Mould1

### F1 -\> LINE1

-   `McId = F McId`
-   `McInstanceNo = 1`
-   `RelatedMcId = LINE McId`
-   `RelatedMcInstanceNo = 1`
-   `SubMcId = NULL`
-   `SubMcInstanceNo = NULL`
-   kind = `RELATED_MAIN`

The LINE proxy is used only to resolve LINE and is not stored as
`LoggerEvent.SubMcId`.

### F1 -\> LINE1 -\> Conv3

-   `McId = F McId`
-   `McInstanceNo = 1`
-   `RelatedMcId = LINE McId`
-   `RelatedMcInstanceNo = 1`
-   `SubMcId = Conv physical SubMcId`
-   `SubMcInstanceNo = 3`
-   kind = `RELATED_SUB`

This is the key example proving why `RelatedMcId` and
`RelatedMcInstanceNo` are required.

### F1 -\> Robot2

-   `McId = F McId`
-   `McInstanceNo = 1`
-   `RelatedMcId = Robot MainMachine McId`
-   `RelatedMcInstanceNo = 2`
-   `SubMcId = NULL`
-   `SubMcInstanceNo = NULL`
-   kind = `RELATED_MAIN`

Robot instance count comes from `Fitting_MainMachine.No`, not the proxy
row's `No`.

## 9. Cause Master Is a Shortcut

Cause Master exists primarily to make entry fast.

Selecting Cause may populate/suggest:

-   Sub / Related M/C
-   Stop Type
-   Sub Stop Type
-   M/E/O

Manual selection must remain possible for cases not covered by Cause
Master.

### Critical Cause rule

`Fitting_Cause.McId` is **not the LOGGER downtime subject**.

It is Cause relationship/owner context.

It must never overwrite an already selected `LoggerEvent.McId`.

Example: operator is logging F1 and selects `สายพานหยุด`. If the Cause
mapping points to LINE, F1 remains the downtime subject. Cause may
suggest LINE1 or LINE1/Conv3, but must not change the logged machine to
LINE.

Cause-first selection also must not make `Cause.McId` authoritative as
the downtime subject. The downtime subject comes independently from
Machine selection/page context.

## 10. Cause Resolver Order

1.  Use the active Cause mapping to suggest Stop Type, Sub Stop Type,
    M/E/O, and the one `Sub / Related M/C` dropdown.
2.  Resolve any supplied `Fitting_Cause.SubMcId` to an active
    `Fitting_SubMachine` row when it is available.
3.  If the resolved row has `IsRelated = 1`, treat it as a Related Main
    Machine proxy, resolve its Main Machine, and never save the proxy as
    `LoggerEvent.SubMcId`.
4.  If the resolved row has `IsRelated = 0`, use it as a suggested
    physical SubMachine option. Its owner does not have to equal
    `Fitting_Cause.McId` for the Cause mapping to be valid.
5.  Let the operator confirm or change the suggested Machine,
    Sub/Related M/C, Type, Sub Type, M/E/O, and Note values.
6.  Normalize the final selected hierarchy as `DIRECT_SUB`,
    `RELATED_MAIN`, or `RELATED_SUB`.
7.  Store the final operator-confirmed IDs and instances in
    `LoggerEvent`. Cause Master values do not determine the transaction
    hierarchy unless the operator leaves the suggested values unchanged.

If a Cause value cannot resolve to an active selectable option, report
that the shortcut is unavailable and retain manual selection. Do not
label the Cause `CONFIGURATION_AMBIGUOUS` solely because its `McId`
differs from the owner of its `SubMcId`, and do not silently repair
Master data.

## 11. Instance Selection

Master mappings identify types, not necessarily actual instances.

Example: LINE `No = 2` means LINE1 and LINE2. Conv `No = 5` means Conv1
through Conv5.

A Cause mapping cannot silently decide LINE1, LINE2, Conv3, Robot2, etc.

When multiple valid instances exist, the operator must choose the actual
normalized option.

Auto-select only when exactly one valid instance exists.

## 12. M/E/O

-   `M` = Mechanical
-   `E` = Electrical
-   `O` = Operation

M/E/O is tied to Cause as a default/shortcut. The transaction preserves
the final operator-confirmed value.

Proposed representation: `MEO char(1) NULL`.

## 13. SMDT / BD Duration Rule

Do not duplicate Cause Master rows merely because a rule-based event may
become SMDT or BD.

For rule-based SMDT causes:

-   `DurationMin < 10` -\> keep SMDT
-   `DurationMin >= 10` -\> save LOGGER transaction as BD

Only the transaction changes. **Never update `Fitting_Cause` because of
duration.**

Explicit classifications such as SETUP, CHGOVER, IDLE, and CLEAN bypass
this conversion.

Example: `ปรับตั้งโมล` is SETUP because it occurs before production begins;
it does not become SMDT/BD based on duration.

Use stable verified Master IDs for the SMDT/BD resolver. Do not compare
editable display text at runtime and do not scatter magic numeric IDs
through the application.

## 14. Time Entry

Operator enters Stop and Start. Application calculates `DurationMin`
automatically.

Current intent:

-   `StopDateTime datetime2(0)`
-   `StartDateTime datetime2(0)`
-   `DurationMin int NOT NULL`

Support midnight crossing.

Example: 23:55 -\> 00:05 means StartDateTime is next calendar day and
duration = 10 minutes.

## 15. Proposed LoggerEvent Machine Hierarchy

Required machine fields:

-   `McId`
-   `McInstanceNo`
-   `RelatedMcId`
-   `RelatedMcInstanceNo`
-   `SubMcId`
-   `SubMcInstanceNo`

Snapshots:

-   `MachineNameSnapshot`
-   `RelatedMachineSnapshot`
-   `SubMachineSnapshot`

Relational meaning:

-   `McId -> Fitting_MainMachine.McId`
-   `RelatedMcId -> Fitting_MainMachine.McId`
-   `SubMcId -> Fitting_SubMachine.SubMcId`

`SubMcId` is not polymorphic in the final design, so a normal FK to
`Fitting_SubMachine` is valid.

## 16. Proposed LoggerEvent Fields

Current proposed fields:

-   `LoggerEventID bigint IDENTITY`
-   `ProductionDate date`
-   `StopDateTime datetime2(0)`
-   `StartDateTime datetime2(0)`
-   `DurationMin int`
-   `McId`
-   `McInstanceNo`
-   `RelatedMcId`
-   `RelatedMcInstanceNo`
-   `SubMcId`
-   `SubMcInstanceNo`
-   `StopId`
-   `SubStopId`
-   `CauseId`
-   `MEO char(1)`
-   `MachineNameSnapshot`
-   `RelatedMachineSnapshot`
-   `SubMachineSnapshot`
-   `StopTypeSnapshot`
-   `SubStopTypeSnapshot`
-   `CauseSnapshot`
-   `Note`
-   `SourceType`
-   `ClassificationSource`
-   `CreatedAt`
-   `CreatedBy`

No `ProductionID` or `PressProductionID` is currently required.

## 17. Snapshots

Master IDs preserve relational identity. Snapshot columns preserve what
the operator saw/confirmed even if Master descriptions change later.

Do not replace IDs with snapshots. Keep both.

## 18. ClassificationSource

Intended values:

-   `CAUSE_SHORTCUT`: Cause mapping supplied classification and remained
    final
-   `MANUAL`: operator manually selected/changed classification
-   `DURATION_RULE`: rule-based SMDT was converted to BD by duration

Duration conversion never modifies Cause Master.

## 19. SourceType

Initial value: `MANUAL`.

Future possibilities: `PLC`, `SYSTEM`.

PLC integration is outside the current LOGGER implementation phase.

## 20. Master Validation Before Implementation

Inspect live Master tables read-only and validate:

1.  Every active Cause `McId` exists in MainMachine.
2.  Every non-null Cause `SubMcId` exists in SubMachine.
3.  Every `IsRelated = 1` proxy resolves to a valid active Main Machine.
4.  Related Main Machines satisfy the agreed `Relate` eligibility rule.
5.  Main/Sub Machines used for instance generation have positive `No`.
6.  Active Cause mappings resolve to available shortcut options where
    the mapping is intended to provide one.
7.  Stop/SubStop relationships are valid.
8.  Actual SMDT and BD Master IDs are identified from live data.
9.  SQL types and PKs of all Master ID columns are verified before
    creating FKs.

If inconsistent data is found: **REPORT ONLY. DO NOT AUTO-FIX.**

The discussion referenced proxy rows around SubMcId 20-26, but
remembered numeric IDs are not authoritative until verified live.

## 21. Example Factory Causes

Examples collected from the factory Excel:

-   ปูนติดโมล
-   ขึ้นแหย่คอถ้วยจ่าย
-   ส่วนผสมไม่เท่ากัน
-   Robot Alarm เคลียร์งาน
-   ทำความสะอาด ชุดจ่ายปูน/โม่/Mix
-   เคลียร์ปูนที่เรือ
-   วางครอบไม่ได้
-   ปรับตั้งเครื่องจักร น้อยกว่า 10 นาที
-   สายพานหยุด
-   Line สี หยุด
-   รอปูน
-   รอแบบ
-   ปรับตั้งชุดรับแบบ
-   ปรับตั้งชุดเสิร์ฟ
-   ปรับตั้งชุดวาง Product กลาง Line
-   ปรับตั้งโมล
-   แบบขัดตัว
-   อื่นๆ

These are Master data examples, not hard-coded application rules.

## 22. Manual Entry Must Remain Possible

Cause shortcut is convenience, not restriction.

For a new/unlisted case, operator must still be able to select manually:

-   Machine
-   Sub / Related M/C
-   Type
-   Sub Type
-   Cause/Other as applicable
-   M/E/O
-   Note

If Cause is `อื่นๆ`, Note may contain the additional free-text detail.

## 23. UI Direction

Use the existing compact FittingMES style.

Preferred interaction: top entry form -\> SAVE -\> event appears in log
table below, similar to the existing DEPALLET interaction pattern.

Do not make operators understand the database hierarchy.

One `Sub / Related M/C` dropdown may show:

-   Mould1
-   Hydraulic Pump1
-   LINE1
-   LINE2
-   LINE1 / Conv1
-   LINE1 / Conv3
-   Robot2

Backend stores the normalized hierarchy.

## 24. Decisions Copilot/Codex Must Not Reinterpret

Unless explicitly changed later:

1.  `McId` is the downtime subject.
2.  `Cause.McId` is not automatically the downtime subject.
3.  Cause selection must not overwrite an already selected downtime
    Machine.
4.  `RelatedMcId` is a Main Machine.
5.  `SubMcId` is a physical SubMachine only.
6.  An `IsRelated = 1` proxy is never saved as `LoggerEvent.SubMcId`.
7.  Keep one operator dropdown: `Sub / Related M/C`.
8.  `F1 -> LINE1 -> Conv3` must preserve all three levels.
9.  Cause is a shortcut/default mechanism; manual selection remains
    possible.
10. Multiple instances require operator selection unless exactly one
    valid choice exists.
11. SMDT/BD conversion affects LOGGER transaction only.
12. SETUP/CHGOVER/IDLE/CLEAN bypass the SMDT/BD duration rule.
13. Do not infer relationships from editable display names.
14. Do not silently repair inconsistent Master data.
15. `EquipmentTimeEvent` remains separate.
16. PLC/PIS integration is outside the current LOGGER phase.

## 25. Next Phase

Next step: **read-only live Master validation**.

Allowed: - SELECT from the five Fitting Master tables - inspect SQL
metadata, PKs, data types, relationships - inspect existing DB
configuration only as required to establish the connection

Not yet allowed without explicit approval: - create `LoggerEvent` -
modify application/repository files - INSERT/UPDATE/DELETE Master data -
PLC/PIS work - unrelated migrations

After validation, report actual IDs/types and inconsistencies, then wait
for approval.

## 26. Quick Mental Model

Canonical example:

`F1 -> LINE1 -> Conv3`

means:

**F1 stopped. LINE1 is the related Main Machine. Conv3 is the physical
sub-equipment involved.**

Therefore:

-   `Mc = F1`
-   `RelatedMc = LINE1`
-   `SubMc = Conv3`

For `F1 -> Mould1`:

-   `Mc = F1`
-   `RelatedMc = NULL`
-   `SubMc = Mould1`

For `F1 -> Robot2`:

-   `Mc = F1`
-   `RelatedMc = Robot2`
-   `SubMc = NULL`

This is the canonical interpretation for the FittingMES LOGGER.
