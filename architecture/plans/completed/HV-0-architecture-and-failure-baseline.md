# HV-0: Architecture, Finding Code Inventory, and Failure Baseline

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Establish the policy foundation and evidence baseline before changing any
acceptance behavior. No validation threshold is relaxed in this package.

## What the audit found

The codebase has **approximately 75 enumerable finding codes** across 4
validator lanes (verified 2026-08-12 against `53efd01`):

| Lane | File | Static literal codes | Notes |
| --- | --- | --- | --- |
| Scientific (P1-P5) | `scientific_validators.py` | 48 | Plus 2 f-string composed codes and a few codes passed via variables |
| Context inputs | `inputs.py` | 7 | All literal |
| Structural outputs | `outputs.py` | about 1 | Most codes composed dynamically: `error.code` (line 207), `issue.code` (line 262) |
| Submission / integrity | `submission_validation.py` | 19 | All literal |

Dynamically-composed codes (jsonschema paths, `JsonLoadError.code`) are
unbounded and cannot be enumerated; the HV-2 registry therefore needs a
fail-closed default policy for unregistered codes, not just a complete list.

**Every single code is `ValidationSeverity.ERROR`.** The `WARNING` and
`INFORMATION` enum values have zero uses in the entire repo (src, tests, web).
The pass/fail decision is computed purely from `any(severity == ERROR)` with no
per-code `blocks_publication` policy (`validation.py:52-53`).

**Namespace warning for the inventory:** finding codes are emitted as the
first positional argument of `_finding(...)`, not via `code="..."` keyword
arguments. A grep for `code="` finds only about 21 of the 75 literals.
Additionally, the `pN.*` prefix namespace is shared with non-code constants:
output-type and object-id literals such as `p4.protocol`, `p4.decision`,
`p5.assembly`, and mode names such as `p2.focused_method` and
`p3.theory_revision` appear in the same files but are not finding codes (for
example `scientific_validators.py:674-679` uses them as an output-id set).
The inventory must extract `_finding(` first-argument literals and manually
exclude these constants.

## Work items

### HV-0.1: Finding code inventory

Produce a machine-readable registry (JSON or YAML) listing every finding code:

```
code: p3.established_statement_unsupported
lane: scientific
phase: P3
validator: _validate_theory_statements
default_severity: error
provisional_class: scientific_claim_blocker  # see HV-2 §5.4
blocks_publication: true
applicable_modes: [p3.theory_establishment, p3.theory_revision]
responsible_component: scientific_validators.py:520-540
user_guidance: "A theorem is labeled established without a proof or proof location."
```

Source the codes by static analysis. Codes are the first positional argument
of `_finding(...)`; keyword grep misses most of them. Use a small extraction
script, not a one-line grep:

```python
import re, pathlib
for name in ("scientific_validators", "submission_validation", "inputs", "outputs"):
    text = pathlib.Path(f"src/method_hub/harness/{name}.py").read_text()
    codes = re.findall(r'_finding\(\s*"([a-z0-9_.]+)"', text)
    print(name, len(set(codes)))
```

Then manually review the extracted literals and exclude non-code constants
that share the `pN.*` namespace (mode names such as `p2.focused_method`,
`p3.theory_revision`, `p5.review_revision`; output-type/object-id literals such
as `p4.protocol`, `p4.decision`, `p5.assembly`). Also capture
dynamically-composed codes from:
- `JsonLoadError` factory in `outputs.py`
- jsonschema `SchemaError` / `ValidationError` paths (`outputs.py:207,262`)
- Any code composed via f-string or variable (at least 2 exist in
  `scientific_validators.py`)

Map each code provisionally to one of the 6 classes defined in parent plan §5:

| Class | Example codes |
| --- | --- |
| Operational failure | (executor-level, not finding codes) |
| Integrity blocker | `submission.digest_mismatch`, `submission.project_mismatch`, `submission.phase_mismatch`, `input.method_identity_mismatch` |
| Correctable contract error | `submission.required_output_missing`, `submission.output_shape_mismatch`, `output.role_has_no_contract` |
| Scientific claim blocker | `p3.established_statement_unsupported`, `p5.claim_without_evidence`, `p4.evidence_method_mismatch` |
| Scientific attention | (none currently -- all would need reclassification) |
| Information | (none currently) |

**Acceptance:** every finding code appears exactly once in the inventory.
Provisional class assignments are reviewed per phase.

### HV-0.2: Collect real failure baseline

Gather representative real Hermes outputs from:
- `~/.method-hub/artifacts/objects/sha256/` (artifact store)
- `~/.method-hub/method-hub.sqlite3` → `role_execution_closures` table
  (formal lane; as of 2026-08-12: 39 runs, 204 closures, 13 submissions;
  findings live on the closures)
