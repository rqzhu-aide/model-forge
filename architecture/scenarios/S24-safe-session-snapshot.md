# S24: Safe Session Snapshot With Verified SQLite Backup

`scenario_id: s24.safe_session_snapshot`

## Purpose

Verify that session state is snapshotted only through the verified SQLite
backup procedure: a read-only source, an integrity-checked copy, a recorded
digest, and a fail-fast refusal when the source is busy.

## Contract under test

- ADR-012 item 5 (memory and sessions use snapshot semantics; session state
  is copied only while quiescent, through Hermes export and import when
  available or a verified SQLite backup procedure; Method Hub never copies a
  live database file): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 3 (treat Hermes session storage as opaque; never copy a
  live `state.db`) and acceptance item 3:
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MH-72 (safe
  session snapshot) and MH-53 (exact snapshot semantics, silent truncation
  prohibited). Invariant INV-003.

## Setup

- The canonical project-role `state.db` exists and is quiescent (no WAL
  activity).
- A second trial presents the same database with an active writer holding a
  lock.

## Steps

1. Quiescent trial: open the canonical database read-only, copy it through
   the SQLite online backup API (never the raw db/wal/shm files), run
   `PRAGMA integrity_check` and a smoke query on the copy, and record its
   sha256.
2. The manifest's `session_snapshot` field records the procedure id, source,
   quiescence flag (WAL present or not), and digest.
3. Busy trial: attempt the same snapshot while a writer holds the source.
   The procedure must fail fast with a clear busy error and compose with the
   seal rollback so no partial run state remains.
4. Verify the copied session actually restores the same conversation state
   and that conversation content is never parsed by Method Hub.

## Expected evidence

- The quiescent copy is byte-consistent, passes `PRAGMA integrity_check`,
  answers the smoke query, and matches the recorded digest.
- The busy source refuses the snapshot with a named error such as
  `SessionSnapshotBusy`, and the failed seal is rolled back.
- No live database file, WAL, or SHM file is ever copied directly.
- Fresh and reviewer policies record an empty session snapshot.

## Failure conditions

- A live database file is copied directly.
- A busy source blocks, hangs, or produces an unverified copy.
- The snapshot digest or quiescence flag is missing from the manifest.
- A truncated or unverified session is promoted as current.
