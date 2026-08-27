# Review: Stage+Role Instruction Changes (2026-08-08)

Status: Review findings, uncommitted changeset under review
Reviewer: coder profile, at Tez's request
Subject: [Stage+Role Instruction Templates for P1, P3, P4, P5](completed/stage-role-instructions-all-phases.md)
plus the uncommitted working tree that implements it (contracts, harness,
instruction templates, Web UI).

Scope of this review: whether the changes are implemented scientifically
(right job per role per stage per mode, authority model intact) and whether
they work functionally in the UI. Every finding was verified against code
or by live probe; suite states are reported from actual runs.

Verification baseline (this tree, 2026-08-08):

- Backend: 666 passed (`.venv/bin/python -m pytest tests/`).
- Spec gate: `architecture/tools/validate_package.py` exits 0.
- Frontend: `npm run build` clean; vitest 117/117.
- Live UI probe against the pilot project (dev backend on :8765 restarted
  to load the uncommitted contracts; vite on :5173).

## Verdict summary

The mode-level redesign (two gated modes for P3/P4, new optional P2 inputs)
is scientifically sound and works end-to-end in the UI. However, the plan's
core deliverable is absent, one change silently discards user-authored
instructions, and one new component rewrites agent outputs before validation
in ways that violate the publication authority model. Three P0 issues.

## P0-1: The 15 stage+role templates do not exist; every P1/P3/P4/P5 role gets the wrong job

**STATUS (2026-08-08, later pass): RESOLVED.** The 15 files were created by
the coder profile exactly per the plan (directives from sections 5-8, output
names from the contract `writes` lists, header block byte-identical to the P2
reference). The plan's section 10 verification now passes 21/21, rendering is
correct with and without the optional brief fields, and the P3 roles receive
three distinct directives (audit for the analyst, development for the
theorist, integration for the lead).

Original finding:

The plan's deliverable (sections 5-8: 15 files `<stage_id>.<role>.md` under
`resources/instructions/`) was not created. `resources/instructions/` holds
only the mode-level files and the P2 stage+role set. Running the plan's own
section 10 verification: 21 of 21 (mode, role, stage) cases fall back to the
mode-level template.

This is not a neutral fallback. The mode-level text assigns each role a job
that belongs to a different role:

- P3 stage 2 (`p3.analyst`, role data_analyst) receives "Develop the
  theoretical foundations ... prove or disprove the central claims"
  (`resources/instructions/P3/theory_establishment.md:6-16`), which is the
  theorist's stage-1 job. The plan's directive (section 6.3) is an empirical
  audit: identifiability, operational meaning, testability.
- P4 stage 2 (`p4.theorist`, role theorist) receives "Design and execute
  empirical studies ... Implement the method and the baseline"
  (`resources/instructions/P4/preliminary.md:6-16`), which is the analyst's
  stage-1 job. The plan's directive (section 7.3) is a mathematical-fidelity
  audit after the fact.
- P5 `p5.parallel_reviews`, role outside_reviewer, receives "Revise the
  manuscript based on the review feedback"
  (`resources/instructions/P5/review_revision.md:6-12`), which is the
  revision lead's job, and it contradicts the packet-isolated referee role
  the plan specifies (section 8.2).
- P1's three parallel discovery roles all receive the same landscape-wide
  survey text (`resources/instructions/P1/literature_update.md`), with no
  angle split and no isolation rule.

Only P2 behaves per the plan, because its stage+role files exist.

Fix direction: write the 15 files exactly as the plan specifies; the loader
and coordinator wiring already resolve them.

## P0-2: User-authored custom instructions are silently discarded at execution

Chain of evidence:

1. `run_coordinator.py:488-520` populates `role_instructions` for every
   (stage, role) pair in the plan. The existence check calls
   `_resolve_template_name`, but that function implements the full fallback
   chain (`default_instructions.py:66-102`) and therefore returns the
   mode-level template whenever no stage+role file exists. Every mode has a
   mode-level template, so the check never raises `FileNotFoundError`.
   Verified by probe: every (mode, stage, role) combination in all five
   phase contracts resolves.
2. `role_execution.py:668-676` computes
   `effective_instruction = role_instruction or self.context.phase_instruction`.
   Since `role_instruction` is always populated, the user's sealed
   `.instructions` choice (`context.phase_instruction`) never reaches the
   task brief.

The UI still invites custom instructions (textarea, draft persistence,
"Leave empty to use the default instruction"), so a researcher who writes
specific directives believes they are used; they are not. The placeholder
replacement in `service.py:2252-2279` (`_apply_default_instruction`) already
handles the empty case upstream, so the coordinator override is redundant
for defaults and destructive for custom text. No test covers the custom
path (`tests/test_run_coordinator_e2e.py` only renamed the mode).

