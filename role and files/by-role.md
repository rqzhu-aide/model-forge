# Role Read and Write Matrix

This page is the role-centered inverse of the split P1 through P5 contracts.
It lists the scientific inputs each role may read and the run-local outputs it
must write. All writes remain inside the assigned role workspace. Publication
is a separate harness operation.

## How to read this page

- Parallel roles receive the same frozen group-start basis and cannot read one
  another's outputs from that group.
- A current-run output becomes readable only after its producer closes and the
  harness accepts the exact artifact and digest.
- Rerun-only inputs are absent on the first applicable run:
  `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`,
  `p2.current_catalog`, `p3.current_theory`, `p4.current_evidence_index`,
  `p4.current_empirical`, and `p4.current_implementation`.
- `p3.prior_theory` is required only in `p3.theory_revision`.
- If-available exact-match inputs are `p3.current_empirical_index`,
  `p3.current_empirical`, `p3.current_implementation`, and
  `p4.current_theory`.
- `p5.current_manuscript` is required in review-revision and optional in
  assembly. `p5.review_issue_ledger` is included when a current same-lineage
  ledger exists.
- Selected history is frozen separately and does not expand these stage read
  sets.

## Research lead

The research lead integrates specialist work, preserves unresolved
disagreement, prepares candidate formal records, and states user decisions.

### Phase 1: Literature basis

#### `p1.discovery`, parallel

- Mode: `p1.literature_update`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.lead_discovery`
- Boundary: the three current inputs are rerun-only; the lead cannot read the
  other current-run discovery outputs.

#### `p1.lead_synthesis`, serial

- Mode: `p1.literature_update`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`, `p1.lead_discovery`, `p1.theory_discovery`, `p1.empirical_discovery`
- Writes: `p1.source_changes`, `p1.synthesis_candidate`, `p1.coverage_candidate`, `p1.phase2_handoff`, `p1.attention_items`, `p1.decision`
- Boundary: all three discovery artifacts must be accepted first.

### Phase 2: Method catalog

#### `p2.lead_reconciliation`, serial

- Modes: `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal`, `p2.theory_review`, `p2.empirical_review`
- Writes: `p2.method_changes`, `p2.attention_items`, `p2.decision`
- Boundary: the lead reconciles only the authorized scope. In
  researcher-proposal mode, it decides whether the supplied method warrants
  formal registration.

### Phase 3: Theory development

#### `p3.lead`, serial

- Modes: `p3.theory_establishment`, `p3.theory_revision`
- Reads: `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.analyst_audit`, `p3.analyst_handoff`
- Writes: `p3.complete_theory`, `p3.attention_items`, `p3.decision`
- Boundary: all specialist outputs must be accepted. The lead publishes a
  complete `TheoryRecord`, preserves statement status and revision changes,
  and does not invent an unaudited proof or result.

### Phase 4: Empirical evaluation

#### `p4.lead`, serial

- Modes: `p4.preliminary`, `p4.comprehensive`
- Reads: `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.theory_audit`, `p4.theory_handoff`
- Writes: `p4.empirical_index_candidate`, `p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`, `p4.attention_items`, `p4.decision`
- Boundary: preliminary and comprehensive are scopes, not run numbers. The lead
  preserves protocol deviations and does not create a new computation during
  synthesis.

### Phase 5: Manuscript assembly and revision

#### `p5.assembly_lead`, serial

- Mode: `p5.assembly`
- Reads: `p5.project_brief`, `p5.literature_library`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.current_manuscript`
- Writes: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report`, `p5.attention_items`, `p5.decision`
- Boundary: `p5.manuscript_candidate` is a complete `ManuscriptPackage`.
  `p5.current_manuscript` is optional. No review stage runs.

#### `p5.revision_lead`, serial

- Mode: `p5.review_revision`
- Reads: `p5.project_brief`, `p5.literature_library`, `p5.current_manuscript`, `p5.review_issue_ledger`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review`
- Writes: `p5.review_issues`, `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.revision_account`, `p5.attention_items`, `p5.decision`
- Boundary: all three review outputs arrive together. The lead converts every
  open `ReviewFinding` into a dispositioned `ReviewIssue`, preserves issue
  lineage, and writes the complete revised `ManuscriptPackage`.

## Theorist

The theorist develops and audits mathematical definitions, assumptions,
claims, proofs, counterexamples, and method boundaries. Empirical performance
is not treated as proof.

### Phase 1: Literature basis

#### `p1.discovery`, parallel

- Mode: `p1.literature_update`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.theory_discovery`
- Boundary: current inputs are rerun-only; parallel discovery outputs remain
  isolated.

### Phase 2: Method catalog

#### `p2.independent_proposals`, parallel

