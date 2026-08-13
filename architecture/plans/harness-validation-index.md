# Harness Validation Program -- Implementation Index

Status: Revised plan, 2026-08-12

Parent plan: [harness-validation-and-output-recovery-plan.md](harness-validation-and-output-recovery-plan.md)

This index replaces the delivery-order narrative in the parent plan's
Section 11. Each work package now has its own detailed revision file with
concrete code evidence, file targets, and acceptance criteria derived from a
four-way audit of the current codebase (commit `53efd01`).

## Audit findings that shape every package

1. **About 75 enumerable finding codes** across 4 validator lanes (48
   scientific, 19 submission, 7 inputs, plus dynamically composed codes in
   outputs that are unbounded). Every single one is `ValidationSeverity.ERROR`.
   The `WARNING` and `INFORMATION` enum values have zero uses repo-wide.
   Pass/fail is computed purely from `any(severity == ERROR)`. (Count verified
   2026-08-12; codes are positional `_finding(...)` arguments, so keyword
   greps undercount. See HV-0 for the exact extraction recipe.)

2. **Repair runs before sealing.** `_apply_disclosed_mechanical_repairs`
   rewrites output in-place (`role_execution.py:976-997`); `_seal_output`
   seals post-repair bytes. `preserve_raw_output` runs only in the FAILED
   branch (`role_execution.py:1008-1015`). No transformation log exists --
   the "disclosed" in the function name is aspirational.

3. **The supervised mode shim actively generates false failures.**
   `_phase_plan_shim` (`output_validation.py:440-464`) hardcodes
   `mode_id=""`, causing `p3.development_mode_mismatch` and
   `p4.protocol_mode_mismatch` to fire on every valid record. This is worse
   than "inconsistent decisions" -- it is a correctness bug.

4. **The pull landed 5 schemas with rich frozen enums** (severity, confidence,
   finding_type, resolution_class, statement status, deviation disposition).
   None connect to machine `ValidationSeverity`. HV-2's policy registry must
   map to these, not redefine them, and publication policy keys on
   harness-owned finding codes only: agent-authored severity (for example
   `severity=minor`) informs display and triage but must never change whether
   a finding blocks publication, or a model could downgrade its own findings.

5. **Both FAILED and REJECTED are terminal with no correction path.** The
   plan's recovery machinery must explicitly cover both, or explain why not.

6. **Stale enum members and unvalidated statuses.** Two P5 disposition
   branches (`scientific_validators.py:954,965`) list retired values
   (`addressed`, `accepted`, `wont_fix`) alongside the live enum
   (`[open, fixed, partially_fixed, deferred, rejected]`); the branches are
   live, the retired members unreachable. The real gaps: theory-record
   statuses `conditional`, `untested`, `retracted` are schema-valid with no
   validator checks, and no per-enum coverage audit exists. HV-2.7 owns the
   fix.

## File map

| File | Package | Scope |
| --- | --- | --- |
| [HV-0-architecture-and-failure-baseline.md](HV-0-architecture-and-failure-baseline.md) | HV-0 | Finding code inventory, ADR, scenarios, baseline evidence |
| [HV-1-raw-preservation-and-validation-unification.md](HV-1-raw-preservation-and-validation-unification.md) | HV-1 | Raw sealing, repair safety, unified validation context |
| [HV-2-validation-policy-registry.md](HV-2-validation-policy-registry.md) | HV-2 | Finding classification, severity tiers, per-code block policy |
| [HV-3-lifecycle-separation-and-diagnostics.md](HV-3-lifecycle-separation-and-diagnostics.md) | HV-3 | Domain model refactor: 4 independent axes, needs_output_correction |
| [HV-4-harness-envelope-construction.md](HV-4-harness-envelope-construction.md) | HV-4 | Harness-owned identity/digest/timestamp/envelope construction |
| [HV-5-bounded-user-controlled-recovery.md](HV-5-bounded-user-controlled-recovery.md) | HV-5 | Revalidate, normalize, targeted correction commands |
| [HV-6-phase-schema-calibration.md](HV-6-phase-schema-calibration.md) | HV-6 | Per-phase schema loosening for valid scientific structures |
| [HV-7-pilot-measure-harden.md](HV-7-pilot-measure-harden.md) | HV-7 | Shadow comparison, calibration corpus, operational hardening |

## Delivery order

```
Block 1 (fix data loss + correctness):  HV-0  →  HV-1
Block 2 (classification + lifecycle):   HV-2  →  HV-3
Block 3 (reduce agent burden):          HV-4
Block 4 (recovery):                     HV-5
Block 5 (schema calibration):           HV-6  (per-phase, one at a time)
Block 6 (hardening):                    HV-7
```

HV-0 and HV-1 are the first implementation block. They fix the mode-context
defect and prevent output loss while collecting evidence needed to calibrate
strictness. Do not implement automatic or model-based correction (HV-5) before
raw preservation (HV-1) and complete validation reports (HV-2/HV-3) exist.

## Decisions recorded in Revision 2 (2026-08-12)

Full evidence: [harness-validation-review-2026-08-12.md](harness-validation-review-2026-08-12.md).
Each HV file carries its own amendment changelog.

- **Registry totality**: dynamically composed finding codes are unbounded, so
  unregistered codes default to blocking; a completeness test catches
  unregistered literal codes.
- **Correction basis pinning**: a correction attempt seals against the
  original run's frozen basis content, not the current authority head;
  concurrent publication surfaces as `conflicted` through the existing atomic
  publication check.
- **Submission re-entry**: the base submission row is immutable and unique
  per run, so corrections create `run_submission_attempts` records and
  publication binds the latest passing attempt (HV-5.1).
- **HV-4 rescoped**: harness populates harness-owned fields within the
  EXISTING schema shapes; no new envelope document, no contract change.
- **HV-3 control gating**: the run page shows accurate status and findings
  but renders no recovery controls until HV-5 machinery exists.
- **Schema ownership**: HV-0.6 authors the ValidationAttempt,
  OutputTransformationRecord, RoleAttempt, and OutputCorrectionCommand
  schemas before runtime code depends on them.
- **Traceability**: new scenarios require the validator range extension and
  `traceability.json` registration procedure (HV-0.5); without it the spec
  gate fails.