Fix direction: populate `role_instructions` only for files that actually
exist at chain levels 1-3 (test file existence, not the resolver), or only
when the user's instruction is empty/placeholder. Add a test asserting a
custom `.instructions` value reaches the task brief.

## P0-3: `_auto_fill_timestamps` silently rewrites agent outputs before validation and publication

`role_execution.py:50-390` adds a post-processor that runs on SUCCEEDED role
executions immediately before `validate_role_outputs`
(`role_execution.py:823-830`). Despite its name it mutates far more than
timestamps, with no audit trail:

- Fabricates the literal string `"No specific check required."` into any
  required array-of-strings field with `minItems >= 1` that the agent left
  empty (`_schema_info`, `role_execution.py:380-399`). Affected schemas:
  `handoff.schema.json` (`completed_work`, `required_checks`) and
  `literature-source.schema.json` (`authors`). Consequences: a literature
  source missing its author list enters the formal library with a fake
  author string; a theory handoff missing its check list tells the auditing
  data analyst there is nothing to check, corrupting the P3/P4 audit chain.
- Fabricates method lineage `change_source`, with a hardcoded fallback
  `run_id` of `"run.p2.p2-full-catalog"` when none is passed.
- Remaps attention severity by guesswork (`major` to `reassessment_required`,
  `high` to `blocking`, and so on) and truncates scientific text fields at
  2000 characters (headline at 240).
- Strips fields and restructures `mathematical_definition` against a
  hardcoded field model embedded in code, duplicating schema knowledge that
  will drift from the schemas.

The formal record that validation passes and publication commits is
therefore not the artifact the agent produced. This contradicts the
authority model (publication only through validated, unconflicted
submissions) and the WP-E1 doctrine of raw evidence before judgment. The
WP-E1 output-validation path (trusted-local lane) has no equivalent
mutation, so the two execution lanes now apply different scientific
standards to outputs.

Fix direction: keep only mechanical, disclosed repairs (timestamps,
`schema_version`) and record every repair in the validation report; never
fabricate semantic content (authors, checks, lineage, severity); fail
validation with a precise error for the rest. Rename the function to
describe what it does.

## P1-1: Contract changes exceed the plan's stated scope without a decision record

The plan header states "No contract, schema, or code changes are required"
and section 11 puts contract changes out of scope. The tree delivers, per
`git diff` of `architecture/contracts/`:

- P3 mode renamed `p3.theory_update` to `p3.theory_establishment`, plus a
  new gated mode `p3.theory_revision` and a new `p3.prior_theory` input
  (`presence: required_in_modes`).
- P4 `p4.comprehensive` gated on a prior preliminary record, plus new
  `p4.prior_implementation` and `p4.prior_evidence` inputs.
- P2 gains three optional method-scoped inputs (`p2.theory_result`,
  `p2.empirical_result`, `p2.manuscript_result`).

The project rule is that contract changes require an ADR and scenario
updates before code depends on them; neither exists. The changes themselves
are scientifically sound (the establishment-then-revision gating mirrors
the intended lifecycle and the live gate works; see Positive findings), but
the decision trail is missing and the plan document was not updated to
reflect the expanded scope. Stale references to `p3.theory_update` remain
in `role and files/by-role.md` (lines 60, 130, 194) and
`role and files/by-phase.md` (line 137).

Sub-findings:

- Slot redundancy: in revision runs, `p3.current_theory`
  (`required_on_rerun`) and `p3.prior_theory` (`required_in_modes`) both
  resolve to the same current theory_record, and stage 1 reads both. It
  works, but two overlapping slots for one record will confuse role briefs;
  pick one mechanism.
- Duplicate finding codes: a live phase-view probe of `p3.theory_revision`
  without a prior theory returns
  `finding_codes: ['input.required_current_record_missing',
  'input.required_current_record_missing']` for two different missing
  inputs. Codes should identify the input they refer to.

## P2-1: `P2.json` was reformatted wholesale

`architecture/contracts/phases/P2.json` shows a 527-to-549-line whole-file
indentation rewrite with the real change (three new inputs) buried inside.
This defeats review and blame, against the project's compact-change
convention. Reformat separately from semantic edits, or not at all.

## P2-2: `default_instructions.py` module docstring documents the wrong chain

The docstring (lines 1-24) describes a 4-level chain
(`mode.role / mode / default.role / default`) without the two stage levels
the code implements (6 levels). Users editing templates per the docstring
will place files that never resolve.

