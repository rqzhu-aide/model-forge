# Phase 2: Method Catalog

## 1. Purpose

Phase 2 develops and maintains a structured catalog of feasible methods grounded in the current literature basis. It defines each method precisely enough for later theoretical and empirical work, records the method's provenance and revision lineage, and compares its scientific opportunities and risks.

Phase 2 presents possible methods. It does not select a branch for Phase 3 or Phase 4. That selection remains a later user action.

## 2. User choices

Before launch, the user chooses:

- Full-catalog mode, which may add or update multiple methods
- Focused-method mode, which may update only one selected existing method
- Additional scientific instructions
- Optional current project context
- Whether to include selected historical run material

In focused-method mode, the selected stable method ID is mandatory. Current formal records are included by default, and history is excluded unless selected. After completion, the user decides whether to rerun Phase 2, retire or reactivate a method through an explicit catalog action, or select a method in Phase 3 or Phase 4.

## 3. Prerequisites

Every run requires:

- A current project research brief
- A validated current Phase 1 literature basis
- The current method catalog, if one exists

Focused-method mode additionally requires an active or explicitly reactivatable method with the selected stable ID. Scientific disagreement or a weak method assessment does not block a full-catalog run. A missing or outdated Phase 1 formal record blocks preparation.

## 4. Frozen inputs

The run basis freezes:

- The exact current project brief
- The current Phase 1 literature library, synthesis, and coverage generation identities
- The current method catalog generation
- Current method records within the selected scope
- Full-catalog or focused-method mode
- The selected stable method ID in focused mode
- User instructions and optional current context
- Exact historical records selected by the user
- Role instruction, knowledge, skill, and tool manifests

The system computes and records the input digests before work starts. Later Phase 1 or catalog changes do not alter the active run.

## 5. Role order

Phase 2 has three stages.

1. The research lead, theorist, and data analyst independently generate method proposals or scoped revisions from the same frozen basis. They do not see one another's in-run proposals before submitting their own.
2. The theorist and data analyst cross-review all in-scope proposals against the frozen project, literature, and catalog basis. The theorist examines mathematical definition, assumptions, identifiability, and inferential claims. The data analyst examines implementability, study design, data requirements, computational behavior, and empirical distinguishability.
3. The research lead receives the frozen project, literature, and catalog basis together with the independent proposals and cross-reviews, reconciles disagreements, and produces the candidate catalog update and user decision record.

The lead may recommend later investigation or retirement but cannot choose the user's Phase 3 or Phase 4 branch. The outside reviewer does not participate in Phase 2.

## 6. Run-local outputs

The active run workspace must contain:

- Independent proposal reports from the lead, theorist, and data analyst
- The theorist and data analyst cross-review reports
- Candidate structured method records within the authorized scope
- A catalog change set with additions, revisions, unchanged records, and retirement recommendations
- For each method, an authoritative mathematical definition, stable ID, version, definition digest, whole-record digest, and lineage
- Literature provenance linking method motivation and claims to Phase 1 references
- Assumptions, target or estimand, calculation-defining equations, algorithm, tuning definitions, constraints, and intended scope
- Feasibility, novelty, theoretical-risk, empirical-risk, and biological or substantive relevance assessments
- Open questions and proposed P3 and P4 investigations
- A compact lead comparison and structured user decision record

In focused-method mode, candidate changes to any other method are prohibited. Substantially different alternatives may be recorded as recommendations for a future full-catalog run but may not be promoted as new catalog entries.

## 7. Machine validation

Before promotion, the system verifies that:

- All required role reports and cross-reviews exist
- Every method has one unique immutable stable ID
- Every method contains the required calculation-defining mathematical section
- The definition digest is computed only from the normalized authoritative mathematical definition
- The whole-record digest is recorded separately from the definition digest
- A changed definition digest advances the monotonically increasing method version by one revision and records an explicit revision reason
- An unchanged definition digest does not create a mathematical version solely because prose or metadata changed
- Every source supporting a formal material claim resolves to the frozen Phase 1 basis; unresolved new literature remains run-local and creates a Phase 1 attention item
- Focused-method mode changes no record outside the selected stable ID
- Method retirement is either a recommendation or an explicitly user-authorized catalog action
- Catalog references, lineage links, and parent-child relationships resolve without cycles or missing identities
- The complete change set is contained within the active run workspace

Machine validation cannot determine that a method is novel, mathematically correct, useful, feasible, or biologically meaningful.

