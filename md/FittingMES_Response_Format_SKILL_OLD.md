---
description: Enforce copy-friendly Markdown blockquote responses for
  FittingMES Copilot work and keep work in DESIGN/REVIEW mode until the
  user explicitly approves implementation.
name: fittingmes-response-format
---

# FittingMES Response Format and Design/Review Guard

## Purpose

Use this skill for all FittingMES design, review, SQL-design,
LOGGER-design, database-review, and implementation-planning
conversations.

The user needs responses that can be selected and copied as ordinary
Markdown text. Do not render SQL, Python, configuration, schemas,
examples, or any other content in a code/code-copy box.

This skill also prevents accidental implementation while the user is
still reviewing a design.

## Rule 1 --- Entire final response must be one Markdown blockquote

EVERY visible line in the final response MUST begin with exactly:

This applies to absolutely everything in the final response, including:

-   headings
-   normal paragraphs
-   bullet lists
-   numbered lists
-   SQL
-   CREATE TABLE statements
-   ALTER TABLE statements
-   SELECT statements
-   Python
-   JavaScript
-   HTML
-   configuration examples
-   file paths
-   column lists
-   schemas
-   examples
-   warnings
-   conclusions

There must be no visible final-response line outside the Markdown
blockquote.

Before sending the final answer, perform a formatting check:

1.  Inspect every visible line.
2.  Confirm every visible line starts with `>`.
3.  If any line does not start with `>`, fix it before responding.

## Rule 2 --- Never create a code block in the final response

NEVER use fenced code blocks.

NEVER use triple backticks.

NEVER use indented code blocks.

NEVER indent SQL or other example code by four spaces.

NEVER use Markdown inline-code formatting with backticks.

NEVER use syntax-highlighted blocks.

NEVER create a separate code/code-copy box.

SQL is ordinary Markdown blockquote text, not code formatting.

Wrong conceptual format:

CREATE TABLE dbo.LoggerEvent ( LoggerEventID bigint )

Required final-response format:

> CREATE TABLE dbo.LoggerEvent ( LoggerEventID bigint, ProductionDate
> date NOT NULL )

The same rule applies to Python, PowerShell, JSON, HTML, configuration,
file paths, and all other technical text.

## Rule 3 --- Do not defeat the rule with escaped or encoded formatting

Do not use HTML entities, escaped spaces, encoded indentation, `<pre>`,
`<code>`, or any other technique that causes text to render as a code
block.

Do not insert four leading spaces after `>`.

Prefer simple plain text after `>`.

For example:

> ALTER TABLE dbo.LoggerEvent ADD CONSTRAINT FK_LoggerEvent_SubMachine
> FOREIGN KEY (SubMcId) REFERENCES dbo.Fitting_SubMachine(SubMcId);

## Rule 4 --- DESIGN / REVIEW mode is non-destructive

Unless the user explicitly authorizes implementation, remain in DESIGN /
REVIEW mode.

In DESIGN / REVIEW mode, do not:

-   modify application files
-   modify SQL files
-   create migrations
-   execute write SQL
-   ALTER database objects
-   CREATE database objects
-   DROP database objects
-   INSERT data
-   UPDATE data
-   DELETE data
-   MERGE data
-   change Master data
-   change `.env`
-   install packages
-   run implementation scripts
-   start implementing the proposed design
-   modify EquipmentTimeEvent
-   send PIS requests
-   implement PLC integration

Design, analyze, inspect, explain, and propose only.

Do not interpret phrases such as "continue", "check this", "review
this", "verify this", or "what next" as implementation approval.

Implementation approval must be explicit, for example:

-   implement it
-   make the changes
-   create the migration
-   run the migration
-   modify the files
-   execute the SQL

If approval is ambiguous, stay in DESIGN / REVIEW mode.

## Rule 5 --- Read-only inspection is allowed only when explicitly requested

When the user explicitly asks for read-only validation or inspection,
read-only actions may be performed.

Allowed examples:

-   SELECT queries
-   SQL metadata queries
-   reading source files
-   reading configuration
-   reading database schema
-   reading Master rows
-   inspecting relationships
-   running tests that do not modify persistent data, when explicitly
    requested

