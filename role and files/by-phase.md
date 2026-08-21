# Files and Roles by Research Phase

This page is the phase-centered cross-check of who reads and writes each
research object. The executable sources are the split P1 through P5 contracts,
all at contract version `2.0.0`. IDs below are contract IDs, not required
physical filenames.

Every output begins inside its producing role's run workspace. A later stage
can read it only after the role closes and the harness accepts the artifact and
digest. Formal records change only through declared publication bindings after
submission and validation. Historical records are excluded unless the user
selects them.

## Phase 1: Literature Basis

Contract: `P1@2.0.0`

Mode: `p1.literature_update`

User choices:

- `p1.scope`, required: `broad_update` or `focused_update`
- `p1.instructions`, required
- `p1.selected_history`, optional

Formal inputs:

- `p1.project_brief`, always
- `p1.current_library`, `p1.current_synthesis`, and `p1.current_coverage`,
  required on reruns and absent on the first run

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p1.discovery`, parallel | Research lead | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.lead_discovery` |
| `p1.discovery`, parallel | Theorist | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.theory_discovery` |
| `p1.discovery`, parallel | Data analyst | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.empirical_discovery` |
| `p1.lead_synthesis`, serial | Research lead | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`, `p1.lead_discovery`, `p1.theory_discovery`, `p1.empirical_discovery` | `p1.source_changes`, `p1.synthesis_candidate`, `p1.coverage_candidate`, `p1.phase2_handoff`, `p1.attention_items`, `p1.decision` |

The three discovery roles share a frozen basis and cannot see one another's
current-run outputs.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p1.append_literature_sources` | `p1.source_changes` | Append unique sources to `p1.literature_sources` |
| `p1.rebuild_literature_library` | `p1.source_changes` and prior library when present | Deterministically replace `p1.literature_library.current` |
| `p1.replace_literature_synthesis` | `p1.synthesis_candidate` | Replace `p1.literature_synthesis.current` |
| `p1.replace_literature_coverage` | `p1.coverage_candidate` | Replace `p1.literature_coverage.current` |
| `p1.replace_phase_decision` | `p1.decision` | Replace `p1.phase_decision.current` |
| `p1.append_attention_items` | `p1.attention_items` | Append to `project.attention_history` |

Discovery reports and `p1.phase2_handoff` remain run-local provenance. Phase 2
reads the promoted library, synthesis, and coverage.

## Phase 2: Method Catalog

Contract: `P2@2.0.0`

Modes:

- `p2.full_catalog`: propose or revise multiple methods within the catalog scope
- `p2.focused_method`: reassess exactly one selected stable method
- `p2.researcher_proposal`: evaluate a researcher-supplied method specification
  and decide whether it warrants formal registration

User choices:

- `p2.instructions`, required in every mode
- `p2.selected_method`, required only in `p2.focused_method`
- `p2.researcher_method_spec`, required only in `p2.researcher_proposal`
- `p2.selected_history`, optional

Formal inputs:

- `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, and
  `p2.literature_coverage`, always
- `p2.current_catalog`, required on reruns and absent on the first run
- Exact-match `p2.theory_result`, `p2.empirical_result`, and
  `p2.manuscript_result`, included when they exist in focused mode

The three optional downstream results are phase inputs, but they do not appear
in the current role-stage read allowlists. The table therefore omits them.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p2.independent_proposals`, parallel | Theorist | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog` | `p2.theory_proposal` |
| `p2.independent_proposals`, parallel | Data analyst | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog` | `p2.empirical_proposal` |
| `p2.cross_review`, parallel | Theorist | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal` | `p2.theory_review` |
| `p2.cross_review`, parallel | Data analyst | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal` | `p2.empirical_review` |
| `p2.lead_reconciliation`, serial | Research lead | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.theory_proposal`, `p2.empirical_proposal`, `p2.theory_review`, `p2.empirical_review` | `p2.method_changes`, `p2.attention_items`, `p2.decision` |

The same stage sequence applies to all three modes. Isolation applies within
both parallel stages.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p2.upsert_method_records` | `p2.method_changes` | Upsert complete method records in `p2.method_records` |
| `p2.rebuild_method_catalog` | `p2.method_changes` and prior catalog when present | Deterministically replace `p2.method_catalog.current` |
| `p2.replace_phase_decision` | `p2.decision` | Replace `p2.phase_decision.current` |
| `p2.append_attention_items` | `p2.attention_items` | Append to `project.attention_history` |

