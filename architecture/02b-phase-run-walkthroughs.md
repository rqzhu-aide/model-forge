# Phase Run Walkthroughs (P1-P5)

Code-anchored walkthroughs of how each research phase runs through the
**formal lane** (`run_coordinator.py`, reached from the Web UI's phase pages
via `POST /projects/{id}/runs`). This is the companion to
[02a-supervised-run-walkthrough.md](02a-supervised-run-walkthrough.md), which
covers the supervised lane. Section 1 explains the machinery once; every later
section is the phase-specific content: modes, stages, who writes what, the
instruction the agents actually receive, validators, and where results land.

The authoritative sources for this doc are the executable phase contracts
(`architecture/contracts/phases/P1.json` .. `P5.json`, loaded by
`src/method_hub/contracts/phases.py`), the Jinja2 instruction templates under
`resources/instructions/<Phase>/`, the stage executor
(`src/method_hub/harness/stage_execution.py`), and the scientific validators
(`src/method_hub/harness/scientific_validators.py`). When prose here and a
contract disagree, the contract wins.

## 1. Shared machinery (read once)

A formal-lane run is started from a phase page: the user picks a **mode** and
**choice values**, the UI posts `StartRunRequest` (phase, mode, choices,
context policy), and `MethodHubService.start_run` freezes a manifest and hands
the run to the `RunCoordinator`. The coordinator then walks the contract's
**role stages** in `sequence` order. For each stage:

- **Serial stage** (`execution: "serial"`): one Hermes invocation per step,
  one after another. Each later step receives the earlier steps' frozen
  outputs as inputs.
- **Parallel stage** (`execution: "parallel"`): one invocation per listed
  role, launched together via `asyncio.gather` (`stage_execution.py`). Every
  role receives the **same frozen basis** and, per the contract's
  `isolation_rule`, does **not** see the other roles' current-run outputs
  before submitting its own.
- **Task brief** (`harness/task_briefs.render_task_brief`): rendered per
  stage+role from the frozen contract data: stage objective, inputs (resolved
  read set), output plan skeletons derived from each output's JSON schema
  (never golden example content), plus the mode/role instruction layer.
- **Instruction layer** (`application/default_instructions.py`): the Jinja2
  template resolved in this precedence:
  `<stage_id>.<role>.md` > `<stage_id>.md` > `<mode>.<role>.md` >
  `<mode>.md` > `default.<role>.md` > `default.md`, under
  `resources/instructions/<Phase>/`. Templates receive the project brief
  (research question, scope, constraints, decision criteria) and
  `phase_id`/`mode_id`/`stage_id`/`role`. A harness-owned/agent-authored
  field separation note is appended once per layer.
- **Executor**: configured via `METHOD_HUB_EXECUTOR_KIND` (`disabled` |
  `fake` | `hermes_kanban` | `local_hermes`). Real phases run
  `local_hermes`; `fake` (schema-example executor, development mode only)
  emits schema-valid example outputs for pipeline testing; `disabled` builds
  no coordinator.
- **Run-local outputs**: every role writes only run-local documents named by
  the contract (`p<N>.<name>` output ids). Validators check the complete
  phase output set, then publication bindings atomically commit formal
  records (current slots, cumulative collections).
- **Run directory**: `~/.method-hub/runs/run.<phase>.<mode>.<uuid>/` with
  `roles/` and `tasks/` subtrees.

The rest of this document is the phase-specific contract content, quoted or
summarized from `P<N>.json` with stage objectives verbatim.

## 2. Phase 1: Literature basis

**Mode.** `p1.literature_update` (one mode; user choices include search scope
`broad_update`/`focused_update`, instructions, and context policy).

**Stage 1 `p1.discovery` (parallel).** Objective: "Search and assess the same
frozen question from scientific, mathematical, and empirical perspectives."
`research_lead`, `theorist`, `data_analyst` each search from their own angle
and write `p1.lead_discovery`, `p1.theory_discovery`,
`p1.empirical_discovery` (all `handoff.schema.json`). Isolation: discovery
roles do not read one another's current-run reports before submission.

**Stage 2 `p1.lead_synthesis` (serial, research_lead).** Objective:
"Deduplicate sources, reconcile or expose disagreements, assess coverage, and
produce the candidate current basis." Writes `p1.source_changes`
(literature-source), `p1.synthesis_candidate` + `p1.coverage_candidate`
(scientific-record), `p1.phase2_handoff` (handoff), `p1.attention_items`
(attention-item), `p1.decision` (decision-record).

**Validators.** `_validate_p1`: role sequence order and run-localness;
source identity (stable id, citation metadata, search provenance, no
duplicate identities), plus the contract's blocking rules.

