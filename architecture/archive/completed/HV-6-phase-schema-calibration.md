# HV-6: Phase Schema Calibration

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Accept valid research structures without encouraging artificial filler. Each
phase schema is calibrated so that honest science -- including negative,
inconclusive, and sparse results -- passes validation without fabricating
content.

## What the audit found

### The pull landed 5 schemas with rich enums -- but validators don't use them

The pull (commit `53efd01`) added:

| Schema | Key structural features |
| --- | --- |
| `theory-record` | Statement `status` (established/conditional/incomplete/contradicted/retracted/untested); assumption status (active/weakened/rejected/unverified); `open_obligation`; `revision_account` (8 statement-id sets) |
| `empirical-protocol` | `protocol_status` const `"prespecified"`; deviation `disposition` (4 values); `falsification_rule`; `decision_thresholds`; `finalized_at` ordering |
| `manuscript-package` | `manuscript_kind`; 8 core `sections_present`; `claim_support_index` with minItems:1 |
| `review-finding` | `severity` (blocking/major/minor); `confidence`; 9 `finding_type`s; `resolution_class` |
| `review-report` | `novelty_search_boundary`; `prioritized_issues` with `raised_by=outside_reviewer` |

**But the validators don't consume most of these.** Specifically:

1. Theory statuses `conditional`, `untested`, `retracted` have **no validator
   checks** -- they're schema-valid but scientifically unexamined.
2. Deviation `disposition` (`rerun_required` etc.) and `impact_assessment` are
   **never enforced**.
3. Manuscript `sections_present` and `target_audience` are **schema-only** --
   no semantic validation.
4. Review-finding `severity` and `confidence` have **zero effect** on
   publication decisions.
5. Stale enum members: two live P5 disposition branches
   (`scientific_validators.py:954,965`) still list the retired values
   `addressed`, `accepted`, `wont_fix` alongside the live ones. The branches
   work for the current enum; the retired members are unreachable. See HV-2.7
   for the precise statement and the per-enum coverage audit.

### Calibration must map to frozen enums, not redefine them

HV-2's policy registry must map to the frozen enums above. Any HV-6 calibration
that conflicts with these enums needs an ADR or contract amendment.

## Constraint

**Perform this package only after HV-0 provides real failure evidence.** Each
phase is a separate reviewed change. Do not batch phases.

## Per-phase work

### HV-6.P1: Literature

**Target:** `architecture/schemas/scientific-record.schema.json` (P1 output),
`src/model_forge/harness/scientific_validators.py` (P1 validators)

Calibration goals:

1. Represent search, researcher-supplied, imported-library, and citation-chain
   source origins.
2. Require truthful provenance appropriate to the origin rather than a search
   record for every source. Currently `p1.search_provenance_missing` fires as
   ERROR for every source regardless of origin.
3. Reclassify `p1.search_provenance_missing` as `SCIENTIFIC_ATTENTION`
   (WARNING) when the source origin is researcher-supplied or imported-library.

**Files:**
- `scientific-record.schema.json`: add `origin_type` enum if not present
- `scientific_validators.py:3` (P1 section): origin-aware provenance check
- HV-2 registry: reclassify `p1.search_provenance_missing`

### HV-6.P2: Methods

**Target:** `architecture/schemas/scientific-record.schema.json` (P2 output),
`src/model_forge/harness/scientific_validators.py` (P2 validators)

Calibration goals:

1. Allow justified empty or not-applicable assumptions, literature, and
   limitation categories where scientifically appropriate.
2. Keep exact mathematical identity and method-lineage requirements strict.
   The 11 P2 finding codes include identity and lineage checks
   (`p2.mathematical_digest_unchanged`, `p2.mathematical_stable_id_changed`,
   `p2.predecessor_identity_mismatch`) -- these remain integrity blockers.
3. Retain a method-class-specific definition rather than forcing one universal
   representation.

**Files:**
- `scientific-record.schema.json`: allow justified empty categories
- `scientific_validators.py` P2 section: conditional severity for empty
  categories
- HV-2 registry: review all 11 P2 codes

### HV-6.P3: Theory

