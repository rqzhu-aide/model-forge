# Stage+Role Instruction Templates for P1, P3, P4, P5

Status: Ready for implementation
Prepared: 2026-08-08

Scope: Create stage+role-specific instruction templates for Phases P1, P3, P4,
and P5, matching the existing P2 pattern. P2 is complete and serves as the
format reference. No contract, schema, or code changes are required - the
template loader (`src/model_forge/application/default_instructions.py`) already
supports stage+role templates; this work only adds the missing template files.

## 1. Goal in one sentence

Give every role in every stage of P1, P3, P4, and P5 its own directive: a
stage-scoped instruction that says exactly what that role must do in that
stage - using the same Jinja2 template format, brief block, and resolution
chain that P2 already uses, so the serial and parallel flows of each phase are
expressed in the instructions rather than only in the phase contracts.

## 2. Format reference (P2 pattern)

Every P2 template begins with the brief block header, followed by the
role/stage directive. All new templates must reproduce the header verbatim:

```jinja
Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
```

Renderer context (from `load_instruction`): `research_question`, `scope`,
`constraints`, `decision_criteria`, `role`. Note: **no `mode` or `stage_id`
variable is injected** - templates cannot branch on mode; keep stage+role
templates mode-agnostic and put mode-level nuance in the mode templates.

Existing P2 files (reference):

| File | Role | Directive |
|---|---|---|
| `P2/p2.independent_proposals.theorist.md` | theorist | Propose the single most promising method from a mathematical standpoint; six canonical components; state assumptions, provable results, open questions |
| `P2/p2.independent_proposals.data_analyst.md` | data_analyst | Propose the single most promising method from an empirical standpoint; implementation + benchmarking plan; experiments that would validate/refute |
| `P2/p2.independent_proposals.research_lead.md` | research_lead | Propose from a scientific-value standpoint |
| `P2/p2.cross_review.theorist.md` | theorist | Review all three proposals for correctness, assumptions, identifiability, algorithm soundness, risks; one review document |
| `P2/p2.cross_review.data_analyst.md` | data_analyst | Review all three proposals empirically |
| `P2/p2.lead_reconciliation.research_lead.md` | research_lead | Reconcile proposals + cross-reviews into the final catalog: keep/merge/drop; complete method records; attention items; decision record |
| `P2/full_catalog.md`, `P2/focused_method.md` | (mode-level) | Shared mode directives; remain as fallbacks |

## 3. Resolution chain (authoritative, from `default_instructions.py`)

The loader `_resolve_template_name(phase_or_mode, role, stage_id)` tries, first
hit wins:

1. `<Phase>/<stage_id>.<role>.md` - **stage + role** (what we create)
2. `<Phase>/<stage_id>.md` - stage, all roles
3. `<Phase>/<mode>.<role>.md` - mode + role
4. `<Phase>/<mode>.md` - mode, shared
5. `<Phase>/default.<role>.md` - default + role
6. `<Phase>/default.md` - shared default

The `run_coordinator` calls `load_instruction(mode, brief, role=role,
stage_id=stage.stage_id)` for every role step (keying `role_instructions` as
`{stage_id}.{role}`), so stage+role files are picked up automatically once
they exist. At runtime the effective instruction is `stage+role → role-only →
phase_instruction`, where the phase_instruction fallback is the rendered
mode-level template; the coordinator only populates stage+role keys, so in
practice the chain exercised is stage+role template, else mode-level template.

## 4. Naming rules (critical)

- **Stage IDs come from the phase contracts (`architecture/contracts/phases.json`), not from mode names.** In particular P5's stage IDs are `p5.assembly_lead`, `p5.parallel_reviews`, `p5.revision_lead` - the mode IDs `p5.assembly` / `p5.review_revision` are *not* stage IDs.
- **Role names come from each stage's `roles` array** in the contract: `research_lead`, `theorist`, `data_analyst`, `outside_reviewer`. Note P3 stage 2 and P4 stage 1 use the role `data_analyst` even though the stage is named `*.analyst`.
- Filename pattern: `<stage_id>.<role>.md` under `resources/instructions/<Phase>/`.
- No stage-level files (chain level 2) are needed: every stage has either exactly one role or full role coverage, so stage+role files fully determine the directive.

