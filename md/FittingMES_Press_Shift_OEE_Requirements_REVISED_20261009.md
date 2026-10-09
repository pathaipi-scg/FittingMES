# FittingMES — Press/Shift OEE Report Requirements (Revised)

**Date:** 2026-10-09<br>
**Status:** Confirmed business requirements; implementation pending<br>
**Purpose:** Replace the earlier broader OEE redesign draft with the user's clarified, minimal-change requirements.<br>
**Project destination (copy this file to):** `D:\AI\FittingMES\md\FittingMES_Press_Shift_OEE_Requirements_REVISED_20261009.md`

> **This document supersedes the earlier Press/Shift OEE requirements draft wherever they conflict.** The goal is to reproduce the familiar Excel report in FittingMES using existing production and LOGGER information, not to redesign OEE, downtime recording, or database architecture.

## 1. Confirmed objective

The existing Excel report contains per-machine, per-shift Start/End times and detailed downtime and OEE tables. FittingMES already contains the production quantities, manual downtime categories, LOGGER records, and OEE calculation functionality. The one missing operator input identified by the user is **Start / End for each Press (F machine) in each Shift**, previously removed from the PRESS PRODUCTION screen. The user states that the relevant SQL columns already exist.

Deliver the Excel-style report by:

1. Restoring editable **Start** and **End** fields for each PRESS PRODUCTION assignment row.
2. Saving/loading those values using the **existing PressProduction SQL fields**, subject to verification of actual column names and existing code paths.
3. Using **each Press assignment's own saved Start/End** to derive its production duration in PRINT OEE.
4. **Removing the temporary fallback** that substitutes parent Production Lot Start/End or configured Shift Start/End as the machine's actual operating interval.
5. Rendering the existing production figures, LOGGER downtime details, and standard OEE results in a layout closely matching the original Excel report.

**Do not change the approved standard OEE calculation merely to match Excel presentation.** Only the operating-time input source changes to the actual Press Start/End; any downstream calculation naturally dependent on duration must use that corrected duration.

## 2. PRODUCTION — restore only the missing inputs

### 2.1 PRESS PRODUCTION row

Restore `Start` and `End` alongside the existing columns, independently for each **PressProductionID / Press / Shift** assignment. The same Press can have different times in Shift 1 and Shift 2, and different Presses in the same Lot may have different start/end times.

- Display and input format: **24-hour `HH:mm`**; no AM/PM.
- Correctly handle overnight intervals, e.g. `19:00` to `04:30` the following calendar day.
- Read previously stored values when the row loads and preserve them on refresh, selection changes, edit and normal save flows.
- Save through the **existing row SAVE action**, together with the existing row data. Validate errors without silently discarding other fields.
- Verify the existing SQL columns, data types, nullability, and app save/read paths before editing. **No new SQL column or migration is requested.**
- Preserve PressProductionID identity, ShiftMasterID, EDIT FITTING, RELEASE MOULD, history, concurrency and legacy-NULL-Shift safeguards.
- Do not copy parent Lot times or Shift boundary times into empty Press Start/End fields.

### 2.2 Existing fields remain unchanged

**Keep exactly the current operator workflow and behavior** for:

`Dispatch`, `Counter`, `Curing`, `Setup`, `ChgOver`, `Idle`, `Cleaning`, `Breakdown`, `SMDT`, `LOG CAL`, `SAVE`, `EDIT FITTING`, and `RELEASE MOULD`.

No additional downtime-entry form, no replacement manual-summary workflow, and no change to existing LOGGER save/import semantics are requested. Preserve the current meaning/behavior of SMDT; do not redefine it during this work.

### 2.3 Lot and Shift times remain available for their own purposes

Production Lot Start/End and configured Shift definitions **remain unchanged** in the system. They can still serve their existing production-day, Shift identification and applicable validation purposes. They must **not be substituted as the actual Press Start/End for PRINT OEE**.

Any time-boundary validation must respect the existing distinction between the **production-day cutoff** and configured **Shift boundaries**, and must not invent actual machine operating times.

## 3. PRINT OEE — use actual machine times, retain OEE method

