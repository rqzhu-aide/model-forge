# Revised Implementation Plan: Hermes Diagnostic Lane for Method Hub

Status: Historical OCI-specific design record. Its profile, memory, validation,
and lifecycle observations remain useful, but it is not the Version 1 work
order.
Implementation checkpoint: commit `009a50a`, audited 2026-08-04.
Current plan:

- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)

## Historical OCI implementation audit


Commit `009a50a` implements useful additional foundations:

- a rootless OCI executor and pinned-image verification scaffold;
- runtime-profile snapshot, promotion, quarantine, and memory-policy helpers;
- expanded diagnostic lifecycle, process-identity, usage, and output contracts;
- CLI operations for preflight, start, status, logs, cancel, reconcile, memory,
  and evidence;
- broader output, resource, network, secret, and real-Linux tests; and
- a successful hand-built Hermes invocation through Podman on the tested host.

The diagnostic lane is still not operationally complete:

- the public CLI constructs the Bubblewrap one-shot executor rather than the
  OCI executor;
- the scientific `oci` setting incorrectly installs Bubblewrap in the
  scientific coordinator and must remain disabled;
- the service enters acknowledged and running states before the executor emits
  launch intent, so the real callback sequence is invalid;
- the OCI command ignores the runtime profile and mounts the complete host
  Hermes home read-write;
- the actual container identity is not durably acknowledged before work starts;
- fencing does not atomically require a live lease, heartbeats do not renew the
  lease, and expired locks can be reclaimed without proving quiescence;
- all successful memory policies can be promoted, including read-only and
  ephemeral profiles;
- cancellation and CLI reconciliation do not prove termination of the same
  container;
- output draining, file and retained-state quotas, provider-only networking,
  and secret-safe delivery remain incomplete; and
- the H0-B evidence does not run the complete public path or full required
  matrix.

Per-project Hermes memory remains supplementary working context. It becomes
load-bearing only after the renamed ADR-011 is aligned with schemas, examples,
digest contracts, traceability, and real policy evidence. Formal records remain
the scientific authority.

## Revision 1 changelog

The original revision's three adaptations (per-project profiles, baked SOUL.md,
mounted task brief) are verified against Hermes v0.19.0 and kept. This revision
corrects six technical errors and adds four requirements for clean, sustainable
per-project memory:

1. **C1 - The split-mount strategy in §3.4 will break Hermes.** A one-shot run
   writes far more than `memories/` and `sessions/`: `state.db` (session and
   kanban state, opened on every run), `logs/`, `checkpoints/`, and `cache/`.
   Mounting the profile base read-only with only two writable subdirectories
   will fail or degrade every invocation. The mount strategy is inverted: the
   profile is writable; the *identity files* (`SOUL.md`, `config.yaml`,
   `skills/`) are bind-mounted read-only over it.
2. **C2 - No growth policy existed for profile state.** Measured on this host,
   one active profile accumulated 390 sessions (121 MB), 34 MB logs, 20 MB
   checkpoints, and a 292 MB `state.db` in about three months. Four profiles
   per project across many projects is unsustainable without bounds. Section
   2.7 adds retention budgets and pruning, reusing Hermes' own tooling.
3. **C3 - Memory must be digest-recorded, and §2.6 overstated its role.**
   "This replaces the need for explicit context-passing" contradicts the
   authority model: the sealed basis and frozen prepared contexts remain the
   auditable channel. Memory is supplementary working context. Each invocation
   must record its digest, but a digest only identifies the state. An immutable
   content-addressed snapshot is required to reconstruct what the role could
   read.
4. **C4 - Per-role memory policy added; the reviewer conflict resolved.**
   Persistent reviewer memory violates the outside-reviewer closed-packet
   requirement (architecture 08 §5.4; WP4). Each role profile now carries an
   explicit `memory_policy` (`persistent` / `read_only` / `ephemeral`);
   the `outside_reviewer` role, normally mapped to the `paper_reviewer`
   profile, defaults to `ephemeral`.
5. **C5 - Concurrency mutex per profile.** The architecture permits concurrent
   runs on disjoint targets; two concurrent runs sharing one role profile race
   on `state.db` and `MEMORY.md`. Profile-level execution fencing is now
   required.
6. **C6 - `HTTPS_PROXY=localhost:9090` is wrong under netns isolation.**
   Inside a private network namespace, localhost is the container's loopback.
   Section 3.5 now specifies reachable proxy topologies per runtime and adds
   the mechanism to the spike checklist.
