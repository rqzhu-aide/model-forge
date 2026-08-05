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
- **WP-D2a complete** (commit `f865717`, zero validation defects): verified
  SQLite session snapshot procedure - read-only source, shared-lock-held
  preflight, fail-fast `SessionSnapshotBusy`, integrity-checked copy,
  quiescence flag, conversation content never parsed. Busy abort composes
  with the WP-D1 seal rollback. 478 tests green.
- **WP-D2b complete** (commit `e915804`, zero validation defects): run
  preflight service - 8 named checks (hermes version drift, asset and state
  digests, paths/permissions, free space, lock ownership, task brief,
  output contract with escape rejection), read-only, report-only, 37 tests
  with positive and negative cases each. 515 tests green.
- **WP-D2c complete** (commit `2c991eb`, zero validation defects): Block 3
  determinism checkpoint - two seals of the same basis produce
  byte-identical run profiles (state.db included) and manifests equal
  after an explicit, narrow exception list; negative control detects
  drift. 518 tests green. **Block 3 is CLOSED.**
- **WP-E0 complete** (commit `c2a7868`; two-pass: implementation hit the
  iteration cap, code reviewed sound, small completion pass finished it):
  supervised launch wiring - seal -> state lock -> preflight gate -> brief
  materialization -> LocalHermesExecutor with HERMES_HOME=run profile and
  no -p arg (backward-compatible `use_profile_arg`), bounded logs,
  launch-record lifecycle, widened `sk-` redaction for modern keys.
  524 tests green.
- **WP-E1 complete** (commit `077808d`, zero validation defects):
  post-execution output validation - terminal-launch guard (post-
  quiescence), raw-output inventory before judgment (symlinks recorded,
  never followed), undeclared files fail, present-but-empty scientific
  fields fail, wrong-basis identity fails, per-file digests, verdicts
  recorded on a sibling table (seal registry untouched). 551 tests green.
- **WP-E2 complete** (commit `c6ed95f`; subagent verified but hit the cap
  before committing - validator reviewed and committed): allowlisted
  promotion - gates (succeeded launch, passed validation, promotable
  policy, lock), staging of memories/ + state.db only (secrets excluded,
  digest-verified), atomic replace with last-known-good backups, full
  rollback even on record-write failure. Block 5 checkpoint tested as an
  injected-failure matrix. 575 tests green.
- **WP-E3 complete** (commit `5a7a7ae`; subagent capped before final
  verification - validator fixed a wrong backup-name regex and one
  fixture, then committed): deterministic idempotent promotion receipts
  with JCS sidecars; dry-run-by-default retention with a hard never-prune
  list and tamper reporting. 590 tests green. **Block 5 is CLOSED** -
  the runtime loop seal -> preflight -> launch -> validate -> promote is
  fully implemented.
- **WP-G complete** (commit `8edeeb1`; subagent capped before commit,
  validator verified and committed): S13-S24 trusted-local scenario suite,
  traceability extended MH-61..MH-72 with contract/test/scenario mapping
  and pilot evidence citations, OCI scenarios marked deferred hardening.
  592 tests green. **Pilot milestone**: project-004-eld Phase 2 completed
  through the real supervised path (5 runs, 6 promotions, memory
  continuity verified); preflight drift-noise fix `7986f12`.
- **WP-H1 complete** (commit `f494aa0`; four passes - audit, design,
  rewrite, completion - with two real defects caught by live probing,
  including a swallowed manifest-path error my own design review missed):
  acceptance-time completeness gate for the sealed basis (C6-respecting),
  empty-choices role omission fixed, and all four silently-skipped drift
  classes (unmatched input, method identity, missing live role, extra
  digests) now reject with stable stale_basis codes. 603 tests green.
- **WP-H2 complete** (commits `b8f7b37` + `095b421`): exact installed role
  configuration sealed in the basis - memory policy from the catalog,
  explicit null model/provider and phase instruction where the catalog
  lacks them, drift rejection via the WP-H1 machinery. The co-programmer
  absorbed the capped subagent's production work into their audit-fix
  commit (executor C1-C4 PID-reuse/boot-id safety, assembler C5/H1/H5,
  provisioner H2-H8, OCI doc cleanup) - reviewed by file:line, all sound;
  I added the two missing WP-H2 drift/snapshot tests. 636 tests green.
  **WP0 exit gate is now reviewable.**