## P2-3: Silent failure in the coordinator's instruction resolution

`run_coordinator.py:519-520` wraps the whole resolution block in
`except Exception: pass`. Any defect (brief row shape, template syntax
error at render time, encoding issue) silently drops all stage+role
instructions with no log, and the run proceeds with the phase-level
instruction. At minimum log the exception.

## P2-4: UI loses per-option context selection granularity

`GroupedContextCards.tsx:44-49` toggles every non-required, non-disabled
option in a group together. The literature group carries three records
(library, synthesis, coverage), so a researcher can no longer deselect one
record while keeping the others, although `resolve_run_inputs` and the
sealed-basis fix support per-option omission. Mixed-selection groups also
render as unchecked with no indeterminate state
(`contextCardState.ts:71`, `allSelected`). The previous per-option checkbox
list allowed full granularity; this is a functional regression traded for a
cleaner layout. Consider per-record checkboxes inside the "more" modal.

Smaller UI notes:

- `GroupFeedbackModal.tsx:66` uses a raw `fetch` instead of the API client;
  failures surface as bare "Could not load: HTTP 404" with no `ApiError`
  handling.
- `buildGroups` (`GroupedContextCards.tsx:164`) drops the `brief` group
  entirely, so the sealed project brief no longer appears as run context in
  the form (previously a visible locked entry). Confirm this is intended.
- The browser-tool radio/label clicks initially appeared broken; retesting
  showed a viewport artifact of the tool, not a UI defect. Method selection
  survives mode switches correctly.

## Open design question (not a defect)

The P1 discovery isolation rule and the P5 outside-reviewer packet
isolation exist only as prose in the (currently missing) instruction
templates. Nothing in the harness prevents parallel roles in one stage from
reading each other's same-stage run-local outputs. If isolation is
scientifically load-bearing, it needs a reads-scoping mechanism in the
contract or harness, not only instruction text.

## Round 2 audit (2026-08-08, second pass)

Second-pass audit over the remaining uncommitted diffs (view models,
repository views, bootstrap, executors, spec gate, examples, docs, and the
frontend), plus live UI probes of every phase page. Ordered by severity.

### P1-2: P2 focused_method mode receives full-catalog stage directives

The resolution chain puts stage+role templates (level 1) above mode
templates (level 4), and P2's existing stage+role templates are written in
full-catalog language: "propose the single method you believe is most
promising" and "the catalog should contain your method alongside methods
proposed from other perspectives"
(`resources/instructions/P2/p2.independent_proposals.theorist.md`). The
`p2.focused_method` contract purpose is the opposite: "Reassess or revise
exactly one existing stable method without changing another method." The
mode template says so, but it is shadowed. Result: in focused mode every
role is instructed to act outside the authorized scope. The chain also has
a design gap: stage+role text cannot vary by mode (no mode variable is
injected, and level 3 mode+role never wins over level 1). Fix options:
rewrite the P2 stage+role templates in mode-agnostic authorized-scope
language (content-only), or extend the loader with a
`<mode>.<stage_id>.<role>.md` level above the current level 1.

### P1-3: Brief-embedded schema examples carry concrete example identities

`task_briefs.py:_load_schema_example` embeds up to 1500 characters of
`architecture/examples/*.example.json` verbatim into agent task briefs with
the instruction "fill with real values, preserve structure". The examples
carry concrete identities: `method.example.json` has stable_id
`method.overlap_stabilized_score`; `handoff.example.json` has run_id
`run.p4.preliminary.20260801t140000z`. Agents copy example identities into
real outputs; the hardcoded `run.p2.p2-full-catalog` fallback inside
`_auto_fill_timestamps` is direct evidence this has already happened (the
post-processor was written to repair copied example values). Fix:
neutralize identity-bearing fields in the embedded template (replace
ids, run ids, timestamps, and digests with `<...>` placeholders) while
keeping the structure, or embed a structure-only skeleton.

### P2-5: `_fixture_summary` in the fake executor is dead code

`executors/fake.py` matches uppercase phase ids (`"P1" in run_id`) against
lowercase run ids (`run.p1.literature-update-<hex>`, from
`service._run_id`) and lowercase stage ids. Verified by probe: it returns
None for every real run-id shape, so the phase-appropriate dev summaries it
was added for never reach any output. Fix: match on the lowercase prefix
(`run.p1.`) or normalize case.

### P2-6: The full validation report is no longer reachable from the run page

