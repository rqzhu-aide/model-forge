# K-5 Production Re-Exercise: P2 Full Catalog (2026-08-20)

Controlled re-run of the known-failing P2 `p2.full_catalog` mode through the
repaired formal lane (ISS-1..7 + K-1 correction lane landed), per the K-5 item
in `architecture/plans/k1-remaining-implementation-plan-2026-08-17.md` and the
harness audit 2026-08-16.

## Setup

- Server: `METHOD_HUB_EXECUTOR_KIND=local_hermes
  METHOD_HUB_DATA_ANALYST_PROFILE=data_scientist method-hub serve`
  (loopback :8765). The `data_analyst` role needed the profile override: no
  `data_analyst` Hermes profile directory exists; the configured
  `data_scientist` profile carries the deepseek-v4-flash credentials.
- Backup before exercise: `~/.method-hub-backups/20260820-085410` (55 MB:
  database, artifacts, runs).
- Project: `project.entangled_langevin_particle_acceleration.b2d9f388...`
  (the project with all 27 historical full-catalog runs: 22 failed, 5
  published).
- Controlled input: the SAME instruction text as the last published
  full-catalog run (`...9789b57d`), `current_only` context, default current
  inputs.
- Run: `run.p2.p2-full-catalog.6c5396b46884491996678351277b4721`, launched
  2026-08-20 08:57 CDT via `POST /runs` with an Idempotency-Key.

Client-side incidents during launch (both machinery working as designed):

1. A phase view fetched WITHOUT `?mode=` yields a start_run descriptor whose
   basis differs from the explicit-mode view the command path recomputes;
   the command was correctly refused CONTROL_HEAD_STALE. The web UI always
   passes the mode; ad-hoc API clients must too.
2. Reusing one Idempotency-Key after changing the request body was correctly
   refused IDEMPOTENCY_KEY_REUSED.

## Run outcome

FAILED after ~40 minutes (08:57 -> 09:36:58 CDT) at stage
`p2.independent_proposals`:

| Role | Closure |
|---|---|
| research_lead | succeeded |
| theorist | FAILED, `output.structural_validation_failed` |
| data_analyst | succeeded |

The theorist closure carries ONE finding, correctly classified by the
repaired lane (historical rows had `finding_class: null`):

```
schema.required | correctable_contract_error | blocks | json_pointer ""
"'to_role' is a required property"
```

The theorist's `theory-proposal.json` (a `handoff.schema.json` document) is
complete and coherent on disk; it simply lacks the harness-owned `to_role`.

## Finding K5-1: deterministic harness gap, not an agent failure

`handoff.schema.json` REQUIRES `to_role` (enum `roleId`: user, system,
research_lead, theorist, data_analyst, outside_reviewer). The harness owns
this field: `populate_harness_fields` (envelope.py:360) writes it ONLY when
`run_facts.to_role` is truthy, and `_sealed_run_facts`
(role_execution.py:2066-2072) resolves `to_role` ONLY when the NEXT stage
has exactly ONE role:

```python
if len(later_roles) == 1:
    to_role = later_roles[0]
```

P2 stage 1's next stage (`p2.cross_review`) has TWO roles (theorist +
data_analyst), so `to_role` stays empty, the field is never written, and the
handoff output fails `schema.required` EVERY time. Under the current contract
P2 full_catalog cannot pass stage 1: the failure is produced by the harness's
own population gap, with the agent fully brief-obedient. The five historical
publications predate the HV envelope regime (2026-08-15).

DESIGN DECISION NEEDED (contract change; ADR + scenario updates first per
repo rules): what is `to_role` for a handoff into a multi-role stage?
Options: (a) make `to_role` optional in handoff.schema.json; (b) permit a
broadcast sentinel (`system` reads naturally); (c) drop the handoff schema
from the stage-1 theorist output set if the handoff is not load-bearing
there.

## Finding K5-2: correction lane unreachable for role-group failures

Verified LIVE (not just by code reading):

```
POST .../corrections/preview  {"transformation_codes": []}
  -> 409 CORRECTION_NOT_APPLICABLE
     "This run has no correctable contract error to correct; its findings
      are integrity blockers."

POST .../corrections  {revalidate, scope [p2.theory_proposal], descriptor}
  -> 409 CORRECTION_NOT_APPLICABLE (same message)
```

The message is factually wrong for this run: the sealed closure finding IS a
`correctable_contract_error`. Root cause: `RunCoordinator._fail` on the
role-group failure path (run_coordinator.py:305) does NOT pass the failed
closure's findings, so the run payload never gains `closure_findings`. Both
correction gates (service.py:2055 and :2663) read ONLY the run payload's
`closure_findings`, so every correction type refuses. Meanwhile the run
detail emits all four correction descriptors ENABLED (the surface condition
is recovery_summary-based), so the UI advertises controls that all refuse -
a UI/backend consistency gap on top of the propagation gap.

Fix direction (coder-actionable, no contract change): pass the failed
stage's closure findings into `_fail` (the orchestration stage outcomes carry
them), and align the researcher_message with the actual gate outcome.

## Finding K5-3: the empty-outputs scope wall behind K5-2

Even with findings propagated, this failure class hits two more walls:

1. The failed closure declares ZERO outputs (validation failed before output
   sealing), so the scope gate (`permitted_output_scope` subset of the
   closure's declared outputs) rejects every non-empty scope. Natural
   semantics: when the target closure sealed nothing, the scope should be
   the failed stage/role's plan-declared contract outputs (the preview
   machinery already resolves exactly that set via the frozen recipe).
2. Lane B's source-bytes materialization indexes
   `source_output_bytes[spec.contract_output_id]` directly (KeyError on
   absent outputs) where the P5a-ii design sketch said skip-if-missing. With
   an empty-outputs base closure every declared output is absent.

The landed lane therefore covers (a) REJECTED runs whose closures all
succeeded (D5) and (b) FAILED runs whose closure failed AFTER sealing
outputs. It does NOT cover the dominant production failure class: role
output fails validation, closure failed, nothing sealed.

## Evidence verdict

- ISS-fix classification works in production: the finding was classified
  `correctable_contract_error` (historical rows: null).
- The correction command path's transport protections (CONTROL_HEAD_STALE,
  IDEMPOTENCY_KEY_REUSED, schema validation) all behaved correctly against
  real client mistakes.
- The correction lane has never yet been exercisable end to end in
  production: K5-1 blocks the phase itself, and K5-2/K5-3 block recovery
  for the failure class that phase produces.
- Recommended order: decide K5-1 (contract; unblocks the phase) -> fix K5-2
  (findings propagation + message) -> fix K5-3 (empty-outputs scope
  semantics + Lane B skip-if-missing) -> re-run this exercise. The same
  controlled input remains valid for the re-run.