- `~/method-hub-data/pilot-eld/hub.sqlite3` (supervised lane; 7 seals,
  8 launch records, 7 validation reports, 6 promotion records). This is the
  only store with persisted validation reports, and its records exercise the
  supervised mode-shim defect that HV-1.5 fixes.

Target cases:
- Completed work rejected for structural reasons (the false-rejection shape)
- Sparse / negative / inconclusive scientific outcomes
- Missing harness-owned fields repaired by the post-processor
- Wrong method identity / digest mismatch (genuine rejections)

Anonymize private research content while preserving the failure shape.

Record baseline counts:

| Dimension | Metric |
| --- | --- |
| By phase × mode × role | Total runs, rejected count, rejection reason breakdown |
| By validator code | Frequency, outcome (published/rejected/failed) |
| By finding class (provisional) | How many would be correctable vs. blocking |

Store as `architecture/plans/completed/evidence/hv0-failure-baseline.json`.

### HV-0.3: ADR for independent lifecycle axes

Write a new ADR (ADR-014 or next available number) covering:

1. The 4 independent axes (execution, conformance, publication, scientific
   outcome) as domain concepts, distinct from the current single-scalar
   `RunStatus`.

2. `needs_output_correction` as a recoverable condition: Hermes completed,
   work preserved, publication withheld, blocking findings are correctable,
   next action under researcher control.

3. Which actions require new user authority:
   - Revalidation: no new authority (just re-checks bytes)
   - Deterministic normalization: covered by launch authority (mechanical only)
   - Packaging correction: explicit user click (model call, no scientific change)
   - Scientific correction: explicit user click + instruction (model call, within frozen scope)
   - Phase rerun: existing run/rerun control

4. Relationship to ADR-013's validation boundary principle: classification
   establishes conformance, never scientific truth. Honest negative /
   contradictory / incomplete outputs remain valid.

5. Relationship to ADR-012's trusted local execution: the harness owns
   harness facts (identity, basis, digests, timestamps).

6. Policy registry totality: dynamically composed finding codes are unbounded,
   so the registry defines a fail-closed default (unregistered codes block
   publication), and agent-authored severity fields (for example
   review-finding `severity=minor`) never set publication policy. Publication
   policy keys on harness-owned finding codes only.

7. Correction basis pinning: a correction attempt seals against the original
   run's frozen basis content (input generations and digests, method identity,
   role profile versions), not the current authority head. Concurrent
   publication since the original run is resolved by the existing atomic
   publication check at promotion time and may yield `conflicted`.

8. Submission re-entry: the base submission record is immutable and unique
   per run (`storage/migrations.py:219-233`, `run_submissions.run_id UNIQUE`
   with immutable triggers). A correction that passes validation creates a new
   submission attempt record; publication binds the latest passing attempt.
   The original submission is never rewritten.

**Important**: This ADR complements ADR-013, it does not repeat it. Reference
ADR-013's validation boundary and layered prompt principles rather than
restating them.

### HV-0.4: Revise S05 scenario

Current S05: "Failed or cancelled run preserves current state."

The scenario does not distinguish executor failure from completed work
requiring output correction. Revise to cover:

1. Hermes process failure → preserve partial work, no publication.
2. Hermes success + structural defect → preserve work, withhold publication,
   surface `needs_output_correction`.
3. Hermes success + integrity violation → preserve work, reject publication.
4. Deterministic normalization applied and disclosed.
5. User-requested correction attempt.
6. Revalidation after policy change.
7. Warning-only publication (honest negative/inconclusive result).
8. Atomic publication conflict.

### HV-0.5: Scenarios for new conditions

Add new scenario files in `architecture/scenarios/`:

- `S-NN-deterministic-normalization.md`: allowlisted representation change,
  visible diff, no scientific content altered.
- `S-NN-output-correction.md`: user authorizes packaging correction, attempt
  retained, scope bounded.
- `S-NN-revalidation.md`: validator policy change, re-check unchanged bytes.
- `S-NN-integrity-rejection.md`: wrong identity/basis/digest, hard rejection.
- `S-NN-warning-only-publication.md`: honest negative result publishes with
  visible advisory findings.

**Traceability registry work (mandatory, not optional):** the spec gate
(`architecture/tools/validate_package.py:2971-2973`) requires scenarios
S01..S24 registered exactly once and in order, so every new scenario requires
all of the following, or the gate fails:

1. Extend the `expected_codes` range in `validate_package.py` (and the error
   message text).
2. Register each scenario in `contracts/traceability.json` with document path,
   `# SXX:` heading, and a `scenario_id` matching `^s[0-9]{2}\.[a-z0-9_]+$`.