Known deviations being corrected: Block 4 landed before Blocks 1-3 (plan
order violated; tolerated because the executor is self-contained, but Block 1
is now overdue because code depends on a `trusted_local` binding the schemas
do not yet define).

## 3. Execution and validation protocol

- Work is dispatched as bounded one-shot tasks to subagents (delegate_task,
  deepseek-v4-flash). The coder profile plans, writes self-contained briefs,
  validates every result, and stewards the plan documents.
- Package sizing rule (2026-08-04, researcher directive): one concern per
  package. Split anything with more than ~3 distinct behaviors or an
  expected diff over ~5 files. A failed package must be cheap to discard
  and re-dispatch with a corrected brief. Subagents do essentially all
  implementation; the coder does only truly tiny surgical fixes.
- Only ONE subagent works the repository at a time. A package is dispatched
  only when the previous one is committed and the tree is clean.
- The coder validates every completed package before the next is
  dispatched: diff review against the package scope, file:line claim checks,
  behavioral probes where the package makes runtime claims, and a full green
  backend suite. Self-reports are not accepted as evidence.
- Every package ends in ONE git commit with a descriptive message. Subagents
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

### WP-D - Block 3: run-profile assembler (developer lane, split for size)

WP-D1 (complete, `1d19a90` + validator fix): assembler core. The remainder
of Block 3 is split into three small packages:

### WP-D2a - session snapshot procedure (subagent, small)

Scope: add safe session-state snapshots to the assembler. Verified fact
(parent probe 2026-08-04): `hermes sessions export` is a READABLE export
(JSONL/MD), NOT a restorable state snapshot; no session import exists.
Per ADR-012 item 5 the mechanism is therefore a verified SQLite backup:
open the canonical project-role `state.db` read-only, copy via the SQLite
online backup API (never copy the raw db/wal/shm files), refuse fast on a
busy database, then `PRAGMA integrity_check` + a smoke query on the copy
and record its sha256. Record in the manifest's reserved `session_snapshot`
field: procedure id, source, quiescence flag (wal present or not), digest.
Fresh/ephemeral policy (and the outside reviewer) gets empty session state.
Acceptance: snapshot of a known DB is byte-consistent and integrity-checked;
a busy source fails fast with a clear error; reviewer snapshot is empty;
suite green.
Depends on: WP-D1.

### WP-D2b - preflight service (subagent, small)

Scope: the Block 3 preflight checklist as a service over WP-D1 sealed runs:
verify Hermes executable + version, role assets vs manifest digests,
selected state presence, run paths and permissions, free disk space, lock
ownership, task brief presence, expected output contract. Structured
pass/fail report per check; no auto-repair.
Acceptance: each check has a positive and negative test; suite green.
Depends on: WP-D1.

### WP-D2c - determinism checkpoint (subagent, small)

Scope: the Block 3 checkpoint as a test package: two preparations from the
same sealed basis produce equivalent manifests and run-profile content,
apart from declared invocation identifiers and timestamps. Also runs the
architecture validator and records its output as evidence.
Acceptance: equivalence test green; any nondeterminism found is reported,
not silently normalized.
Depends on: WP-D2a, WP-D2b.

### WP-E - Block 5: validate, record, promote (split for size)

### WP-E0 - launch wiring (subagent, small-medium)

Scope: connect the pieces into one supervised launch path: take a sealed
invocation (WP-D1), reacquire the state lock, require a passing preflight
(WP-D2b), materialize the task brief into the run directory, and launch
through `LocalHermesExecutor` with the assembled run profile as the Hermes
home, streaming bounded logs into logs/ and recording launch intent and
durable identity. No output validation (E1) and no promotion (E2) yet.
Must resolve and document how the assembled profile becomes a valid Hermes
home for `hermes -z` (profile shape vs HERMES_HOME semantics), verified
with a stub binary.
Acceptance: a sealed run launches a stub hermes end to end under the lock;
preflight failure blocks launch; logs land in logs/ bounded; suite green.
Depends on: WP-D2b.