**Publication.** On pass: append attention items to
`project.attention_history` and sources to `p1.literature_sources`
(cumulative collections); replace current slots for the literature library,
synthesis, coverage, and the phase decision.

## 3. Phase 2: Method development

**Modes.** `p2.full_catalog` (may add/update multiple methods),
`p2.focused_method` (updates exactly one selected existing method; stable
method id mandatory), `p2.researcher_proposal` (evaluate a researcher's
proposed method).

**Stage 1 `p2.independent_proposals` (parallel).** Objective: "Generate
independent proposals, scoped revisions, or evaluations of a
researcher-proposed method. Proposals should seek unique literature
positioning and high novelty relative to the frozen literature basis."
Theorist and data_analyst propose blind (`p2.theory_proposal`,
`p2.empirical_proposal`); the research lead does not propose (ADR-017).

**Stage 2 `p2.cross_review` (parallel, theorist + data_analyst).** Objective:
"Cross-review definitions, assumptions, identifiability, implementation, data
requirements, computation, empirical distinguishability, or the validity and
novelty of a researcher-proposed method. Each review includes a structured
per-method evaluation keyed by the method stable_id, within the reviewer
competency axis." Writes `p2.theory_review` (theoretical_validity axis),
`p2.empirical_review` (empirical_feasibility axis). Literature positioning
and novelty is lead-only; reviewers may only raise issues on it.

**Stage 3 `p2.lead_reconciliation` (serial, research_lead).** Objective:
"Reconcile or expose disagreements and produce the candidate scoped catalog
change and decision summary. For researcher proposals, decide whether the
method warrants formal registration. The lead adjudicates and seals a 1-10
score with justification on three axes (theoretical validity and
identifiability; literature positioning and novelty; empirical testability
and computational efficiency) for every method in the change set." Writes
`p2.method_changes` (method schema, each record carrying the sealed
`evaluation` block), `p2.attention_items`, `p2.decision`. The lead may
recommend but cannot choose the user's P3/P4 branch.

**Validators.** `_validate_p2` (plus `_validate_method_definition` for
method changes: mathematical definition, assumptions, identifiability
claims), including the new blocking rules `p2.method_evaluation` (sealed
evaluation block completeness, score range, issue refs) and
`p2.review_axis_ownership` (reviewer axis ownership).

**Publication.** Append attention items; `upsert_each` method records into
keyed current slots `p2.method_records`; replace the method catalog and phase
decision current slots.

## 4. Phase 3: Theory development

**Modes.** `p3.theory_establishment` (construct a complete scoped theory
record from the frozen current record basis) and `p3.theory_revision`
(revise; the frozen current record is the basis on a rerun).

**Stage 1 `p3.theorist` (serial).** Objective: "Follow the selected
establishment or revision mode, construct a complete scoped theory record,
and register assumptions, exact statements, proof support or counterexamples
or open obligations, dependencies, limitations, and empirical implications."
Writes `p3.theory_candidate` (theory-record), `p3.theory_handoff`.

**Stage 2 `p3.analyst` (serial, data_analyst).** Objective: "Challenge
identifiability, operational meaning, computation, empirical testability,
boundary cases, evidence consistency, and any unjustified status inflation or
untracked weakening or retraction in revision mode." Writes
`p3.analyst_audit`, `p3.analyst_handoff`.

**Stage 3 `p3.lead` (serial, the research lead).** Objective: "Integrate the
theory and audit without introducing unaudited formal content, resolve or
expose disagreement, preserve all statement statuses and revision changes,
and state the current outcome and user-relevant changes." Writes
`p3.complete_theory`, `p3.attention_items`, `p3.decision`.

**Validators.** `_validate_p3` (incl. `_validate_theory_statement`).
Selected method identity is required (from the P2 catalog; the P3 method
list is read-only for roles).

**Publication.** Append attention items; replace the theory record and phase
decision current slots.

## 5. Phase 4: Empirical development

**Modes.** `p4.preliminary` (small set of decisive checks, implementation
verification, feasibility) and `p4.comprehensive` (prespecified full
evaluation with comparisons, sensitivity, robustness). Scope is a user
choice on every run; it is not determined by run number.

**Stage 1 `p4.analyst` (serial).** Objective: "Apply the selected preliminary
or comprehensive scope, finalize a claim-linked empirical protocol before
inspecting outcomes, verify the exact implementation, execute only that
protocol, append deviations without rewriting it, and produce reproducible
evidence and synthesis." Writes `p4.protocol` (empirical-protocol),
`p4.evidence` (evidence), `p4.analyst_synthesis`, `p4.analyst_handoff`.

**Stage 2 `p4.theorist` (serial).** Objective: "Audit mathematical fidelity,
definition-to-code correspondence, protocol adherence, scope-appropriate
comparisons and thresholds, interpretation, deviations, and consistency with
available theory." Writes `p4.theory_audit`, `p4.theory_handoff`.

