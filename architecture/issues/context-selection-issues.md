# Context Selection UI Issues

Status: Open audit findings, 2026-08-07. Revision 1 (2026-08-07, coder
validation pass): every finding independently verified against the code;
P0-4 re-graded; test-count correction.

Identified during a cross-phase audit of context card behavior. Findings combine
live browser inspection of all five phase pages (P1-P5) with four parallel
code-level and pixel-level audits covering: frontend logic, color/theme
rendering, shared utility correctness, and backend contract markings.

All 665 backend tests pass (revision 1 correction: the audit said 661, which
predates the four regression tests added with the required_in_modes semantics
fix). The issues are at the contract/UI layer, not the data pipeline.

## Revision 1 changelog (validation pass)

- **V1 (blocking correction): P0-4 re-graded Critical -> Minor (defensive
  hardening only).** The claimed state cannot arise: the only producer of
  `disabled: true` options (view_models.py, missing-optional branch) sets
  `selected_by_default: False`, so RunForm's initial selection never contains
  a disabled option. And even if a disabled option id were submitted,
  `resolve_run_inputs` (harness/inputs.py:160-173) silently drops non-required
  inputs whose record is None. No user-visible or data-integrity impact.
  The suggested guard remains worthwhile as cheap insurance.
- **V2: P0-2 is a pre-existing contract defect, not introduced by the
  context-selection work.** Independently confirmed: the P5 contract's
  condition text ("optional in assembly mode") and the `p5.assembly_lead`
  stage's declared `reads: [p5.current_manuscript]` both contradict
  `presence: required_in_modes: [p5.review_revision]`. The schema forbids the
  `required_in_modes` key on any other presence value, so there is currently
  no schema-legal way to express "required in one mode, optional in another."
  Contract-author decision required (Tez); a schema change needs an ADR.
- **V3: P0-1, P0-3, P1-1, P1-2, P2-1, P2-2, P2-3 all reproduced at
  file:line level.** Verdicts annotated per issue below.
- **V4: P1-3 is the deliberately implemented behavior** (lookup guard in
  repository_views.current_record + `_HIDDEN_BY_MODE` in view_models.py),
  introduced with the required_in_modes semantics fix. The open product
  decision (hide vs dim) rests with Tez; see the annotation.

---

## Priority levels

- **P0 - Critical**: wrong behavior the user can see or that affects data
  integrity.
- **P1 - Moderate**: inconsistency or degraded experience.
- **P2 - Minor**: cosmetic or code-quality issue.

---

## P0-1: P5 review-revision mode locks an optional item

**Phase**: P5 (Manuscript), review-revision mode

The optional review-issue-ledger shares a card group with the required
current-manuscript. Because the group-lock rule says "any required item in a
group locks the entire group," the optional ledger is permanently locked. The
user cannot uncheck it.

This is the only phase where an optional item is wrongly locked. Every other
optional input across P2/P3/P4/P5 sits in a required-free group and behaves
correctly.

**Fix direction**: either split the ledger into its own single-item group, or
change the group-lock logic to lock only the required items within a mixed
group (requires per-option checkbox UI instead of per-group).

**Validation (Rev 1): CONFIRMED.** `deriveCardState` (contextCardState.ts)
locks the whole group when any member is required; the manuscript group in
review_revision mixes the required `p5.current_manuscript` with the optional
`p5.review_issue_ledger`. The ledger also cannot be deselected via the
backend view, which marks it `selected_by_default: true`; the group toggle is
the only deselection path and it is locked. Recommended of the two fix
directions: lock only the required items within a mixed group (per-option
checkbox in the group modal), because splitting the group hides the
manuscript/ledger relationship.

---

## P0-2: P5 assembly mode makes the prior manuscript invisible

**Phase**: P5 (Manuscript), assembly mode

The phase contract marks `p5.current_manuscript` as
`required_in_modes: [p5.review_revision]`. In assembly mode this means the
manuscript is excluded entirely - no card, no dimmed placeholder, nothing.

The contract's own condition text contradicts this: "Required in review-revision
mode **and optional in assembly mode**." The `p5.assembly_lead` role stage also
declares `p5.current_manuscript` in its `reads` list.

The system's presence model has no value that expresses "required in one mode,
optional in another." This needs a contract-author decision: either assembly
genuinely shouldn't consume the prior manuscript (fix the condition text and
stage reads), or the presence model needs a new value (e.g.
`required_in_modes` + `optional_in_modes`).