Total new files: **15** (P1: 4, P3: 3, P4: 3, P5: 5). Existing mode-level
templates (`P1/literature_update.md`, `P3/theory_revision.md`,
`P4/preliminary.md`, `P4/comprehensive.md`, `P5/assembly.md`,
`P5/review_revision.md`) are left untouched and remain as the mode-level
fallback.

---

## 5. P1 - Literature (mode `p1.literature_update`)

### 5.1 Files to create

| # | File | Stage | Role | Contract stage objective |
|---|---|---|---|---|
| 1 | `resources/instructions/P1/p1.discovery.theorist.md` | p1.discovery | theorist | Search and assess from a mathematical perspective |
| 2 | `resources/instructions/P1/p1.discovery.data_analyst.md` | p1.discovery | data_analyst | Search and assess from an empirical perspective |
| 3 | `resources/instructions/P1/p1.discovery.research_lead.md` | p1.discovery | research_lead | Search and assess from a scientific/landscape perspective |
| 4 | `resources/instructions/P1/p1.lead_synthesis.research_lead.md` | p1.lead_synthesis | research_lead | Deduplicate, reconcile, assess coverage, produce the candidate current basis |

### 5.2 Directive content per template

**p1.discovery.theorist.md** - The theorist searches the literature from a
mathematical angle: theoretical foundations of the relevant problem family,
mathematical tools and formal frameworks that bear on the question, related
formal methods and their assumptions, and known theoretical limits. For each
source found, record its contribution, its relation to the research question,
and its limitations. Produce the `p1.theory_discovery` handoff. Do not read the
other discovery roles' current-run reports before submitting (isolation rule);
do not attempt to cover the whole literature - cover the mathematical angle
and flag where other angles are needed.

**p1.discovery.data_analyst.md** - The data analyst searches from an empirical
angle: existing empirical methods and baselines, benchmark datasets and study
designs, evaluation protocols, computational feasibility and reproducibility
findings, and what the data/evidence side of the literature establishes.
Produce the `p1.empirical_discovery` handoff. Same isolation rule; flag
empirical gaps rather than surveying everything.

**p1.discovery.research_lead.md** - The research lead searches from the
landscape angle: the overall research landscape, how the project question is
positioned within it, competing lines of work, and - most importantly - where
the concrete gap is that this project addresses. Assess coverage: what is
established, what is contested, what is missing. Produce the `p1.lead_discovery`
handoff. Same isolation rule.

**p1.lead_synthesis.research_lead.md** - The lead receives the three discovery
handoffs plus the current library/synthesis/coverage. Deduplicate sources
against the cumulative library (stable identities, no duplicates), reconcile
disagreements between the three angles or expose them explicitly, assess
coverage against the question, and produce: `p1.source_changes`,
`p1.synthesis_candidate`, `p1.coverage_candidate`, `p1.phase2_handoff`,
`p1.attention_items`, and `p1.decision`. Emphasize specificity: a focused
synthesis of 15-25 directly relevant sources beats an exhaustive survey;
material synthesis statements must cite promoted sources or mark evidence as
missing/unresolved.

### 5.3 Key difference from P2

P2 stage 1 roles **propose methods** into a method catalog (each writes a
candidate method with six canonical components); P1 stage 1 roles **find and
assess sources** from their angle (each writes a discovery handoff). P2 stage 2
reconciles proposals into catalog records with keep/merge/drop decisions;
P1 stage 2 reconciles sources into a cumulative library plus a replaceable
synthesis and coverage record. No canonical definitions, no catalog records,
no user-facing method choice.

---

## 6. P3 - Theory (modes `p3.theory_establishment`, `p3.theory_revision`, method-scoped)

### 6.1 Mode structure - two gated modes

P3 runs in one of two modes over the same three serial stages
(theorist → analyst → lead). Mode 2 **requires** mode 1 results:

| Mode | What it does | Gate |
|---|---|---|
| 1 - `p3.theory_establishment` | Establish the complete theoretical foundation: define assumptions, prove or disprove the central claims, identify convergence and limitations | None beyond the usual P3 prerequisites (current brief, P1 basis, P2 catalog, active method) |
| 2 - `p3.theory_revision` | Revise or strengthen the established theory: mend proof gaps, tighten assumptions, explore stronger claims, address audit findings, extend results | **Requires a complete formal current theory record from a prior establishment run** |

Directive differences between the modes (mirrored in the mode-level
templates `P3/theory_establishment.md` and `P3/theory_revision.md`, which
already exist and remain the mode-level fallbacks):

- **Establishment** builds the theory from scratch: derive the key
  mathematical properties (convergence, mixing time, bias-variance
  tradeoffs, guarantees, limitations), state assumptions precisely, prove
  or disprove the central claims, and identify the conditions under which
  the method succeeds and fails. The account must be rigorous enough to
  guide empirical implementation; if the method cannot work as hoped,
  say so plainly rather than overstating results.
- **Revision** refines an existing complete theory record: mend incomplete
  proofs, close boundary cases, resolve identifiability and testability
  concerns raised by the analyst audit, and - where reflection or the
  audit suggests it - explore stronger claims (tighter convergence rates,
  broader applicability, sharper guarantees). The revised record must be
  strictly stronger or more complete than the one it replaces; claims
  that cannot be salvaged are stated clearly and the theoretical position
  adjusted.

Because the loader injects no mode variable, the same three stage+role
files serve both modes; mode-level nuance lives in the mode templates
above.

### 6.2 Files to create

| # | File | Stage | Role | Contract stage objective |
|---|---|---|---|---|
| 5 | `resources/instructions/P3/p3.theorist.theorist.md` | p3.theorist | theorist | Construct the complete theory: proofs, assumptions, convergence, limitations |
| 6 | `resources/instructions/P3/p3.analyst.data_analyst.md` | p3.analyst | data_analyst | Challenge the theory: identifiability, operational meaning, testability, boundary cases |
| 7 | `resources/instructions/P3/p3.lead.research_lead.md` | p3.lead | research_lead | Integrate theory + audit, resolve disagreements, state outcome |

### 6.3 Directive content per template

**p3.theorist.theorist.md** - The theorist works **alone** and **develops**, not
proposes: construct the complete theory of the selected method - a rigorous
mathematical definition, precise assumptions, proofs or disproofs of the
central claims (convergence, guarantees, bias-variance tradeoffs where
relevant), conditions under which the method succeeds and fails, and stated
limitations and open obligations. Output is a complete readable theory
manuscript (`p3.theory_candidate`), not a patch, plus a `p3.theory_handoff`
stating changes, claims, unresolved obligations, and the specific checks the
data analyst should perform. If the theory shows the method cannot work as
hoped, say so plainly - do not overstate results.

**p3.analyst.data_analyst.md** - The data analyst performs an **audit, not a
peer review**: challenge the theory from the empirical/computational side -
identifiability of the estimand, operational meaning (can a practitioner
compute it?), computational soundness of the proposed procedures, empirical
testability (what experiment could falsify it), boundary cases, and consistency
with available evidence. Produce `p3.analyst_audit` listing every concern with
specificity (each issue must be actionable by the lead), plus
`p3.analyst_handoff`. The audit directly shapes the lead's integration.

**p3.lead.research_lead.md** - The lead receives the theory candidate and the
analyst audit. Integrate them: resolve disagreements where the evidence
permits, expose them where it does not, decide what stands as the current
theory. Produce `p3.complete_theory` (the current theory record),
`p3.attention_items` for anything downstream must address, and `p3.decision`
stating the outcome and user-relevant changes. The outcome states the theory's
status - not a catalog choice.

### 6.4 Key difference from P2

P2 is **parallel proposals + cross-review**: three roles each propose a method,
then two roles cross-review all three, then the lead builds a multi-method
catalog. P3 is a **serial pipeline, method-scoped**: theorist → analyst → lead,
one role per stage, no parallelism, no alternatives. The analyst audits a
single theory (challenge/verify), whereas P2's cross-review compared three
proposals. The lead integrates rather than curating a catalog.

---

