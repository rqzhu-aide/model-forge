# Role Read and Write Matrix

This page is the role-centered inverse of the five machine-readable phase contracts in `architecture/contracts/phases/`. It records the scientific inputs each role may read and the run-local outputs each role must write.

All writes below remain inside the role's assigned run workspace. A role never writes directly to formal project storage. The harness verifies each completed role invocation, accepts declared outputs, assembles the run submission, and performs publication separately.

## How to read this page

- `Parallel` roles receive the same frozen group-start basis and cannot read one another's outputs from that group.
- A current-run output listed under `Reads` becomes available only after its producing role closes successfully and the harness accepts the exact artifact and digest.
- Rerun-only inputs are absent on the first applicable run: `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`, `p2.current_catalog`, `p3.current_theory`, `p4.current_evidence_index`, `p4.current_empirical`, and `p4.current_implementation`.
- If-available inputs are included only when an exactly aligned record exists: `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`, and `p4.current_theory`.
- In Phase 5, `p5.current_manuscript` is required in review-revision mode and optional in assembly mode. `p5.review_issue_ledger` is included in review-revision mode when a current ledger exists for the selected stable method.
- Optional user-selected history and other context are frozen separately by the harness. They do not expand the phase contract read sets shown here.

## Research lead

The research lead participates in every phase. The lead integrates specialist work, preserves unresolved disagreement, prepares candidate formal records, and states the decisions that remain with the user.

### Phase 1: Literature basis

#### Stage 1: `p1.discovery`

- Mode: `p1.literature_update`
- Execution: Parallel with `theorist` and `data_analyst`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.lead_discovery`
- Conditions: The three `p1.current_*` inputs are required on reruns and absent on the first run. The lead cannot read the other current-run discovery reports during this stage.

#### Stage 2: `p1.lead_synthesis`

- Mode: `p1.literature_update`
- Execution: Serial after all three discovery roles close successfully
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`, `p1.lead_discovery`, `p1.theory_discovery`, `p1.empirical_discovery`
- Writes: `p1.source_changes`, `p1.synthesis_candidate`, `p1.coverage_candidate`, `p1.phase2_handoff`, `p1.attention_items`, `p1.decision`
- Conditions: The three discovery outputs must be accepted artifacts from the completed parallel stage.

### Phase 2: Method catalog

#### Stage 1: `p2.independent_proposals`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Parallel with `theorist` and `data_analyst`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`
- Writes: `p2.lead_proposal`
- Conditions: `p2.current_catalog` is required after the first catalog run and absent on the first run. In focused-method mode, the authorized scope is exactly the user-selected stable method. The lead cannot read the other current-run proposals during this stage.

#### Stage 3: `p2.lead_reconciliation`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Serial after proposals and cross-reviews close successfully
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal`, `p2.theory_review`, `p2.empirical_review`
- Writes: `p2.method_changes`, `p2.attention_items`, `p2.decision`
- Conditions: The lead reconciles the accepted proposals and reviews within the user-authorized catalog scope. The lead does not select a Phase 3 or Phase 4 branch for the user.

### Phase 3: Theory development

#### Stage 3: `p3.lead`

- Mode: `p3.theory_update`
- Execution: Serial after `p3.theorist` and `p3.analyst`
- Reads: `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.analyst_audit`, `p3.analyst_handoff`
- Writes: `p3.complete_theory`, `p3.attention_items`, `p3.decision`
- Conditions: The run targets one exact current method identity. `p3.current_theory` is rerun-only. The three empirical inputs are included only when an exactly aligned Phase 4 record exists. All four current-run specialist outputs must be accepted before this stage starts.

### Phase 4: Empirical evaluation

#### Stage 3: `p4.lead`

- Modes: `p4.preliminary`, `p4.comprehensive`
- Execution: Serial after `p4.analyst` and `p4.theorist`
- Reads: `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.theory_audit`, `p4.theory_handoff`
- Writes: `p4.empirical_index_candidate`, `p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`, `p4.attention_items`, `p4.decision`
- Conditions: The user may select either scope on any run. The three current empirical inputs are rerun-only. `p4.current_theory` is included only when an exactly aligned Phase 3 record exists. All six current-run specialist outputs must be accepted before this stage starts.

### Phase 5: Manuscript assembly and revision

#### Assembly stage: `p5.assembly_lead`

- Mode: `p5.assembly`
- Execution: Serial
- Reads: `p5.project_brief`, `p5.literature_library`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.current_manuscript`
- Writes: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report`, `p5.attention_items`, `p5.decision`
- Conditions: The exact Phase 5 readiness predicate must pass. `p5.current_manuscript` is optional in assembly mode. No review stage runs in this mode.

#### Revision stage: `p5.revision_lead`

- Mode: `p5.review_revision`
- Execution: Serial after all three parallel reviews close successfully
- Reads: `p5.project_brief`, `p5.literature_library`, `p5.current_manuscript`, `p5.review_issue_ledger`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review`
- Writes: `p5.review_issues`, `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.revision_account`, `p5.attention_items`, `p5.decision`
- Conditions: A complete current manuscript from the selected stable method lineage is required. `p5.review_issue_ledger` is included when it exists. The three review outputs arrive together only after the parallel review stage closes.

## Theorist

The theorist develops and audits mathematical definitions, assumptions, claims, proofs, counterexamples, and method boundaries. The role does not treat empirical performance as proof.

### Phase 1: Literature basis

#### Stage 1: `p1.discovery`

