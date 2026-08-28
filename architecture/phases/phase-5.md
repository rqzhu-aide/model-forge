# Phase 5: Manuscript Assembly and Revision

## 1. Purpose

Phase 5 maintains one complete current manuscript for a user-selected method. It assembles the paper from exact current upstream records or revises a frozen manuscript after specialist audits and an independent outside review. It preserves traceability from manuscript claims to literature, method definition, theory, and empirical evidence.

Phase 5 does not require favorable P3 or P4 findings. It requires validated, current, exactly aligned upstream records and must represent partial, negative, contradictory, or inconclusive findings accurately. The phase enables the user to decide whether to revise again, return to an upstream phase, defer, or prepare the manuscript for submission.

## 2. User choices

Before launch, the user chooses:

- One active method and its exact current version
- Assembly mode or review-revision mode
- Additional writing, scientific, or venue instructions
- Optional current project context
- Whether to include selected historical records

Assembly mode creates or updates the complete manuscript through the research lead. Review-revision mode freezes an existing complete manuscript, obtains specialist audits and an independent outside review, and then assigns revision to the research lead.

Current aligned formal records are included by default. Historical runs are excluded unless selected. After completion, the user decides the next action. The system never submits a manuscript, launches an upstream rerun, or begins another Phase 5 run automatically.

## 3. Prerequisites

Every Phase 5 run uses one machine-checkable readiness predicate:

- The project research brief and Phase 1 literature record are formal, current, and readable.
- The selected Phase 2 method record is formal, current, and active.
- A complete Phase 3 record is formal and current for the selected stable method.
- A Phase 4 evidence index, empirical synthesis, and implementation record are formal and current for the selected stable method.
- The P3 and P4 records both name the exact current method version and mathematical-definition digest.
- All required source artifacts pass integrity checks, and no required record is withdrawn or invalid.

The complete Phase 2 catalog is contextual input. An update to another method cannot block or invalidate this manuscript. P3 and P4 do not need to have consumed one another's latest generation. Any sibling-generation drift is passed to Phase 5 as research attention for reconciliation, avoiding an endless P3 and P4 rerun cycle.

The gate distinguishes structural readiness from scientific outcome. A promoted P3 or P4 record satisfies workflow completion even when its outcome is partial, negative, contradictory, or inconclusive. Such outcomes do not block Phase 5, but the manuscript must state them faithfully. A missing record, failed integrity check, withdrawn record, noncurrent record position, or exact-method mismatch blocks preparation.

Review-revision mode additionally requires one complete formal Phase 5 manuscript within the selected stable method lineage. The review target may describe an older version of that stable method, because reconciling it with the newly frozen current basis is part of the revision. It must never come from another stable method ID. If no manuscript exists within the selected lineage, the user must run assembly mode first.

## 4. Frozen inputs

The run basis freezes:

- The current project research brief
- The current Phase 1 literature registry, synthesis, and coverage generation
- The exact selected Phase 2 method record as a hard dependency and the current catalog generation as contextual information
- The complete current Phase 3 record for the exact method identity
- The current Phase 4 evidence index, empirical synthesis, and implementation record for the exact method identity
- Current cross-phase dependencies, alignment states, research-attention items, and unresolved issues
- User-selected mode, instructions, optional context, and venue requirements
- Exact historical records selected by the user
- Researcher-supplied supplementary material seeded with the run command (for example figures or supplementary text), frozen with researcher_seed provenance; additive only and never a substitute for published records - the manuscript itself always comes from the published pipeline state
- Role instruction, knowledge, skill, and tool manifests

Review-revision mode also freezes:

- The exact complete manuscript snapshot to be reviewed and its stable method lineage
- Its prior upstream basis manifest
- `p5.review_packet`, prepared by the harness from the manuscript snapshot, submitted supplements, cited references available to an external referee, and reviewer-facing user or venue instructions
- The theorist read set: `p5.review_packet`, `p5.review_target_manuscript`, `p5.method`, `p5.theory`, and `p5.literature_synthesis`
- The data analyst read set: `p5.review_packet`, `p5.review_target_manuscript`, `p5.method`, `p5.empirical_index`, `p5.empirical`, `p5.implementation_record`, and `p5.literature_synthesis`

The outside reviewer's input allowlist contains only `p5.review_packet`. It excludes specialist audits, internal formal records, internal deliberation, hidden memory, and later role outputs. The sealed RunManifest role plan and prepared-context provenance freeze all three review-role allowlists and make reviewer independence testable.

## 5. Role order

Assembly mode has one role stage:

