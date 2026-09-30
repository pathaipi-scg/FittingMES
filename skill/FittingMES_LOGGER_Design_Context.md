# FittingMES LOGGER — Master, Shortcut & Transaction Design Context

**Status:** Design source of truth.  
**Updated:** 2026-09-30  
**Purpose:** Prevent Copilot/Codex from reinterpreting LOGGER Master data, Cause shortcuts, machine hierarchy, and SMDT/BD behavior.

---

# 0. READ THIS FIRST — NON-NEGOTIABLE MENTAL MODEL

There are **three different things**. Do not mix them.

1. **MASTER**
   - Editable reference/configuration data.
   - Used to build dropdowns and shortcut mappings.
   - A future Master page will allow authorized employees to maintain it.
   - Master rows are **not historical LOGGER transactions**.

2. **CAUSE SHORTCUT**
   - Convenience mapping to make operator entry faster.
   - May prefill/suggest Machine, Sub / Related M/C, Type, Sub Type, and M/E/O.
   - Every populated value remains editable before SAVE.
   - Cause mapping is **not a strict relational hierarchy definition**.

3. **LOGGER EVENT**
   - Historical transaction.
   - Stores the **final operator-confirmed selection**.
   - The final hierarchy is normalized before SAVE.
   - Snapshot columns preserve what the operator saw at that time.

The most important rule is:

> **Do not use Cause Master to prove or reject the final machine hierarchy. Cause is a shortcut. The final operator-confirmed selection is what LoggerEvent stores.**

---

# 1. LOGGER Objective

Add a manual machine-stop LOGGER page to FittingMES.

Navigation:

`PRODUCTION | LOGGER | USAGE | DEPALLET | PROD API | REJECT API | PressMc | Mould | PRINT PROD | PRINT OEE`

Operator entry:

`STOP | START | MIN | Machine | Sub / Related M/C | Type | Sub Type | Cause | M/E/O | Note | SAVE`

LOGGER remains separate from:

- `EquipmentTimeEvent`
- `ProductionData`
- `ProductionLot`

No PLC/PIS/CAL FROM LOG behavior is part of this design phase.

---

# 2. Existing Master Tables

Use the existing Fitting Master tables:

- `dbo.Fitting_MainMachine`
- `dbo.Fitting_SubMachine`
- `dbo.Fitting_StopType`
- `dbo.Fitting_SubStopType`
- `dbo.Fitting_Cause`

These tables exist to support operator selection and future Master maintenance.

They are **reference/configuration Masters**, not LOGGER history.

---

# 3. Master Philosophy

All Fitting Master data must be treated as editable.

Future authorized employees may:

- add Master rows
- edit descriptions
- edit mappings
- change instance counts
- activate/deactivate rows
- maintain Cause shortcuts

Therefore application behavior must use Master IDs and Master data, not hard-coded display text.

Historical `LoggerEvent` rows must never be rewritten merely because a Master description or mapping changes later.

Snapshot fields exist specifically to preserve historical display meaning.

Referenced Master rows should normally be deactivated rather than deleted.

Active Master rows normally populate new LOGGER dropdowns.

---

# 4. Main Machine and Instance Expansion

`Fitting_MainMachine` stores a machine **type**, not one row per physical instance.

`Fitting_MainMachine.No` is the number of instances.

Example:

`Machine = F`  
`No = 14`

UI generates:

`F1 ... F14`

The transaction stores:

- `McId`
- `McInstanceNo`

Do not create 14 separate MainMachine Master rows.

The same principle applies to other Main Machine types.

---

# 5. SubMachine and Related Main Machine

`Fitting_SubMachine` contains normal physical SubMachine rows and may also contain proxy rows representing another Main Machine type.

Design semantics for `IsRelated`:

- `IsRelated = 0` → physical SubMachine
- `IsRelated = 1` → proxy/reference to a Related Main Machine

