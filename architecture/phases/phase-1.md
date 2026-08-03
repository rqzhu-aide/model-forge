# Phase 1: Literature Basis

## 1. Purpose

Phase 1 builds and maintains the cumulative literature basis for the research project. It discovers relevant work, verifies source identity and provenance, synthesizes the current scientific landscape, and identifies evidence gaps that affect later method development. It does not define the project method or select a later branch.

The phase enables the user to decide whether the literature basis is sufficient for Phase 2 or whether another focused literature run is needed.

## 2. User choices

Before launch, the user chooses:

- The literature question or update focus
- Search boundaries such as fields, populations, study designs, dates, or source types
- Additional scientific instructions
- Optional project context to expose to the team
- Whether to include selected historical run material

Current formal records are included by default. Historical runs are excluded unless the user selects them. After completion, the user decides whether to rerun Phase 1, refine its scope, or launch a later available phase.

## 3. Prerequisites

A run requires a current project research brief that states the scientific problem and intended scope. The first Phase 1 run requires no earlier phase record. A rerun requires access to the current literature registry so that discovery remains cumulative and duplicate searches or references can be recognized.

A favorable prior assessment is never a prerequisite. Missing or unreadable required current records block preparation rather than causing the system to construct an implicit replacement.

## 4. Frozen inputs

The run basis freezes:

- The exact current project research brief and its digest
- The current cumulative literature registry generation, if one exists
- The current literature synthesis and coverage record, if they exist
- User instructions and search boundaries
- Optional current project context selected by the user
- Exact historical records selected by the user
- Role instruction, knowledge, skill, and tool manifests used for the run

The run basis records which inputs were absent because this is the first run. Later changes to the project or literature registry do not alter an active run.

## 5. Role order

Phase 1 has two stages.

1. The research lead, theorist, and data analyst conduct discovery in parallel. They receive the same frozen project basis but do not see one another's in-run discovery reports before submitting their own.
2. The research lead receives the frozen literature basis and all three discovery reports, resolves duplicate and conflicting findings, and produces the candidate current synthesis.

The research lead emphasizes scientific importance, biological or substantive context, and coverage of the motivating question. The theorist emphasizes mathematical foundations, assumptions, related methods, and known limits. The data analyst emphasizes study design, data sources, measurement, computation, empirical evaluation, and reproducibility. The outside reviewer does not participate in Phase 1.

## 6. Run-local outputs

The active run workspace must contain:

- One discovery report from each participating role
- Candidate reference records with stable source identifiers, bibliographic metadata, and source locators
- Search provenance, including queries, sources searched, search dates, and stated boundaries
- Duplicate, correction, retraction, and conflict decisions
- Claim-to-reference links for material statements in the synthesis
- A candidate literature synthesis that distinguishes established results, disputed results, and open gaps
- A coverage assessment describing what was and was not searched
- A lead handoff for Phase 2
- A structured user decision record

Lawfully obtained full-text material may remain as a run artifact when permitted, but a promoted reference must not depend on an untracked local file. Agents may not write directly into the formal reference library.

## 7. Machine validation

Before promotion, the system verifies that:

- All required role reports and structured records exist and match their schemas
- Every candidate reference has a stable internal ID and sufficient source identity
- Local source artifacts, when present, match their recorded digests
- Duplicate candidates have an explicit merge or separation decision
- New references do not silently overwrite existing reference records
- Corrections and retractions preserve the earlier record and add an explicit status transition
- Material synthesis statements link to one or more reference records or are labeled as team interpretation
- The coverage assessment and search provenance are complete
- Every output is contained within the active run workspace
- The candidate synthesis and decision record identify the frozen literature generation they used

Machine validation confirms identity, traceability, completeness, and consistency. It cannot establish that a paper is correct, that the search is scientifically exhaustive, or that a cited source truly supports the interpretation.

## 8. Scientific assessment boundary

The three discovery roles assess relevance and evidence from their disciplinary perspectives. The research lead owns the final synthesis, resolves or exposes disagreements, and states the limits of search coverage. Conflicting evidence must remain visible rather than being reduced to a single unsupported conclusion.

The promoted record may conclude that evidence is strong, mixed, weak, absent, or outside the searched scope. These are scientific outcomes, not run failures. A run fails only when its required operation or validation contract is not satisfied.

## 9. Promotion rule

Promotion is one atomic operation with two effects:

1. Append unique reference and provenance records to the cumulative library. Existing records are preserved; corrections, retractions, and revised metadata are represented through versioned status records.
2. Replace the current literature synthesis, coverage assessment, and user decision record with the newly validated generation.

The Phase 2 handoff remains immutable run provenance. Phase 2 consumes the promoted library, synthesis, and coverage records as its formal basis. The complete run workspace remains immutable. Supersession events give the previous synthesis a historical derived position. If any publication step fails, neither the cumulative library, authority-event journal, nor current-index slot changes.

## 10. Formal current record

The formal Phase 1 record consists of:

- The cumulative reference registry
- Current source status and provenance records
- The current literature synthesis
- The current search coverage assessment
- The current user decision record
- A manifest linking all of these objects to the source run and frozen project brief

Downstream phases use this formal record by default, not the most recent attempted run.

## 11. Invalidation effects

Adding references or replacing the literature synthesis does not automatically invalidate a method, proof, computation, or manuscript. Instead, the Phase 1 lead identifies any existing methods or claims that may require research attention.

A correction, retraction, or newly identified contradiction appends authority events that mark directly dependent claims for reassessment. It does not silently change their scientific outcome. An authority event gives Phase 5 outdated derived alignment when its recorded literature basis is no longer the current basis because the current manuscript must explicitly incorporate or disposition the changed literature record.

No Phase 1 change launches Phase 2 or any rerun automatically.

## 12. UI projection

The Phase 1 tab displays:

- Authority state of the current literature record
- Current literature generation and source run
- Total references, references added by the last successful run, and duplicate count
- Search boundaries and coverage limitations
- Compact synthesis of established findings, conflicts, and gaps
- References or downstream claims requiring research attention
- What changed from the previous current synthesis
- The exact question another Phase 1 run could answer
- Controls for instructions, search boundaries, optional context, and selected history
- A user-controlled Run or Rerun action

The UI reads structured current records. It does not infer successful completion from the presence of files in a run folder.

## 13. Acceptance criteria

- Given a project with no Phase 1 record, when a valid first run is promoted, then the reference registry is created, the synthesis becomes current, and no later phase starts.
- Given an existing current registry, when a rerun finds new sources, then only unique references are appended and the new synthesis explicitly states what changed.
- Given a source already in the registry, when another role rediscovers it, then promotion records the additional search provenance without creating a duplicate reference identity.
- Given conflicting reports about a source, when the lead cannot resolve the interpretation, then the conflict is visible in the current synthesis and decision record.
- Given a retracted source, when the retraction is validated, then the original record is preserved, its status changes explicitly, and dependent claims receive research attention.
- Given no historical context selection, when a rerun is prepared, then prior run workspaces are absent from role context and only current formal records are frozen.
- Given explicitly selected historical records, when a rerun is prepared, then their exact identities appear in the run basis and no other history is loaded.
- Given invalid candidate records, when validation fails, then the run is rejected and the prior current record remains unchanged.
- Given an interrupted promotion, when the project is read, then it exposes either the complete previous generation or the complete new generation, never a mixture.
- Given a successful run, when the UI presents next steps, then the user can choose a new action and the system launches nothing automatically.
