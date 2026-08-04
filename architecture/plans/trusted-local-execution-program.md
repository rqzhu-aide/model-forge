# Trusted Local Execution Program

Status: Active program plan, 2026-08-04. Supersedes the WP0-WP9 framing of
`operational-completion-plan.md` for Version 1 execution work; that document
remains as historical program context.

Baseline: commit `720b307` + Block 4 hardening (in review).

Controlling documents:

- [ADR-012: Trusted local Hermes execution](../decisions/ADR-012-trusted-local-hermes-execution.md)
  (+ Amendment 1: OCI code removed)
- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)
  (Revision 1) - the block definitions this program dispatches

## 1. Why this plan exists

The execution-boundary decision changed mid-program (OCI removed per ADR-012),
Block 4 landed out of order, and the work is now executed by two supervised
agent profiles (`developer`, `worker`) with independent validation. This plan
restructures the remaining work into dispatchable packages with explicit
dependencies, sizes, and acceptance checks. It replaces - it does not
summarize - the earlier WP sequencing for execution work.

## 2. Current state (validated 2026-08-04)

Done and verified:

- OCI executor, Bubblewrap, Containerfile, OCI secret delivery, and all OCI
  test suites removed (ADR-012 Amendment 1). 401 backend tests green.
- `LocalHermesExecutor` (Block 4 core): direct no-shell `hermes -z` launch,
  durable process identity with PID-reuse detection, version recording,
  SIGTERM→SIGKILL process-group termination, diagnostic lane rewired.
- Worker audit of OCI leftovers in schemas/examples (`~/oci-schema-audit.md`,
  independently verified accurate).
- Block 4 hardening (commit `5c1d399`, probe-verified): cumulative output
  cap with drain-and-discard, chunked stream reads, `cwd=workspace`, five
  end-to-end synthetic tests (success, flood, over-long line, cancel kills
  grandchild, timeout), interim `oneshot.py` removed. 404 tests green.
- **WP-A complete** (commit `5857865`, independently validated): the
  `trusted_local` executor binding is now in
  `role-invocation-start.schema.json` with both examples conforming (positive
  and negative schema checks verified through the repo SchemaCatalog).
- **WP-C complete** (commit `ab2d9c4`, live-API verified): the Block 2 role
  configuration service exposes all four role definitions, skill
  version/source/digest reporting, customization-conflict protection, and
  atomic rollback. 444 tests green.
- **WP-B complete** (commit `b40c9c9` + validator fix-up `e7d3e62`):
  ADR-012 wording applied to the numbered docs, `validate_package.py`
  aligned with the trusted-local binding, the stale example digest cascade
  left by WP-A repaired (start -> closure -> submission -> downstream ->
  run-state -> receipts), and the architecture package validator exits 0.
- **WP-D1 complete** (commit `1d19a90` + validator fix): run-profile
  assembler core - DB-backed state lock with fencing tokens and leases,
  run directory layout, byte-exact profile assembly from the WP-C role
  definition with per-asset digests, policy-driven memory snapshot
  (reviewer always fresh), fail-closed credential exclusion, immutable
  JCS-digested manifest, idempotent sealing, and seal rollback. 471 tests
  green. Custom skills are manifest declarations (the catalog carries no
  bundled content). WP-D2 (session snapshots, preflight, determinism
  checkpoint) is next.

Known deviations being corrected: Block 4 landed before Blocks 1-3 (plan
order violated; tolerated because the executor is self-contained, but Block 1
is now overdue because code depends on a `trusted_local` binding the schemas
do not yet define).

## 3. Execution and validation protocol

- Work is dispatched as bounded one-shot tasks to the `developer` profile
  (larger packages) or the `worker` profile (smaller, verifiable packages).
- Only ONE profile works the repository at a time. A package is dispatched
  only when the previous one is committed and the tree is clean.
- The coder profile validates every completed package before the next is
  dispatched: diff review against the package scope, file:line claim checks,
  behavioral probes where the package makes runtime claims, and a full green
  backend suite. Self-reports are not accepted as evidence.
- Every package ends in ONE git commit with a descriptive message. Workers
  never amend architecture decision records. Phase contracts and role order
  are out of scope for all packages.

## 4. Work packages

### WP-A - Block 1: `trusted_local` executor binding in contracts (worker, small)

Scope: `architecture/schemas/role-invocation-start.schema.json`
(replace the `executorBinding` $def, lines 437-504, with a trusted-local
binding per the worker audit), the two `role-invocation-*.example.json`
fixtures, and one-line rewords in `schemas/README.md` (182-183) and
`examples/README.md` (69). Binding must record: backend const
`trusted_local`, Hermes executable identity (path, version, available
immutable identity), role-definition revision, project-state snapshot
identity, working roots, and local process-control policy - per ADR-012
"Schema changes". Keep `broker_transport` and explicit executor type/version
so future OCI records stay distinguishable. Remove namespace/rootfs/
capability/mount/egress-enforcement fields.
Acceptance: full backend suite green; both examples validate against the
updated schema through the existing specification-package tests; no remaining
`rootless_oci`/namespace fields outside historical docs.
Depends on: nothing (audit complete).

### WP-B - Block 1 remainder: numbered architecture docs + validation tool (worker, small)