**Important:** `IsRelated` is a Master representation flag. It is not a Cause-validity rule.

For an `IsRelated = 1` proxy:

`Fitting_SubMachine.McId -> Fitting_MainMachine.McId`

The proxy is used to resolve a Related Main Machine.

The proxy's `SubMcId` must **not** be stored as the final physical `LoggerEvent.SubMcId`.

Instance source:

- Main Machine instance → `Fitting_MainMachine.No`
- physical SubMachine instance → `Fitting_SubMachine.No`
- Related Main Machine proxy → resolve Main Machine and use `Fitting_MainMachine.No`

Do not use a proxy row's `No` as the Related Main Machine instance count.

Phase 1 has been completed on the live database. `dbo.Fitting_SubMachine.IsRelated`
exists as `bit NOT NULL` with default constraint
`DF_Fitting_SubMachine_IsRelated` and default value `0`.

Confirmed current Master configuration:

-   physical SubMachine rows `SubMcId` 1 through 19 have `IsRelated = 0`
-   Related Main Machine proxy rows `SubMcId` 20 through 26 have
   `IsRelated = 1`
-   `20 -> SANDMIX -> McId 1`
-   `21 -> MIXER -> McId 2`
-   `22 -> CABLE CAR -> McId 3`
-   `23 -> Robot -> McId 4`
-   `24 -> LINE -> McId 5`
-   `25 -> LINE(dry) -> McId 6`
-   `26 -> F -> McId 7`

Runtime behavior must use `IsRelated` from the active Master data, not
these current row numbers.

---

# 6. `Relate` Meaning

`Fitting_MainMachine.Relate` indicates whether that Main Machine type is intended/eligible to participate as a Related Main Machine.

`IsRelated` and `Relate` are separate Master configuration fields:

-   `IsRelated` answers: what kind of `Fitting_SubMachine` row is this?
-   `Relate` answers: is this Main Machine currently eligible for Related
   M/C use?

`Relate` remains independent from `Fitting_SubMachine.IsRelated`. The
confirmed current values are SANDMIX = 1, MIXER = 1, CABLE CAR = 1,
Robot = 1, LINE = 1, LINE(dry) = 0, and F = 0. Do not reinterpret or
change `Relate` because a proxy row has `IsRelated = 1`.

It is useful when building manual Related M/C choices.

However:

> **Do not use `Relate` or ownership equality to declare a Cause row invalid merely because the Cause shortcut combines IDs from different Master contexts.**

Cause Master is allowed to be a shortcut/reference mapping.

Master validation may report missing/inactive IDs, but it must not invent a strict Cause parent-child rule that the business has not defined.

---

# 7. ONE Operator Dropdown

Keep exactly one operator-facing dropdown:

`Sub / Related M/C`

Do not force employees to understand backend hierarchy.

The dropdown may contain simple or composite display options such as:

- `Mould1`
- `Hydraulic Pump1`
- `LINE1`
- `LINE2`
- `LINE1 / Conv1`
- `LINE1 / Conv3`
- `Robot2`

The backend may internally normalize the final choice as:

- `DIRECT_SUB`
- `RELATED_MAIN`
- `RELATED_SUB`

These are **transaction normalization kinds only**.

They are not Cause types and must not be used to decide whether a Cause Master row is valid.

---

# 8. Canonical LoggerEvent Machine Semantics

These meanings are fixed.

## 8.1 Downtime Subject

`LoggerEvent.McId` + `LoggerEvent.McInstanceNo`

= the Main Machine whose downtime is being logged.

Example:

`F1`

## 8.2 Related Main Machine

`LoggerEvent.RelatedMcId` + `LoggerEvent.RelatedMcInstanceNo`

= another Main Machine involved in the final selected hierarchy.

Example:

`LINE1`

## 8.3 Physical SubMachine

`LoggerEvent.SubMcId` + `LoggerEvent.SubMcInstanceNo`

= physical `Fitting_SubMachine` only.