**Validation (Rev 1): CONFIRMED, and it predates the context-selection
feature.** Verified against `architecture/contracts/phases/P5.json`: the
condition text reads "Required in review-revision mode and optional in
assembly mode", and `p5.assembly_lead` declares
`reads: [p5.current_manuscript]` - a read the prepared basis can never
satisfy in assembly mode because the input is filtered out entirely. Note
that the execution layer tolerates this silently (the stage read is
advisory), so nothing crashes; the contract is simply internally
inconsistent. A new presence value is a schema change and requires an ADR
plus validator range updates before code may rely on it.

---

## P0-3: Required checkbox checkmarks are nearly invisible

**Phases**: All

When a checkbox is `disabled` (as required-locked checkboxes are), browsers
ignore the CSS `accent-color` property. The checkmark renders at ~1.6:1 contrast
- well below the 4.5:1 WCAG minimum. The most important state ("this is required
and included") is the hardest to see on the page.

Affects every required context card on every phase.

**Fix direction**: since `accent-color` cannot style disabled checkboxes, use a
custom checkbox visual (e.g. a styled label or icon overlay) that doesn't rely
on the native disabled-checkbox rendering.

**Validation (Rev 1): CONFIRMED mechanism; exact contrast ratio not
re-measured.** styles.css:946-950
(`.context-card__check input:disabled { accent-color: var(--accent); opacity: 0.5; }`)
carries a comment claiming "visible accent, not dimmed", but
`accent-color` is indeed ignored on disabled native checkboxes in current
Chrome/Firefox and the extra `opacity: 0.5` dims the whole control further.
The precise 1.6:1 figure was not independently reproduced, but the failure
mechanism is real and the fix direction is correct.

---

## P2-4: Disabled options can be silently submitted (re-graded from P0-4)

**Phases**: All (in `RunForm.tsx` initial selection)

When the page loads, the system pre-selects options based on
`required || selected_by_default`. If an option is both `disabled` (missing
record) and `selected_by_default: true`, it enters the selection set. The card
renders as unavailable/unchecked, but the option ID is still sent in
`selected_context_option_ids` on submit.

The user sees "nothing selected" but the system includes it. The user cannot
remove it because the checkbox is disabled.

**Fix direction**: exclude `disabled` options from the initial selection set
in `RunForm.tsx` (around line 136-145).

**Validation (Rev 1): NOT REPRODUCIBLE as stated - re-graded to Minor
(defensive hardening).** Two independent layers prevent the claimed outcome:
(1) the only code that emits `disabled: true` options
(`view_models.py`, missing-optional branch) always sets
`selected_by_default: False`, so the initial selection never contains a
disabled option; (2) even if such an id were submitted,
`resolve_run_inputs` (harness/inputs.py:160-173) drops non-required inputs
whose record is absent (`record is None` → skipped), so nothing is silently
bound into the prepared basis. The frontend guard is still worth adding as
cheap insurance against future backend changes. Note: hidden *required*
inputs (e.g. the literature library) ARE submitted without a visible card -
that is deliberate (they are auto-sealed context), not this bug.

---

## P1-1: Missing-record cards fail accessibility contrast

**Phases**: All

Cards for missing records are dimmed to 40% opacity. The title text drops to
2.5:1 contrast (light theme) and 3.4:1 (dark theme) - both fail WCAG 1.4.3. The
description text is effectively unreadable at 1.3-1.4:1.

There is also no textual or icon cue for why the card is unavailable. The
`disabled_reason` text exists in the data but is only shown in the run-history
list, never on the cards themselves.

**Fix direction**: avoid card-level `opacity` in favor of targeted muted colors
that keep text ≥4.5:1. Surface the `disabled_reason` text on unavailable cards.

**Validation (Rev 1): CONFIRMED.** styles.css:913-916
(`.context-card--unavailable { opacity: 0.4; }`). Contrast ratios not
re-measured, but 0.4 opacity over both themes cannot reach 4.5:1 for body
text, and `GroupedContextCards` renders the contract `purpose` as the
description, never the backend-supplied `disabled_reason`
("No current record for this method.").

---

## P1-2: Partially-selected groups show as fully unchecked

**Phases**: All card groups with 2+ optional items

If a card group has 2 optional items and only 1 is checked, the group checkbox
shows as fully unchecked (not indeterminate). Clicking it then selects all,
which may not be what the user intended.

**Fix direction**: set the checkbox `indeterminate` property when the group is
partially selected. Note: `indeterminate` is a DOM property, not an HTML
attribute - needs a `ref` or `useEffect`.

**Validation (Rev 1): CONFIRMED.** `deriveCardState` maps partial selection
to `checked: false`; no indeterminate handling exists in GroupedContextCards.

---

## P1-3: P2 full-catalog mode hides optional cards entirely

**Phase**: P2, full-catalog mode

In full-catalog mode, the optional theory/empirical/manuscript result cards
don't appear at all - not even as dimmed placeholders. Switching to focused-
method mode suddenly reveals 3 new cards. This is intentional (no method to
match against), but the inconsistency between modes is jarring.

**Decision needed**: is this acceptable, or should the cards always show (dimmed)
even in full-catalog mode?

**Validation (Rev 1): CONFIRMED as behavior; it is deliberate.** The hiding
comes from `_HIDDEN_BY_MODE[("P2", "p2.full_catalog")]` plus the lookup guard
(a method-scoped match with no selected method resolves nothing), both added
with the required_in_modes semantics fix. Rationale: in full-catalog mode
there is no method to match, so the slots can only ever be empty; showing
three permanently-dimmed "No current record for this method." cards would
misstate the reason (records may well exist - just not addressable without a
method). Alternatives if the mode switch feels jarring: (a) keep hiding
(status quo), (b) show dimmed cards with an accurate reason ("Select the
focused-method scope to attach method-bound results"), or (c) collapse them
into a single informational line. Decision rests with Tez.

---

## P2-1: Undefined CSS variable `var(--bg)`

**Location**: `web/src/styles.css` lines ~1019 and ~1122

Two CSS rules reference `var(--bg)` which does not exist in either theme's
variable definitions. The size badge and feedback highlight backgrounds silently
fall back to transparent.

**Fix**: replace `var(--bg)` with `var(--surface-soft)` (or whichever theme
variable is intended).

**Validation (Rev 1): CONFIRMED.** `--bg` is defined in neither `:root`
block; both references silently fall back to transparent.

---

## P2-2: `toggleGroup` duplicates lock logic

**Location**: `web/src/components/GroupedContextCards.tsx`

The `toggleGroup` function re-implements the lock check (`opt.required ||
opt.disabled`) inline instead of deriving it from the shared
`contextCardState.ts` utility. Not a user-visible bug, but future changes to
lock logic would need to be made in two places.

**Validation (Rev 1): CONFIRMED.** GroupedContextCards.tsx `toggleGroup`
checks `opt.required || opt.disabled` inline while `deriveCardState` encodes
the same rule.

---

## P2-3: Card descriptions inconsistent within the same row

**Phases**: All

Some cards show a record count ("2 records", "3 records") while others show a
descriptive sentence ("Expose the current theory conclusion, scope, and
assumptions."). The two styles are mixed in the same row.

**Validation (Rev 1): CONFIRMED.** `buildGroups`/`GroupCard` render
"N records" for multi-option groups and the single option's description
otherwise, so mixed rows are the norm.

---

## Summary table

| ID | Priority | Phase | One-liner | Rev 1 verdict |
|----|----------|-------|-----------|----------------|
| P0-1 | Critical | P5 rev-rev | Optional ledger permanently locked | Confirmed |
| P0-2 | Critical | P5 assembly | Prior manuscript slot completely invisible | Confirmed; pre-existing contract defect; needs Tez decision (+ADR if schema changes) |
| P0-3 | Critical | All | Required checkbox checkmarks invisible (1.6:1) | Mechanism confirmed; ratio not re-measured |
| P2-4 | Minor (was P0-4) | All | Disabled options silently included in submission | Not reproducible; defensive guard still recommended |
| P1-1 | Moderate | All | Missing cards fail WCAG contrast (2.5:1) | Confirmed (opacity 0.4; reason not surfaced) |
| P1-2 | Moderate | All | Partial groups show unchecked, not indeterminate | Confirmed |
| P1-3 | Moderate | P2 | Full-catalog hides optional cards vs focused shows them | Confirmed deliberate; product decision for Tez |
| P2-1 | Minor | All | Undefined `var(--bg)` in two CSS rules | Confirmed |
| P2-2 | Minor | All | `toggleGroup` duplicates lock logic | Confirmed |
| P2-3 | Minor | All | Mixed card description styles in same row | Confirmed |
