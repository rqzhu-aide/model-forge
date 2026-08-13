# Review: Harness Validation and Output Recovery Plans

Status: Review findings, 2026-08-12
Reviewer: coder profile (verification against commit `53efd01`)
Scope: `harness-validation-and-output-recovery-plan.md`, `harness-validation-index.md`,
HV-0 through HV-7.

## 1. Overall verdict

The core diagnosis is real and verified in code. Execution failure and output
conformance are conflated today: a successful Hermes exit followed by any schema
finding becomes role FAILED (`role_execution.py:991-993`), stage FAILED, run
FAILED, and the UI reports "Execution failed". The all-ERROR severity model, the
repair-before-seal ordering, and the supervised empty-mode shim are all
confirmed exactly as the audit describes. The delivery order (fix data loss and
the mode defect first, recovery last) is sound and respects the governing
constraints: fail-closed publication, no hidden automation, no post-run
approval step.

The plans are implementable in direction but have nine issues that block or
distort implementation, two overstated audit claims, and four smaller gaps.
Details below. Verified facts are cited as file:line against `53efd01`.

## 2. Verified audit claims (confirmed, no action needed)

1. All 4 finding factories hardcode `ValidationSeverity.ERROR`
   (`scientific_validators.py:1299`, `submission_validation.py:413`,
   `inputs.py:104-233`, `outputs.py:133`). `WARNING`/`INFORMATION` have zero
   uses repo-wide. `passed` is `any(severity == ERROR)`
   (`domain/validation.py:52-53`).
2. Repair runs in-place before sealing on SUCCEEDED
   (`role_execution.py:976-997`); `preserve_raw_output` runs only in the FAILED
   branch and is wrapped in `except Exception: pass`
   (`role_execution.py:1008-1015`). No transformation log exists.
3. `_add_missing_timestamps` walks the entire JSON tree and injects
   suffix-matched fields into any dict (`role_execution.py:245-275`); field
   collection is suffix-based (`role_execution.py:539-561`).
4. Closed-schema repair silently deletes undeclared keys
   (`role_execution.py:149-154`). The plan understates this layer: the same
   pass also rewrites agent-authored identifiers (`_ID_KEYS` sanitization),
   bumps method identity versions, and injects `schema_version`
   (`role_execution.py:100-165`). This is more content mutation than "missing
   field repair" and strengthens the case for HV-1.2's transformation record.
5. `_phase_plan_shim` hardcodes `mode_id=""` (`output_validation.py:440-464`)
   while validators dispatch on `plan.mode_id` at six sites
   (`scientific_validators.py:151,351,486,583,885,999`). The shim docstring's
   claim that only `phase_id` is used is stale. Confirmed consequences:
   `p3.development_mode_mismatch` and `p4.protocol_mode_mismatch` fire on every
   real record in the supervised lane; P2 focused-method and P5
   review-revision checks are silently skipped there.
6. FAILED and REJECTED are terminal with no outgoing edges
   (`domain/runs.py:81,83`); transitions are enforced by `require_transition`
   and DB CAS. `NO_SCIENTIFIC_ROLE_RETRY` is frozen
   (`orchestration/protocol.py:24,136`).
7. `review-issue` disposition enum is `[open, fixed, partially_fixed, deferred,
   rejected]` (`review-issue.schema.json:80-90`); theory statuses
   `conditional`/`untested`/`retracted` have no validator logic (only the
   `retracted_statement_ids` field name appears).
8. Test count 830 confirmed (pytest collect). `python -m method_hub validate`
   exists (`cli.py:21`), so HV-7.5's command is valid.
9. HV-0.2's evidence base exists: `~/.method-hub/method-hub.sqlite3` holds 39
   runs, 204 role closures, 13 submissions (formal lane).

## 3. Blocking or distorting issues

### R1. HV-0.1's inventory procedure misses about 75 percent of codes

The prescribed `grep 'code="'` finds only 21 literal sites (15 scientific, 7
input, 1 output). The real codes are passed POSITIONALLY to `_finding(...)`:
57 call sites in `scientific_validators.py`, 18 distinct codes in
`submission_validation.py`, 7 in `inputs.py`, 1 in `outputs.py`, plus unbounded
dynamic codes from `outputs.py:207` (`error.code`) and `outputs.py:262`
(`issue.code`). Additionally the `pN.*` namespace is polluted: literals such as
`p4.protocol`, `p4.decision`, `p5.assembly`, and mode names like
`p3.theory_revision` are output-type/object-id constants, not finding codes
(e.g. `scientific_validators.py:674-679` uses them as an output-id set). A
naive grep inventory will conflate the two families. Fix the procedure:
extract first-argument string literals of `_finding(` calls, then manually
exclude mode/record-type constants. The index's per-lane table (62/7/1/19) is
also off; the real static count is approximately 83 plus dynamic codes.