Example:

`Conv3`

Absolute rule:

> `LoggerEvent.SubMcId` must never contain the `SubMcId` of an `IsRelated = 1` proxy.

---

# 9. Canonical Final-Selection Examples

These examples describe **final LOGGER storage**, not Cause validity.

## 9.1 F1 -> Mould1

Kind:

`DIRECT_SUB`

Final hierarchy:

- Machine = `F1`
- Related Main = `NULL`
- Physical SubMachine = `Mould1`

Storage concept:

- `McId = F`
- `McInstanceNo = 1`
- `RelatedMcId = NULL`
- `RelatedMcInstanceNo = NULL`
- `SubMcId = Mould physical SubMcId`
- `SubMcInstanceNo = 1`

## 9.2 F1 -> LINE1

Kind:

`RELATED_MAIN`

Final hierarchy:

- Machine = `F1`
- Related Main = `LINE1`
- Physical SubMachine = `NULL`

Storage concept:

- `McId = F`
- `McInstanceNo = 1`
- `RelatedMcId = LINE`
- `RelatedMcInstanceNo = 1`
- `SubMcId = NULL`
- `SubMcInstanceNo = NULL`

The LINE proxy may help resolve LINE, but the proxy itself is not saved as physical `SubMcId`.

## 9.3 F1 -> LINE1 -> Conv3

Kind:

`RELATED_SUB`

Final hierarchy:

- Machine = `F1`
- Related Main = `LINE1`
- Physical SubMachine = `Conv3`

Storage concept:

- `McId = F`
- `McInstanceNo = 1`
- `RelatedMcId = LINE`
- `RelatedMcInstanceNo = 1`
- `SubMcId = Conv physical SubMcId`
- `SubMcInstanceNo = 3`

This example is the reason `RelatedMcId` / `RelatedMcInstanceNo` are separate from `SubMcId` / `SubMcInstanceNo`.

## 9.4 F1 -> Robot2

Kind:

`RELATED_MAIN`

Final hierarchy:

- Machine = `F1`
- Related Main = `Robot2`
- Physical SubMachine = `NULL`

Robot instance count comes from Robot MainMachine `No`.

---

# 10. Cause Master — SHORTCUT ONLY

`Fitting_Cause` exists primarily to reduce operator clicks.

A Cause row may contain shortcut/default IDs for:

- Machine context
- Sub / Related M/C context
- Stop Type
- Sub Stop Type
- M/E/O

The Cause columns are shortcut dimensions.

**Do not assume that `Fitting_Cause.McId` and `Fitting_Cause.SubMcId` define a strict SQL parent-child relationship with each other.**

In particular:

> `Fitting_Cause.McId` does NOT have to equal `Fitting_SubMachine.McId` for the Cause row to be valid.

Do not create a rule such as:

`Cause.McId must equal owner McId of Cause.SubMcId`

unless the user explicitly adds that business rule later.

Do not label a Cause `CONFIGURATION_AMBIGUOUS` merely because those IDs differ.

Examples such as:

- SANDMIX + MIXER
- LINE + ถ้วยจ่าย
- F + ชุดวาง Product

may be intentional shortcut combinations.

---

# 11. Cause-First and Machine-First Behavior

This section is critical.

## 11.1 Cause selected FIRST

If the operator selects Cause before Machine:

Cause may **prefill/suggest**:

- Machine
- Sub / Related M/C
- Type
- Sub Type
- M/E/O

`Fitting_Cause.McId` may be used as the **initial Machine suggestion/default** when no Machine has been selected yet.

But it is not locked.

The operator may change Machine or any other populated field before SAVE.

The final selected Machine becomes `LoggerEvent.McId`.

## 11.2 Machine selected FIRST

If the operator already selected a Machine, for example `F1`, and then selects Cause:

- Do **not** overwrite the selected Machine automatically.
- Keep `F1` as the downtime subject.
- Use Cause to populate/suggest the remaining fields.
- The operator may still edit all populated fields.