7. **C7 - One credential rule.** The original draft said credentials were
   "injected at setup" (§1.3), "fixed at creation" (§2.5), and "injected at
   runtime, not mounted" (§3.4). One rule now: secrets never persist in the
   project profile. Note that `hermes profile create --clone-from` copies the
   source `.env` - provisioning must scrub it.
8. **C8 - Executor naming aligned with code.** `executors/bubblewrap.py`
   already implements the one-shot decision; this plan extends it with a
   Podman backend rather than replacing it.
9. **C9 - Spike checklist extended** with the write-footprint enumeration,
   read-only identity files, memory-tool availability in one-shot mode, and
   provider override resolution.
10. **C10 - ADR required.** Per-project persistent memory changes the
    role-context model accepted in architecture 08 (frozen per-run context
    snapshots). The plans README forbids code relying on an invariant change
    before the decision record exists.

---

## What changed from the programmer's plan

The main adaptations are directionally sound, subject to the memory decision
record and the operational gates below. They correct three assumptions:

1. **Profile isolation is per-project, not per-invocation.** Each project
   may maintain its own Hermes role profiles. Persistent author memory and
   prior-session access remain provisional until the C10 decision is accepted.
   Formal project records remain the only scientific authority, and memory
   must not silently supply a claim or assumption. For the diagnostic lane,
   persistence is exercised but not load-bearing. The exit gate does not
   depend on accumulated content.
2. **SOUL.md is baked into the profile, not re-injected per run.** The role
   identity (SOUL.md) is written to the profile once at project or profile
   setup time via `hermes profile` commands or direct file management. It is
   not copied or pasted into each invocation.
3. **Task brief delivery uses a mounted file, not a CLI argument.** `hermes -z`
   takes its prompt as a direct argument, but the full task brief is too large
   and sensitive for the command line. The invocation mounts the brief as a
   file and the one-shot prompt instructs Hermes to read it.

---

## 1. Hermes system on this host (verified)

### 1.1 Runtime facts

| Item | Verified value |
|---|---|
| Hermes version | v0.19.0 (2026.7.20), `/home/tez/.local/bin/hermes` |
| Profile mechanism | `-p PROFILE` / `--profile` selects profile (argv pre-parse in `main.py:499-581`, sets `HERMES_HOME`); each profile has own `config.yaml`, `SOUL.md`, `skills/`, `memories/`, `sessions/`, `.env` |
| Profile name rules | `^[a-z0-9][a-z0-9_-]*$` (`service_manager.py:29`) - hyphens and underscores allowed; `<project_id>-<role>` is valid |
| Profile creation | `hermes profile create <name> --clone-from <base> --no-alias` copies `.env`; this is an observed Hermes behavior, not the Method Hub provisioning design |
| One-shot mode | `hermes -z "prompt"` - synchronous, stdout-only final response, exits with process code |
| Profile switching | Changes model/provider config correctly (theorist→deepseek, developer→glm-5.2) |
| Skills | `--skills name1,name2` / `-s` preloads skills; skills live in `~/.hermes/profiles/<name>/skills/` |
| Memory | `~/.hermes/profiles/<name>/memories/MEMORY.md` + `USER.md` - persists across `-z` invocations |
| Sessions | Each `-z` run creates a new session recorded in `state.db`; `sessions/` contains request-dump files rather than the authoritative session record |
| Usage report | `--usage-file PATH` writes JSON cost report (one-shot only) |
| Egress proxy | `hermes egress` (iron-proxy) subcommand exists; disabled by default; not installed on this host |
| Kanban | `hermes kanban` - gateway-spawned workers, NOT suitable for containment |
| Container runtime | `bwrap` v0.11.1 available at `/usr/bin/bwrap`; **Podman not installed** |
| State footprint (measured) | One active profile over about three months: 390 session-related request-dump files (121 MB), logs 34 MB, checkpoints 20 MB, `state.db` 292 MB |

### 1.2 Why kanban is unsuitable for production execution

The kanban path (`hermes kanban create --assignee PROFILE`) submits a task to
a shared board. The Hermes gateway dispatches the actual worker as a separate
process outside any sandbox we create. This means:

- **No containment** - the gateway worker runs with full host access
- **No truthful identity** - `archived` status ≠ worker terminated
- **Requeue risk** - `--max-runtime` timeout can re-dispatch the task
- **Shared boards** - cross-project contamination risk

The one-shot path (`hermes -z`) is synchronous, so the supervised process is
the agent entrypoint rather than a detached Kanban submission. Reliable
control still requires a durable identity that resists PID reuse and supports
restart reconciliation. The Kanban adapter remains a development connectivity
tool only.

### 1.3 Profile directory structure

```
~/.hermes/profiles/<profile_name>/
├── SOUL.md           ← Role identity / system prompt (baked once, not per-run)
├── config.yaml       ← Model, provider, toolsets, agent settings
├── .env              ← ABSENT in project profiles (C7: runtime injection only)
├── auth.json         ← Credential pool state - not provisioned into project profiles
├── skills/           ← Installed skills (per-profile)
├── memories/         ← MEMORY.md + USER.md - persistent across invocations
├── sessions/         ← Request dumps; authoritative sessions are in state.db
├── checkpoints/      ← Context compression snapshots (bounded per §2.7)
├── logs/             ← Gateway and agent logs (bounded per §2.7)
├── cache/            ← Model cache
├── state.db          ← Kanban and session state (written on every run - see C1)
└── ...
```

---

## 2. Proposed profile architecture: per-project memory policy

### 2.1 Design decision

Each Method Hub project gets its own set of Hermes profiles. Author-role
working memory and session state may persist across runs in that project.
This can improve continuity, but it is not scientific authority. Formal
records must independently carry every conclusion, assumption, and decision
needed by a later phase. The exact memory exposed to a run must be visible and
reconstructible. The outside reviewer receives fresh mutable state and only
the declared review packet.

### 2.2 Profile naming convention

```
~/.hermes/profiles/<project_id>-<role>/
```

(Valid under `^[a-z0-9][a-z0-9_-]*$` provided project IDs are lowercase.)

Examples:
```
~/.hermes/profiles/proj-004-research_lead/
~/.hermes/profiles/proj-004-theorist/
~/.hermes/profiles/proj-004-data_analyst/
~/.hermes/profiles/proj-004-paper_reviewer/
```

### 2.3 Profile lifecycle

| Stage | When | What happens |
|---|---|---|
| **Create** | Project creation or first use | Build a clean profile in a temporary directory from the declared SOUL, configuration, and exact skill set. Do not clone base memories, sessions, databases, logs, checkpoints, caches, credentials, or other mutable state. Validate it, write its ownership manifest, then rename it atomically. |
| **Configure** | Profile creation or explicit reconfiguration | Set the stable role identity, model/provider references, exact skills, memory policy, policy version, and profile revision. Project scientific context is not written into SOUL.md. |
| **Run** | Each invocation | Supply the project question, method state, evidence, user instructions, and other scientific context through the sealed task brief and frozen prepared context. Apply the declared memory policy. |
| **Maintain** | After evidence is sealed and no profile lock is active | Use only verified Hermes-supported session and database maintenance operations; record the action. |
| **Retire** | Project deletion or archival | Resolve ownership from the exact profile manifest. Never select profiles for deletion by a project-name prefix. |

### 2.4 SOUL.md handling

SOUL.md defines stable role identity, expertise, scientific standards, and
behavioral constraints. It is versioned as part of the profile identity. It
must not contain the project's research question, current method, results, or
other mutable scientific context.

The Method Hub resource system (`resources/team/`) supplies the declared role
soul. Profile provisioning records the source digest and complete rendered
SOUL.md digest in the profile manifest. A SOUL change is an explicit role
reconfiguration that creates a new profile revision.

### 2.5 What gets isolated vs. what persists

| Component | Isolation and persistence rule |
|---|---|
| SOUL.md | stable, versioned role identity; read-only during execution; no project scientific context |
| config.yaml | versioned non-secret runtime configuration; read-only during execution |
| Credentials | never persisted in a profile, workspace, manifest, log, artifact, or evidence record |
| skills/ | exact declared and versioned skill set; read-only during execution |
| memories/ | governed by the declared memory policy; immutable before and after snapshots are recorded when exposed |
| state.db | selected-profile runtime and session state; persistent only under the persistent policy and tracked as reproducibility-sensitive context |
| sessions/ | Hermes request dumps, not the authoritative session store; retained only under the declared policy and budget |
| logs/, checkpoints/, cache/ | mutable runtime state governed by the whole-profile memory policy and retention rules |
| Workspace and task brief | fresh per invocation; task brief and frozen inputs are read-only; declared outputs are writable |

