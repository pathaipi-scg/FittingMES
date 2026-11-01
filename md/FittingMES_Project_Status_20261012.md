# FittingMES Project Status — 2026-10-12

## Git checkpoint

- Previous checkpoint commit: `254033f5ef5abce85a5d979d511506727ce173cc`
- Branch: `main`, tracking `origin/main`
- The previous checkpoint was clean. The CREATE LOT override changes described here are local and uncommitted.
- No commit, push, reset, or pull was performed for this work.

## Production CREATE LOT running-number override

The Production CREATE LOT workflow now allows an operator to override the
proposed running suffix while keeping the product prefix and date-derived
prefix server-controlled.

### Suggestion and sequence scope

- The Lot prefix is derived from the active Product Family mapping, Product
  Code, and the selected Production Plan date. It includes the product
  prefix, Buddhist year, and month.
- The database suggestion is the historical maximum `RunningNo` for the
  exact prefix and selected month, plus one. It includes active and voided
  Lot rows; it does not rely on Lots currently displayed in the page.
- Different prefixes and months have independent sequences. The Lot prefix
  and `SequenceMonth` constrain the query.
- When no matching historical Lot exists, the suggestion is `01`.
- The read-only Next Running No remains the automatic suggestion when the
  operator enters an override.

### Manual suffix and skipped/voided numbers

- Only the final two digits are editable. The suffix must contain exactly
  two ASCII digits and be from `01` through `99`.
- A suffix is allowed only when it is strictly greater than the historical
  maximum. This permits an operator to choose a higher number, but makes
  every skipped number below that maximum unavailable.
- A historical maximum of `99` exhausts the sequence. CREATE LOT is
  disabled and the page displays an exhaustion message.
- Voided Lots remain historical sequence records. Their suffixes are not
  reused, and duplicate Lot numbers are rejected even if the matching row
  is voided.

### Frontend, backend, and concurrency checks

- The Lot preview displays the read-only prefix beside the editable suffix.
  The suffix is a text input with numeric input mode and a two-character
  maximum, preserving leading zeroes.
- Inline validation checks two ASCII digits, range, and that the suffix is
  greater than the historical maximum. It disables CREATE LOT for an
  invalid suffix or exhausted sequence.
- The backend validates the suffix independently, derives and checks the
  authoritative prefix, recomputes the maximum, rejects values at or below
  that maximum, checks all persisted Lot numbers for duplicates, and
  constructs the final Lot No. server-side.
- Maximum validation and insertion are protected by the existing
  transaction-owned `FittingMES.ProductionLot` application lock. A stale
  submission is rejected; the request re-reads the suggestion and retains
  the submitted suffix for operator review.

### VOID LOT eligibility adjustment

The existing latest-only VOID rule remains in effect, but the definition
of “latest” now includes voided sequence records. The page's `CanVoid`
calculation was updated to agree with backend validation. Without this
change, voiding the highest-numbered Lot could make a lower active Lot look
eligible in the UI even though backend MAX validation correctly refuses
that VOID. The adjustment avoids offering an action that cannot succeed
and ensures a voided number remains consumed. Lower active Lots behind a
higher voided sequence remain ineligible; the Lot and its history are not
deleted or renumbered.

## Files changed

- `app/lots.py` — historical maximum, strict suffix and duplicate
  validation, and VOID eligibility aligned with historical sequence use.
- `app/main.py` — database-backed previews and string suffix form
  submission.
- `app/templates/production.html` — editable suffix, preview, inline
  validation, and exhausted-sequence state.
- `docs/production-workflow.md` — sequence and VOID behavior documented.
- `tests/test_production.py` — CREATE LOT UI, suffix, duplicate, stale,
  exhaustion, and VOID regressions.
- `tests/test_product_families.py` — MAX behavior for voided rows,
  separate products, and separate months.
- `tests/test_family_ui.cjs` — browser-side suffix validation and
  exhaustion regressions.
- `md/FittingMES_Project_Status_20261012.md` — this checkpoint document.

## Tests and verification

Isolated automated validation completed for this local code change:

- `.venv\Scripts\python.exe -m unittest tests.test_production tests.test_product_families` — 49 tests passed.
- `node tests/test_family_ui.cjs` — passed; Lot suffix validation,
  exhaustion, existing family-product interactions, and navigation
  regressions ran.
- `git diff --check` — passed during the change review. Rerun after adding
  this status document; the final post-documentation check passed.

The checks above are automated local regressions; they do not verify the
workflow against live SQL Server or by operating the actual browser.

## Pending verification and limitations

- **Actual browser verification: PENDING.** Verify the compact form,
  prefix/suffix preview, leading-zero handling, inline warning, and
  disabled CREATE LOT state in a browser without submitting a Lot.
- **Live CREATE LOT testing: PENDING.** No CREATE LOT request was submitted
  against live SB23. No live database operation or migration was performed
  for this checkpoint.
- The implementation relies on the shared transaction-owned application
  lock used by the application's Lot writers. External writers that bypass
  that convention were not exercised.
- If another CREATE LOT commits after a request has rendered its refreshed
  maximum but before that request acquires the application lock, backend
  validation still rejects a stale suffix. The rejection page may reflect
  the earlier read; refresh the page to obtain the newly committed maximum
  before confirming another suffix.
- The sequence maximum reads persisted `ProductionLot.RunningNo` values for
  the matching prefix and month. Historical rows are assumed to have
  internally consistent `LotPrefix`, `SequenceMonth`, and `RunningNo`
  values; no historical records were modified or reconciled.

## Next-session instructions

1. Confirm the branch and worktree before continuing; the implementation
   and this status document are expected to remain uncommitted unless
   separately authorized.
2. Rerun the focused Python and JavaScript regressions and
   `git diff --check` after any further edits.
3. Perform the pending browser-only verification in a suitable local/test
   environment. Do not submit CREATE LOT as part of that check.
4. Do not run CREATE LOT against live SB23, modify the database, or run a
   migration without separate explicit authorization.
5. If a controlled live CREATE LOT test is later authorized, first agree
   on the test product, date, plan, and cleanup/retention expectations;
   never assume a test Lot can be deleted or its number reused.