Example:

Operator selects:

`Machine = F1`

Then selects:

`Cause = สายพานหยุด`

Even if the Cause shortcut references LINE, the already-selected downtime subject remains:

`F1`

The Cause may suggest a Sub / Related M/C option involving LINE.

## 11.3 SAVE rule

At SAVE time, do not save “what Cause originally meant.”

Save the **final values currently confirmed in the form**.

Cause is the shortcut.

The form is the operator confirmation.

LoggerEvent is the historical transaction.

---

# 12. How Cause Should Drive `Sub / Related M/C`

Cause shortcut resolution should be permissive and UI-oriented.

Use Cause IDs to locate/suggest selectable Master options.

Do not use Cause to manufacture a strict hierarchy that is not explicitly stored.

Rules:

1. Resolve referenced IDs if they exist and are active.
2. Use `IsRelated` when a referenced SubMachine row is a Related Main Machine proxy.
3. Use normal physical SubMachine rows as physical choices.
4. Use Cause `McId` as shortcut context/default information.
5. Do not reject the Cause merely because Cause `McId` and SubMachine owner `McId` differ.
6. If multiple instances are possible, present valid instance choices to the operator.
7. Auto-select an instance only when exactly one valid choice exists.
8. Operator may override the suggestion.
9. Normalize the **final selected option** into `DIRECT_SUB`, `RELATED_MAIN`, or `RELATED_SUB`.
10. Save that final normalized hierarchy.

If a Cause references a missing/inactive Master ID:

- report the shortcut as unavailable
- keep manual selection available
- do not silently alter Master data
- do not guess from display text

---

# 13. Manual Selection Is Always Allowed

Cause is optional convenience, not a restriction.

If the employee encounters a case not represented by Cause Master, the employee can select manually:

- Machine
- Sub / Related M/C
- Type
- Sub Type
- Cause/Other as applicable
- M/E/O
- Note

The operator must be able to override Cause-populated values before SAVE.

---

# 14. Instance Selection

Master rows identify machine/submachine types and instance counts.

They do not necessarily identify the actual physical instance involved in an event.

Example:

`LINE.No = 2`

means:

- LINE1
- LINE2

If:

`Conv.No = 5`

the UI may expose Conv1 ... Conv5 as appropriate.

A Cause shortcut must not silently decide LINE1, LINE2, Conv3, Robot2, etc. when multiple choices exist.

Auto-select only when exactly one valid instance exists.

---

# 15. Stop Type / Sub Stop Type

Current intended Stop Types:

1. RUN
2. SETUP
3. CHGOVER
4. IDLE
5. CLEAN
6. SMDT
7. BD

Database IDs are authoritative.

Use actual Master IDs from the live database.

Do not use editable display names as runtime logic.

Do not scatter magic numeric IDs throughout Python/HTML/JavaScript.

Centralize any IDs required for rule behavior.

---

# 16. SMDT / BD Duration Rule

Cause Master should not be duplicated just because a rule-based stop may become SMDT or BD.

For a Cause configured as the rule-based SMDT case:

- `DurationMin < 10` → keep SMDT classification
- `DurationMin >= 10` → save final LoggerEvent classification as BD

Only the transaction changes.

Never update `Fitting_Cause` because of event duration.

Explicit classifications such as:

- SETUP
- CHGOVER
- IDLE
- CLEAN

bypass SMDT/BD duration conversion.

Example:

`ปรับตั้งโมล`

is SETUP because it occurs before production starts. It does not become BD merely because its duration exceeds 10 minutes.

The live Master IDs for the SMDT/BD pair must be verified and centrally resolved before implementation.

---

# 17. Time Entry

Operator enters:

- STOP
- START

Application calculates:

`DurationMin`

Current intended types:

- `StopDateTime datetime2(0)`
- `StartDateTime datetime2(0)`
- `DurationMin int NOT NULL`

