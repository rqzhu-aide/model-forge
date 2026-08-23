# HV-7: Pilot, Measure, and Harden

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Demonstrate fewer false rejections without weakening formal integrity. Validate
the entire program through shadow comparison, a calibration corpus, and
operational hardening.

## When to start

This package runs after HV-0 through HV-6 are implemented. It validates the
program end-to-end.

## Work items

### HV-7.1: Build the calibration corpus

**Target:** `architecture/plans/completed/evidence/hv7-calibration-corpus/`

A corpus of test cases covering:

**Valid but structurally diverse:**
- Full P1→P5 outputs from real Hermes runs
- Sparse outputs (minimal valid content)
- Dense outputs (complex multi-object records)
- Each phase × mode combination

**Honest scientific edge cases:**
- Negative result (theory contradicted, empirical null finding)
- Inconclusive result (open proof obligation, inconclusive diagnostic)
- Contradictory result (assumption weakened, statement retracted)
- Not-applicable categories (justified empties)
- Failed proof attempt with counterexample
- Outside reviewer reporting no strengths

**Correctable packaging defects:**
- Malformed JSON (original artifact preserved)
- Missing harness-owned fields
- Envelope shape mismatch
- Wrong timestamp format
- Undeclared fields in closed schema

**Genuine integrity violations (must reject):**
- Wrong method identity
- Wrong frozen basis
- False provenance
- Digest mismatch
- Unsafe paths
- Malformed artifacts

**Publication conflicts:**
- Atomic-publication head conflict during promotion

**Anonymized real false rejections:**
- From the HV-0 baseline evidence

Store each case as:
```
hv7-calibration-corpus/
  case-001-negative-theory/
    input/          # raw agent output
    expected/       # expected validation decision + finding classes
    description.md
```

### HV-7.2: Shadow mode comparison

**Target:** `src/model_forge/harness/` (new shadow comparison harness)

Run the new policy in shadow mode: for each validation, record both:
- The **current** decision (old all-ERROR policy)
- The **proposed** decision (new classified policy)

without changing publication. Two evidence sources:

1. Live runs during the pilot period.
2. REPLAY of the HV-0 baseline: the 204 historical role closures in
   `~/.model-forge/model-forge.sqlite3` and the 7 supervised validation reports
   in `~/model-forge-data/pilot-eld/hub.sqlite3` already carry their findings.
   Re-deciding those findings under the new policy costs no model calls and
   immediately quantifies the false-rejection fix rate before any new run.

The comparison record:

```python
@dataclass
class ShadowComparison:
    run_id: str
    role_closure_id: str
    old_decision: Literal["passed", "failed", "rejected"]
    old_blocking_codes: list[str]
    new_decision: Literal["passed", "correction_required", "rejected"]
    new_blocking_codes: list[str]
    new_advisory_codes: list[str]
    disagreement: bool
    disagreement_reason: str | None
```

Review disagreements by phase and validator code. Track:
- Cases where old=failed but new=passed (potential false rejections fixed)
- Cases where old=passed but new=rejected (potential new catches)
- Cases where old=failed and new=correction_required (recovery now possible)

### HV-7.3: Track operational metrics

**Target:** `architecture/plans/completed/evidence/hv7-metrics.json`

| Metric | Definition |
| --- | --- |
| First-pass conformance rate | Fraction of runs that pass validation on first attempt |
| Correction success rate | Fraction of correction attempts that achieve conformance |
| Agent-completed but nonconforming rate | Fraction of runs where Hermes succeeded but validation failed |
| Hard integrity rejection rate by code | Count of each integrity-blocker code |
| Confirmed false rejection rate | Fraction of old-failed runs that new policy would pass |
| Complete phase reruns avoided | Count of reruns avoided by correction |
| Median time from output completion to publication | Wall-clock from role closure to publication |

Track these before and after the program to measure improvement.

### HV-7.4: Full acceptance matrix

**Target:** `tests/` (new E2E test suite)

The parent plan §9 acceptance matrix -- 14 cases, each asserting backend state,
Web UI wording, available controls, complete findings, preserved artifacts, and
whether formal project state changed:

1. Hermes process failure with preserved partial work and no publication.
2. Hermes success + malformed JSON → output correction, not execution failure.
3. Hermes success + missing harness-owned field → repaired and disclosed.
4. Hermes success + correctable scientific cross-reference error.
5. Unsupported theorem labeled established → blocked pending correction.
6. Honest failed proof or inconclusive empirical result → published with
   correct scientific outcome.
7. P4 preliminary output that omits comprehensive-only protocol elements.
8. Evidence for a previous method version → preserved but excluded from
   synthesis.
9. Wrong method identity or frozen basis → strictly rejected.
10. Unsafe path or digest mismatch → strictly rejected.
11. Atomic publication conflict → preserving both attempt and current state.
12. Revalidation after validator-policy change, with unchanged output digest.
13. User-authorized targeted correction, with all attempts retained.
14. Restart during correction, with no automatic relaunch.

### HV-7.5: Backend, architecture, API, and frontend suite pass

**Target:** all test suites

```
.venv/bin/python -m pytest tests/ -q           # Python backend (830+ tests)
cd web && npx vitest run                        # Frontend (110+ tests)
python -m model_forge validate                   # Architecture contract validation
```

All must pass. No exceptions.

## Acceptance criteria

- [ ] Repairable representation defects recover without repeating scientific
      work
- [ ] Wrong identity, basis, provenance, or digest never publishes
- [ ] Warning-only negative and inconclusive outcomes publish and remain
      visible
- [ ] Restart, cancellation, and conflict tests preserve immutable evidence
- [ ] The full backend, architecture, API, and frontend acceptance suites pass
- [ ] The registry-completeness test passes: every literal finding code in the
      source is registered in the HV-2 policy registry
- [ ] Shadow comparison shows zero cases where the new policy is more
      permissive than intended for integrity blockers
- [ ] Shadow comparison shows improvement in false-rejection rate, quantified
      against the HV-0 baseline replay

## Dependencies

- All prior packages (HV-0 through HV-6) must be implemented and individually
  tested

## Risks

- **Shadow comparison cost**: running both policies doubles validation work
  during the comparison period. Acceptable for a bounded pilot.
- **E2E test infrastructure**: some acceptance cases require real Hermes runs
  (process failure, correction with model call). Use the development executor
  with crafted fixtures where possible.
- **Metric baseline**: the "before" metrics must be captured before any HV
  package changes acceptance behavior. Capture them in HV-0 and preserve for
  comparison here.

## Revision 2 changelog (2026-08-12, coder review)

- A1 (HV-7.2): added the baseline replay as a shadow-comparison evidence
  source. The historical closures and validation reports already carry
  findings, so the false-rejection fix rate is measurable without new model
  calls.
- A2: added the registry-completeness test to acceptance.
