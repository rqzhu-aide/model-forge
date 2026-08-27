# Phase 4: Empirical Evaluation

## 1. Purpose

Phase 4 builds and maintains the empirical and computational evidence base for one user-selected method. It evaluates implementation fidelity, statistical behavior, robustness, comparison with alternatives, and consistency between observed results and the method's stated claims.

Phase 4 is parallel in pipeline status to Phase 3. It may run immediately after Phase 2 and does not require Phase 3 to have run. The phase enables the user to judge what the current evidence supports, which evidence remains applicable, and what computation or analysis a rerun should address.

## 2. User choices

Before launch, the user chooses:

- One active method and its exact current version
- Preliminary or comprehensive scope
- Additional empirical, computational, or scientific instructions
- Optional current project context
- Whether to include selected historical Phase 3, Phase 4, or other run material

Preliminary scope targets a small set of decisive checks, implementation verification, and feasibility evidence. Comprehensive scope targets a prespecified full evaluation including relevant comparisons, sensitivity analyses, and robustness checks. Either scope may be selected on any run; scope is not determined by run number.

Current aligned records are included by default. Historical runs are excluded unless selected. After completion, the user decides whether to rerun Phase 4, run Phase 3, return to Phase 2, defer, or proceed when Phase 5 is eligible.

## 3. Prerequisites

A run requires:

- A current project research brief
- A validated current Phase 1 literature basis
- A current Phase 2 method catalog
- One active selected method with an exact stable ID, version, and mathematical-definition digest

A Phase 3 record is optional. The prior Phase 4 evidence index, empirical synthesis, and implementation record are absent on the first run and required together as current context on a rerun for the same exact method identity. A negative or inconclusive prior empirical outcome does not block a rerun. A retired, withdrawn, or noncurrent method selection blocks preparation, and an older method version cannot be selected as the current target.

## 4. Frozen inputs

The run basis freezes:

- The exact selected method record, stable ID, version, and definition digest
- The current project brief and Phase 1 literature basis
- The current Phase 2 catalog generation and method provenance
- The current Phase 4 evidence index, empirical synthesis, and implementation record for this exact method identity, if they exist
- The current Phase 3 theory record and empirically testable implications for this exact method identity, if they exist
- Current cross-phase alignment, dependency, and unresolved-issue records
- Preliminary or comprehensive run scope
- User instructions and optional current context
- Exact historical records selected by the user
- Role instruction, knowledge, skill, tool, data-access, and execution-environment manifests

Current records for another method version are excluded from current context and may appear only as selected history.

## 5. Role order

The role order is fixed.

1. The data analyst performs the primary Phase 4 work. The analyst states the evaluation protocol, implements or verifies the exact selected method, executes the authorized scope, and produces the candidate evidence records and synthesis.
2. The theorist receives the frozen basis and analyst output, then checks mathematical fidelity, correspondence between implementation and definition, interpretation of comparisons, and consistency with current theory when available.
3. The research lead receives the frozen project, literature, method catalog, selected method, prior empirical, and available theory basis together with both role outputs, resolves or exposes disagreements, and produces the candidate formal empirical record and user decision summary. Before sealing, the lead performs the in-house scientific check: every claim in the empirical record and handoff is linked to its supporting evidence or theory record, or recorded as a limitation or open question. An unlinked or unsupported claim is the lead's defect to resolve in-house, never the outside reviewer's discovery.

Each handoff states what was computed, the exact method and configuration used, what changed, what the evidence supports, and what the next role must verify. There is no silent repair loop. If implementation fidelity or evidence validity remains unresolved, the lead reports it and gives the user an exact rerun question. The outside reviewer does not participate in Phase 4.

## 6. Run-local outputs

The active run workspace must contain:

- A scope-appropriate evaluation protocol and analysis plan
- Source code or exact code references with immutable digests
- Data, simulation mechanism, benchmark, and preprocessing identities
- Configuration, tuning, random-seed, dependency, and execution-environment records
- Immutable primary outputs, tables, figures, logs, and diagnostic artifacts
- Structured evidence records with stable evidence IDs
- An analyst synthesis distinguishing new evidence from previously current applicable evidence
- A theorist audit with stable issue IDs and explicit method-fidelity findings
- Claim-to-evidence links and limitations
- A candidate current evidence index
- A candidate current empirical synthesis
- A candidate current implementation and reproducibility record
- A structured candidate phase decision with an exact rerun question

Every evidence item identifies whether it evaluates the selected method, a baseline, an ablation, or a sensitivity case. Agents may not overwrite formal evidence or the current evidence index directly.

## 7. Machine validation

Before promotion, the system verifies that:

- The required analyst, theorist, and lead outputs exist in the stated order
- Every selected-method computation records the frozen stable method ID, version, and definition digest
- The protocol maps calculation-defining method components to implementation and configuration records
- Evidence concerning a baseline or ablation is labeled separately and cannot satisfy selected-method fidelity
- Every evidence item has a unique stable ID, source run, code digest, data or simulation identity, configuration, seed policy, environment identity, and output locations
- All artifact links and recorded digests resolve
- Preliminary and comprehensive runs satisfy their distinct required-scope schemas
- The current evidence index contains only evidence eligible for the exact current method identity
- Superseded, outdated, withdrawn, invalid, and unresolved evidence remains explicit and is not silently deleted
- Claims in the empirical synthesis link to eligible evidence or are labeled as interpretation
- The theorist's fidelity issues have dispositions or acknowledged unresolved states in the lead synthesis
- All writes remain inside the active run workspace