Support midnight crossing.

Example:

`23:55 -> 00:05`

means StartDateTime is on the next calendar date and duration is 10 minutes.

---

# 18. LoggerEvent Transaction Fields

Current design:

- `LoggerEventID`
- `ProductionDate`
- `StopDateTime`
- `StartDateTime`
- `DurationMin`
- `McId`
- `McInstanceNo`
- `RelatedMcId`
- `RelatedMcInstanceNo`
- `SubMcId`
- `SubMcInstanceNo`
- `StopId`
- `SubStopId`
- `CauseId`
- `MEO`
- `MachineNameSnapshot`
- `RelatedMachineSnapshot`
- `SubMachineSnapshot`
- `StopTypeSnapshot`
- `SubStopTypeSnapshot`
- `CauseSnapshot`
- `Note`
- `SourceType`
- `ClassificationSource`
- `CreatedAt`
- `CreatedBy`

No `ProductionID` or `PressProductionID` is required by the current design.

Relational meaning:

- `McId -> Fitting_MainMachine.McId`
- `RelatedMcId -> Fitting_MainMachine.McId`
- `SubMcId -> physical Fitting_SubMachine.SubMcId`
- `StopId -> Fitting_StopType.StopId`
- `SubStopId -> Fitting_SubStopType.SubStopId`
- `CauseId -> Fitting_Cause.CauseId`

---

# 19. Snapshot Rule

IDs preserve relational identity.

Snapshots preserve historical display meaning.

Keep both.

Examples:

- `MachineNameSnapshot = F1`
- `RelatedMachineSnapshot = LINE1`
- `SubMachineSnapshot = Conv3`

If Master names are edited later, old LoggerEvent snapshots remain unchanged.

---

# 20. M/E/O

Current values:

- `M` = Mechanical
- `E` = Electrical
- `O` = Operation

Cause may provide the default.

Operator may edit it.

LoggerEvent stores the final operator-confirmed value.

Current proposed representation:

`MEO char(1) NULL`

---

# 21. ClassificationSource

Intended transaction values:

- `CAUSE_SHORTCUT`
- `MANUAL`
- `DURATION_RULE`

Meaning:

- `CAUSE_SHORTCUT` → Cause supplied the classification and operator left it unchanged
- `MANUAL` → operator manually selected/changed classification
- `DURATION_RULE` → rule-based SMDT was converted to BD by duration

This is transaction metadata.

It does not change Cause Master.

---

# 22. SourceType

Initial:

`MANUAL`

Possible future values:

- `PLC`
- `SYSTEM`

PLC integration is outside the current phase.

---

# 23. Future Master Maintenance Page

A future employee-facing Master page is expected.

Its purpose is to maintain reference data used by LOGGER dropdowns and Cause shortcuts.

Therefore the LOGGER implementation must not depend on today's Excel rows being permanent.

The future Master page may maintain:

- Main Machines
- instance counts
- Related eligibility
- SubMachines
- proxy/physical classification
- Stop Types
- Sub Stop Types
- Causes
- Cause shortcut mappings
- M/E/O defaults
- active/inactive state

The LOGGER transaction design must remain stable even when Master content changes.

---

# 24. What Live Validation SHOULD Check

Read-only validation before implementation may check:

1. Actual SQL data types and PKs.
2. Whether referenced Master IDs exist.
3. Whether referenced rows are active.
4. Positive instance counts.
5. StopType/SubStopType relationships.
6. Actual SMDT/BD Master IDs.
7. Confirmed `IsRelated` definition and active values.
8. Whether dropdown options can be generated from current Master data.

Validation may **report** suspicious or unavailable shortcuts.

Validation must **not**:

- auto-fix Master rows
- rewrite Cause mappings
- invent parent-child Cause rules
- reject Cause merely because `Cause.McId != SubMachine.McId`
- infer relationships from editable display text
- modify SQL or application files unless explicitly approved

