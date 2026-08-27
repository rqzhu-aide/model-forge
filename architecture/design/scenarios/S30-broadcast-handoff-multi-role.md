# S30: Broadcast Handoff Into a Multi-Role Stage

## Purpose

Verify that a role output using the handoff schema validates when the next
stage declares more than one role, and that a genuinely unresolvable
harness-owned field surfaces as an operational failure rather than an
agent-correctable defect (ADR-015, from the K-5 production evidence).

## Initial state

- A phase whose stage N declares a handoff-schema output and whose stage
  N+1 declares TWO OR MORE roles (for example P2: `p2.independent_proposals`
  handing off into `p2.cross_review`).

## User action

The researcher launches a run of that phase and mode.

## Expected behavior

- The harness does not write `to_role` (no single addressee exists), and
  the handoff output VALIDATES with the field absent: absence is the
  broadcast form.
- When the next stage declares exactly one role, `to_role` is populated
  deterministically with that role id, as before.
- If any harness-owned field cannot be satisfied by the harness, the
  finding classifies as `operational_failure` with
  `correction_class: "none"`: it blocks publication, names the harness
  fault in its message, and offers no correction control. The run's
  recovery routing is the plain failed path, not `needs_output_correction`.
- Agent-authored content findings on fields the agent owns keep their
  existing correctable classification.

## Out of scope

- Who consumes broadcast handoffs downstream; consumption semantics are
  unchanged by this scenario.