Scope: apply ADR-012 wording to `00-system-principles.md` (1 hit),
`02-run-harness.md` (1 hit), `06-implementation-roadmap.md` (3 hits),
`08-role-context-and-communication.md` (3 hits) - replace enforced-isolation
claims with the trusted-local boundary. Preserve frozen-context, immutable
record, user-control, reviewer-packet, and publication invariants. Also fix
`architecture/tools/validate_package.py` (found during WP-A): its
`validate_role_invocation_lifecycle` still checks OCI binding fields
(`network_egress` at line 897) and crashes on post-WP-A examples - align its
checks with the `trusted_local` binding and verify the tool runs cleanly
against the full architecture package.
Acceptance: no doc claims OS-level isolation from Hermes; the validation
tool passes against the package; all changes reviewed diff-by-diff.
Depends on: WP-A (so wording matches the new binding).

### WP-C - Block 2: role configuration service (developer, large)

Scope: configuration-managed definitions for research lead, theorist, data
analyst, outside reviewer (SOUL, base config, recommended+custom skills,
library guidance); one-click skill install/update showing version, source,
digest, customization status; no silent overwrite of customizations; atomic
provisioning with rollback; status for missing Hermes/profiles, invalid role
files, skill mismatch, unsupported versions. Backend + API + tests.
Acceptance: Block 2 checkpoint - configuration page data (API level) can
create and inspect all four role definitions and report exact installed
assets; conflict path requires explicit user choice; suite green.
Depends on: Block 4 hardening committed.

### WP-D - Block 3: run-profile assembler (developer, large)

Scope: project-role state lock; sealed idempotent invocation; run directory
(profile/workspace/inputs/outputs/logs/manifest); profile assembly from role
definition + selected project-role memory and safe session snapshot
(export/import when available, else verified SQLite backup while quiescent -
never copy a live `state.db`); fresh-state mode for first runs and the
outside reviewer; materialize only selected context; credentials never copied
into profiles/manifests/logs/evidence; preflight (Hermes, assets, state,
paths, permissions, space, lock, brief, output contract).
Acceptance: Block 3 checkpoint - two preparations from the same sealed basis
produce equivalent manifests and run-profile content apart from declared
invocation identifiers/timestamps; suite green.
Depends on: WP-C.

### WP-E - Block 5: validate, record, promote (developer, large)

Scope: post-quiescence validation through the real run path (names, safe
paths, schemas, nonempty scientific fields, companions, run/method identity,
phase consistency); memory-before/runtime-after inventories; allowlisted
memory/session staging (never SOUL/skills/config/credentials/logs/caches);
atomic pointer advance with last-known-good preservation; promotion receipts;
retention rules; failure/cancel/timeout/invalid/stale/unresolved runs change
no current state.
Acceptance: Block 5 checkpoint - injected failure at any promotion step
leaves previous formal and project-role state usable; suite green.
Depends on: WP-D.

### WP-F - Block 6: Web operation surface (developer, medium)

Scope: role-definition health + Hermes version + customization status on
configuration pages; pre-run basis display; live state/elapsed/bounded logs +
cancellation during runs; closure view with validation result, promoted/
retained items, memory-session disposition, promotion receipt, smallest safe
next action. No automatic phase progression anywhere.
Acceptance: Block 6 checkpoint - configure, start, observe, cancel, and
understand one real local run entirely through the UI; frontend + backend
tests green.
Depends on: WP-C, WP-D, WP-E.

### WP-G - scenarios and traceability (worker, medium)

Scope: add the ADR-012 scenario set (exact role setup, first-run state,
continuation, fresh reviewer, invalid output, cancellation, timeout, restart
reconciliation, stale locks, failed promotion, Hermes version change, bounded
logs, safe session snapshots) and align `07-contract-traceability.md`;
move OCI escape/network-isolation scenarios to a deferred-hardening note.
Acceptance: every scenario cites the contract it tests; review against
ADR-012 "Scenario changes"; docs only.
Depends on: WP-A, WP-B.

### WP-H - WP0 reviewed-basis completion (developer, medium)

Scope: close the audited WP0 gaps - phase-role resolution with empty choices
silently omitting role resources; underspecified basis acceptance; missing
input/method/digest drift passing without rejection; resource snapshot must
cover the exact installed profile, model/provider, phase instruction, tools,
knowledge resources, memory policy (not bundled recommendations); basis
inspection in the Web interface.
Acceptance: WP0 exit-gate items in `wp0-reviewed-basis-closure.md`; suite
green.
Depends on: WP-C (exact role assets exist to bind).

### WP-I - WP2 adapters and five-phase pilot (developer + worker, large)

Scope: remaining phase-specific WP2 output adapters with real Hermes
fixtures, then a controlled real five-phase pilot through the local path
(acceptance evidence §7 of the closure plan, item by item).
Depends on: WP-D, WP-E, WP-F. WP0 (WP-H) must pass before publishable runs.

## 5. Sequence

```text
WP-A ──> WP-B ──> WP-G          (worker lane, docs/contracts)
WP-C ──> WP-D ──> WP-E ──> WP-F (developer lane, runtime)
WP-C ──> WP-H                   (reviewed basis needs exact role assets)
WP-D + WP-E + WP-F ──> WP-I     (pilot; WP-H gate for publishable runs)
```

Lanes alternate: while the developer holds the repository, worker packages
wait, and vice versa (§3 single-writer rule). Suggested interleave:
WP-A → WP-C → WP-B → WP-D → WP-G → WP-E → WP-H → WP-F → WP-I.

## 6. Explicitly out of scope (unchanged from ADR-012 §9)

Rootless OCI or any security sandbox; provider-only network enforcement;
malicious-tool protection; multi-user hosting; unattended remote execution;
Windows support; automatic scientific retries or phase progression;
autonomous project direction.