### 2.6 Memory as supplementary research context (C3)

Persistent project memory changes the accepted frozen-context model in
architecture 08. It therefore remains a proposal until an architecture
decision record defines its authority, visibility, retention, and
reproducibility rules. Before that decision is accepted, persistent memory
may be exercised only in the non-publishing diagnostic lane.

Under the proposed policy, memory may preserve researcher-visible notation,
preferences, working reminders, and pointers to formal records. It is never
scientific authority and cannot be the only location of a conclusion,
assumption, method definition, result, or user decision. The sealed basis and
frozen contract-prepared context remain authoritative.

Because memory can influence output, a digest alone is not enough to
reconstruct the role's context. Each invocation record must capture:

- immutable content-addressed snapshots of the exact `MEMORY.md` and
  `USER.md` supplied at invocation start;
- SHA-256 digests of those snapshots, the complete profile revision, the
  memory policy, and the memory-policy version;
- the new Hermes `session_id`, model, provider, completion fields, and usage
  metadata from `usage.json`; and
- separate after-run snapshots and digests for every persistent memory update.

If Hermes can browse prior sessions, Method Hub must either disable that
capability or preserve an immutable snapshot of the exact accessible session
state, including the relevant `state.db` and request dumps. Recording only a
database digest and size is not sufficient for reconstruction.

The researcher must be able to inspect, clear, export, and reconfigure the
memory. Material scientific content becomes durable only through the normal
phase output and publication contract.

### 2.7 Growth bounds and retention (C2)

Per-project profiles must not overburden the host. Budgets per profile
(configurable, measured against §1.1 host data):

| State | Budget | Mechanism |
|---|---|---|
| Sessions recorded in `state.db` | e.g. keep newest 50 sessions or 90 days | use a verified Hermes-supported maintenance operation; never delete database rows directly |
| `sessions/` request dumps | e.g. 25 MB or 90 days | prune only closed request-dump files after invocation evidence is sealed |
| `checkpoints/` | e.g. 25 MB | prune oldest compression snapshots |
| `logs/` | e.g. 25 MB, rotated | truncate/rotate outside active invocations |
| `state.db` | warn at 250 MB | run only a verified Hermes compact or vacuum operation, with no active profile lock |
| `memories/` | agent-managed; warn at 100 KB | memory tool is self-compacting; flag for researcher review, never auto-delete |

Rules: maintenance never runs during an active invocation (profile mutex,
C5); pruning never touches `memories/` content automatically; every
maintenance action is recorded in the operational log.

### 2.8 Per-role memory policy (C4)

Each project role profile carries a declared `memory_policy`:

| Policy | Meaning | Default for |
|---|---|---|
| `persistent` | selected project-profile state persists; exact memory before and after the run is snapshotted | research_lead, theorist, data_analyst |
| `read_only` | a disposable writable runtime profile is seeded from frozen memory; all runtime changes are discarded | reserved |
| `ephemeral` | a fresh writable runtime profile starts without project memory or prior mutable state and is discarded after the run | outside_reviewer, normally mapped to `paper_reviewer` |

The reviewer default implements the outside-reviewer closed-packet requirement
(architecture 08 §5.4): a review run starts without prior `state.db`, session
records, request dumps, logs, checkpoints, caches, or project memory. The
no-memory attestation therefore covers the complete mutable runtime profile,
not only `memories/`. Changing a role's policy is a role-reconfiguration
event, versioned like any other profile change.

### 2.9 Per-profile execution mutex (C5)

The architecture allows concurrent runs on disjoint targets, but two
invocations sharing one project role profile race on `state.db` and
`MEMORY.md`. The fencing layer (§4.5) must include a **profile-level mutex**:
at most one active invocation per project role profile. A second run needing
the same role waits (queued, visible in the UI) rather than corrupting shared
profile state.

---

## 3. Execution architecture

### 3.1 Topology: a separate non-publishing diagnostic lane

```text
Method Hub diagnostic composition root
  DiagnosticService
    DiagnosticStore and profile mutex
    ProjectProfileManager
    OneShotDiagnosticExecutor
      rootless runtime adapter
      selected project-role profile
      sealed task brief and diagnostic workspace
      bounded supervisor
      provider-only network path
```