### R2. HV-0's scenario and ADR work omits the machine-checked traceability graph

`validate_package.py:2971-2973` requires scenarios S01..S24 "exactly once and
in order". Any new scenario (HV-0.5 adds five) requires: extending
`expected_codes` in the validator, registering each scenario in
`contracts/traceability.json` (document path, heading, `scenario_id` pattern),
wiring `invariant_coverage` back-links bidirectionally and in registry order,
and updating `scenarios/README.md`. ADR-014 must match the enforced decisions
index link format (`validate_package.py:3141-3146`). HV-0's "Files touched"
lists none of these. As written, HV-0 fails the spec gate on its own
acceptance. Add a work item: "traceability registry + validator range updates
per the WP-G recipe" and cite `references/wp-g-scenarios-traceability.md`.

### R3. The HV-2 registry has no policy for unknown or dynamic codes

Jsonschema-derived codes are unbounded (R1), so the registry cannot enumerate
every code. The plans never state the default for an unregistered code. Two
requirements belong in HV-2.1: (a) unknown codes default to blocking
(fail-closed), and (b) finding factories validate the emitted code against the
registry at construction time so a typo cannot silently change acceptance
behavior. Without (b), HV-2's own acceptance line "changing message wording
cannot change acceptance behavior" has a hole: an unregistered code is
equivalent to a wording change.

### R4. HV-3.2's `recovery_summary` type cannot represent most run states

The Literal `["ok", "needs_output_correction", "failed", "rejected"]` has no
value for `conflicted` (the mapping table says "unchanged", which is not a
value), `cancelled`, or any of the seven in-progress states. The projection
type must cover all 13 `RunStatus` values. Separately, the mapping keys on the
`failure_code` string (`output.structural_validation_failed`), which
reintroduces inferring policy from message text, the pattern the parent plan
Section 5 bans. Acceptable as an interim projection, but the plan should label
it as interim and name the durable replacement (finding classes from HV-2).

### R5. HV-3 Option B displays a recovery state that cannot be acted on until HV-5

Under Option B the coordinator still transitions the run to terminal FAILED.
HV-3.3 and HV-3.4 then show `needs_output_correction` plus "available recovery
controls" for a run whose state machine has no outgoing edges. Between HV-3
and HV-5 the UI would advertise actions that cannot work. HV-3 must either
ship without controls (status wording only) or gate every control on HV-5
capability flags. State this explicitly in HV-3.3/HV-3.4 acceptance.

### R6. HV-5.1's transition edges ignore the submission gate mechanics

`correcting -> submitted` has no path in the current design: the only edge into
SUBMITTED is `running -> submitted` via the atomic `seal_submission` CAS, and
the status pair is a context-level setting (`execution_context.py:56-57`). For
a REJECTED run the problem is doubled: it already consumed `running ->
submitted` and holds an immutable submission row, so correction requires either
a second submission per run (unaddressed interaction with immutability triggers
and the atomic publication head) or an amendment record. The correction flow's
re-entry into the submission/publication path is the hardest mechanics problem
in the whole program and is currently one diagram line. HV-5 needs a design
section covering: which CAS pair the correction uses, how a second submission
coexists with the first, and what the publication head check sees.

### R7. "Inherits the exact frozen run basis" conflicts with reviewed-basis sealing

HV-5.5 and parent Section 6.3 say a correction attempt inherits the exact
frozen basis of the original run. But WP0/WP-H1 seal commands against the
CURRENT authority head and input generations; if anything has published since
the original run, re-binding the old basis either fails drift checks
(`stale_basis.*`) or requires bypassing them. Three resolutions exist (pin the
original head and handle the publication conflict at promotion; bypass drift
for corrections, which weakens WP0; or re-review, which makes it a new run).
The plans pick none. This decision gates HV-5's core mechanism and belongs in
the HV-0 ADR, not in implementation.

### R8. No package owns the architecture schemas the parent plan requires

Parent Section 6: "Define these concepts in architecture schemas before runtime
code depends on them" (ValidationAttempt, OutputTransformationRecord,
OutputCorrectionCommand, RoleAttempt). HV-0 is docs-only per its own Files
list; HV-1.2 and HV-2.6 reference the records "if not added in HV-0". Under
the governing rule that contract changes precede code, schema authorship needs
an explicit owner. Add to HV-0 or create HV-0.6.

