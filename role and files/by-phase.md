# Files and Roles by Research Phase

This page is the phase-by-phase cross-check of who reads and writes each
research object. The executable sources are
`architecture/contracts/phases/P1.json` through `P5.json`, all at contract
version `2.0.0`. The IDs below are contract IDs, not required physical
filenames.

## How to read this page

Every role output is first written inside that role's active run workspace. A
completed role workspace is closed before a later role can use its output. The
harness verifies the output, records its digest, and exposes an accepted
run-local reference to only the declared downstream roles.

A run-local candidate becomes a formal project record only through a declared
publication binding after submission and validation. Roles never write to the
formal project store. A failed, rejected, cancelled, or conflicted run leaves
the prior formal records unchanged.

Historical records are excluded by default in every phase. They enter a run
only when the user explicitly selects them through that phase's
`selected_history` choice. Selected history supplements the declared current
basis. It does not become current merely because a role reads it.

## Phase 1: Literature Basis

Contract: `P1@2.0.0`

Run mode: `p1.literature_update`

User choices:

- `p1.scope`, required: `broad_update` or `focused_update`
- `p1.instructions`, required
- `p1.selected_history`, optional

The broad or focused search setting is a user choice within the literature
update mode, not a separate run mode.

Formal inputs:

- `p1.project_brief`, always required
- `p1.current_library`, required on a rerun and absent on the first run
- `p1.current_synthesis`, required on a rerun and absent on the first run
- `p1.current_coverage`, required on a rerun and absent on the first run

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p1.discovery`, parallel | Research lead | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.lead_discovery` |
| `p1.discovery`, parallel | Theorist | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.theory_discovery` |
| `p1.discovery`, parallel | Data analyst | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage` | `p1.empirical_discovery` |
| `p1.lead_synthesis`, serial | Research lead | `p1.project_brief`, `p1.current_library`, `p1.current_synthesis`, `p1.current_coverage`, `p1.lead_discovery`, `p1.theory_discovery`, `p1.empirical_discovery` | `p1.source_changes`, `p1.synthesis_candidate`, `p1.coverage_candidate`, `p1.phase2_handoff`, `p1.attention_items`, `p1.decision` |

The three discovery roles start from the same frozen basis and cannot see one
another's current-run reports before closing their work. The outside reviewer
does not participate.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p1.append_literature_sources` | `p1.source_changes` | Append unique source records to `p1.literature_sources` |
| `p1.rebuild_literature_library` | `p1.source_changes`, with prior `p1.current_library` when present | Deterministically replace `p1.literature_library.current` |
| `p1.replace_literature_synthesis` | `p1.synthesis_candidate` | Replace `p1.literature_synthesis.current` |
| `p1.replace_literature_coverage` | `p1.coverage_candidate` | Replace `p1.literature_coverage.current` |
| `p1.replace_phase_decision` | `p1.decision` | Replace `p1.phase_decision.current` |
| `p1.append_attention_items` | `p1.attention_items` | Append to `project.attention_history` |

The three discovery reports and `p1.phase2_handoff` remain run-local
provenance. Phase 2 reads the promoted literature library, synthesis, and
coverage, not a mutable handoff or the latest attempted Phase 1 run.

## Phase 2: Method Catalog

Contract: `P2@2.0.0`

Run modes:

- `p2.full_catalog`, which may add methods or update multiple methods
- `p2.focused_method`, which may reassess exactly one selected stable method

User choices:

- `p2.instructions`, required in both modes
- `p2.selected_method`, required only in `p2.focused_method`
- `p2.selected_history`, optional

Formal inputs:

- `p2.project_brief`, always required
- `p2.literature_synthesis`, always required
- `p2.literature_library`, always required
- `p2.literature_coverage`, always required
- `p2.current_catalog`, required after the first catalog run and absent on the
  first run

The two modes use the same role sequence. Their difference is publication
scope. Focused mode cannot change another method or add a different method.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p2.independent_proposals`, parallel | Research lead | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog` | `p2.lead_proposal` |
| `p2.independent_proposals`, parallel | Theorist | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog` | `p2.theory_proposal` |
| `p2.independent_proposals`, parallel | Data analyst | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog` | `p2.empirical_proposal` |
| `p2.cross_review`, parallel | Theorist | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal` | `p2.theory_review` |
| `p2.cross_review`, parallel | Data analyst | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal` | `p2.empirical_review` |
| `p2.lead_reconciliation`, serial | Research lead | `p2.project_brief`, `p2.literature_synthesis`, `p2.literature_library`, `p2.literature_coverage`, `p2.current_catalog`, `p2.lead_proposal`, `p2.theory_proposal`, `p2.empirical_proposal`, `p2.theory_review`, `p2.empirical_review` | `p2.method_changes`, `p2.attention_items`, `p2.decision` |

The proposal roles cannot see one another's current-run proposals until all
three proposals close. The two cross-review roles receive the same accepted
proposal set and cannot see one another's current-run review before closure.
The outside reviewer does not participate.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p2.upsert_method_records` | `p2.method_changes` | Upsert complete method records in `p2.method_records` |
| `p2.rebuild_method_catalog` | `p2.method_changes`, with prior `p2.current_catalog` when present | Deterministically replace `p2.method_catalog.current` |
| `p2.replace_phase_decision` | `p2.decision` | Replace `p2.phase_decision.current` |
| `p2.append_attention_items` | `p2.attention_items` | Append to `project.attention_history` |