**Target:** `architecture/schemas/theory-record.schema.json`,
`src/model_forge/harness/scientific_validators.py` (P3 validators, 18 codes)

Calibration goals:

1. Permit proof-only, definition-focused, impossibility, counterexample, and
   unsuccessful exploratory outcomes. The schema's statement `status` enum
   already supports these (`incomplete`, `contradicted`, `untested`) -- the
   validators need to accept them instead of treating them as failures.

2. Recognize a proof contained in the primary theory manuscript rather than
   requiring a duplicate artifact.

3. Permit explicit not-applicable categories and structured novel theoretical
   objects.

4. Continue blocking claims labeled `established` without an identifiable proof.
   `p3.established_statement_unsupported` remains a scientific claim blocker.

5. Add validator checks for statuses `conditional`, `untested`, `retracted` --
   currently schema-valid but unvalidated. These need:
   - `conditional`: require conditioning assumption reference
   - `untested`: require explicit open obligation
   - `retracted`: require retraction reason and what supersedes it

**Dead branch fix:** `p3.development_mode_mismatch` (currently fires on every
real record via the supervised shim -- fixed in HV-1.5, but verify it dispatches
correctly after the mode fix).

**Files:**
- `theory-record.schema.json`: already has the enum; add conditional
  requirements if needed
- `scientific_validators.py` P3 section (18 codes): add status-specific checks,
  reclassify honest-negative codes
- HV-2 registry: review all 18 P3 codes

### HV-6.P4: Evidence

**Target:** `architecture/schemas/empirical-protocol.schema.json`,
`src/model_forge/harness/scientific_validators.py` (P4 validators, 17 codes)

Calibration goals:

1. Define separate preliminary and comprehensive requirement profiles. ADR-013
   already established that comprehensive no longer requires prior preliminary.
   The validators must dispatch on mode.

2. Make baselines, tuning, multiplicity, stopping rules, leakage checks, and
   reproducibility items **conditional on study type**:
   - `p4.preliminary`: relaxed (exploratory, may omit comprehensive checks)
   - `p4.comprehensive`: strict (full protocol, thresholds, deviations)

3. Retain evidence for an older or nonexact method version, but mark it
   `inapplicable` and exclude it from current-method synthesis. The
   `p4.evidence_not_exactly_applicable` code currently blocks -- reclassify as
   `SCIENTIFIC_ATTENTION` (WARNING) so the evidence is preserved but excluded
   from synthesis.

4. Derive prespecification order from harness events rather than
   agent-authored timestamps. `p4.protocol_finalized_after_evidence` currently
   compares agent-authored document timestamps
   (`scientific_validators.py:662-672`: protocol `finalized_at` vs evidence
   `created_at`). Note the scope honestly: harness authority events exist at
   run/stage/role granularity, not per-artifact authorship order within one
   role's output. This item therefore requires either (a) harness-stamped
   per-output sealed times recorded at role closure (the harness knows when
   each declared output file was sealed, per HV-1), or (b) new
   per-artifact authority events. Option (a) is cheaper and sufficient for
   protocol-vs-evidence ordering because protocol and evidence are produced by
   different roles in different stages. The ValidationContext from HV-1.5 must
   carry these harness timestamps into the validator.

5. Enforce deviation `disposition` and `impact_assessment` -- currently
   schema-only, never validated.

**Files:**
- `empirical-protocol.schema.json`: conditional requirements by study type
- `scientific_validators.py` P4 section (17 codes): mode-aware checks,
  reclassify `evidence_not_exactly_applicable`
- HV-2 registry: review all 17 P4 codes

### HV-6.P5: Manuscript

**Target:** `architecture/schemas/manuscript-package.schema.json`,
`architecture/schemas/review-finding.schema.json`,
`architecture/schemas/review-report.schema.json`,
`src/model_forge/harness/scientific_validators.py` (P5 validators, 13 codes)

Calibration goals:

1. Map manuscript sections to scientific functions instead of fixed literal
   headings. The 8 core `sections_present` should map to scientific functions
   (intro, methods, results, discussion, etc.) not literal title strings.

2. Permit a justified absence of claims from a phase. If P3 or P4 produced no
   publishable claims, the manuscript should be able to say so honestly.