The scientific `RunCoordinator`, `HarnessExecutionServices`, and
`RoleLifecycleService` do not select or call this executor. The diagnostic
lane cannot create a scientific run, satisfy a phase prerequisite, publish an
artifact, mutate formal project state, or trigger another role. The
`oneshot` setting must therefore be removed from, or rejected by, scientific
executor selection.

This separation is a hard safety gate, not only an API organization choice.

### 3.2 Task brief delivery

The task brief is written to a file in the role workspace and mounted
read-only into the container. The one-shot prompt is a short instruction:

```bash
hermes -p <profile_name> -z "Read and execute the task brief at /workspace/task.md. Write only the declared output files." --skills <declared_skills> --usage-file /workspace/usage.json
```

This avoids:
- `ARG_MAX` limits on command-line length
- Brief content appearing in `ps` output
- Brief content in process metadata or logs

### 3.3 Runtime choice and architecture status

**Required production boundary: rootless OCI.** Accepted ADR-004 requires
rootless OCI isolation for CLI roles. Podman remains the current reference
runtime because its create, inspect, stop, kill, logs, and durable container
identity operations support restart-safe supervision.

**Interim diagnostic boundary: Bubblewrap.** Bubblewrap may be used to close
a narrower, non-publishing headless subgate on a verified Linux host. Its
durable identity must include boot ID, PID, `/proc` start ticks, executable
identity, and an invocation marker. Identity uncertainty closes as
`unresolved`; it never causes a replacement launch or an assumed success.

Bubblewrap evidence does not by itself close Phase 0 or WP1 while ADR-004
requires rootless OCI. Any decision to make Bubblewrap a production boundary
must be recorded in a new or superseding architecture decision.

Either runtime must carry a pinned Hermes installation and runtime
dependencies. That exact runtime content and digest are provisioning
deliverables, not unrecorded host state.

### 3.4 Profile mounting strategy (C1 - inverted)

Hermes needs writable runtime state, but it does not need access to the host's
complete Hermes home. Each invocation receives a synthetic Hermes home that
contains only the selected project-role profile:

```text
sandbox/
  workspace/                 # declared role workspace, read-write
  workspace/task.md         # sealed task brief, read-only
  hermes-home/
    profiles/<selected>/
      SOUL.md                # read-only identity
      config.yaml            # read-only, with no persisted secrets
      skills/                # exact declared skills, read-only
      memories/              # policy-controlled mutable state
      state.db               # policy-controlled mutable state
      sessions/              # request dumps, policy-controlled
      logs/
      checkpoints/
      cache/
```

The runtime must pass `-p <selected-profile>` explicitly. It must not expose
sibling profiles, boards, global memory, or other host Hermes state.

Policy realization is defined over the whole mutable profile. The canonical
project profile is never mounted directly as writable. Each invocation writes
to a per-run runtime profile or overlay:

- `persistent`: seed from a consistent canonical snapshot; after validated
  success and verified quiescence, atomically promote allowed changes only
  while the original fencing token and lease remain current;
- `read_only`: seed a disposable writable runtime profile from the declared
  immutable memory snapshot, then discard the complete runtime profile; and
- `ephemeral`: start with a fresh writable runtime profile containing no prior
  project memory or mutable state, then discard it completely.

Failed, cancelled, timed-out, lease-lost, or unresolved changes are not
promoted. The identity mounts, runtime overlays, promotion path, and all three
policy realizations must be verified by real sandbox tests.

### 3.5 Network and secret handling (C6, C7)

**Provider-only egress via Hermes egress proxy (iron-proxy):**
- TLS-intercepting egress firewall
- Swaps proxy tokens for real API credentials before outbound requests
- Allows only declared provider endpoints
- Keeps real credentials out of the container environment

**Proxy reachability (C6).** `localhost` inside a private network namespace is
the container's own loopback - a host-side proxy is unreachable at
`localhost:9090`. The topology must be one of:

- **Podman (slirp4netns):** proxy listens on the host; container reaches it at
  the slirp4netns gateway address (e.g. `10.0.2.2:9090`); or
- **Shared netns:** the proxy process runs in the *same* network namespace as
  the sandbox (start proxy first, `bwrap` shares its netns), so `localhost`
  is correct and no external interface exists beyond the proxy; or