## 7. P4 - Evidence (modes `p4.preliminary`, `p4.comprehensive`, method-scoped)

### 7.1 Mode structure - two gated modes

P4 runs in one of two modes over the same three serial stages
(analyst → theorist → lead). Mode 2 **requires** mode 1 results:

| Mode | What it does | Gate |
|---|---|---|
| 1 - `p4.preliminary` | Establish the code implementing the method and validate it on a simple testing example: a small set of decisive feasibility, implementation, and diagnostic checks | None beyond the usual P4 prerequisites (current brief, P1 basis, P2 catalog, active method) |
| 2 - `p4.comprehensive` | Comprehensive simulation results across settings and tunings for publication: a prespecified full evaluation with comparisons, sensitivity analyses, and robustness checks, built on the validated preliminary implementation and evidence | **Requires a complete formal current preliminary evidence record from a prior preliminary run** |

Directive differences between the modes (mirrored in the mode-level
templates `P4/preliminary.md` and `P4/comprehensive.md`, which already
exist and remain the mode-level fallbacks):

- **Preliminary** establishes the working implementation and validates it
  on a simple test case: design and execute decisive feasibility,
  implementation, and diagnostic checks, pre-register the design (target
  distributions, metrics, parameter grid, stopping rules), implement the
  method and baseline under identical conditions, and report convergence
  diagnostics, effective sample sizes, wall-clock comparisons, and
  sensitivity to hyperparameters.
- **Comprehensive** builds on the validated preliminary implementation and
  evidence - reuse the validated code, do not reimplement from scratch -
  and extends it to publication quality: pre-register the full design
  (adding ablation studies and scaling behavior), evaluate the method
  across a wide range of settings and tunings, and report fully
  reproducible results.

Because the loader injects no mode variable, the same three stage+role
files serve both modes; scope differences (breadth of experiments,
thoroughness of uncertainty analysis) are deferred to the user's
`p4.instructions` choice and the mode-level templates above.

### 7.2 Files to create

| # | File | Stage | Role | Contract stage objective |
|---|---|---|---|---|
| 8 | `resources/instructions/P4/p4.analyst.data_analyst.md` | p4.analyst | data_analyst | Specify protocol, verify implementation, execute, produce evidence |
| 9 | `resources/instructions/P4/p4.theorist.theorist.md` | p4.theorist | theorist | Audit mathematical fidelity: definition-to-code correspondence, validity of comparisons |
| 10 | `resources/instructions/P4/p4.lead.research_lead.md` | p4.lead | research_lead | Integrate evidence + audit, state scientific outcome |

The P4 stages apply to **both** modes - one set of stage+role files
covers both (see 7.1 for the mode structure, gating, and directive
differences).

### 7.3 Directive content per template

**p4.analyst.data_analyst.md** - The data analyst **drives** this stage:
specify the protocol **before** executing - design, metrics, comparisons,
diagnostics, and uncertainty analysis - then verify that the implementation
under test matches the selected method exactly (exact-method identity), execute
the authorized scope, and produce reproducible evidence. Outputs:
`p4.protocol` (prespecified), `p4.evidence` (results with full provenance:
seeds, environments, commands, diagnostics), `p4.analyst_synthesis`, and
`p4.analyst_handoff`. Where evidence contradicts the theory, report it
explicitly rather than explaining it away.