1. The research lead assembles or updates the complete manuscript from the frozen P1 through P4 records and produces the claim traceability and user decision records. The run is situation-driven: when no current manuscript exists for the selected stable method lineage (`p5.current_manuscript` resolves to the absent-input marker on a first run), the lead writes the first complete manuscript; when a current draft exists (a rerun, where the input is required), the lead continues that draft, preserving its structure and voice, extending it where the frozen basis now supports more, and narrowing or removing claims the basis no longer supports. Before sealing, the lead performs the in-house scientific check: every manuscript claim is linked in the claim traceability to its supporting literature, method, theory, or empirical record, or recorded as a limitation or open question. An unlinked claim is the lead's defect to resolve in-house, never the outside reviewer's discovery.

Review-revision mode has two stages:

1. The theorist, data analyst, and outside reviewer work in parallel on the same frozen manuscript snapshot. The theorist uses only its frozen mathematical read set to audit mathematical fidelity and proof reporting. The data analyst uses only its frozen empirical read set to audit implementation, empirical reporting, reproducibility, and statistical interpretation. The outside reviewer uses only `p5.review_packet` for an independent first-time-reader review.
2. After all three assessments are fixed, the research lead receives them together with the frozen upstream basis and revises the complete manuscript. The lead records a disposition for every review issue and produces the final decision summary. The lead re-verifies claim-evidence linkage across the revised manuscript before sealing, with the same in-house scientific check as assembly.

The outside reviewer never sees the specialist audits during that run. Specialist roles do not edit the manuscript directly in review-revision mode. Unresolved issues remain explicit for the user rather than causing an automatic review cycle.

## 6. Run-local outputs

Every Phase 5 run must produce within its active workspace:

- One complete candidate manuscript
- An exact upstream basis manifest
- A structured claim traceability record linking material claims to P1, P2, P3, and P4 records
- A citation and reference integrity report
- A statement of limitations, unresolved issues, and scientific scope
- A compact user decision record

Assembly mode must additionally produce a lead assembly report explaining major editorial and scientific choices.

Review-revision mode must additionally produce:

- A theorist audit with stable issue IDs
- A data analyst audit with stable issue IDs
- An independent outside-review report with stable issue IDs
- A complete issue disposition ledger using fixed, partially fixed, deferred, or rejected with justification
- A lead revision account linked to changed manuscript locations

The reviewed manuscript remains the frozen `p5.review_target_manuscript` input. The sealed RunManifest role plan and `p5.review_packet` provenance are the authoritative access manifests. The promoted manuscript package references its source run and manifest rather than duplicating them as role-produced scientific outputs.

All work remains run-local until validation and promotion. No role writes directly into the formal current manuscript location.

## 7. Machine validation

Before promotion, the system verifies that:

- The exact aligned gate was satisfied by the frozen basis
- All required mode-specific role outputs exist and respect the stated ordering
- The candidate manuscript is complete and names the exact selected method identity
- The basis manifest resolves to the frozen current P1 through P4 records
- Every central mathematical and empirical claim links to the relevant structured upstream record and primary artifact location
- Citations resolve to the frozen literature registry or are explicitly marked as unresolved and prohibited from unsupported final claims
- Reported theorem, assumption, estimate, uncertainty, comparison, and limitation statuses agree structurally with their source records
- Review-revision mode uses one immutable manuscript snapshot from the selected stable method lineage for all three assessments
- The sealed RunManifest role plan and prepared-context provenance match every frozen role read set and the exact sources of `p5.review_packet`
- The outside reviewer input allowlist contains only `p5.review_packet`, and that packet excludes internal formal records, specialist audits, deliberation, hidden memory, and later outputs
- The theorist and data analyst input allowlists exactly match their frozen role-specific read sets
- Every specialist and reviewer issue has a unique ID and a final disposition
- Deferred, partially fixed, or rejected issues remain visible in the manuscript decision record
- All writes remain inside the active run workspace

Machine validation confirms identity, completeness, access separation, traceability, and cross-record consistency. It cannot determine whether the paper is persuasive, the prose is clear, the science is correct, or a review concern has been resolved adequately.

## 8. Scientific assessment boundary

In assembly mode, the research lead owns the manuscript argument, scientific interpretation, contribution statement, limitation framing, and faithful integration of upstream outcomes. The lead also owns the in-house scientific check: claim-evidence linkage is verified before sealing, so the outside reviewer's independent audit never discovers an unlinked claim first.