**Stage 3 `p4.lead` (serial, research_lead).** Objective: "Integrate
evidence and fidelity findings without creating unaudited results, retain
only applicable evidence, preserve protocol deviations and unresolved
disagreement, and state a scope-calibrated scientific outcome and
user-relevant changes." Writes `p4.empirical_index_candidate`,
`p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`,
`p4.attention_items`, `p4.decision`.

**Validators.** `_validate_p4` (incl. `_validate_empirical_protocol` and
`_validate_reproducibility`). Selected method identity required.

**Publication.** Append attention items and evidence to cumulative
collections; replace current slots for the evidence index, empirical
synthesis, implementation record, and phase decision.

## 6. Phase 5: Manuscript assembly and revision

**Modes.** `p5.assembly` and `p5.review_revision`. Stages are mode-specific
(assembly mode runs one stage; review-revision runs two).

**Assembly mode, stage `p5.assembly_lead` (serial, research_lead).**
Objective: "Assemble or update the complete manuscript, claim traceability,
limitations, and decision record from the exact frozen basis." Writes
`p5.manuscript_candidate`
(manuscript-package), `p5.claim_traceability`, `p5.upstream_basis_manifest`,
`p5.citation_integrity_report`, `p5.limitations_record`,
`p5.assembly_report` (optional), `p5.attention_items`, `p5.decision`.

**Review-revision mode, stage 1 `p5.parallel_reviews` (parallel).**
Objective: "Audit one immutable manuscript snapshot from mathematical,
empirical, reproducibility, theory-to-implementation, novelty, significance,
validity, and reader perspectives." `theorist`, `data_analyst`, and
`outside_reviewer` work on the same frozen snapshot. Isolation rule: "The
outside reviewer receives only its frozen review packet as project-specific
context and never specialist audits, internal deliberation, or later role
output. Controlled public scholarly search remains allowed and must be
reported." Writes `p5.theory_audit`, `p5.empirical_audit` (review-finding),
`p5.outside_review`.

**Review-revision mode, stage 2 `p5.revision_lead` (serial, research_lead).**
Receives all three assessments plus the frozen upstream basis and revises the
complete manuscript; records a disposition for every review issue. Writes the
full assembly output set (`p5.manuscript_candidate`, `p5.claim_traceability`,
`p5.upstream_basis_manifest`, `p5.citation_integrity_report`,
`p5.limitations_record`), plus `p5.review_issues`, `p5.revision_account`,
`p5.attention_items`, `p5.decision`.

**Validators.** `_validate_p5` (incl. `_validate_manuscript_package` and
`_validate_open_review_finding`).

**Publication.** Append attention items; `bundle` the assembly or reviewed
manuscript into the manuscript current slot; review-revision additionally
appends review issues to `p5.review_issue_history` and replaces the review
issue ledger.

## 7. Which lane runs which phase today

- The **phase pages** (P1-P5 navigation) drive the **formal lane**
  (`POST /projects/{id}/runs`): multi-stage, multi-role, publishes formal
  records. This doc.
- The **Runs page** supervised form drives the **supervised lane**
  (`POST /projects/{id}/supervised-runs/start`): one sealed Hermes process
  with a free-form brief and expected outputs. Doc
  [02a](02a-supervised-run-walkthrough.md).
- Both lanes validate phase outputs: output validation reuses the
  phase-specific scientific validators when the run's phase has one and the
  declared output ids match the phase prefix (`output_validation.py` check 7,
  `phase_consistency`).
- The two lanes are not yet connected: supervised outputs are not ingested
  into formal phase records. The phase pages' start action is the full
  pipeline; the supervised lane is the trusted-local execution program
  (ADR-012) whose briefs can be any phase work scoped to one role.

## 8. Where to verify this document

| Claim | Source of truth |
|---|---|
| Modes, stages, execution types, isolation rules | `architecture/contracts/phases/P<N>.json` (`run_modes`, `role_stages`) |
| Output ids, producers, schemas | Same contracts (`run_local_outputs`) |
| Instruction text agents receive | `resources/instructions/<Phase>/*.md` |
| Parallel/serial dispatch | `src/method_hub/harness/stage_execution.py` |
| Task brief rendering | `src/method_hub/harness/task_briefs.py` |
| Scientific validators | `src/method_hub/harness/scientific_validators.py` |
| Publication bindings | Contracts (`publication_bindings`) executed by `harness/publication.py` |
| Formal run dir layout | `~/.method-hub/runs/run.<phase>.<mode>.<uuid>/` |
| Executor choice | `METHOD_HUB_EXECUTOR_KIND` (`application/settings.py`) |