---

# 25. DO NOT REINTERPRET THESE DECISIONS

Unless the user explicitly changes the design later:

1. Master tables are editable reference/configuration data.
2. A future employee Master page will maintain them.
3. Cause is a shortcut/default mechanism.
4. Cause fields are not a strict relational hierarchy contract.
5. Cause-first may prefill Machine when Machine is still empty.
6. Cause-first Machine prefill is only a suggestion and remains editable.
7. If Machine is already selected, Cause must not overwrite it automatically.
8. LoggerEvent stores final operator-confirmed values.
9. `McId` is the final downtime subject.
10. `RelatedMcId` is a Related Main Machine.
11. `SubMcId` is a physical SubMachine only.
12. An `IsRelated = 1` proxy is never saved as physical `LoggerEvent.SubMcId`.
13. Keep one operator dropdown: `Sub / Related M/C`.
14. `DIRECT_SUB`, `RELATED_MAIN`, `RELATED_SUB` describe final transaction hierarchy only.
15. They must not be used to judge Cause validity.
16. `Cause.McId` does not have to equal the owner `McId` of `Cause.SubMcId`.
17. `F1 -> LINE1 -> Conv3` must preserve all three levels.
18. Multiple instances require operator choice unless only one choice exists.
19. Manual selection remains possible even when no Cause shortcut exists.
20. SMDT/BD duration conversion changes LoggerEvent only.
21. SETUP/CHGOVER/IDLE/CLEAN bypass the SMDT/BD duration rule.
22. Later Master edits must not rewrite historical LoggerEvent rows.
23. Do not silently repair Master data.
24. Do not infer business relationships from editable names.
25. `EquipmentTimeEvent` remains separate.
26. PLC/PIS/CAL FROM LOG is outside this phase.
27. Phase 1 migration `016_submachine_is_related.sql` has been executed
   successfully on the live database.
28. `Fitting_Cause` contains 18 active rows and was not modified by Phase
   1. Cause remains a permissive shortcut/default mechanism.

---

# 26. Decision Priority When Anything Seems Ambiguous

Copilot/Codex must apply this priority:

1. **Explicit current user instruction**
2. **This design context**
3. **Final operator-confirmed form state**
4. **Current active Master data**
5. **Cause shortcut defaults**
6. **Display text only for presentation — never for relational inference**

If a Cause shortcut and the operator's current selections differ:

> **Operator-confirmed form state wins.**

If Master data changed after an old event was saved:

> **Historical LoggerEvent IDs/snapshots remain unchanged.**

If a relationship cannot be established safely:

> **Keep manual selection available and report the shortcut issue. Do not invent a relationship.**

---

# 27. Quick Mental Model

## MASTER

“What choices are available now?”

## CAUSE

“Can I fill some of those choices quickly for the employee?”

## FORM

“What did the employee finally confirm?”

## LOGGER EVENT

“What exactly happened historically?”

Canonical transaction examples:

`F1 -> Mould1`

means:

- Mc = F1
- RelatedMc = NULL
- SubMc = Mould1

`F1 -> LINE1`

means:

- Mc = F1
- RelatedMc = LINE1
- SubMc = NULL

`F1 -> LINE1 -> Conv3`

means:

- Mc = F1
- RelatedMc = LINE1
- SubMc = Conv3

`F1 -> Robot2`

means:

- Mc = F1
- RelatedMc = Robot2
- SubMc = NULL

---

# 28. Phase 2 Live Status

Phase 1 Master configuration is complete and live. Migration
`016_submachine_is_related.sql` was executed successfully.

Phase 2 is complete and live. Migration `017_logger_event.sql` was
executed successfully through the existing FittingMES application
database connection using `app.database.get_connection()`.

`dbo.LoggerEvent` exists in the live database and contained zero rows at
the time of verification. Its live schema, primary key, CHECK
constraints, DEFAULT constraints, six foreign keys, and indexes were
verified successfully.