### WP-E1 - output validation (subagent, small)

Scope: post-quiescence validation through the real run path: expected
output inventory and names, safe paths, required schemas, nonempty
scientific fields, declared companions, run and method identity, phase-
specific consistency. Exit code zero alone is never sufficient. Preserve
raw run directory and bounded diagnostics before adaptation.
Acceptance: exit-zero with missing/malformed/wrong-basis/undeclared
outputs fails validation and changes no state; suite green.
Depends on: WP-E0.

### WP-E2 - allowlisted promotion (subagent, medium)

Scope: memory-before and runtime-after inventories; stage only allowlisted
memory files and the safe session snapshot (never SOUL, skills, base
configuration, credentials, logs, caches); verify lock and command heads;
atomically advance current pointers with last-known-good preservation;
failed/cancelled/timed-out/invalid/stale/unresolved runs change nothing.
Acceptance: Block 5 checkpoint - injected failure at any promotion step
leaves the previous formal and project-role state usable; suite green.
Depends on: WP-E1.

### WP-E3 - receipts and retention (subagent, small)

Scope: compact promotion receipts (input snapshot, output digests,
validation results, promoted state, previous current state); explicit
retention rules for old run profiles, logs, sessions, snapshots; never
prune active or unresolved evidence.
Acceptance: receipt contents verified; retention prunes only expired,
resolved, non-current evidence; suite green.
Depends on: WP-E2.

### WP-F - Block 6: Web operation surface (split for size, sequential)

Block 6 checkpoint: configure, start, observe, cancel, and understand one
real local run entirely through the UI; frontend + backend tests green.
No automatic phase progression anywhere - every action is an explicit user
command.

- **WP-F0 - supervised-run read surface (backend)**: wire the run-profile
  assembler's durable records into the app service (currently pilot-script
  only). Read-only endpoints: list supervised invocations per project;
  per-invocation detail (seal manifest summary, preflight report, launch
  records, validation report, promotion records). Durable state only.
- **WP-F0 complete** (commit `b4cd6a1`): supervised-run read surface -
  list/detail endpoints over the seal store with digest-verified manifest
  reads (tampered manifest -> null + note, never silent acceptance).
  Finding: preflight reports are NOT persisted today (detail exposes
  null + note). 642 tests green.
- **WP-F1a complete** (commit `1590061`): POST start - seal + synchronous
  preflight + non-blocking background launch (202 immediately, progress
  via the read surface; TestClient cannot observe mid-flight state - the
  running -> succeeded transition is proven at the service level).
  Idempotent replay, 409 lock/preflight, env-allowlist secrets, strict
  request schema. 651 tests green.
- **WP-F1b complete** (commit `b5a0a5a`): POST cancel - durable external
  id now recorded at launch_acknowledge (running-guarded), identity-safe
  cancel via the executor, explicit cancels classify as cancelled (not
  failed; executor emits no CANCELLED status - optional launcher hook,
  default None). 657 tests green.
- **WP-F1c complete** (commit `2719829`): preflight reports persisted at
  start time (pass and fail paths), detail view serves them; sealed-but-
  never-started keeps null + note. 660 tests green. **Backend lane of
  WP-F is complete** - read, start, cancel, preflight, validation,
  promotion all exposed.
- **WP-F2 - Configuration page (frontend)**: role list with health badges,
  role detail (SOUL/config/skills/guidance + provenance), provision action
  with the 409 CUSTOMIZATION_CONFLICT -> explicit force-choice flow. Uses
  the existing WP-C API.
- **WP-F3 - supervision views (frontend)**: per-project supervised-run
  list, run-start form (brief, role, memory policy, expected outputs),
  detail view (pre-run basis, live state/elapsed/bounded logs, cancel,
  closure view with validation result, promoted/retained items, receipt,
  smallest safe next action).
- **WP-F4 - reviewed-basis panel (frontend)**: the complete reviewed basis
  on the phase page (WP0 audit item 5) + memory policy display + nav.
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