## 8. Scientific assessment boundary

The theorist owns assessment of mathematical coherence, assumptions, identifiability, and claim plausibility. The data analyst owns assessment of implementation, measurement, data requirements, computation, and empirical discriminability. The research lead owns synthesis of scientific importance, biological or substantive interpretation, portfolio distinctness, and unresolved disagreement.

Feasibility and novelty are scientific assessments, not machine validation states. A method may be promoted with a negative, partial, contested, or inconclusive assessment if the record states that outcome accurately. Promotion makes the record current; it does not certify the method as correct or preferred.

## 9. Promotion rule

After successful validation, the system atomically applies the scoped catalog change set.

- Full-catalog mode may add methods and replace current records for multiple existing methods.
- Focused-method mode may replace only the current record for the selected stable method ID.
- A mathematically changed method advances its monotonically increasing version by one revision under the same stable ID. If the scientific object is genuinely distinct, a future full-catalog run must create a new stable ID and lineage link.
- Previous method versions and catalog generations remain historical.
- Retirement preserves the complete record and history while removing the method from the default active set.

If any promotion step fails, the current catalog and all current method pointers remain unchanged.

## 10. Formal current record

The formal Phase 2 record consists of:

- The current method catalog generation
- One current structured record for each active or retired stable method ID
- Exact version and definition identity for every method
- Method revision and retirement lineage
- Per-method literature provenance
- Comparative scientific assessments and open questions
- Current P3 and P4 investigation suggestions
- The current user decision record
- A manifest linking the catalog generation to its source run and Phase 1 basis

No field in this record selects a method on the user's behalf.

## 11. Invalidation effects

A changed mathematical definition digest creates a new exact method identity. The latest P3, P4, and P5 generations remain current in derived position, but publication appends authority events that set their derived alignment to `outdated` for the new version and require reassessment. Only a successful replacement run moves a prior current generation to history. No rerun starts automatically.

Changes limited to prose, presentation, non-calculation metadata, or literature annotation do not create mathematical misalignment. They may create research attention when they alter interpretation, scope, or claimed novelty.

Retiring a method prevents new default launches for that method but does not delete its theory, evidence, manuscript, or history. Reactivation is an explicit user action. A newly promoted catalog never selects a branch or launches Phase 3 or Phase 4.

## 12. UI projection

The Phase 2 tab displays:

- The current method catalog, including an empty state before the first successful run
- Stable method ID, name, version, definition identity, and lifecycle status
- Compact method purpose and mathematical summary
- Literature provenance and last successful update
- Feasibility, novelty, main assumptions, principal risks, and unresolved questions
- Separate P3 and P4 authority, alignment, research-attention, and scientific-outcome indicators
- What changed in the latest current catalog generation
- Controls for full-catalog or focused-method scope, instructions, optional context, and selected history
- User actions to Run, Rerun, retire, or reactivate within their authorized conditions

The table does not select the method for later work. Method selection occurs in the Phase 3 or Phase 4 tab.

## 13. Acceptance criteria

- Given an empty catalog and a current Phase 1 basis, when a valid full-catalog run is promoted, then all validated methods appear in the current catalog and no method is selected for a later phase.
- Given an existing catalog, when a full-catalog rerun is promoted, then the scoped change set applies atomically and unchanged method identities remain stable.
- Given focused-method mode, when a valid revision is promoted, then only the selected stable method ID changes.
- Given focused-method mode, when an output attempts to add or alter another method, then validation rejects the run and the catalog remains unchanged.
- Given a mathematical definition change, when promotion succeeds, then the method version and definition digest change and dependent P3, P4, and P5 records require reassessment.
- Given only a prose clarification, when promotion succeeds, then the definition digest remains unchanged and mathematical alignment is preserved.
- Given an attempted duplicate stable ID, when validation runs, then the run is rejected before promotion.
- Given a retirement recommendation without explicit user authorization, when promotion succeeds, then the recommendation is recorded but the method remains active.
- Given no history selection, when a run is prepared, then role context includes current formal records but no prior run workspace.
- Given selected historical material, when a run is prepared, then only the selected identities appear in the frozen basis.
- Given invalid or incomplete output, when validation fails, then the prior catalog remains current.
- Given a successful Phase 2 run, when the UI displays possible methods, then Phase 3 and Phase 4 remain user-launched and no branch begins automatically.