- Mode: `p1.literature_update`
- Execution: Parallel with `research_lead` and `data_analyst`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.theory_discovery`
- Conditions: The three `p1.current_*` inputs are rerun-only. The theorist cannot read the other current-run discovery reports during this stage.

### Phase 2: Method catalog

#### Stage 1: `p2.independent_proposals`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Parallel with `research_lead` and `data_analyst`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`
- Writes: `p2.theory_proposal`
- Conditions: `p2.current_catalog` is rerun-only. Focused-method mode permits work only on the user-selected stable method. The theorist cannot read the other current-run proposals during this stage.

#### Stage 2: `p2.cross_review`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Parallel with `data_analyst`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal`
- Writes: `p2.theory_review`
- Conditions: All three proposal artifacts must be accepted before this stage starts. The theorist cannot read the analyst's current-run cross-review while both reviews are in progress.

### Phase 3: Theory development

#### Stage 1: `p3.theorist`

- Mode: `p3.theory_update`
- Execution: Serial first stage
- Reads: `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical`
- Writes: `p3.theory_candidate`, `p3.theory_handoff`
- Conditions: The run targets one exact current method identity. `p3.current_theory` is rerun-only. `p3.current_empirical` is included only when an exactly aligned Phase 4 synthesis exists.

### Phase 4: Empirical evaluation

#### Stage 2: `p4.theorist`

- Modes: `p4.preliminary`, `p4.comprehensive`
- Execution: Serial after `p4.analyst`
- Reads: `p4.method`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.current_theory`
- Writes: `p4.theory_audit`, `p4.theory_handoff`
- Conditions: The user-selected scope applies on every run. All four analyst outputs must be accepted before this stage starts. `p4.current_theory` is included only when an exactly aligned Phase 3 record exists.

### Phase 5: Manuscript assembly and revision

- Assembly mode: Does not participate.

#### Stage 1: `p5.parallel_reviews`

- Mode: `p5.review_revision`
- Execution: Parallel with `data_analyst` and `outside_reviewer`
- Reads: `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.literature_synthesis`
- Writes: `p5.theory_audit`
- Conditions: This is the exact role-specific read set. It replaces the stage's shared reads. The theorist cannot read either other review while the parallel stage is active and does not edit the manuscript directly.

## Data analyst

The data analyst develops and audits study design, implementation, computation, data provenance, uncertainty, empirical interpretation, and reproducibility. The role does not treat a successful computation as a general theorem.

### Phase 1: Literature basis

#### Stage 1: `p1.discovery`

- Mode: `p1.literature_update`
- Execution: Parallel with `research_lead` and `theorist`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.empirical_discovery`
- Conditions: The three `p1.current_*` inputs are rerun-only. The analyst cannot read the other current-run discovery reports during this stage.

### Phase 2: Method catalog

#### Stage 1: `p2.independent_proposals`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Parallel with `research_lead` and `theorist`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`
- Writes: `p2.empirical_proposal`
- Conditions: `p2.current_catalog` is rerun-only. Focused-method mode permits work only on the user-selected stable method. The analyst cannot read the other current-run proposals during this stage.

#### Stage 2: `p2.cross_review`

- Modes: `p2.full_catalog`, `p2.focused_method`
- Execution: Parallel with `theorist`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal`
- Writes: `p2.empirical_review`
- Conditions: All three proposal artifacts must be accepted before this stage starts. The analyst cannot read the theorist's current-run cross-review while both reviews are in progress.

### Phase 3: Theory development

#### Stage 2: `p3.analyst`

- Mode: `p3.theory_update`
- Execution: Serial after `p3.theorist`
- Reads: `p3.method`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`
- Writes: `p3.analyst_audit`, `p3.analyst_handoff`
- Conditions: The theorist outputs must be accepted before this stage starts. The three empirical inputs are included only when an exactly aligned Phase 4 record exists.

### Phase 4: Empirical evaluation

#### Stage 1: `p4.analyst`

- Modes: `p4.preliminary`, `p4.comprehensive`
- Execution: Serial first stage
- Reads: `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`
- Writes: `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`
- Conditions: The user selects preliminary or comprehensive scope on every run. The three current empirical inputs are rerun-only. `p4.current_theory` is included only when an exactly aligned Phase 3 record exists.

### Phase 5: Manuscript assembly and revision

- Assembly mode: Does not participate.

#### Stage 1: `p5.parallel_reviews`

- Mode: `p5.review_revision`
- Execution: Parallel with `theorist` and `outside_reviewer`
- Reads: `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`
- Writes: `p5.empirical_audit`
- Conditions: This is the exact role-specific read set. It replaces the stage's shared reads. The analyst cannot read either other review while the parallel stage is active and does not edit the manuscript directly.

## Outside reviewer

The outside reviewer assesses one frozen manuscript as an independent first-time reader. The role never edits the manuscript and never participates in internal method, theory, or empirical development.

### Phases 1 through 4

- Phase 1: Does not participate.
- Phase 2: Does not participate.
- Phase 3: Does not participate.
- Phase 4: Does not participate.

### Phase 5: Manuscript assembly and revision

- Assembly mode: Does not participate.

#### Stage 1: `p5.parallel_reviews`

- Mode: `p5.review_revision`
- Execution: Parallel with `theorist` and `data_analyst`
- Reads: `p5.review_packet`
- Writes: `p5.outside_review`
- Conditions: `p5.review_packet` is the complete and exclusive scientific input. It contains the immutable manuscript snapshot, submitted supplements, cited material available to an external referee, and reviewer-facing user or venue instructions. The reviewer cannot resolve internal formal records, specialist audits, internal deliberation, hidden or project-specific memory, selected history, attention items, or later role outputs. The reviewer cannot read the other current-run reviews.

## Cross-check rule

For any phase, the corresponding phase-centered page must show the same role, stage, read IDs, write IDs, order, and mode conditions listed here. A discrepancy means the documentation is stale; the machine-readable phase contract remains authoritative.
