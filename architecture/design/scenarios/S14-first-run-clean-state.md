# S14: First Run Starts With Clean State

`scenario_id: s14.first_run_clean_state`

## Purpose

Verify that the first persistent run of a project-role starts from clean
memory and session state, never from a stale or foreign copy.

## Contract under test

- ADR-012 items 4 and 5 (private runtime profile; memory and sessions use
  snapshot semantics): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 3, fixed rule 3, and acceptance item 2 (a first
  persistent run starts with clean project-role state):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-62
  (first-run state is clean), MF-34 and MF-53 (exact memory and session
  snapshot semantics). Invariant INV-003.

## Setup

- A project exists and at least one role definition is configured.
- No project-role state has ever been promoted for the role under test:
  there is no current memory directory and no current session snapshot.
- Other projects or roles have unrelated memory and session state that must
  not leak.

## Steps

1. The user starts the first persistent run for the role.
2. The assembler seals the invocation with the declared fresh state policy.
3. The run profile is assembled: memory files are absent or empty, and the
   session snapshot is empty.
4. The run executes and produces valid outputs.
5. Validation passes and promotion stages only what the run itself wrote.

## Expected evidence

- The manifest records empty memory and session snapshot inputs with complete
  provenance.
- The run profile contains no memory files copied from any other project,
  role, or the global Hermes profile.
- The promoted state digest equals the digest of the run's own memory and
  session files.
- Pilot evidence: in the project-004-eld Phase 2 pilot, the three first-stage
  runs each promoted from a null before-state
  (`/home/tez/model-forge-data/pilot-eld/hub.sqlite3`, `run_promotion_records`
  with `before_digest` of `{"memories": null, "state.db": null}`).

## Failure conditions

- The first run inherits memory or session state from another project, role,
  or the global profile.
- The manifest claims a fresh state policy but the profile contains copied
  state.
- A stale snapshot is promoted as if the run produced it.