## Phase 3: Theory Development

Contract: `P3@2.0.0`

Modes:

- `p3.theory_establishment`: construct the complete scoped theory account for
  the exact selected method
- `p3.theory_revision`: compare the current theory statement by statement and
  repair, weaken, condition, contradict, or retract claims as warranted

User choices: `p3.selected_method` and `p3.instructions`, required;
`p3.selected_history`, optional.

Formal inputs:

- `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, and
  exact-match `p3.method`, always
- Exact-match `p3.current_theory`, required on reruns and absent on the first run
- Exact-match `p3.prior_theory`, required in `p3.theory_revision`
- Exact-match `p3.current_empirical_index`, `p3.current_empirical`, and
  `p3.current_implementation`, included when aligned Phase 4 records exist

Phase 4 is not a prerequisite.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p3.theorist`, serial | Theorist | `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.prior_theory`, `p3.current_empirical` | `p3.theory_candidate`, `p3.theory_handoff` |
| `p3.analyst`, serial | Data analyst | `p3.method`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation` | `p3.analyst_audit`, `p3.analyst_handoff` |
| `p3.lead`, serial | Research lead | `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.analyst_audit`, `p3.analyst_handoff` | `p3.complete_theory`, `p3.attention_items`, `p3.decision` |

`p3.theory_candidate` and `p3.complete_theory` use
`theory-record.schema.json`. Each is a complete `TheoryRecord` with a readable
primary artifact and statement-level proof, counterexample, or open-obligation
support. A rerun publishes a full replacement, not a patch.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p3.replace_theory_record` | `p3.complete_theory` | Replace `p3.theory_record.current` for the exact method identity |
| `p3.replace_phase_decision` | `p3.decision` | Replace `p3.phase_decision.current` |
| `p3.append_attention_items` | `p3.attention_items` | Append to `project.attention_history` |

The candidate, handoffs, and analyst audit remain run-local provenance.

## Phase 4: Empirical Evaluation

Contract: `P4@2.0.0`

Modes:

- `p4.preliminary`: a small set of decisive feasibility, implementation,
  diagnostic, or falsification checks
- `p4.comprehensive`: a self-contained, prespecified full evaluation with
  claim-linked comparisons, sensitivity, robustness, uncertainty, ablations,
  and scaling where relevant

These are scientific scopes independent of chronology. Either scope may be
selected on a first run or rerun. Comprehensive does not require a prior
preliminary run.

User choices: `p4.selected_method` and `p4.instructions`, required;
`p4.selected_history`, optional.

Formal inputs:

- `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, and
  exact-match `p4.method`, always
- Exact-match `p4.current_evidence_index`, `p4.current_empirical`, and
  `p4.current_implementation`, required on reruns and absent on the first run
- Exact-match `p4.current_theory`, included when an aligned Phase 3 record exists

A current implementation may be reused only after digest, invariant, and
mathematical-fidelity checks. Otherwise the run implements and versions the
method itself. Phase 3 is not a prerequisite.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p4.analyst`, serial | Data analyst | `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory` | `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff` |
| `p4.theorist`, serial | Theorist | `p4.method`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.current_theory` | `p4.theory_audit`, `p4.theory_handoff` |
| `p4.lead`, serial | Research lead | `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.theory_audit`, `p4.theory_handoff` | `p4.empirical_index_candidate`, `p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`, `p4.attention_items`, `p4.decision` |

`p4.protocol` uses `empirical-protocol.schema.json`. The analyst fixes its
prespecified fields before outcome inspection and appends later departures as
deviations. The protocol, syntheses, audits, and handoffs remain run-local.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p4.append_evidence` | `p4.evidence` | Append immutable evidence to `p4.evidence_history` |
| `p4.replace_evidence_index` | `p4.empirical_index_candidate` | Replace `p4.empirical_evidence_index.current` |
| `p4.replace_empirical_synthesis` | `p4.empirical_synthesis_candidate` | Replace `p4.empirical_synthesis.current` |
| `p4.replace_implementation_record` | `p4.implementation_record_candidate` | Replace `p4.implementation_record.current` |
| `p4.replace_phase_decision` | `p4.decision` | Replace `p4.phase_decision.current` |
| `p4.append_attention_items` | `p4.attention_items` | Append to `project.attention_history` |