For each eligible Press/Shift assignment:

- **Actual machine interval:** saved `PressProduction.Start/End` (verify actual column names).
- **Duration:** elapsed time from that Start to End, including valid cross-midnight intervals.
- **Quantities:** existing per-Press Counter/Curing/Reject data and existing standard speed/capability sources.
- **Downtime used in calculations:** preserve the existing approved Press Production/manual downtime logic; **do not add the LOGGER detail totals again**.
- **AR / PR / QR / OEE:** keep the current approved standard formulas and rules, except that time-dependent calculations now use the Press's actual saved interval rather than substituted Lot/Shift intervals.
- **Missing or invalid Press Start/End:** show an explicit missing/invalid-time state and exclude or otherwise handle the affected result under the existing report's safe-invalid-row convention; **never silently fall back** to Lot or Shift time or invent a plausible OEE value.
- Preserve protections against negative run time, excess downtime, ambiguous repeated episodes, unknown historical Shift, and double counting.

**Important:** Before implementation, Copilot should trace the existing code and tests to identify the exact time-related inputs to AR, PR, QR, OEE and summaries. Do not make an unapproved formula rewrite or claim the Excel spreadsheet's historical numeric results must equal a different day's FittingMES data.

## 4. PRINT OEE — reproduce the Excel report structure

### Section A — Per-Press production by Shift

Show, where supported by existing data: Press (F code), Mould/Product, standard speed, Start, End, elapsed production minutes, Counter, Curing, Reject, with Shift 1 and Shift 2 side by side or otherwise visibly aligned to the original Excel layout. Show meaningful per-Shift and all-day totals without mixing machine/shift identities.

### Section B — Downtime breakdown (Thai form labels)

The original Excel report presents downtime rows in Thai under grouped sections. Populate each cell by **reading LOGGER records and summing duration for the correct Production Date + Press + Shift + mapped item**. The task is to map existing Type / Sub Type / Cause (and related machine where relevant) to the **Thai form labels**, not to create new downtime inputs.

Examples of visible Excel form sections and labels:

- **(ก) เวลาหยุดจากแผนผลิต** — e.g. `ก.1 เตรียมการผลิต`, `ก.4 หยุดเปลี่ยนผ้าตะแกรง`.
- **(ข) เวลาหยุดระหว่างผลิต** — e.g. `ข.1 ปรับตั้งเครื่องจักร`, `ข.2 เครื่องจักรหยุด < 10 นาที`.
- **(ค) เวลาหยุดซ่อมเครื่อง** — e.g. `ค.1 เครื่องจักรเสียตั้งแต่ 10 นาทีขึ้นไป` and other relevant Thai form rows.
- **(ง) Breakdown details** — where the original form includes individual stop records, display existing LOGGER details such as machine, cause, time/duration, and relevant note.

The labels and section membership above describe the Excel presentation; **do not infer a definitive mapping solely from similar names**. Confirm actual mapping from authoritative LOGGER master definitions and code before implementation. The user has indicated the relevant information is already captured in LOGGER. Use existing Type/Sub Type/Cause and mapping IDs rather than fragile display-text guessing.

**No matching LOGGER record:** show blank/dash in that Press/Shift/item cell, as in Excel. Do not invent values or display zero in every unused detail cell.

**Critical separation:** LOGGER-derived itemized tables are for report detail; the existing saved Press Production downtime summaries remain the OEE calculation inputs unless the existing approved logic already explicitly specifies otherwise. Do not sum the two sources together.

### Section C — OEE calculation summary

Reproduce the original Excel-style rows for each F machine and Shift, with totals, including the available concepts:

- เวลาที่ทำการผลิต (actual machine production interval)
- เวลาที่ต้องสูญเสีย / เวลาที่ได้ผลผลิต, using existing approved logic
- Plan Stop / Breakdown Loss / Idle or other existing loss classifications
- Availability Rate (**AR**)
- Performance Rate (**PR**)
- Quality Rate (**QR**)
- Overall Equipment Effectiveness (**OEE**)