3. Distinguish self-contained definitions and assumptions from claims that need
   external evidential support. `p5.claim_without_evidence` remains a
   scientific claim blocker, but self-contained definitions are exempt.

4. Allow an outside reviewer to report no strengths when that is the reviewer's
   honest judgment. Currently the schema requires `prioritized_issues` -- the
   validator should accept an empty list when the reviewer honestly reports
   no significant findings.

5. **Remove stale enum members** (owned by HV-2.7, verified against this
   phase): the disposition sets at `scientific_validators.py:954,965` drop
   `addressed`, `accepted`, `wont_fix`; the live values are already handled.

6. Consume review-finding `severity` and `confidence` for DISPLAY and triage
   only. Publication policy must key on harness-owned finding codes (HV-2),
   never on agent-authored severity: a model must not be able to downgrade its
   own findings by writing `severity=minor`. The harness's own finding codes
   (for example `p5.claim_without_evidence`) keep their registry-assigned
   classes. The agent-authored severity/confidence values are recorded,
   displayed, and may order the finding list, but they do not change
   `blocks_publication`.

**Files:**
- `manuscript-package.schema.json`: functional section mapping
- `review-finding.schema.json`: already has enums; ensure validators consume
  them
- `scientific_validators.py` P5 section (13 codes): fix dead branches, wire
  severity, reclassify
- HV-2 registry: review all 13 P5 codes

## Cross-phase: no fabricated `not applicable` prose

**Constraint across all phases:** no schema should require fabricated
`not applicable` prose merely to satisfy `minItems`. If a category is empty,
the agent should be able to omit it honestly.

Review every `minItems` constraint across all schemas:

```bash
grep -rn '"minItems"' architecture/schemas/
```

For each, determine: is this `minItems` scientifically necessary, or does it
force filler content?

## Acceptance criteria

- [ ] Each schema change has an ADR or amendment when it changes an accepted
      contract
- [ ] Every newly allowed structure has a positive example and semantic test
- [ ] Every retained integrity boundary has a negative test
- [ ] No phase requires fabricated `not applicable` prose merely to satisfy
      `minItems`
- [ ] Dead validator branches fixed across P3, P4, P5
- [ ] Review-finding severity/confidence recorded and displayed for triage, but publication policy keys on harness-owned finding codes only (agent-authored severity never changes `blocks_publication`)
- [ ] All existing tests pass (update tests that assumed old strictness)

## Per-phase delivery

Each phase is delivered as a separate reviewed change:

```
HV-6.P1 → HV-6.P2 → HV-6.P3 → HV-6.P4 → HV-6.P5
```

P3 and P4 are the best first scientific pilots (per parent plan §10) because
their outputs combine complex content with the strictest structured
requirements. Consider starting with P3 or P4, then P5, then P1/P2.

## Dependencies

- HV-0 (real failure evidence to justify calibration)
- HV-2 (policy registry to classify reclassified findings)
- HV-1.5 (mode fix -- calibration depends on correct mode dispatch)

## Risks

- **Over-loosening**: relaxing too many constraints may let invalid science
  through. Each loosening needs a positive example (valid structure passes) and
  a negative test (invalid structure still blocks).
- **Schema-enum conflicts**: any calibration that conflicts with frozen enums
  needs a contract amendment, which cascades digests. Use the
  `contract-bundle-sync.md` recipe.
- **Test churn**: existing tests assume all-ERROR strictness. Reclassified
  codes will break tests that assert blocking behavior. Update tests to assert
  the new policy.

## Revision 2 changelog (2026-08-12, coder review)

- A1 (P4 item 4): scoped the prespecification-order change honestly. Validators
  today compare agent-authored timestamps; harness events have run/stage/role
  granularity, so the item now specifies harness-stamped per-output sealed
  times carried by the HV-1.5 ValidationContext.
- A2 (P5 item 6): closed a policy hole. The original draft mapped
  agent-authored `severity=minor` to non-blocking, which would let a model
  downgrade its own findings. Publication policy now keys on harness-owned
  finding codes only; agent severity is display/triage metadata.
- A3: corrected the "dead branches" framing to match the verified statement
  (live branches, stale members) and assigned the cleanup to HV-2.7.