## Phase 5: Manuscript Assembly and Revision

Contract: `P5@2.0.0`

Modes:

- `p5.assembly`: assemble or update a complete manuscript from the exact current
  Phase 1 through Phase 4 basis
- `p5.review_revision`: freeze a complete current manuscript, obtain three
  isolated reviews, disposition their findings, and publish a complete revision

User choices: `p5.selected_method` and `p5.instructions`, required;
`p5.selected_history`, optional.

Formal inputs in both modes are `p5.project_brief`, `p5.literature_library`,
`p5.literature_synthesis`, `p5.literature_coverage`, `p5.method_catalog`, and
exact-match `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, and
`p5.implementation_record`.

`p5.current_manuscript` is required in review-revision and optional in assembly.
It must use the same stable method lineage but may refer to an older method
version. `p5.review_issue_ledger` is included when a current same-lineage ledger
exists.

### Assembly mode

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p5.assembly_lead`, serial | Research lead | `p5.project_brief`, `p5.literature_library`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.current_manuscript` | `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report`, `p5.attention_items`, `p5.decision` |

`p5.manuscript_candidate` uses `manuscript-package.schema.json` and points to
the complete readable manuscript artifact. No reviewer participates.

### Review-revision mode

The harness constructs immutable `p5.review_packet` from the current manuscript,
literature library, and reviewer-facing instructions. This scientific prepared
input differs from the infrastructure `PreparedRoleContext` used for every role.

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p5.parallel_reviews`, parallel | Theorist | `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.implementation_record`, `p5.literature_synthesis` | `p5.theory_audit` |
| `p5.parallel_reviews`, parallel | Data analyst | `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis` | `p5.empirical_audit` |
| `p5.parallel_reviews`, parallel | Outside reviewer | `p5.review_packet` | `p5.outside_review` |
| `p5.revision_lead`, serial | Research lead | `p5.project_brief`, `p5.literature_library`, `p5.current_manuscript`, `p5.review_issue_ledger`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review` | `p5.review_issues`, `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.revision_account`, `p5.attention_items`, `p5.decision` |

The specialist audits are arrays of open `ReviewFinding` objects using
`review-finding.schema.json`. The outside review is one `ReviewReport` using
`review-report.schema.json`. Reviewers do not disposition findings. The revision
lead converts every open finding into a dispositioned `ReviewIssue`, writes the
complete revised `ManuscriptPackage`, and preserves unresolved disagreement.

### Publication effects

| Binding | Mode and run-local source | Formal effect |
|---|---|---|
| `p5.publish_assembly_manuscript` | Assembly: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report` | Deterministically bundle and replace `p5.manuscript.current` |
| `p5.publish_reviewed_manuscript` | Review-revision: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review`, `p5.review_issues`, `p5.revision_account` | Deterministically bundle and replace `p5.manuscript.current` |
| `p5.append_review_issues` | Review-revision `p5.review_issues` | Append to `p5.review_issue_history` |
| `p5.replace_review_issue_ledger` | Review-revision `p5.review_issues` and prior ledger when present | Deterministically replace `p5.review_issue_ledger.current` |
| `p5.replace_phase_decision` | Both modes: `p5.decision` | Replace `p5.phase_decision.current` |
| `p5.append_attention_items` | Both modes: `p5.attention_items` | Append to `project.attention_history` |

`p5.review_packet` and all original role outputs remain immutable run-local
provenance even when the formal manuscript bundle references them.

## Cross-phase checks

- P1 grows the source collection and replaces its current assessment.
- P2 has full-catalog, focused-method, and researcher-proposal modes. The user,
  not P2, selects later work.
- P3 and P4 are parallel research directions after P2. Either may run first.
- P3 replaces one complete `TheoryRecord`; revision may weaken or retract.
- P4 appends evidence and replaces its complete current index, synthesis,
  implementation, and decision. Its scopes do not encode chronology.
- P5 requires the exact current Phase 1 through Phase 4 basis and replaces one
  complete `ManuscriptPackage`.
- No phase treats the latest attempted run as formal or starts another phase
  automatically.