3. Wire `invariant_coverage` back-links bidirectionally and in registry order:
   each scenario's `test_ids` equal the ordered union of its invariants' test
   ids; each cited invariant's `scenario_ids` lists the new scenario in
   registry order.
4. Any new MH requirement row extends the MH range check
   (`validate_package.py:2934`) and `architecture/07-contract-traceability.md`.
5. Update `architecture/scenarios/README.md` (not machine-checked but must
   stay consistent).
6. The S05 revision (HV-0.4) must keep S05's existing registry entry
   consistent; only extend test/invariant links if the revision cites new
   ones.

Use the established text-surgery recipe for `traceability.json` (custom
aligned pretty-printer; naive `json.dumps` produces huge noisy diffs).

### HV-0.6: Architecture schemas for the new record types

Parent plan Section 6 requires ValidationAttempt, OutputTransformationRecord,
RoleAttempt identity, and OutputCorrectionCommand to exist as architecture
schemas before runtime code depends on them. That authorship lives here.

Work:

1. Author `architecture/schemas/` documents for ValidationAttempt and
   OutputTransformationRecord (immutable records, JCS-canonical digest
   conventions, versioned), and for the OutputCorrectionCommand command
   shape.
2. Define the RoleAttempt identity extension (attempt ordinal/ID, link to the
   prior closure, pinned basis reference) in the appropriate contract or
   schema document.
3. Define the submission-attempt record shape referenced by HV-0.3 item 8 and
   HV-5.1 (attempt ID, run ID, ordinal, payload digest, link to the base
   submission).
4. Follow the contract-change rule: schema documents land (with the ADR)
   before any HV-1/HV-2 runtime code imports these types. Runtime-side
   dataclasses in HV-1+ mirror the schemas; they do not redefine them.

**Acceptance:** the four record types exist as architecture schemas; the spec
gate passes; no runtime code in HV-0 depends on them.

## Acceptance criteria

- [ ] Every enumerable finding code (about 75 static, per the verified
      extraction recipe) appears exactly once in the inventory, with
      non-code `pN.*` constants excluded
- [ ] The ADR states which actions require new user authority, plus the
      registry-totality, basis-pinning, and submission re-entry principles
      (HV-0.3 items 6-8)
- [ ] S05 distinguishes executor failure from completed work requiring
      output correction
- [ ] New scenarios cover normalization, correction, revalidation, integrity
      rejection, and warning-only publication
- [ ] `contracts/traceability.json`, the validator ranges, and
      `scenarios/README.md` are updated; `validate_package.py` exits 0
- [ ] The four record-type schemas (HV-0.6) are authored and the gate passes
- [ ] No validation threshold is relaxed in this package
- [ ] Baseline counts recorded for future comparison

## Files touched

| File | Change |
| --- | --- |
| `architecture/plans/completed/evidence/hv0-failure-baseline.json` | New: baseline metrics |
| `architecture/plans/completed/evidence/hv0-finding-code-inventory.yaml` | New: code registry |
| `architecture/decisions/ADR-014-*.md` | New: lifecycle axes + correction authority |
| `architecture/decisions/README.md` | Index entry for the new ADR (link format is machine-checked, `validate_package.py:3141-3146`) |
| `architecture/scenarios/S05-*.md` | Revised: distinguish failure modes |
| `architecture/scenarios/S-NN-*.md` | New: 5 new scenarios |
| `architecture/scenarios/README.md` | Index the new scenarios |
| `contracts/traceability.json` | Register new scenarios + invariant back-links |
| `architecture/tools/validate_package.py` | Extend scenario (and possibly MH) ID ranges |
| `architecture/schemas/` | New: ValidationAttempt, OutputTransformationRecord, correction command + attempt record schemas (HV-0.6) |

No runtime code changes in this package. `validate_package.py` is a
spec-gate tool and editing its expected ID ranges is an accepted part of
scenario/traceability work (WP-B and WP-G precedent).

## Revision 2 changelog (2026-08-12, coder review)

- A1: corrected the code counts (was "89 (62/7/1/19)"; verified 48
  scientific + 19 submission + 7 inputs + dynamic outputs codes, about 75
  enumerable total) and replaced the `grep 'code="'` recipe, which misses
  about 75 percent of codes because they are positional `_finding(...)`
  arguments. Added the `pN.*` namespace-pollution warning.
- A2: added the supervised pilot database as an HV-0.2 evidence source (it
  holds the only persisted validation reports).
- A3: extended HV-0.3 with three ADR content requirements (registry
  totality, correction basis pinning, submission re-entry).
- A4: added the mandatory traceability-registry procedure to HV-0.5; without
  it the spec gate fails on any new scenario.
- A5: new work item HV-0.6 owning the Section 6 record-type schemas, which
  previously had no owner.
- A6: updated acceptance criteria and files-touched accordingly.