- Modes: `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`
- Writes: `p2.theory_proposal`
- Boundary: focused mode is limited to the selected stable method;
  researcher-proposal mode evaluates the supplied specification.

#### `p2.cross_review`, parallel

- Modes: `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal`
- Writes: `p2.theory_review`
- Boundary: all proposals must be accepted first. The theorist cannot read the
  analyst's current-run review.

### Phase 3: Theory development

#### `p3.theorist`, serial

- Modes: `p3.theory_establishment`, `p3.theory_revision`
- Reads: `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.prior_theory`, `p3.current_empirical`
- Writes: `p3.theory_candidate`, `p3.theory_handoff`
- Boundary: establishment constructs the scoped account. Revision compares the
  exact prior theory statement by statement and may weaken, condition,
  contradict, or retract claims. `p3.prior_theory` is required only for
  revision. The candidate is a complete `TheoryRecord`, not a patch.

### Phase 4: Empirical evaluation

#### `p4.theorist`, serial

- Modes: `p4.preliminary`, `p4.comprehensive`
- Reads: `p4.method`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.current_theory`
- Writes: `p4.theory_audit`, `p4.theory_handoff`
- Boundary: all analyst outputs must be accepted. The theorist audits
  mathematical fidelity, protocol adherence, and scope-calibrated conclusions.

### Phase 5: Manuscript review

- Assembly mode: does not participate.

#### `p5.parallel_reviews`, parallel

- Mode: `p5.review_revision`
- Reads: `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.implementation_record`, `p5.literature_synthesis`
- Writes: `p5.theory_audit`
- Boundary: `p5.theory_audit` is a set of open `ReviewFinding` items. The
  theorist does not disposition issues, read another review, or edit the
  manuscript.

## Data analyst

The data analyst develops and audits design, implementation, computation, data
provenance, uncertainty, interpretation, and reproducibility.

### Phase 1: Literature basis

#### `p1.discovery`, parallel

- Mode: `p1.literature_update`
- Reads: `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`
- Writes: `p1.empirical_discovery`
- Boundary: current inputs are rerun-only; parallel discovery outputs remain
  isolated.

### Phase 2: Method catalog

#### `p2.independent_proposals`, parallel

- Modes: `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`
- Writes: `p2.empirical_proposal`
- Boundary: focused mode is limited to the selected stable method;
  researcher-proposal mode evaluates the supplied specification.

#### `p2.cross_review`, parallel

- Modes: `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal`
- Reads: `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal`
- Writes: `p2.empirical_review`
- Boundary: all proposals must be accepted first. The analyst cannot read the
  theorist's current-run review.

### Phase 3: Theory development

#### `p3.analyst`, serial

- Modes: `p3.theory_establishment`, `p3.theory_revision`
- Reads: `p3.method`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`
- Writes: `p3.analyst_audit`, `p3.analyst_handoff`
- Boundary: the theorist outputs must be accepted. The analyst checks
  operational meaning, falsifiability, evidence consistency, and unrecorded
  revision changes without silently repairing the theory.

### Phase 4: Empirical evaluation

#### `p4.analyst`, serial

- Modes: `p4.preliminary`, `p4.comprehensive`
- Reads: `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`
- Writes: `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`
- Boundary: `p4.protocol` is an `EmpiricalProtocol` fixed before outcome
  inspection. Preliminary is a small decisive scope. Comprehensive is a
  self-contained full scope and does not require preliminary work. Prior code
  is reused only after exact-method verification.

### Phase 5: Manuscript review

- Assembly mode: does not participate.

#### `p5.parallel_reviews`, parallel

- Mode: `p5.review_revision`
- Reads: `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`
- Writes: `p5.empirical_audit`
- Boundary: `p5.empirical_audit` is a set of open `ReviewFinding` items. The
  analyst does not disposition issues, read another review, or edit the
  manuscript.

## Outside reviewer

The outside reviewer assesses one frozen manuscript as an independent
first-time reader. It does not participate in Phases 1 through 4 or in Phase 5
assembly.

### Phase 5: Manuscript review

#### `p5.parallel_reviews`, parallel

- Mode: `p5.review_revision`
- Reads: `p5.review_packet`
- Writes: `p5.outside_review`
- Boundary: `p5.outside_review` is a `ReviewReport` whose prioritized findings
  remain open. The packet is the complete and exclusive project-specific input.
  The reviewer cannot resolve internal formal records, selected history,
  specialist audits, deliberation, hidden memory, or later outputs. It cannot
  read another current-run review or edit the manuscript.

## Cross-check rule

The phase-centered page must show the same role, stage, read IDs, write IDs,
order, and mode conditions. A discrepancy means the documentation is stale;
the split contract remains authoritative.
