# HV-2: Validation Policy Registry

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Distinguish unsafe material from correctable or advisory findings. Replace the
binary all-ERROR model with an explicit, per-code policy registry.

## What the audit found

### Current state: flat single-severity registry

**About 75 enumerable finding codes** (48 scientific literals + 19 submission +
7 inputs + dynamic outputs codes; see HV-0 for the verified breakdown), all
`ValidationSeverity.ERROR`, all blocking. The pass/fail decision:

```python
# validation.py:53
@property
def passed(self) -> bool:
    return not any(item.severity == ValidationSeverity.ERROR for item in self.findings)
```

Since every finding is ERROR, every one of the approximately 75 codes hard-blocks publication.
There is no per-code policy, no warning-that-blocks, no error-that-doesn't.

### Frozen schema enums that must be mapped to, not redefined

The pull (commit `53efd01`) landed 5 schemas with rich enums:

| Schema | Enum field | Values |
| --- | --- | --- |
| review-finding | `severity` | blocking, major, minor |
| review-finding | `confidence` | high, medium, low |
| review-finding | `finding_type` | error, unsupported_claim, open_question, preference, clarity, reproducibility, novelty, significance, other |
| review-finding | `resolution_class` | (7 values) |
| theory-record | statement `status` | established, conditional, incomplete, contradicted, retracted, untested |
| empirical-protocol | deviation `disposition` | retain_with_caveat, exclude_affected_result, reanalyze_as_exploratory, rerun_required |
| review-issue | `disposition` | open, fixed, partially_fixed, deferred, rejected |

**None of these connect to machine `ValidationSeverity`.** The schema says
"this is a minor finding" but the validator emits ERROR and blocks publication.

### Dead validator branches: precise statement

Verified 2026-08-12: two P5 disposition checks mix live and dead enum members:

- `scientific_validators.py:954`: `disposition in {"fixed", "partially_fixed",
  "addressed", "accepted"}` -- `fixed`/`partially_fixed` are live;
  `addressed`/`accepted` are dead.
- `scientific_validators.py:965`: `disposition in {"deferred", "rejected",
  "wont_fix"}` -- `deferred`/`rejected` are live; `wont_fix` is dead.

The branches are LIVE and handle the current enum; the dead members are
unreachable but harmless. The original audit's "branches on values that no
longer exist ... correctness bugs that produce wrong results today" overstates
these two sites.

The real correctness gaps in this area:

- Theory-record statuses `conditional`, `untested`, `retracted` have no
  validator checks despite being schema-valid (confirmed: only the field name
  `retracted_statement_ids` appears in the validators).
- No per-enum coverage audit exists: nobody has verified that every live enum
  value in the 5 schemas is either checked or deliberately unchecked. For
  example `open` appears covered by `p5.issue_undispositioned`, but this has
  never been systematically verified.

## Work items

### HV-2.1: Implement the policy registry

**Target:** `src/method_hub/domain/validation.py`

Add a `FindingClass` enum matching the parent plan §5:

```python
class FindingClass(StrEnum):
    OPERATIONAL_FAILURE = "operational_failure"
    INTEGRITY_BLOCKER = "integrity_blocker"
    CORRECTABLE_CONTRACT_ERROR = "correctable_contract_error"
    SCIENTIFIC_CLAIM_BLOCKER = "scientific_claim_blocker"
    SCIENTIFIC_ATTENTION = "scientific_attention"
    INFORMATION = "information"
```

Add a `FindingPolicy` dataclass:

```python
@dataclass(frozen=True, slots=True)
class FindingPolicy:
    code: str
    finding_class: FindingClass
    default_severity: ValidationSeverity
    blocks_publication: bool
    correction_class: str  # "none", "deterministic", "packaging", "scientific"
    applicable_phases: tuple[str, ...]
    applicable_modes: tuple[str, ...]  # empty = all modes
    deterministic_repair_allowed: bool
    model_call_required: bool
    researcher_override_allowed: bool
    rationale: str
    user_guidance: str
```

Register all codes from the HV-0 inventory (about 75 static literals; dynamic
codes are covered by the default rule below). Default classifications:

| Class | Severity | Blocks? | Codes (examples) |
| --- | --- | --- | --- |
| Integrity blocker | ERROR | Yes | `submission.digest_mismatch`, `submission.project_mismatch`, `submission.phase_mismatch`, `input.method_identity_mismatch`, `submission.artifact_identity_mismatch` |
| Correctable contract error | ERROR | Yes (correctable) | `submission.required_output_missing`, `submission.output_shape_mismatch`, `output.role_has_no_contract` |
| Scientific claim blocker | ERROR | Yes | `p3.established_statement_unsupported`, `p5.claim_without_evidence`, `p4.evidence_method_mismatch` |
| Scientific attention | WARNING | No | (reclassified from current ERRORs -- see HV-2.3) |
| Information | INFORMATION | No | (new -- see HV-2.3) |

### HV-2.2: Classified findings instead of forced ERROR

**Registry totality rule (applies to HV-2.1 and HV-2.2):** dynamically
composed codes (jsonschema paths, JSON parse errors) cannot be enumerated, so
the registry defines a default policy: unregistered codes block publication.
No code becomes non-blocking by omission. Finding factories look up policy at
emission time, and a registry-completeness test extracts every literal
`_finding(...)` first argument from the source and asserts it is registered,
so a typo or a newly added code fails the test suite loudly instead of
silently inheriting a default.

**Constructor safety (verified 2026-08-12):** `ValidationFinding`
(`domain/validation.py:17-23`) is a frozen dataclass whose fields beyond
`code`/`message` already carry defaults. New fields must follow the same
pattern (defaulted) so all existing construction sites keep working.

**Target:** `src/method_hub/harness/scientific_validators.py:1296-1302`,
`src/method_hub/harness/submission_validation.py:404-416`,
`src/method_hub/harness/inputs.py`, `src/method_hub/harness/outputs.py`

Currently both `_finding` helpers hardcode `ValidationSeverity.ERROR`:
- `scientific_validators.py:1299`: `severity=ValidationSeverity.ERROR`
- `submission_validation.py:413`: `severity=ValidationSeverity.ERROR`

Change the finding factories to look up severity and blocking status from the
policy registry instead of hardcoding ERROR.

Extend `ValidationFinding` (`validation.py:17`) with:
- `finding_class: FindingClass`
- `blocks_publication: bool`
- `correction_class: str`

### HV-2.3: Reclassify findings by class

The bulk of the work: review each of the approximately 75 codes and assign its true class.

**Likely reclassifications from ERROR → WARNING (scientific attention):**
- `p1.search_provenance_missing` -- may be attention if the source origin is
  researcher-supplied, not search-derived
- Codes triggered by justified empty categories (HV-6 will define which)
- Honest `open_obligation` in theory-record

**Likely reclassifications from ERROR → INFORMATION:**
- Optional presentation improvements (new -- no current codes)

**Must remain ERROR (integrity blockers):**
- All `submission.*_mismatch` codes (project, phase, method, artifact)
- All `submission.digest_*` codes
- `input.method_identity_mismatch`, `input.method_lineage_mismatch`
- `submission.unsafe_path` (if it exists)

**Must remain ERROR (scientific claim blockers):**
- `p3.established_statement_unsupported`
- `p5.claim_without_evidence`
- `p4.evidence_method_mismatch`

This is a per-code review requiring domain understanding. Defer to HV-0's
evidence baseline and the phase-specific review in HV-6.

### HV-2.4: Compute decision from explicit blocks_publication

**Target:** `src/method_hub/domain/validation.py:53`,
`src/method_hub/harness/submission_validation.py:31`

Replace:
```python
@property
def passed(self) -> bool:
    return not any(item.severity == ValidationSeverity.ERROR for item in self.findings)
```

With:
```python
@property
def passed(self) -> bool:
    return not any(item.blocks_publication for item in self.findings)
```

The overall decision comes from explicit `blocks_publication` policy, not from
the mere presence of any finding or severity level.

### HV-2.5: Mode-aware policy

**Target:** `src/method_hub/domain/validation.py`, policy registry