Read-only inspection does NOT authorize implementation.

After inspection, report findings and stop for approval if the user has
not authorized changes.

Do not silently repair discovered inconsistencies.

## Rule 6 --- Tool execution UI is different from the final response

Copilot/Agent may display its own tool-execution UI such as:

-   Ran
-   Search
-   Read
-   command approval cards
-   terminal command previews
-   confirmation prompts

Those UI elements are not Markdown final-response text and cannot be
converted into a Markdown blockquote by response formatting alone.

Therefore:

-   If the user requested DESIGN / REVIEW only, avoid unnecessary
    command execution entirely.
-   If read-only execution was explicitly authorized, tool/command UI
    may still appear in the agent interface.
-   The final written response after the tool work must still follow
    this skill: every line begins with `>` and no code blocks are used.

Do not execute a command merely to restate or reformat a previous
answer.

## Rule 7 --- Reformat requests mean reformat only

If the user says to repeat, reformat, rewrite, or return the previous
design using this format:

-   do not inspect the repository
-   do not connect to SQL
-   do not run commands
-   do not edit files
-   do not implement anything
-   do not perform additional validation unless explicitly requested

Only reformat the requested content.

## Rule 8 --- FittingMES LOGGER source of truth

For LOGGER design work, read and follow:

md/FittingMES_LOGGER_Design_Context.md

Treat that document as the LOGGER design source of truth unless the user
explicitly changes the design.

Do not redesign established LOGGER semantics from memory when the design
document is available.

When a new request appears to conflict with the LOGGER design document,
identify the conflict and ask/review before implementation.

## Rule 9 --- LOGGER design semantics that must not be accidentally reversed

The established LOGGER model includes these meanings:

-   McId and McInstanceNo identify the downtime-subject Main Machine.
-   RelatedMcId and RelatedMcInstanceNo identify another Main Machine
    related to the downtime.
-   SubMcId and SubMcInstanceNo identify a physical Fitting_SubMachine
    only.
-   An IsRelated = 1 Fitting_SubMachine row is a proxy used to resolve a
    Related Main Machine.
-   An IsRelated = 1 proxy is never saved as LoggerEvent.SubMcId.
-   Fitting_MainMachine.Relate controls eligibility for Related Main
    Machine use.
-   Fitting_Cause mappings are shortcuts/default mappings, not the
    LOGGER downtime subject.
-   Fitting_Cause.McId must never overwrite an already selected
    LoggerEvent.McId.
-   Cause resolution must inspect Fitting_SubMachine.IsRelated before
    deciding DIRECT_SUB, RELATED_MAIN, or RELATED_SUB.
-   Composite hierarchy such as F1 -\> LINE1 -\> Conv3 must preserve all
    three levels.
-   Multiple possible instances require operator selection unless
    exactly one valid instance exists.
-   Ambiguous Master relationships must be reported, not guessed from
    editable display text.
-   Cause Master must not be modified by the SMDT/BD duration rule.
-   Rule-based SMDT remains SMDT below 10 minutes and becomes BD at 10
    minutes or more.
-   Explicit SETUP, CHGOVER, IDLE, and CLEAN classifications bypass
    SMDT/BD conversion.

The detailed and current definition remains in
md/FittingMES_LOGGER_Design_Context.md.

## Rule 10 --- Final response self-check

Immediately before producing any final response, verify all of the
following:

-   Every visible line begins with `>`.
-   No triple backticks exist.
-   No fenced code block exists.
-   No indented code block exists.
-   No inline backticks exist.
-   SQL is plain blockquote text.
-   Technical examples are plain blockquote text.
-   No implementation occurred unless explicitly approved.
-   A reformat-only request did not trigger tools or commands.
-   LOGGER work follows md/FittingMES_LOGGER_Design_Context.md.

If any check fails, correct the response before sending it.

## Minimal response example

> ## Review Result
>
> The design is consistent with the current LOGGER contract.
>
> SQL for review only:
>
> SELECT McId, Machine, No, Relate FROM dbo.Fitting_MainMachine ORDER BY
> McId;
>
> No files or database objects were modified.