### R9. Wiring agent-authored review severity into publication policy is a hole

HV-6.P5 item 6 and index finding 4 propose mapping review-finding
`severity=minor` to non-blocking SCIENTIFIC_ATTENTION. That severity is written
by the producing agent. Keying publication policy on agent self-assessment lets
a model downgrade its own findings. Publication policy must key on
harness-owned finding codes; agent-authored severity may inform triage display
but must not change `blocks_publication`. Reword HV-6.P5.6 accordingly.

## 4. Overstated audit claims (corrections)

### C1. "Dead validator branches" is imprecise

The two disposition sites (`scientific_validators.py:954,965`) mix live enum
values (`fixed`, `partially_fixed`, `deferred`, `rejected`) with dead ones
(`addressed`, `accepted`, `wont_fix`). The branches are live; the stale members
are unreachable but harmless. The claim "correctness bugs that produce wrong
results today" is not supported by these two sites. The real defect in this
area is the confirmed absence of checks for theory statuses `conditional`,
`untested`, `retracted`, plus an unaudited question: does any LIVE enum value
fall through all checks (`open` appears covered by `p5.issue_undispositioned`,
but this needs a systematic per-enum coverage pass, which belongs in HV-2.7).

### C2. "89 distinct finding codes" needs re-sourcing

See R1: the per-lane table (62/7/1/19) does not match the code (57/7/1/18
static plus dynamic). The headline number is the right order of magnitude, but
HV-0.1's acceptance "every code appears exactly once" is only checkable against
a correct extraction procedure.

## 5. Smaller gaps

- S1. HV-6.P4.4 (prespecification order from harness events): validators today
  receive only output documents and compare agent-authored timestamps
  (`scientific_validators.py:662-672`). Harness events exist at run/stage/role
  granularity, not per-artifact authorship order within one role output. This
  item requires new event granularity or harness-stamped per-output times;
  larger than the one-line work item suggests.
- S2. HV-4 blast radius is understated. If the canonical envelope restructures
  output JSON, every phase schema, all ~83 codes, and most validation tests
  change, and it is a contract change requiring an ADR before code. Recommend
  scoping HV-4 as build-time assembly into the EXISTING schema shapes (agent
  writes the scientific payload subset; harness fills identity/digest fields in
  place), which avoids a contract change entirely. Also state explicitly that
  artifact digests bind the stored artifact bytes, not recomputed content.
- S3. HV-1's raw-vs-candidate digests must flow through to the submission lane:
  state which digest `submission.digest_mismatch` binds (recommend: publication
  binds the candidate; the raw digest is preserved as evidence on the closure).
- S4. HV-0.2 should add the supervised pilot DB
  (`~/method-hub-data/pilot-eld/hub.sqlite3`: 7 seals, 8 launches, 7 validation
  reports, 6 promotion records) as a source. It is the only store with
  persisted validation reports; the formal DB it names has zero validation
  report rows (its findings live on closures).

## 6. What is good and should survive revision

- HV-1.5 is confirmed feasible and is the highest-value single fix: validators
  read only `plan.mode_id`, `plan.identity`, and `plan.publication_bindings`
  (grep-verified), and the run manifest carries `mode`, `phase`,
  `phase_contract_version`, `phase_contract_sha256`, and `publication_plan`
  (`run-manifest.schema.json`). A real ValidationContext can be built from the
  sealed manifest without fabricating contract choices. The shim docstring's
  justification is stale, not load-bearing.
- Extending `ValidationFinding` (HV-2.2) is constructor-safe: it is a frozen
  dataclass with defaulted fields (`domain/validation.py:17-23`); new defaulted
  fields break no existing call sites.
- The delivery order and dependency structure (data loss and mode defect first,
  classification before lifecycle projection, recovery last, schema calibration
  evidence-gated on HV-0) are correct. The HV-5 dependency on all prior
  packages is honestly declared.
- The refusal to add a generic post-run Approve button (parent Section 8)
  matches the architecture's no-hidden-automation and no-approval-step
  constraints. The authority table's split of revalidate/normalize/correct is
  the right shape for the ADR.

## 7. Recommended next step

Resolve R6, R7, and R9 as direction decisions (they change what HV-5 and HV-6
build), then revise the ten files in place with a numbered amendment changelog:
R1-R5, R8, C1-C2, S1-S4 are mechanical plan corrections. I can do the in-place
revision pass on confirmation, including the traceability/validator recipe
references for R2.