- **veth pair** between proxy netns and sandbox netns (bwrap "separate netns"
  claim in the current prototype must be verified - the spike must demonstrate
  the actual mechanism).

The chosen mechanism is a spike checklist item, not an assumption.

**Credential rule (C7).** Real provider credentials are never written to a
profile, workspace, command argument, manifest, log, database record,
artifact, API result, or evidence package. The preferred design supplies only
a narrowly scoped proxy credential through a tested non-argument mechanism.
If no secret-safe provider path is available, preflight fails before Hermes
starts.

The observed `hermes profile create --clone-from` operation copies `.env`.
Method Hub provisioning therefore builds a clean profile from declared
identity resources rather than cloning mutable base state. Legacy imports are
quarantined and verified secret-free before they can become discoverable.
---

## 4. Implementation deliverables

### 4.0 One-shot Hermes evidence checkpoint

The [completed host observations](completed/spike-report-s5.0.md) establish
useful Hermes v0.19.0 facts, but they are not sandbox or control evidence.

Observed on the named host:

- [x] clean stdout and stderr behavior for the tested cases;
- [x] `usage.json` fields, including `session_id`, model, provider, token
  counts, and completion flags;
- [x] SIGTERM behavior for the observed main process and process group;
- [x] host write footprint, including `state.db`, WAL files, logs,
  `auth.lock`, and temporary files;
- [x] one-shot memory-tool availability and persistence;
- [x] new session creation in `state.db`; `sessions/` contains request dumps;
- [x] task-brief delivery by file reference;
- [x] base-profile cloning copies `.env` and therefore cannot be used without
  exact exclusion and verification; and
- [x] model and provider override behavior.

Still required before the headless diagnostic subgate closes:

- [ ] a committed, reproducible script that uses the new diagnostic lane;
- [ ] exact `-p <profile>` selection inside the sandbox;
- [ ] access to only the selected profile and exact declared skills;
- [ ] read-only SOUL, configuration, skills, task brief, and frozen inputs;
- [ ] persistent author memory across two runs with exact before and after
  snapshots;
- [ ] a disposable `read_only` runtime profile seeded from frozen memory;
- [ ] a fully fresh reviewer profile with no prior memory, `state.db`,
  sessions, request dumps, logs, checkpoints, or cache;
- [ ] provider-only egress and secret-safe delivery;
- [ ] incremental bounded stdout and stderr under flood;
- [ ] complete descendant termination and output quiescence after cancel and
  timeout;
- [ ] restart reconciliation at every launch boundary; and
- [ ] outcome validation that detects an internal Hermes failure even when
  the process exits with code 0.

### 4.1 Atomic, exact profile provisioning

`ProjectProfileManager` must create a profile in a temporary directory from
declared identity resources, validate it, write an ownership manifest, and
rename it atomically. It must not clone base memories, `state.db`, sessions,
request dumps, logs, checkpoints, cache, credentials, or undeclared skills.

The manifest records the exact project ID, role, mapped Hermes profile name,
SOUL digest, configuration digest, exact skill names and digests, memory
policy and version, profile revision, and creation provenance. All source and
destination paths are containment-checked, and symlinks cannot escape the
profile root.

Profile lookup and retirement use manifest ownership, not name-prefix
matching. `outside_reviewer`, normally mapped to `paper_reviewer`, defaults
to `ephemeral` unless a later accepted decision explicitly changes it.

### 4.2 One-shot diagnostic executor and supervisor

The executor passes `-p <selected-profile>`, mounts only the selected profile,
and realizes the declared whole-profile memory policy. It writes the sealed
brief before launch and accepts outputs only in the diagnostic workspace.

The supervisor must:

- persist the real runtime identity immediately after spawn through a launch
  handshake, before acknowledging active execution;
- incrementally drain stdout and stderr into bounded, redacted buffers;
- parse `usage.json` and validate the declared output contract;
- treat exit code as one signal, never as sufficient evidence of task
  success;
- cancel the complete process tree with TERM, bounded wait, KILL escalation,
  reaping, and output-quiescence verification;
- reconcile only the exact durable runtime identity after restart; and
- close ambiguous identity as `unresolved`, without retrying or launching a
  replacement.

### 4.3 Resource, network, and secret controls

Enforce wall-time, CPU, memory, process-count, open-file, per-file, file-count,
workspace-growth, retained-log, and aggregate diagnostic-storage limits.