`web/src/pages/RunPage.tsx` lost the "Open validation report" link (the
`validation_report.href` anchor was deleted in the restyle). Only the
status pill and summary remain. For an audit-first system the researcher
must be able to open the full report. Restore the link or relocate it.

### P2-7: Orphaned frontend code after the redesign

`ProjectBriefPanel.tsx` and its test are unused after the overview
redesign (the brief moved into a collapsible section on the overview).
`ScientificStatusGrid` has no remaining page usage. Project convention is
to delete retired code fully, including its tests.

### P2-8: Unavailable context groups render "0 B"

`GroupedContextCards.tsx` sums missing `size_bytes` to 0 and renders
`formatSize(0)` as "0 B" on unavailable cards. A group with no records
should show no size. Cosmetic but misleading.

### P2-9: Hardcoded "No current record for this method." reason

`view_models.py` emits that `disabled_reason` for every missing optional
record, including non-method-scoped contexts (for example a first P1 run,
where the absent library/synthesis/coverage have nothing to do with a
method). Use a record-type-appropriate message.

### P2-10: The two execution lanes apply different output standards

`bootstrap.py` now wires `local_hermes` into the formal harness lane, where
`_auto_fill_timestamps` mutates outputs before validation
(`role_execution.py`). The trusted-local supervised lane (WP-E1
`validate_run_outputs`) validates raw bytes and never mutates. The same
scientific content can therefore pass in one lane and fail in the other.
After P0-3 is resolved, converge the lanes on one declared output policy.

### P3-1: No regression test guards the instruction template inventory

P0-1 shipped because nothing asserts that stage+role templates exist. Add
a pytest that runs the plan's section 10 verification (all 21 resolution
cases plus rendering with and without the optional brief fields) so a
deleted or renamed template fails the suite.

### P3-2: Dead fallback branch in role_execution

`role_execution.py` falls back to `role_instructions.get(role)`, but the
coordinator only ever populates `{stage_id}.{role}` keys. Harmless; remove
or document.

### P3-3: Role matrix documentation is out of sync with the contracts

`role and files/by-role.md` and `by-phase.md` still cite `p3.theory_update`
and do not describe the new modes, gates, or inputs (the P3 revision mode,
the P4 comprehensive gate, the new P2 optional inputs). These pages
describe themselves as the role-centered inverse of the contracts; they
should be regenerated from the current contracts.

### Round 2 positive verifications

- Live UI: project overview (phase chips, method table, open questions,
  active runs) renders; P2 full_catalog hides the three optional slots and
  focused_method shows them as unavailable cards with the method picker;
  P4 comprehensive mode gates on both new inputs with precise messages
  ("Required current implementation_record is unavailable. Required current
  empirical_synthesis is unavailable."); P5 defaults to Assembly on fresh
  load and renders its in-form method selector.
- The spec-gate change is a legitimate coverage bump (8 to 9 modes) and
  the test-suite edits are clean rename-and-extend updates.
- `view_models` lookup guard (method-scoped match with no selected method
  returns None) is present and correct.
- Example and doc diffs are mode renames, link repairs for the moved
  plans, and formatting; `04-ui-contract.md` has no ContextOption spec, so
  the new card fields create no doc drift there.

## Positive findings (verified)

- Mode gating works end-to-end in the live UI: on the P3 page, "Revise
  theory" without a prior theory record disables start with the researcher
  message "Required current theory_record is unavailable."; "Establish
  theory" is startable and shows the correct consequence text.
- The loader's 6-level resolution chain matches the plan, and the plan's
  naming rules check out against the contracts: P5 stage ids are the
  contract stage ids (`p5.assembly_lead`, `p5.parallel_reviews`,
  `p5.revision_lead`), and role names come from stage `roles` arrays
  (P3 stage 2 and P4 stage 1 use `data_analyst` under stage ids named
  `*.analyst`).
- The deselected-optional-input sealed-basis fix
  (`run_coordinator.py:651-680`, `commands.py` disabled-entry skip) is
  correct and covered by new tests
  (`test_sealed_basis.py`, `test_input_resolution.py`): a deselected
  optional input is no longer treated as basis drift, while a missing
  required input still rejects.
- P1 page renders the new tiered layout correctly: compact status card,
  grouped context card with three literature records locked on, and the
  "more" modal showing per-record summaries with full-record links.
- The new mode-level templates for P3/P4/P5 are scientifically sound as
  shared fallbacks; the defect is only that they are served as per-role
  directives (P0-1).
- Suites green as listed in the verification baseline; the specification
  package is internally consistent (phases.json byte-match, traceability,
  examples) despite the contract edits.