Keep the **existing standard OEE formulas**, precision conventions, exclusion rules, and valid total/aggregation policy. Thai names are presentation labels, not authorization to alter calculation semantics.

### Section D — Printing

Maintain a usable on-screen report and **PRINT / SAVE PDF** layout. The table must remain readable with multiple Presses, both Shifts, and long Thai labels; avoid clipping and misaligned total columns. Visually inspect actual browser output and print/PDF where possible; passing template tests alone does not prove layout fidelity.

## 5. Non-goals / explicit constraints

- **No OEE formula redesign.**
- **No database schema migration** unless inspection disproves the existing-column assumption and the user separately approves a proposal.
- **No changes** to the current Setup, ChgOver, Idle, Cleaning, Breakdown, SMDT, LOG CAL or SAVE workflows beyond integrating Start/End with the existing row save.
- **No LOGGER master-data editing**, remapping or mutation; preserve bidirectional Cause ↔ Sub/Related M/C and normalized machine identity.
- **No double counting** of LOGGER and Press Production manual downtime.
- **No guessing** unknown legacy Shift, ambiguous repeated Press/Shift episodes or missing times.
- **No direct SB23 writes**, test Lots, historical updates, migrations, Git commit or push without explicit separate authorization.
- Preserve previously completed Step 8C/Step 9 behaviors and tests.

## 6. Verification and acceptance criteria

1. Press Production shows editable Start/End in every applicable per-Press/Shift row, with existing values loaded.
2. Saving F7 Shift 1 does not overwrite F7 Shift 2 or any other Press; assignment identity and existing downtime/quantities are preserved.
3. Cross-midnight entry (e.g. `19:00`–`04:30`) yields correct elapsed duration.
4. PRINT OEE uses the saved **per-Press** interval even when another Press in the same Lot starts/ends at different times.
5. Missing Press times **never** trigger a hidden Production Lot or Shift-time fallback.
6. Existing AR/PR/QR/OEE formulas and source categories remain unchanged, except for corrected machine-time input.
7. LOGGER breakdown cells show the right Thai row, Press, Shift and summed duration; absent records display blank/dash.
8. No LOGGER/manual downtime double counting, and no ambiguous episode attribution.
9. Shift totals and all-day totals remain structurally and numerically consistent with eligible per-Press rows.
10. Existing RELEASE/EDIT, legacy Shift safeguards, and current Step 9 regressions pass.
11. Actual browser and PDF layout visually match the approved Excel-style structure closely enough for operators to use.

## 7. Implementation sequence for Copilot

**Stage 1 — Read-only code/schema inspection and mapping audit.** Read applicable skills and the latest handover. Locate the existing PressProduction Start/End SQL columns, old/current UI save handlers, current PRINT OEE time-source fallback, and LOGGER master mappings. Report any mismatch; do not modify SB23.

**Stage 2 — Restore Start/End entry.** Reuse existing columns, implement 24-hour input/load/save and focused tests; preserve all other fields.

**Stage 3 — Correct PRINT OEE time source.** Use per-assignment Press Start/End, remove Lot/Shift substitution, retain current formulas and exclusions, and test multiple Presses/Shifts and overnight periods.

**Stage 4 — Excel-style PRINT OEE presentation.** Add per-Press time/production table, LOGGER-derived Thai breakdown, and existing OEE results. Confirm authoritative category mapping before binding individual rows.

**Stage 5 — Regression and visual verification.** Run focused and full suites, verify browser/print/PDF, and report changes and any unresolved mapping/data cases. Commit/push only when explicitly requested.

## 8. Source of business clarification

Confirmed in the 2026-10-09 discussion and screenshots:

- Excel historically recorded **Start/Stop for each F machine per Shift**.
- Those input fields were removed from the Production UI but the user says their **SQL columns remain**.
- Current FittingMES used Production Lot times and Shift boundaries as a temporary replacement; **this substitution is to be discontinued for Press OEE**.
- Other Production downtime entry fields and LOGGER recording already exist and **must remain as they are**.
- The requested change is principally **restore actual Press times + format PRINT OEE like the Excel form**, with **standard OEE calculations unchanged**.

**End of revised requirement.**