## 28.1 Live LoggerEvent Columns

- `LoggerEventID bigint IDENTITY(1,1) NOT NULL`
- `ProductionDate date NOT NULL`
- `StopDateTime datetime2(0) NOT NULL`
- `StartDateTime datetime2(0) NOT NULL`
- `DurationMin int NOT NULL`
- `McId int NOT NULL`
- `McInstanceNo int NOT NULL`
- `RelatedMcId int NULL`
- `RelatedMcInstanceNo int NULL`
- `SubMcId int NULL`
- `SubMcInstanceNo int NULL`
- `StopId int NOT NULL`
- `SubStopId int NULL`
- `CauseId int NULL`
- `MEO char(1) NULL`
- `MachineNameSnapshot nvarchar(100) NOT NULL`
- `RelatedMachineSnapshot nvarchar(100) NULL`
- `SubMachineSnapshot nvarchar(100) NULL`
- `StopTypeSnapshot nvarchar(100) NOT NULL`
- `SubStopTypeSnapshot nvarchar(100) NULL`
- `CauseSnapshot nvarchar(500) NULL`
- `Note nvarchar(1000) NULL`
- `SourceType varchar(20) NOT NULL DEFAULT MANUAL`
- `ClassificationSource varchar(20) NOT NULL`
- `CreatedAt datetime2(3) NOT NULL DEFAULT SYSDATETIME()`
- `CreatedBy nvarchar(200) NULL`

## 28.2 Live LoggerEvent Rules

The verified live CHECK rules are:

- `DurationMin > 0`
- `McInstanceNo > 0`
- `RelatedMcId` and `RelatedMcInstanceNo` are both NULL or both NOT NULL.
- `SubMcId` and `SubMcInstanceNo` are both NULL or both NOT NULL.
- Related and physical SubMachine instance numbers are positive when present.
- `MEO` is NULL, `M`, `E`, or `O`.
- `SourceType` is `MANUAL`, `PLC`, or `SYSTEM`.
- `ClassificationSource` is `CAUSE_SHORTCUT`, `MANUAL`, or `DURATION_RULE`.
- `StartDateTime > StopDateTime`.

The verified live foreign keys are:

- `McId -> Fitting_MainMachine.McId`
- `RelatedMcId -> Fitting_MainMachine.McId`
- `SubMcId -> Fitting_SubMachine.SubMcId`
- `StopId -> Fitting_StopType.StopId`
- `SubStopId -> Fitting_SubStopType.SubStopId`
- `CauseId -> Fitting_Cause.CauseId`

The verified live indexes are:

- `PK_LoggerEvent`
- `IX_LoggerEvent_ProductionDate_Stop`
- `IX_LoggerEvent_Machine`
- `IX_LoggerEvent_RelatedMachine`
- `IX_LoggerEvent_Cause`

`IX_LoggerEvent_RelatedMachine` is filtered to `RelatedMcId IS NOT NULL`.
`IX_LoggerEvent_Cause` is filtered to `CauseId IS NOT NULL`.

## 28.3 Phase 2 Boundaries

No LoggerEvent test rows were inserted. No LOGGER backend or UI
implementation has started.

PLC integration, PIS integration, and CAL FROM LOG are not part of this
phase. `EquipmentTimeEvent` remains separate and unchanged.

The application must preserve the following rule during later LOGGER
implementation:

> An `IsRelated = 1` `Fitting_SubMachine` proxy must never be saved as
> `LoggerEvent.SubMcId`. `LoggerEvent.SubMcId` is for a physical
> SubMachine only.

This is enforced by LOGGER application normalization and validation, not
by an additional database constraint.

# 29. Implementation Gate

Phase 2 database execution is complete. LOGGER application
implementation remains a separate approved phase.

When implementation is approved later, re-read this file first and
follow it as the LOGGER design source of truth.
