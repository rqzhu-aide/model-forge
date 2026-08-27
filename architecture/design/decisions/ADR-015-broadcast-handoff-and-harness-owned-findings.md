# ADR-015: Broadcast Handoff Addressing and Harness-Owned-Field Finding Routing

## Status

Accepted (2026-08-20, Tez; decision from the K-5 production re-exercise
fix list, evidence: `architecture/evidence/k5-production-re-exercise-2026-08-20.md`)

## Context

The K-5 controlled production run (P2 full catalog, 2026-08-20) failed at
stage `p2.independent_proposals` on a theorist handoff output with a single
finding: `schema.required`, "'to_role' is a required property". The failure
was deterministic and harness-caused, not agent-caused:

1. `handoff.schema.json` requires `to_role` (enum `roleId`).
2. The harness owns `to_role`: `populate_harness_fields` writes it only when
   `SealedRunFacts.to_role` is truthy, and `_sealed_run_facts` resolves it
   only when the NEXT stage declares exactly ONE role.
3. P2 stage 2 (`p2.cross_review`) declares TWO roles (theorist +
   data_analyst), so `to_role` is never written and the handoff can never
   validate. Under this contract, P2 full catalog cannot pass stage 1.

The same run exposed a routing defect: the finding was classified
`correctable_contract_error`, inviting a correction command. But NO
correction lane can repair a harness-owned field: deterministic
normalization cannot invent a role name, and a Lane B role re-invocation
has its output envelope re-populated (or omitted) by the harness at close.
Offering correction for such findings would spend the bounded correction
budget on an unfixable-by-agent defect and mislead the researcher.

## Decision

1. **Broadcast absence.** `to_role` becomes OPTIONAL in
   `handoff.schema.json`. Absence means the handoff addresses every role of
   the next stage (a broadcast). When the next stage declares exactly one
   role the harness continues to populate `to_role` deterministically. The
   `roleId` enum is unchanged; no sentinel value is introduced.

2. **Harness-owned-field routing.** A `schema.*` finding whose failing
   property is harness-owned for the output's schema (per
   `harness_owned_fields(schema_file)`) classifies as
   `operational_failure` with `correction_class: "none"`, not
   `correctable_contract_error`. Such a finding blocks publication, carries
   a message naming the harness fault, offers NO correction, and routes the
   run to the plain failed recovery path. The policy registry version is
   bumped because the effective policy for the `schema.*` family changed.

## Invariants that must remain true

- The harness still owns envelope fields; agents must not write them.
- A resolvable single-role next stage still yields a populated `to_role`.
- Agent-content findings on non-harness-owned fields keep their existing
  correctable classification unchanged.
- A broadcast handoff (absent `to_role`) validates; an invalid `to_role`
  value still fails `schema.enum`.

## Consequences

- P2 full catalog (and any phase whose stage hands off into a multi-role
  stage) can pass structural validation again.
- A genuine harness population failure now fails loudly and honestly as an
  operational failure instead of masquerading as an agent-correctable
  defect.
- Scenario S30 covers the broadcast case.