The three proposals and two cross-reviews remain run-local provenance. The
formal method records and catalog contain the lead's reconciled change set.
The lead may compare or recommend methods, but the user selects the method for
Phase 3 or Phase 4.

## Phase 3: Theory Development

Contract: `P3@2.0.0`

Run mode: `p3.theory_update`

User choices:

- `p3.selected_method`, required
- `p3.instructions`, required
- `p3.selected_history`, optional

Formal inputs:

- `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, and
  exact-match `p3.method`, always required
- Exact-match `p3.current_theory`, required on a rerun for the same exact
  method identity and absent on the first run
- Exact-match `p3.current_empirical_index`, `p3.current_empirical`, and
  `p3.current_implementation`, included when aligned Phase 4 records exist

Phase 4 is not a prerequisite. Records for another method version are not
current inputs and may enter only as user-selected history.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p3.theorist`, serial | Theorist | `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical` | `p3.theory_candidate`, `p3.theory_handoff` |
| `p3.analyst`, serial | Data analyst | `p3.method`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation` | `p3.analyst_audit`, `p3.analyst_handoff` |
| `p3.lead`, serial | Research lead | `p3.project_brief`, `p3.literature_synthesis`, `p3.method_catalog`, `p3.method`, `p3.current_theory`, `p3.current_empirical_index`, `p3.current_empirical`, `p3.current_implementation`, `p3.theory_candidate`, `p3.theory_handoff`, `p3.analyst_audit`, `p3.analyst_handoff` | `p3.complete_theory`, `p3.attention_items`, `p3.decision` |

Each later role starts only after the required earlier role closure succeeds.
There is no hidden repair loop. Unresolved mathematical or empirical concerns
remain explicit for the user's next run. The outside reviewer does not
participate.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p3.replace_theory_record` | `p3.complete_theory` | Replace `p3.theory_record.current` for the exact method identity |
| `p3.replace_phase_decision` | `p3.decision` | Replace `p3.phase_decision.current` |
| `p3.append_attention_items` | `p3.attention_items` | Append to `project.attention_history` |

`p3.theory_candidate`, both handoffs, and `p3.analyst_audit` remain run-local
provenance. The formal theory is the lead's complete integrated record, not the
theorist's draft alone.

## Phase 4: Empirical Evaluation

Contract: `P4@2.0.0`

Run modes:

- `p4.preliminary`, a small set of decisive feasibility and diagnostic checks
- `p4.comprehensive`, a prespecified full evaluation with comparisons,
  sensitivity analyses, and robustness checks

User choices:

- `p4.selected_method`, required
- `p4.instructions`, required
- `p4.selected_history`, optional

Formal inputs:

- `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, and
  exact-match `p4.method`, always required
- Exact-match `p4.current_evidence_index`, `p4.current_empirical`, and
  `p4.current_implementation`, required on a rerun for the same exact method
  identity and absent on the first run
- Exact-match `p4.current_theory`, included when an aligned Phase 3 record exists

Phase 3 is not a prerequisite. The two modes have the same read and write IDs;
their required scientific scope differs. Preliminary and comprehensive are
explicit user choices, not labels inferred from run number.

### Role sequence

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p4.analyst`, serial | Data analyst | `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory` | `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff` |
| `p4.theorist`, serial | Theorist | `p4.method`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.current_theory` | `p4.theory_audit`, `p4.theory_handoff` |
| `p4.lead`, serial | Research lead | `p4.project_brief`, `p4.literature_synthesis`, `p4.method_catalog`, `p4.method`, `p4.current_evidence_index`, `p4.current_empirical`, `p4.current_implementation`, `p4.current_theory`, `p4.protocol`, `p4.evidence`, `p4.analyst_synthesis`, `p4.analyst_handoff`, `p4.theory_audit`, `p4.theory_handoff` | `p4.empirical_index_candidate`, `p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`, `p4.attention_items`, `p4.decision` |

Each later role sees only accepted earlier outputs. There is no hidden repair
loop. The outside reviewer does not participate.

### Publication effects

| Binding | Run-local source | Formal effect |
|---|---|---|
| `p4.append_evidence` | `p4.evidence` | Append immutable evidence to `p4.evidence_history` |
| `p4.replace_evidence_index` | `p4.empirical_index_candidate` | Replace `p4.empirical_evidence_index.current` |
| `p4.replace_empirical_synthesis` | `p4.empirical_synthesis_candidate` | Replace `p4.empirical_synthesis.current` |
| `p4.replace_implementation_record` | `p4.implementation_record_candidate` | Replace `p4.implementation_record.current` |
| `p4.replace_phase_decision` | `p4.decision` | Replace `p4.phase_decision.current` |
| `p4.append_attention_items` | `p4.attention_items` | Append to `project.attention_history` |

The protocol, analyst synthesis, theorist audit, and both handoffs remain
run-local provenance. The evidence items become cumulative formal objects. The
lead's three candidates become the current evidence index, synthesis, and
implementation record in one atomic publication.

## Phase 5: Manuscript Assembly and Revision

Contract: `P5@2.0.0`

Run modes:

- `p5.assembly`, which creates or updates a complete manuscript from the exact
  current upstream basis
- `p5.review_revision`, which freezes a current manuscript, obtains three
  isolated reviews, and then revises the complete manuscript

User choices:

- `p5.selected_method`, required
- `p5.instructions`, required
- `p5.selected_history`, optional

Formal inputs in both modes:

- `p5.project_brief`, `p5.literature_library`, `p5.literature_synthesis`,
  `p5.literature_coverage`, and `p5.method_catalog`
- Exact-match `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`,
  and `p5.implementation_record`

`p5.current_manuscript` is required in `p5.review_revision` and optional in
`p5.assembly`. It must belong to the same stable method lineage, but it may use
an older version of that method. `p5.review_issue_ledger` is included when it
exists for the selected lineage in review-revision mode.

### Assembly mode

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p5.assembly_lead`, serial | Research lead | `p5.project_brief`, `p5.literature_library`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.current_manuscript` | `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report`, `p5.attention_items`, `p5.decision` |

The theorist, data analyst, and outside reviewer do not participate in assembly
mode.

### Review-revision mode

During preparation, the harness constructs immutable run-local context
`p5.review_packet` from `p5.current_manuscript`, `p5.literature_library`, and
reviewer-facing `p5.instructions`. This phase-specific review packet is
different from the infrastructure `PreparedRoleContext` created for every role
invocation.

| Stage | Role | Reads | Writes |
|---|---|---|---|
| `p5.parallel_reviews`, parallel | Theorist | `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.theory`, `p5.literature_synthesis` | `p5.theory_audit` |
| `p5.parallel_reviews`, parallel | Data analyst | `p5.review_packet`, `p5.current_manuscript`, `p5.method`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis` | `p5.empirical_audit` |
| `p5.parallel_reviews`, parallel | Outside reviewer | `p5.review_packet` | `p5.outside_review` |
| `p5.revision_lead`, serial | Research lead | `p5.project_brief`, `p5.literature_library`, `p5.current_manuscript`, `p5.review_issue_ledger`, `p5.method_catalog`, `p5.method`, `p5.theory`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, `p5.literature_synthesis`, `p5.literature_coverage`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review` | `p5.review_issues`, `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.revision_account`, `p5.attention_items`, `p5.decision` |

The three reviewers assess the same frozen manuscript snapshot but have
different read allowlists. They cannot see one another's current-run reports.
The outside reviewer cannot resolve internal formal records, specialist audits,
internal deliberation, hidden memory, or later role outputs. The lead starts
only after all three review closures succeed.

### Publication effects

| Binding | Mode and run-local source | Formal effect |
|---|---|---|
| `p5.publish_assembly_manuscript` | Assembly: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.assembly_report` | Deterministically bundle and replace `p5.manuscript.current` |
| `p5.publish_reviewed_manuscript` | Review-revision: `p5.manuscript_candidate`, `p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.citation_integrity_report`, `p5.limitations_record`, `p5.theory_audit`, `p5.empirical_audit`, `p5.outside_review`, `p5.review_issues`, `p5.revision_account` | Deterministically bundle and replace `p5.manuscript.current` |
| `p5.append_review_issues` | Review-revision: `p5.review_issues` | Append to `p5.review_issue_history` |
| `p5.replace_review_issue_ledger` | Review-revision: `p5.review_issues`, with prior `p5.review_issue_ledger` when present | Deterministically replace `p5.review_issue_ledger.current` |
| `p5.replace_phase_decision` | Both modes: `p5.decision` | Replace `p5.phase_decision.current` |
| `p5.append_attention_items` | Both modes: `p5.attention_items` | Append to `project.attention_history` |

The original role outputs remain immutable in the source run even when the
formal manuscript bundle copies or references them. `p5.review_packet` remains
a run-local prepared input and is not a separate formal project record.

## Cross-phase checks

- P1 grows the source collection and replaces its current synthesis and
  coverage.
- P2 replaces the current method catalog and in-scope method records. It does
  not select a Phase 3 or Phase 4 branch for the user.
- P3 and P4 are parallel research directions after P2. Either may run first.
  Each uses an aligned sibling record only when one exists.
- P3 replaces one complete theory record. It does not publish incremental proof
  fragments.
- P4 appends immutable evidence while replacing its complete current index,
  synthesis, implementation record, and phase decision.
- P5 requires the exact current P1 through P4 basis and replaces one complete
  manuscript package. It never merges isolated paragraphs into the formal
  manuscript.
- No phase reads the latest attempted run as if it were formal. Downstream work
  reads current formal generations and explicitly selected history.
- Starting a valid run authorizes validation and publication. There is no
  separate generic approval step after the work finishes.