Machine validation establishes reproducibility metadata, exact identity, traceability, and record consistency. It cannot determine whether the study design is scientifically sufficient, whether a result is credible, or whether an empirical conclusion generalizes.

## 8. Scientific assessment boundary

The data analyst owns study design, implementation, computation, data provenance, measurement, missingness, leakage, batch effects, uncertainty, and first interpretation of empirical behavior. The theorist owns the independent assessment of mathematical fidelity and consistency with stated theoretical implications. The research lead owns integrated scientific interpretation, biological or substantive relevance, external validity, and communication of disagreement.

Evidence may support, partially support, contradict, fail to distinguish, or leave a claim untested. Negative or inconclusive results remain part of the cumulative evidence record. They are scientific outcomes, not failed runs. Evidence becomes current only when both its authority and exact-method applicability are explicit.

## 9. Promotion rule

After validation, promotion is one atomic operation with two effects:

1. Append new immutable evidence records and their primary artifact references to the method's cumulative evidence history. Existing evidence artifacts are never overwritten.
2. Replace four current generations for the exact selected method identity: the evidence index, empirical synthesis, implementation record, and phase decision.

The protocol, role handoffs, and detailed run artifacts remain immutable run provenance referenced by the promoted records. They do not create additional current Phase 4 slots.

The current index may retain previously promoted evidence when it uses the exact method identity and the lead still assesses it as applicable. It excludes evidence that is outdated, superseded, withdrawn, invalid, or unresolved for current claims, while preserving that evidence in history. If promotion fails, no evidence is appended and the previous current index remains unchanged.

## 10. Formal current record

The formal Phase 4 view for a method consists of its cumulative immutable evidence registry and four current slots:

- The evidence index for the exact method identity, including explicit evidence exclusions
- The empirical synthesis, including claim-to-evidence links, method-fidelity findings, limitations, and unresolved attention items
- The implementation record, including current code, configuration, environment, and reproducibility references
- The phase decision, including the compact lead summary and meaningful user choices

Each current generation identifies its source run and frozen basis. The publication receipt proves that all four slots were committed atomically.

Downstream phases use the current evidence index and synthesis by default. They do not treat the latest attempted run as the current scientific record.

## 11. Invalidation effects

A change to the method's mathematical-definition digest makes every selected-method computation for the previous version inapplicable to the new version. The latest Phase 4 generation remains current in derived position, while an authority event sets its derived alignment to `outdated` until a successful P4 rerun replaces it. Earlier evidence remains formal and traceable but cannot be reclassified as compatible or included as selected-method evidence for the new version. Selected-method results must be recomputed under the exact new definition and receive new evidence IDs. Baseline, data, or code artifacts may be reused when justified, but they cannot substitute for exact-version evidence.

A new Phase 3 record with the same exact method identity creates research attention when it changes a theoretical claim, assumption, boundary case, or empirical implication connected to existing evidence. It does not automatically create method-identity misalignment.

Publication of a new Phase 4 record appends an authority event that marks the current Phase 5 manuscript outdated. It marks Phase 3 for research attention when current evidence contradicts or materially narrows a theory statement. No event launches a rerun automatically.

## 12. UI projection

The Phase 4 tab displays:

- A read-only list of active feasible methods from Phase 2
- A selected-method panel with purpose, mathematical definition, exact version, assumptions, and provenance
- Preliminary and comprehensive scope controls available on every run
- Whether a current Phase 4 record exists for the exact method identity
- Authority and exact-method alignment
- Counts of current applicable, outdated, superseded, invalid, and unresolved evidence
- Empirical outcome, strongest findings, uncertainty, and limitations
- Research-attention items from theory or evidence conflict
- What changed in the current evidence synthesis
- The exact question a rerun would answer
- Controls for instructions, optional context, and selected history
- A user-controlled Run or Rerun action

The UI distinguishes the current cumulative record from the latest run attempt and displays alignment, scientific outcome, and research attention separately.

## 13. Acceptance criteria

- Given an active method with no Phase 3 or Phase 4 record, when a valid preliminary Phase 4 run is promoted, then a current evidence index is created without requiring Phase 3.
- Given an existing current evidence index, when a valid rerun is promoted, then new evidence is appended and previously applicable evidence is retained unless explicitly reclassified.
- Given any run number, when the user selects preliminary or comprehensive scope, then preparation uses the selected scope rather than inferring it from chronology.
- Given a current aligned Phase 3 record, when Phase 4 runs, then its identity and empirical implications are frozen for the theorist and lead.
- Given a selected-method computation with a mismatched definition digest, when validation runs, then that evidence cannot enter the current evidence index and the run cannot claim exact implementation fidelity.
- Given a baseline using another method, when it is labeled and fully identified, then it may be preserved as comparison evidence but cannot satisfy selected-method evidence requirements.
- Given a mathematical method change, when the new method version becomes current, then evidence for the previous version is excluded from current applicability for the new version.
- Given an inconclusive or negative result with complete provenance, when validation and promotion succeed, then it remains visible as a current scientific outcome.
- Given no history selection, when a rerun is prepared, then older run workspaces are absent and the current cumulative evidence record is used.
- Given invalid output or an interrupted promotion, when the project is read, then the earlier current evidence index remains complete and unchanged.
- Given a successful run, when next actions are displayed, then the system waits for the user's decision and starts no Phase 3, Phase 5, or rerun automatically.
