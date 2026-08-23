# S18: Hermes Version Change Surfaces at Preflight

`scenario_id: s18.hermes_version_change_preflight`

## Purpose

Verify that a changed locally installed Hermes executable surfaces at
preflight, is shown to the user, and is recorded in the next run manifest,
without any Model Forge image rebuild and without false drift alarms from
update-check noise.

## Contract under test

- ADR-012 item 8 (Hermes updates do not require a Model Forge runtime image;
  preflight verifies the installed executable and records path, version, and
  other available immutable identity): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 4 and acceptance item 11 (changing the locally installed
  Hermes version requires preflight review and appears in the next manifest):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-66 (version
  change surfaces at preflight), MF-03 (frozen basis) and MF-34 (executable
  identity in the run basis). Invariant INV-003.

## Setup

- A sealed invocation records the Hermes executable path, version, and
  immutable build identity.
- The same Hermes binary remains installed.

## Steps

1. Run preflight on an unchanged installation; the executable check passes.
2. Replace the installed Hermes binary with a different version.
3. Run preflight again on the same seal; it must report the version change
   with the recorded and current identities.
4. The user reviews and confirms; the next seal and manifest record the new
   version.
5. Control trial: probe `hermes --version` repeatedly on an unchanged binary
   whose output carries update-check state (upstream head hash and an
   "Update available" notice). Preflight must not report drift.

## Expected evidence

- The preflight report names the recorded and current Hermes build identity
  when a real version change occurs.
- The next manifest records the new executable identity; no container or
  image rebuild is involved.
- Update-check noise alone never fails preflight.
- Pilot evidence (attempt 2): in the project-004-eld pilot, a seal recorded
  upstream head `43717123` and preflight refused minutes later against
  `36cb5ae5` on an unchanged binary, because `hermes --version` embeds
  update-check state. Commit `7986f12` fixed drift detection to compare the
  stable `Hermes Agent vX (date)` build identity; the same seal then launched
  and validated successfully.

## Failure conditions

- A real Hermes version change passes preflight silently.
- Update-check noise produces a false drift refusal.
- The manifest records a version that was never verified.
- Preflight blocks on a changed version instead of surfacing it for user
  review.