Network policy is deny-default with a demonstrated provider-only path.
`--share-net` is not an allowlist. Real credentials must not appear in
process arguments, profiles, workspaces, logs, database records, API results,
or evidence packages. A narrowly scoped proxy credential or file-descriptor
delivery mechanism must be tested by an evidence-package secret scan.

### 4.4 Diagnostic service, persistence, and headless interface

Diagnostic invocations remain separate from scientific runs. The application
composition root constructs `DiagnosticService` directly; it is never routed
through `RunCoordinator` or `RoleLifecycleService`.

The durable lifecycle distinguishes at least `pending`, `preflight`,
`creating`, `launch_acknowledged`, `running`, `cancel_requested`,
`timeout_requested`, `terminating`, `closing`, `unresolved`, `succeeded`,
`failed`, `timed_out`, and `cancelled`. The next block exposes this through a headless service or
CLI for real evidence collection. The user-facing diagnostic UI is a later
Phase 0 completion item.

### 4.5 Durable fencing and profile mutex

Every state mutation, acknowledgement, heartbeat, cancellation transition,
terminal closure, memory record, canonical promotion, cleanup, and lock
release is conditioned on the current fencing token and live lease. Leases
renew while work is active. Lease loss blocks promotion and initiates verified
termination or quarantine.

Profile-lock release requires the exact owner and token. Lease expiry alone
does not permit a successor while the prior runtime may still be active;
reclaim requires verified quiescence or controlled adoption of that exact
runtime identity.

The profile mutex applies to every path that can use the same Hermes profile,
including one-shot diagnostics and development Kanban execution. Lock
acquisition, runtime-profile creation, promotion, and cleanup are enclosed by
guaranteed ownership-aware cleanup so exceptions cannot leak ownership or
promote stale state.

---

## 5. Implementation checkpoint at `009a50a`

The table separates code presence from verified behavior.

| Area | Current state | Required closure |
|---|---|---|
| Host and OCI reconnaissance | Hermes and Podman feasibility observed | retain as partial evidence; do not treat it as an integrated gate |
| Project and runtime profiles | substantial scaffold | exact skills, synthetic home, policy enforcement, ownership, atomic fenced promotion |
| OCI executor | component implementation | diagnostic composition, exact mounts, durable container identity, bounded supervision |
| Diagnostic database | lifecycle, token, lock, identity, and memory tables exist | live-lease atomic mutations, renewal, safe lock reclaim, exact reconciliation |
| Diagnostic service | broad unit-level scaffold | valid observer lifecycle, manifest preflight, correct memory policy, awaited cancellation |
| Network and secrets | policy helpers and component tests exist | provider-only enforcement and secret-safe delivery through real OCI |
| Evidence | 22 OCI-oriented tests pass on the reported host | complete public-path matrix, no skips, retained machine-readable evidence |
| Diagnostic UI | not started | defer until the headless OCI gate closes |

## 6. Implementation sequence

### 6.1 Next bounded block

Implement the
[End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md).
It closes the remaining non-publishing backend gap in this order:

1. separate scientific and diagnostic executor composition;
2. bind preflight to one exact manifest and synthetic profile;
3. persist real container identity through a create, acknowledge, then start
   handshake;
4. enforce current-token and live-lease lifecycle and memory promotion;
5. complete bounded supervision, cancellation, timeout, and restart recovery;
6. enforce provider-only egress and secret-safe delivery; and
7. run the complete Linux matrix through the public diagnostic path.

### 6.2 Work after the headless runtime gate

Once the headless exit criteria pass:

1. add the local user-facing diagnostic UI and complete the remaining Phase 0
   usability evidence;
2. close WP0 reviewed-basis integrity;
3. implement phase-specific output adapters and validators; and
4. begin real five-phase pilots only after those gates are satisfied.

---

## 7. What is explicitly deferred

Per the programmer's plan and the dependency order:

- Complete reviewed-basis sealing (WP0 exit gate still open)
- Phase-specific output adapters and validators (WP2)
- Formal Phase 1-5 execution and publication
- Reproducible production role profiles and reviewer no-memory attestation
  (WP4 - §2.8's ephemeral reviewer policy is the hook it will attest)
- Authentication and remote operation (WP5)
- Backup, restore, migration, and release packaging (WP6-WP7)

The diagnostic lane proves the execution boundary. It does not authorize
scientific publication.