In review-revision mode, the theorist owns the mathematical audit, the data analyst owns the empirical and reproducibility audit, and the outside reviewer owns an independent assessment of novelty, significance, validity, clarity, and likely reader concerns. The research lead owns the final revision and must justify every issue disposition.

The current manuscript may accurately report partial theory, negative evidence, contradictions, or unresolved uncertainty. Promotion means it is the latest validated and traceable manuscript, not that it is submission-ready or scientifically favorable.

## 9. Promotion rule

After validation, the system atomically replaces the complete formal current Phase 5 manuscript package for the selected method. The promoted package includes the manuscript, exact basis manifest, claim traceability, limitations, mode-specific audit or assembly records, issue dispositions, and user decision record.

A supersession event gives the previous complete manuscript generation a historical derived position, and the generation remains linked to its immutable source run. Phase 5 never merges individual paragraphs into the formal manuscript outside this complete-package replacement. If promotion fails, the previous complete manuscript remains current.

## 10. Formal current record

The formal Phase 5 record for a method consists of:

- One complete current manuscript
- Exact P1 through P4 basis identities
- Claim-to-source traceability
- Current citation and reference integrity state
- Current limitations and unresolved issues
- The most recent assembly or review-revision account
- Current review issue dispositions, when applicable
- The current user decision record
- A manifest linking the package to its source run

Earlier manuscript packages remain historical but are not loaded into later runs unless selected, except that the current manuscript is necessarily frozen as the target of review-revision mode.

## 11. Invalidation effects

Any change to a formal upstream record included in the current manuscript basis appends an authority event that marks the Phase 5 manuscript outdated until the user runs Phase 5 again. A changed method-definition digest additionally creates exact-method misalignment. Changes to theory, evidence, or literature may leave the prior prose factually useful, but the old manuscript cannot remain the formal current account of the new basis without reassessment.

A newly promoted Phase 5 record has no automatic upstream invalidation effect. Its decision record may request research attention in P1, P2, P3, or P4 and must state the exact question an upstream rerun would answer. No rerun or submission starts automatically.

## 12. UI projection

The Phase 5 tab displays:

- The selected method and exact current identity
- An exact aligned gate checklist for P1 through P4
- Separate authority, alignment, research-attention, and scientific-outcome states
- Assembly and review-revision mode controls with clear eligibility explanations
- Current manuscript status, source run, basis generation, and what changed
- Principal contribution, strongest evidence, limitations, and unresolved issues
- Review issue counts and dispositions in review-revision mode
- Whether the current manuscript is outdated and which upstream record changed
- The exact question another Phase 5 or upstream run would answer
- Controls for instructions, optional context, and selected history
- User-controlled Run or Rerun actions

The UI never labels a manuscript submission-ready solely because its run completed. Submission readiness is a distinct scientific and user decision.

## 13. Acceptance criteria

- Given a current P1 record, an active current selected method, and formal current P3 and P4 records for the exact method identity, when a valid assembly run is promoted, then one complete manuscript package becomes current and no reviewer stage is created.
- Given a partial or negative but validated current P3 or P4 outcome, when the exact aligned gate is evaluated, then the outcome does not block Phase 5 and the manuscript must preserve its limitations.
- Given a missing, outdated, invalid, or method-misaligned P3 or P4 record, when the user attempts launch, then preparation is blocked with the exact unmet prerequisite and no run starts.
- Given an existing complete manuscript within the selected stable method lineage, when review-revision mode starts, then the theorist, analyst, and outside reviewer receive the same immutable manuscript snapshot through their distinct frozen read sets.
- Given review-revision mode, when the outside reviewer works, then it can resolve only `p5.review_packet` and cannot resolve internal specialist or project records.
- Given completed specialist audits and outside review, when lead revision begins, then the lead receives all fixed issue records and every issue receives a final disposition.
- Given an outdated current manuscript from an older version of the selected stable method and newly aligned current P1 through P4 records, when review-revision mode is selected, then the old manuscript may be frozen as the review target and the lead revision must bind the candidate manuscript to the exact new upstream basis.
- Given a manuscript associated with another stable method ID, when review-revision preparation resolves the target, then preparation is blocked before any reviewer role starts.
- Given a central claim with no resolvable upstream support, when validation runs, then promotion is rejected or the claim must be explicitly removed or narrowed before promotion.
- Given an upstream record change after promotion, when project status is recomputed, then the Phase 5 manuscript is marked outdated and remains preserved.
- Given invalid output or interrupted promotion, when the project is read, then the earlier complete manuscript package remains current.
- Given a successful Phase 5 run, when the UI presents next steps, then submission and all reruns remain explicit user actions.