**p4.theorist.theorist.md** - The theorist audits **mathematical fidelity**:
does the code implement the mathematical definition? Are the comparisons
valid (fair baselines, matched settings)? Are interpretations consistent with
the theory (P3's current theory)? Check numerical/identifiability hazards that
could invalidate conclusions. Produce `p4.theory_audit` with every concern
itemized and specific, plus `p4.theory_handoff`. This is an audit of the
analyst's work - not a peer review of a paper.

**p4.lead.research_lead.md** - The lead receives protocol, evidence, analyst
synthesis, and the theory audit. Integrate: retain applicable evidence, decide
what the evidence supports, expose unresolved disagreements between evidence
and audit. Produce `p4.empirical_index_candidate`,
`p4.empirical_synthesis_candidate`, `p4.implementation_record_candidate`,
`p4.attention_items`, and `p4.decision` stating the scientific outcome and
user-relevant changes.

### 7.4 Key difference from P2

P2's analyst role *proposes* a method and cross-reviews others' proposals; in
P4 the analyst **executes** the method and produces the primary artifacts
(protocol + evidence), with the theorist auditing after the fact and the lead
integrating. Serial and method-scoped with exact-method identity checks
throughout - P2 had no execution and no fidelity audit. Flow order is also
inverted relative to P3: analyst (build evidence) → theorist (verify) → lead
(integrate), whereas P3 is theorist (build theory) → analyst (challenge) →
lead (integrate).

---

## 8. P5 - Manuscript (modes `p5.assembly`, `p5.review_revision`)

### 8.1 Files to create

| # | File | Stage | Mode(s) | Role | Contract stage objective |
|---|---|---|---|---|---|
| 11 | `resources/instructions/P5/p5.assembly_lead.research_lead.md` | p5.assembly_lead | assembly | research_lead | Assemble/update the complete manuscript from the exact frozen basis |
| 12 | `resources/instructions/P5/p5.parallel_reviews.theorist.md` | p5.parallel_reviews | review_revision | theorist | Audit manuscript from the mathematical angle |
| 13 | `resources/instructions/P5/p5.parallel_reviews.data_analyst.md` | p5.parallel_reviews | review_revision | data_analyst | Audit manuscript from the empirical angle |
| 14 | `resources/instructions/P5/p5.parallel_reviews.outside_reviewer.md` | p5.parallel_reviews | review_revision | outside_reviewer | Audit as independent referee; packet-only context |
| 15 | `resources/instructions/P5/p5.revision_lead.research_lead.md` | p5.revision_lead | review_revision | research_lead | Dispose every review issue; revise the manuscript |

### 8.2 Directive content per template

**p5.assembly_lead.research_lead.md** - The lead alone assembles (or updates)
the complete manuscript from the **exact frozen** P1-P4 basis (library,
synthesis, method catalog, selected method, theory, empirical index/records,
implementation record). Produce `p5.manuscript_candidate` plus
`p5.claim_traceability` (every claim mapped to its upstream record),
`p5.upstream_basis_manifest`, `p5.citation_integrity_report`,
`p5.limitations_record`, `p5.assembly_report`, `p5.attention_items`, and
`p5.decision`. Do not invent results: claims must trace to the frozen basis;
missing support is recorded as a limitation, not silently patched.

**p5.parallel_reviews.theorist.md** - The theorist audits the frozen manuscript
snapshot from the mathematical angle: correctness of stated theorems/proofs,
fidelity of the mathematical presentation to the current theory (`p5.theory`),
soundness of assumptions as written, and correct citation of theoretical
sources (`p5.literature_synthesis`). Reads: review packet + manuscript +
method + theory + literature synthesis. Produce `p5.theory_audit` with
issue-by-issue severity.

**p5.parallel_reviews.data_analyst.md** - The data analyst audits from the
empirical angle: do the reported results match the evidence records
(`p5.empirical`, `p5.empirical_index`)? Is the implementation record consistent
with the manuscript's claims? Are reproducibility details complete and
experimental comparisons valid? Reads: review packet + manuscript + method +
empirical index/records + implementation record + literature synthesis.
Produce `p5.empirical_audit`.

**p5.parallel_reviews.outside_reviewer.md** - The outside reviewer audits as an
independent referee for the target venue: novelty, significance, clarity,
validity of the argument as a reader would judge it, and presentation quality.
**Reads only the frozen review packet** (manuscript + reviewer-facing venue and
user instructions) - never the specialist audits, internal deliberation, or
later role output (isolation rule). Produce `p5.outside_review` with
severity-calibrated concerns.

**p5.revision_lead.research_lead.md** - The lead receives **all three reviews
together** (theory audit, empirical audit, outside review), disposes **every
stable issue** - accept / revise / rebut with reasoning - into the
`p5.review_issues` ledger, then revises the complete manuscript against the
exact current basis. Produce `p5.manuscript_candidate`, updated
`p5.claim_traceability`, `p5.upstream_basis_manifest`, `p5.attention_items`,
and `p5.decision` including a response-to-reviewers account.

### 8.3 Key difference from P2

P5 has **two modes with different shapes**. Assembly is a single **lead-only**
stage - no parallel roles, no proposals, no catalog; the deliverable is a
manuscript traceable to the frozen basis. Review-revision has **three parallel
reviewers including the new `outside_reviewer` role** (P2 has no outside
reviewer), each auditing from a different angle with role-specific read sets -
the outside reviewer is packet-isolated - followed by a serial lead stage that
**disposes** issues and revises, rather than reconciling method proposals.

---

## 9. Implementation steps

1. Create the 15 files listed above (sections 5-8), each starting with the
   brief block header from section 2, followed by the directive text.
   Directives must name the concrete run-local outputs the role writes (from
   the contract's `writes` lists) so the role knows its deliverable.
2. Do **not** modify existing templates: `P1/literature_update.md`,
   `P3/theory_revision.md`, `P4/preliminary.md`, `P4/comprehensive.md`,
   `P5/assembly.md`, `P5/review_revision.md` remain as mode-level fallbacks
   (chain levels 3-4).
3. Verify resolution + rendering for every stage+role combination (see 10).
4. Optionally add the new files to any instruction-catalog documentation in
   `architecture/` and index this plan in `architecture/plans/README.md`.

## 10. Verification

From the repo root (`/home/tez/product/model-forge`), with the project
environment active:

```python
from model_forge.application.default_instructions import load_instruction, _resolve_template_name

brief = {
    "research_question": "Test question",
    "scope": "Test scope",
    "constraints": ["C1", "C2"],
    "decision_criteria": ["D1"],
}
cases = [
    ("p1.literature_update", "theorist", "p1.discovery"),
    ("p1.literature_update", "data_analyst", "p1.discovery"),
    ("p1.literature_update", "research_lead", "p1.discovery"),
    ("p1.literature_update", "research_lead", "p1.lead_synthesis"),
    ("p3.theory_establishment", "theorist", "p3.theorist"),
    ("p3.theory_establishment", "data_analyst", "p3.analyst"),
    ("p3.theory_establishment", "research_lead", "p3.lead"),
    ("p3.theory_revision", "theorist", "p3.theorist"),
    ("p3.theory_revision", "data_analyst", "p3.analyst"),
    ("p3.theory_revision", "research_lead", "p3.lead"),
    ("p4.preliminary", "data_analyst", "p4.analyst"),
    ("p4.preliminary", "theorist", "p4.theorist"),
    ("p4.preliminary", "research_lead", "p4.lead"),
    ("p4.comprehensive", "data_analyst", "p4.analyst"),
    ("p4.comprehensive", "theorist", "p4.theorist"),
    ("p4.comprehensive", "research_lead", "p4.lead"),
    ("p5.assembly", "research_lead", "p5.assembly_lead"),
    ("p5.review_revision", "theorist", "p5.parallel_reviews"),
    ("p5.review_revision", "data_analyst", "p5.parallel_reviews"),
    ("p5.review_revision", "outside_reviewer", "p5.parallel_reviews"),
    ("p5.review_revision", "research_lead", "p5.revision_lead"),
]
for mode, role, stage in cases:
    template = _resolve_template_name(mode, role, stage)
    assert template.endswith(f"{stage}.{role}.md"), template
    text = load_instruction(mode, brief, role=role, stage_id=stage)
    assert text.startswith("Research question: Test question")
    assert "Constraints: C1, C2." in text
    print(f"OK {mode:24s} {role:16s} {stage:22s} -> {template}")
```

Acceptance: all 21 cases resolve to the expected `<Phase>/<stage_id>.<role>.md`
and render without `StrictUndefined` errors; the brief block renders correctly
both with and without `constraints`/`decision_criteria` (the `{% if %}` guards
must be present in every template).

## 11. Out of scope

- Stage-level (chain level 2) or `default.*` templates - not needed.
- Template variables beyond the current renderer context - would require code
  change and is intentionally avoided.
- P2 templates - already complete.
- Any change to phase contracts, schemas, or the loader.
