---
description: Preserve the FittingMES LOGGER bidirectional Cause ↔ Sub /
  Rel M/C selection workflow, cascade rules, related-machine proxy
  semantics, and persistence safety.
name: fittingmes-logger-bidirectional-selection
---

# FittingMES LOGGER Bidirectional Selection Skill

Use this skill whenever modifying, reviewing, testing, or debugging the
FittingMES LOGGER workflow.

## Non-negotiable behavior

LOGGER supports **both selection directions** after `Main Machine` and
`Instance` are selected.

### A. Forward selection

`Main Machine → Instance → Sub / Rel M/C → Type → Cause → Sub Type → M/E/O`

Example:

`F → F1 → LINE1 / Conv1 → SMDT → สายพานหยุด → อื่นๆ → M`

The selected `Sub / Rel M/C` filters the available Causes.

### B. Reverse selection

`Main Machine → Instance → Type → Cause → Sub / Rel M/C`

The operator is **not required** to choose `Sub / Rel M/C` before Cause.

Example:

`F → F1 → SMDT → รอปูน`

LOGGER resolves compatible targets such as `CABLE CAR1` and
`CABLE CAR2`.

If more than one target is compatible, LOGGER must filter the target
dropdown and wait for the operator to choose. It must not guess an
instance.

## Target resolution rules

-   Exactly **one** compatible target → auto-select it.
-   **Multiple** compatible targets → filter `Sub / Rel M/C` and require
    operator selection.
-   **Never guess** an equipment or related-machine instance.
-   Preserve Cause when the operator later selects a compatible target.
-   Clear/rebuild incompatible Cause/target combinations.
-   Changing Main Machine, Instance, or Type must not leave stale Cause
    or target selections.

## DIRECT_SUB

A physical SubMachine under the selected Main Machine, for example
`F1 → Mould1`.

Physical equipment Cause mappings may be used normally. Persistence
represents the physical SubMachine in `LoggerEvent.SubMcId` /
`SubMcInstanceNo`.

## RELATED_MAIN

Examples: `F1 → CABLE CAR1`, `F1 → LINE1`.

A RELATED_MAIN may use:

1.  a machine-level Cause where `Cause.SubMcId IS NULL`, or
2.  a Cause linked to an **active `IsRelated=1` proxy** belonging to
    that related Main Machine.

Known valid proxy-Cause examples:

-   CABLE CAR proxy → `รอปูน`
-   LINE proxy → `รอแบบ`

### Critical persistence rule

The proxy `SubMcId` identifies the Cause mapping only.

**Never persist a related proxy ID into `LoggerEvent.SubMcId`.**

For `F1 → CABLE CAR1 → SMDT → รอปูน`, preserve approximately:

-   `McId` = F
-   `McInstanceNo` = 1
-   `RelatedMcId` = CABLE CAR
-   `RelatedMcInstanceNo` = 1
-   `SubMcId` = `NULL`
-   `CauseId` = Cause ID for `รอปูน`

The operator selected a related Main Machine, not a physical SubMachine.

## RELATED_SUB

Physical equipment belonging to a related Main Machine, for example
`F1 → LINE1 / Conv1`.

Equipment-specific Causes are valid here,
e.g. `LINE1 / Conv1 → SMDT → สายพานหยุด`.

Persistence includes both:

-   `RelatedMcId` / `RelatedMcInstanceNo`
-   physical `SubMcId` / `SubMcInstanceNo`

## Cause filtering safety

Do not expose a physical equipment Cause merely because `Cause.McId`
matches a RELATED_MAIN machine.

Selecting `LINE1` alone must **not** expose a Conv-specific physical
Cause. A Conv Cause requires a RELATED_SUB target such as
`LINE1 / Conv1`.

Proxy Causes are different: an active `IsRelated=1` proxy mapping may be
used for RELATED_MAIN.

Known mapping caveat: Cause `วางครอบไม่ได้` has shown an inconsistent
cross-machine mapping (`Cause.McId = LINE` while its referenced physical
SubMachine belongs to F). Do not automatically treat it as a valid LINE
Cause without explicit master-data clarification.

## Reverse-selection examples

### `รอปูน`

`F → F1 → SMDT → รอปูน`

Compatible targets: `CABLE CAR1`, `CABLE CAR2`. Do not automatically
choose one.

### `สายพานหยุด`

`F → F1 → SMDT → สายพานหยุด`

Filter `Sub / Rel M/C` to compatible LINE conveyor targets such as
`LINE1 / Conv1` through `LINE1 / Conv5` and `LINE2 / Conv1` through
`LINE2 / Conv5`. The operator chooses the actual stopped conveyor.

### `ปูนติดโมล`

Reverse resolution may expose compatible Mould targets.

-   one target → auto-select
-   multiple targets → filter only; wait for operator

## Initialization requirement

On initial page load and after a `saved=true` redirect, initialization
order must preserve reverse Cause selection.

Sub Type / classification prerequisites must be initialized before
rebuilding reverse Cause candidates.

When `Sub / Rel M/C` is empty, Cause candidates must be built from **all
currently valid targets** for the selected Main Machine, Instance, Type,
and classification context.

Do not return only `No Cause` merely because no target has been
selected.

Regression fix:

`889b783 Fix LOGGER reverse cause initialization`

## Existing implementation checkpoints

-   `4259a9c Complete LOGGER related-machine cause workflow`
-   `b41f4f6 Add bidirectional LOGGER cause selection`
-   `889b783 Fix LOGGER reverse cause initialization`

## Main Machine ordering

`F` is intentionally placed first in the Main Machine dropdown because
it is expected to be selected frequently. Do not undo this ordering
accidentally.

## Regression requirements

Any future LOGGER change must preserve both directions:

-   `Sub / Rel M/C → Cause`
-   `Cause → Sub / Rel M/C`

Tests should cover at minimum:

-   DIRECT_SUB forward
-   DIRECT_SUB reverse
-   RELATED_MAIN forward
-   RELATED_MAIN reverse
-   RELATED_SUB forward/reverse where applicable
-   unique target auto-selection
-   multiple targets = filter only, no guessing
-   Cause preservation after compatible target selection
-   stale selection clearing
-   initial page-load reverse Cause population
-   `saved=true` initialization
-   active proxy Cause acceptance
-   physical Cause rejection under RELATED_MAIN
-   proxy `SubMcId` never stored in `LoggerEvent.SubMcId`
-   equivalent forward/reverse selections persist equivalent normalized
    identities

## Change discipline

1.  Preserve existing database/schema/master data unless explicitly
    required.
2.  Do not change persistence semantics just to simplify UI filtering.
3.  Do not convert related proxies into physical SubMachine selections.
4.  Do not make automatic instance guesses.
5.  Test both forward and reverse paths after cascade changes.
6.  Verify initialization after save/redirect, not only interactive
    changes.
7.  Keep unrelated FittingMES workflows untouched.