Make policy mode-aware where scientific scope differs:
- P3: `p3.theory_establishment` vs `p3.theory_revision`
- P4: `p4.preliminary` vs `p4.comprehensive`

A finding code may have different policy in different modes. For example,
`p4.simulation_seed_missing` might block in `comprehensive` but warn in
`preliminary`.

### HV-2.6: Version the policy

Bind the policy version into each `ValidationAttempt` (defined in HV-0/parent
plan §6.1). When policy changes, old validation attempts retain their original
policy version.

### HV-2.7: Align validators with the current schema enums

**Target:** `src/method_hub/harness/scientific_validators.py`

Three pieces of work:

1. Remove the stale enum members at `scientific_validators.py:954,965`
   (`addressed`, `accepted`, `wont_fix`). The branches themselves are live and
   handle the current enum; this is cleanup, not a behavior fix.
2. Add validator checks for theory-record statuses `conditional`, `untested`,
   `retracted`, currently schema-valid but unvalidated:
   - `conditional`: require a conditioning assumption reference.
   - `untested`: require an explicit open obligation.
   - `retracted`: require a retraction reason and what supersedes it.
3. Run a per-enum coverage audit across the 5 schemas (review-finding
   severity/confidence/finding_type/resolution_class, theory statement and
   assumption statuses, deviation disposition, review-issue disposition):
   every enum value must have at least one validator check, or an explicit
   "deliberately unchecked" rationale recorded in the policy registry. This
   converts the original audit's anecdotal dead-branch finding into a
   systematic guarantee.

This is a correctness fix independent of the classification work. Do it in the
same package since the code is already being modified.

## Acceptance criteria

- [ ] Changing message wording cannot change acceptance behavior (policy is
      code-based, not message-based)
- [ ] All hard identity, provenance, digest, path, and publication checks
      still block (`blocks_publication=True`)
- [ ] Warning-only negative or inconclusive outputs can pass publication
- [ ] Tests exercise at least one finding in every policy class (6 classes)
- [ ] Dead validator branches fixed -- disposition/status checks align with
      current schema enums
- [ ] Policy version recorded in each validation attempt

## Files touched

| File | Change |
| --- | --- |
| `src/method_hub/domain/validation.py` | `FindingClass`, `FindingPolicy`, `ValidationFinding` extension, `passed` logic |
| `src/method_hub/harness/scientific_validators.py` | Classified findings, dead branch fixes |
| `src/method_hub/harness/submission_validation.py` | Classified findings, `passed` logic |
| `src/method_hub/harness/inputs.py` | Classified findings |
| `src/method_hub/harness/outputs.py` | Classified findings |
| `tests/test_scientific_validator_integrity.py` | Classification tests |
| `tests/test_harness_outputs.py` | Finding class tests |

## Dependencies

- HV-0 inventory (provides the code list and provisional classifications)
- HV-1 unified validation context (ensures mode-aware policy is actually
  consulted)

## Risks

- **Reclassification changes acceptance behavior**: codes moving from blocking
  to non-blocking will allow some previously-rejected outputs to publish. This
  is intended but must be validated against the HV-0 evidence baseline. Run in
  shadow mode first (HV-7) if possible.
- **About 75 codes is a lot of manual review**: delegate the per-phase
  classification review to parallel subagents (one per phase).

## Revision 2 changelog (2026-08-12, coder review)

- A1: corrected the code count (89 to about 75; per-lane table fixed).
- A2: replaced the overstated "dead validator branches" claim with the precise
  statement: the two disposition branches are live with dead members
  (`scientific_validators.py:954,965`); the real gaps are unvalidated theory
  statuses and the absence of a per-enum coverage audit.
- A3: added the registry totality rule (unregistered codes block; emission-time
  lookup; completeness test) to HV-2.2, closing the hole where a typo or a
  dynamic code silently changed acceptance behavior.
- A4: noted the verified constructor safety of extending `ValidationFinding`.
- A5: HV-2.7 reframed from "fix dead branches" to "align validators with the
  current schema enums", including the new per-enum coverage audit.
