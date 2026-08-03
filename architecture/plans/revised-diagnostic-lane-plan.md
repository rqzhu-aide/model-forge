# Revised Implementation Plan: Hermes Diagnostic Lane for Method Hub

Status: Revised plan (2026-08-03), Revision 1 (2026-08-03), adapting the
programmer's
[next-block-hermes-diagnostic-closure.md](next-block-hermes-diagnostic-closure.md)
to the actual Hermes system on this host.

## Revision 1 changelog

The original revision's three adaptations (per-project profiles, baked SOUL.md,
mounted task brief) are verified against Hermes v0.19.0 and kept. This revision
corrects six technical errors and adds four requirements for clean, sustainable
per-project memory:

1. **C1 — The split-mount strategy in §3.4 will break Hermes.** A one-shot run
   writes far more than `memories/` and `sessions/`: `state.db` (session and
   kanban state, opened on every run), `logs/`, `checkpoints/`, and `cache/`.
   Mounting the profile base read-only with only two writable subdirectories
   will fail or degrade every invocation. The mount strategy is inverted: the
   profile is writable; the *identity files* (`SOUL.md`, `config.yaml`,
   `skills/`) are bind-mounted read-only over it.
2. **C2 — No growth policy existed for profile state.** Measured on this host,
   one active profile accumulated 390 sessions (121 MB), 34 MB logs, 20 MB
   checkpoints, and a 292 MB `state.db` in about three months. Four profiles
   per project across many projects is unsustainable without bounds. Section
   2.7 adds retention budgets and pruning, reusing Hermes' own tooling.
3. **C3 — Memory must be digest-recorded, and §2.6 overstated its role.**
   "This replaces the need for explicit context-passing" contradicts the
   authority model: the sealed basis and frozen prepared contexts remain the
   auditable channel. Memory is supplementary working context whose state must
   be recorded per invocation (sha256 of `MEMORY.md`/`USER.md`) so every run's
   full context basis remains reproducible.
4. **C4 — Per-role memory policy added; the reviewer conflict resolved.**
   Persistent reviewer memory violates the outside-reviewer closed-packet
   requirement (architecture 08 §5.4; WP4). Each role profile now carries an
   explicit `memory_policy` (`persistent` / `read_only` / `ephemeral`);
   `paper_reviewer` defaults to `ephemeral`.
5. **C5 — Concurrency mutex per profile.** The architecture permits concurrent
   runs on disjoint targets; two concurrent runs sharing one role profile race
   on `state.db` and `MEMORY.md`. Profile-level execution fencing is now
   required.
6. **C6 — `HTTPS_PROXY=localhost:9090` is wrong under netns isolation.**
   Inside a private network namespace, localhost is the container's loopback.
   Section 3.5 now specifies reachable proxy topologies per runtime and adds
   the mechanism to the spike checklist.
7. **C7 — One credential rule.** The original draft said credentials were
   "injected at setup" (§1.3), "fixed at creation" (§2.5), and "injected at
   runtime, not mounted" (§3.4). One rule now: secrets never persist in the
   project profile. Note that `hermes profile create --clone-from` copies the
   source `.env` — provisioning must scrub it.
8. **C8 — Executor naming aligned with code.** `executors/bubblewrap.py`
   already implements the one-shot decision; this plan extends it with a
   Podman backend rather than replacing it.
9. **C9 — Spike checklist extended** with the write-footprint enumeration,
   read-only identity files, memory-tool availability in one-shot mode, and
   provider override resolution.
10. **C10 — ADR required.** Per-project persistent memory changes the
    role-context model accepted in architecture 08 (frozen per-run context
    snapshots). The plans README forbids code relying on an invariant change
    before the decision record exists.

---

## What changed from the programmer's plan

The programmer's plan is architecturally sound. These revisions adapt it to
verified Hermes runtime behavior and correct three assumptions:

1. **Profile isolation is per-project, not per-invocation.** Each project
   maintains its own Hermes profiles with persistent memory and sessions.
   Role memory accumulates across runs within a project — this is a feature,
   not a leak. The "sanitized disposable profile bundle" model is replaced
   with project-scoped profile directories. (Scope note: for the *diagnostic*
   lane, persistence is exercised but not load-bearing — the diagnostic exit
   gate does not depend on memory accumulation. The per-project architecture
   is the production profile model feeding WP1/WP4; see C10.)
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
| Profile mechanism | `-p PROFILE` / `--profile` selects profile (argv pre-parse in `main.py:499–581`, sets `HERMES_HOME`); each profile has own `config.yaml`, `SOUL.md`, `skills/`, `memories/`, `sessions/`, `.env` |
| Profile name rules | `^[a-z0-9][a-z0-9_-]*$` (`service_manager.py:29`) — hyphens and underscores allowed; `<project_id>-<role>` is valid |
| Profile creation | `hermes profile create <name> --clone-from <base> --no-alias` (flags verified); **cloning copies the source `.env` — scrub after clone (C7)** |
| One-shot mode | `hermes -z "prompt"` — synchronous, stdout-only final response, exits with process code |
| Profile switching | Changes model/provider config correctly (theorist→deepseek, developer→glm-5.2) |
| Skills | `--skills name1,name2` / `-s` preloads skills; skills live in `~/.hermes/profiles/<name>/skills/` |
| Memory | `~/.hermes/profiles/<name>/memories/MEMORY.md` + `USER.md` — persists across `-z` invocations |
| Sessions | `~/.hermes/profiles/<name>/sessions/` — each `-z` run creates a new session file |
| Usage report | `--usage-file PATH` writes JSON cost report (one-shot only) |
| Egress proxy | `hermes egress` (iron-proxy) subcommand exists; disabled by default; not installed on this host |
| Kanban | `hermes kanban` — gateway-spawned workers, NOT suitable for containment |
| Container runtime | `bwrap` v0.11.1 available at `/usr/bin/bwrap`; **Podman not installed** |
| State footprint (measured) | One active profile over ~3 months: 390 session files (121 MB), logs 34 MB, checkpoints 20 MB, `state.db` 292 MB |

### 1.2 Why kanban is unsuitable for production execution

The kanban path (`hermes kanban create --assignee PROFILE`) submits a task to
a shared board. The Hermes gateway dispatches the actual worker as a separate
process outside any sandbox we create. This means:

- **No containment** — the gateway worker runs with full host access
- **No truthful identity** — `archived` status ≠ worker terminated
- **Requeue risk** — `--max-runtime` timeout can re-dispatch the task
- **Shared boards** — cross-project contamination risk

The one-shot path (`hermes -z`) is synchronous: the process IS the agent. Its
PID (or container ID) is a truthful execution identity. The hardened kanban
adapter remains a development connectivity tool only.

### 1.3 Profile directory structure

```
~/.hermes/profiles/<profile_name>/
├── SOUL.md           ← Role identity / system prompt (baked once, not per-run)
├── config.yaml       ← Model, provider, toolsets, agent settings
├── .env              ← ABSENT in project profiles (C7: runtime injection only)
├── auth.json         ← Credential pool state — not provisioned into project profiles
├── skills/           ← Installed skills (per-profile)
├── memories/         ← MEMORY.md + USER.md — persistent across invocations
├── sessions/         ← Session history (accumulates — bounded per §2.7)
├── checkpoints/      ← Context compression snapshots (bounded per §2.7)
├── logs/             ← Gateway and agent logs (bounded per §2.7)
├── cache/            ← Model cache
├── state.db          ← Kanban and session state (written on every run — see C1)
└── ...
```

---

## 2. Profile architecture: per-project, persistent memory

### 2.1 Design decision

Each Method Hub project gets its own set of Hermes profiles. Memory and
sessions persist across runs within the same project. This is the correct
behavior for a research team — the theorist should remember what it concluded
in Phase 1 when it works on Phase 3.

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
| **Create** | Project creation or first run | `hermes profile create <project_id>-<role> --clone-from <base_role> --no-alias` — copies SOUL.md, config.yaml, skills from the base role template; **then scrub `.env`/`auth.json` (C7)** |
| **Configure** | Profile creation | Write project-specific SOUL.md (role identity + project context), set model/provider in config.yaml, set the role's `memory_policy` (C4) |
| **Accumulate** | Each role invocation | `-z` runs create new sessions; memories persist and grow within §2.7 budgets; the role remembers prior work in the same project |
| **Maintain** | Scheduled / on thresholds | Prune sessions, compact checkpoints, vacuum state.db per §2.7 |
| **Retire** | Project deletion or archival | Profile directory retained or cleaned per policy; memories represent project-specific research context |

### 2.4 SOUL.md handling

SOUL.md is the role's system prompt — it defines the agent's identity,
expertise, and behavioral guidelines. It is:

- **Written once** at profile creation time, combining the base role template
  with project-specific context (project name, research question, team charter)
- **NOT re-injected per invocation** — it lives in the profile directory and
  Hermes reads it automatically
- **Updated only on explicit role reconfiguration** — not silently overwritten

The Method Hub resource system (`resources/team/`) already defines role souls
(`soul_text`). These are baked into project profiles at creation time via:

```python
# At profile creation:
soul_content = render_role_soul(role, project_context)
profile_dir / "SOUL.md".write_text(soul_content)
```

### 2.5 What gets isolated vs. what persists

| Component | Per-project isolation | Persists across runs |
|---|---|---|
| SOUL.md | ✅ Project-specific role identity | ✅ Fixed at creation (read-only in container) |
| config.yaml | ✅ Model/provider per project | ✅ Fixed at creation (read-only in container) |
| Credentials | ✅ Per-project | ❌ **Never persisted in the profile** — runtime injection or egress token only (C7) |
| skills/ | ✅ Per-project skill set | ✅ Fixed at creation (read-only in container) |
| memories/ | ✅ Project-scoped | ✅ **Accumulates** within §2.7 budget — role remembers prior work |
| sessions/ | ✅ Project-scoped | ✅ **Accumulates** within §2.7 budget |
| state.db / logs/ / checkpoints/ / cache/ | ✅ Project-scoped | ✅ Accumulates within §2.7 budget (writable in container — C1) |
| Workspace (outputs) | ✅ Per-run | ❌ Fresh each run |
| Task brief | ✅ Per-run | ❌ Fresh each run |

### 2.6 Memory as research context — supplementary, digest-recorded (C3)

The role's accumulated memory is valuable working context. When the theorist
completes Phase 1 and later starts Phase 3, its MEMORY.md carries forward
conclusions, noted assumptions, and open questions.

Memory does **not** replace the formal context channel. The sealed basis and
frozen, contract-prepared contexts remain the auditable scientific authority;
memory is agent-managed, mutable, and non-deterministic. To keep the full
context basis of every run reproducible, each invocation record must capture:

- sha256 of `MEMORY.md` and `USER.md` at invocation start;
- the role's `memory_policy` and its version;
- session count (or state.db size class) as a cheap growth signal.

This is cheap (two file hashes) and keeps memory honest: what the agent knew
is attested, even though its content is agent-authored.

### 2.7 Growth bounds and retention (C2)

Per-project profiles must not overburden the host. Budgets per profile
(configurable, measured against §1.1 host data):

| State | Budget | Mechanism |
|---|---|---|
| `sessions/` | e.g. keep newest 50 sessions or 90 days | Method Hub maintenance task prunes; `hermes sessions` for inspection |
| `checkpoints/` | e.g. 25 MB | prune oldest compression snapshots |
| `logs/` | e.g. 25 MB, rotated | truncate/rotate outside active invocations |
| `state.db` | warn at 250 MB | Hermes layout upgrade / vacuum (`main.py:6736+` notes ~60% reclaim) |
| `memories/` | agent-managed; warn at 100 KB | memory tool is self-compacting; flag for researcher review, never auto-delete |

Rules: maintenance never runs during an active invocation (profile mutex,
C5); pruning never touches `memories/` content automatically; every
maintenance action is recorded in the operational log.

### 2.8 Per-role memory policy (C4)

Each project role profile carries a declared `memory_policy`:

| Policy | Meaning | Default for |
|---|---|---|
| `persistent` | memories/ + sessions/ accumulate across runs | research_lead, theorist, data_analyst |
| `read_only` | memories/ mounted read-only; agent may read but not write | (reserved) |
| `ephemeral` | fresh empty memories/ + sessions/ per invocation; discarded after | **paper_reviewer** |

The reviewer default implements the outside-reviewer closed-packet requirement
(architecture 08 §5.4): a review run starts with no project memory. WP4's
no-memory attestation then has something concrete to attest — the ephemeral
mount was empty at start. Changing a role's policy is a role-reconfiguration
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

### 3.1 Topology: one-shot inside rootless container

```
Method Hub RunCoordinator
  └─ HarnessExecutionServices
       └─ RoleLifecycleService
            └─ OneShotExecutor (extends the bubblewrap.py prototype — C8)
                 ├─ Container runtime (Podman or bwrap+PID tracking)
                 ├─ Project-scoped profile (HERMES_HOME=<project profile dir>)
                 ├─ Mounted task brief (file, not CLI arg)
                 ├─ Mounted workspace (role outputs)
                 └─ Network policy (deny-default, provider allowlist via egress)
```

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

### 3.3 Container runtime choice

**Primary: Podman** (needs installation). Provides:
- `podman create` → durable container ID
- `podman start` → start the created container
- `podman inspect` → check status, verify realized policy
- `podman kill` / `podman stop` → cancellation with verification
- `podman logs` → bounded log retrieval
- Rootless operation (no daemon, user namespace)

**Fallback: bwrap with PID tracking** (current prototype, enhanced). Provides:
- Process group isolation, namespace unsharing
- PID file for identity tracking (within one boot)
- No inspect API — must track state manually

The plan targets Podman. If Podman cannot be installed, the bwrap fallback
works for diagnostic purposes but is weaker on restart reconciliation. Either
way the container image or host-bind must carry a **pinned Hermes
installation** (binary + runtime deps); the image content is a provisioning
deliverable, not host state.

### 3.4 Profile mounting strategy (C1 — inverted)

Hermes writes `state.db`, `logs/`, `checkpoints/`, and `cache/` on every run,
so the profile base must be writable. Protection applies to the identity
files, not the directory:

```
Container filesystem:
  /workspace/          ← bind-mounted role workspace (read-write)
  /workspace/task.md   ← task brief (read-only)
  /hermes-home/        ← bind-mounted project profile dir (read-WRITE)
    profiles/<name>/
      SOUL.md          ← read-only bind mount over the writable tree
      config.yaml      ← read-only bind mount (secrets stripped — C7)
      skills/          ← read-only bind mount
      memories/        ← writable (policy-gated: ro for read_only, fresh tmpfs for ephemeral)
      sessions/        ← writable (fresh tmpfs for ephemeral)
      state.db, logs/, checkpoints/, cache/  ← writable (Hermes requires)
```

For `ephemeral` memory policy, `memories/` and `sessions/` are fresh tmpfs (or
a per-run empty directory), discarded after the closure is sealed. The
read-only identity mounts are verified by the spike (C9) before they are
relied upon.

### 3.5 Network and secret handling (C6, C7)

**Provider-only egress via Hermes egress proxy (iron-proxy):**
- TLS-intercepting egress firewall
- Swaps proxy tokens for real API credentials before outbound requests
- Allows only declared provider endpoints
- Keeps real credentials out of the container environment

**Proxy reachability (C6).** `localhost` inside a private network namespace is
the container's own loopback — a host-side proxy is unreachable at
`localhost:9090`. The topology must be one of:

- **Podman (slirp4netns):** proxy listens on the host; container reaches it at
  the slirp4netns gateway address (e.g. `10.0.2.2:9090`); or
- **Shared netns:** the proxy process runs in the *same* network namespace as
  the sandbox (start proxy first, `bwrap` shares its netns), so `localhost`
  is correct and no external interface exists beyond the proxy; or
- **veth pair** between proxy netns and sandbox netns (bwrap "separate netns"
  claim in the current prototype must be verified — the spike must demonstrate
  the actual mechanism).

The chosen mechanism is a spike checklist item, not an assumption.

**Credential rule (C7).** Exactly one rule everywhere: real provider
credentials are never written into the project profile directory, never
mounted, and never persisted in manifests, logs, artifacts, or evidence. With
egress: the container gets only a proxy token. Fallback without egress:
runtime env injection of the minimum credential (weaker — credential is in
container env, though not in image/manifest/logs). Because
`hermes profile create --clone-from` copies the source `.env`, provisioning
must delete `.env`/`auth.json` from the new project profile immediately after
creation.

---

## 4. Implementation deliverables

### 4.0 One-shot Hermes spike (prerequisite — S5.0, extended per C9)

Record and verify:

```bash
# Spike script: verify hermes -z behavior
HERMES_HOME=~/.hermes hermes -p developer \
  -z "Read the file at /tmp/spike-input.md and write your response to /tmp/spike-output.json" \
  --usage-file /tmp/spike-usage.json \
  -m glm-5.2 --provider custom
```

Verify and document:
- [ ] Exit code semantics (0=success, non-zero=failure)
- [ ] stdout contains ONLY final response text
- [ ] `--usage-file` JSON structure
- [ ] Signal handling: SIGTERM to the process tree
- [ ] Output quiescence: no file writes after process exit
- [ ] Skill loading: `--skills` loads only declared skills
- [ ] Profile selection: `-p` switches config/SOUL/skills correctly
- [ ] Memory persistence: MEMORY.md changes persist across `-z` runs
- [ ] Memory tool availability in one-shot mode (can the agent write memories
      during `-z`? Which toolset enables it?)
- [ ] Session creation: each `-z` run creates a new session
- [ ] Task brief via file reference works (not inline prompt)
- [ ] **Write footprint (C1):** enumerate every file Hermes writes during one
      `-z` run (`state.db`, logs, checkpoints, cache, sessions) — this fixes
      the mount design
- [ ] **Read-only identity files (C1):** one-shot succeeds with SOUL.md,
      config.yaml, skills/ read-only
- [ ] **Provider override resolution (C9):** `-m`/`--provider` values resolve
      against the profile's configured providers (custom providers are
      `custom:<name>`)
- [ ] **Egress proxy topology (C6):** the chosen proxy mechanism actually
      reaches the provider from inside the sandbox
- [ ] **Ephemeral memory policy (C4):** one-shot with empty tmpfs memories/
      runs cleanly and leaves the persistent profile untouched

### 4.1 Project-scoped profile management (NEW)

Create `src/method_hub/profiles/project_profiles.py`:

```python
class ProjectProfileManager:
    """Create and manage per-project Hermes profiles."""

    def create_project_profiles(
        self,
        *,
        project_id: str,
        roles: tuple[str, ...],  # research_lead, theorist, etc.
        base_profiles: Mapping[str, str],  # base role template names
        souls: Mapping[str, str],  # role soul text from resources/team/
        model_config: Mapping[str, Any],  # model/provider per role
        skills: Mapping[str, tuple[str, ...]],  # declared skills per role
        memory_policies: Mapping[str, str],  # C4: persistent/read_only/ephemeral
    ) -> Mapping[str, Path]:
        """Create one Hermes profile per role, scoped to this project.

        - Clones from base profile (gets skills, config template)
        - Scrubs .env / auth.json from the clone (C7)
        - Writes project-specific SOUL.md
        - Sets model/provider in config.yaml
        - Records memory_policy per role (C4)
        - Credentials injected at runtime, never stored in profile
        - Returns mapping of role → profile directory path
        """

    def profile_path(self, project_id: str, role: str) -> Path:
        """Return the profile directory for a project role."""

    def profile_state_digests(self, project_id: str, role: str) -> Mapping[str, str]:
        """sha256 of MEMORY.md and USER.md for invocation records (C3)."""

    def maintain_profiles(self, project_id: str) -> None:
        """Prune sessions/checkpoints/logs within §2.7 budgets (C2)."""

    def retire_profiles(self, project_id: str) -> None:
        """Clean up profiles when a project is deleted."""
```

Profile creation uses:
```bash
hermes profile create <project_id>-<role> --clone-from <base_role> --no-alias
```

Then scrubs credentials, writes SOUL.md and config.yaml programmatically, and
records the memory policy.

### 4.2 One-shot executor (extends the bubblewrap prototype — C8)

`executors/bubblewrap.py` already implements the one-shot decision (the
sandbox IS the execution; container PID is the external execution ID). Extend
it into `src/method_hub/executors/oneshot.py` with a pluggable runtime:

```python
class OneShotExecutorSettings:
    hermes_binary: str = "hermes"
    hermes_home: Path  # root containing profiles/
    container_runtime: str = "podman"  # or "bwrap"
    image_digest: str = ""  # pinned image
    poll_interval_seconds: float = 5.0
    default_timeout_seconds: int = 14_400
    output_limit_bytes: int = 1_048_576
    credential_env: Mapping[str, str]  # injected at runtime, never persisted

class OneShotExecutor:
    """Execute role invocations via hermes -z inside a rootless container."""

    async def execute(self, invocation, observer) -> RoleExecutionResult:
        # 1. Write task brief to workspace/task.md
        # 2. Record memory-state digests in the invocation record (C3)
        # 3. Acquire the per-profile mutex (C5)
        # 4. Build container command:
        #    - Mount workspace (rw), task brief (ro), profile (rw with ro identity overlays — C1)
        #    - Apply memory policy mounts (C4)
        # 5. Create container → persist container ID
        # 6. Start container
        # 7. Poll until terminal
        # 8. Capture bounded stdout/stderr (incremental, redacted)
        # 9. Release mutex; return result

    async def cancel(self, external_execution_id) -> None:
        # podman kill <container_id>
        # Verify terminal state

    async def reconcile(self, external_execution_id) -> RoleExecutionResult | None:
        # podman inspect <container_id>
        # Return terminal result or None if still running
```

### 4.3 Container runtime adapter

Create `src/method_hub/executors/container_runtime.py`:

```python
class ContainerRuntime:
    """Abstract rootless container operations."""

    async def create(self, config: ContainerConfig) -> str:
        """Create container, return container ID."""

    async def start(self, container_id: str) -> None: ...

    async def inspect(self, container_id: str) -> ContainerState: ...

    async def kill(self, container_id: str) -> None: ...

    async def logs(self, container_id: str, *, tail_bytes: int) -> tuple[str, str]: ...

    async def remove(self, container_id: str) -> None: ...
```

Implementations: `PodmanRuntime` (primary), `BwrapRuntime` (fallback,
promoting the existing prototype).

### 4.4 Diagnostic service and persistence

Per the programmer's plan (S5.1–S5.8), create a separate diagnostic
persistence model:

- `diagnostic_invocations` table — separate from scientific `runs`
- Diagnostic API endpoints — separate from scientific phase commands
- Diagnostic UI — loopback-only, non-publishing label

The diagnostic service reuses `RoleExecutor` and `ExecutionObserver`
interfaces but never enters submission, validation, or publication.

### 4.5 Durable fencing (S5.7, extended per C5)

Move fencing from in-memory to database-backed:

```sql
CREATE TABLE diagnostic_fencing_tokens (
    execution_id TEXT PRIMARY KEY,
    token INTEGER NOT NULL,
    holder TEXT,
    lease_expires_at TEXT,
    updated_at TEXT NOT NULL
);

-- C5: per-profile execution mutex
CREATE TABLE profile_execution_locks (
    profile_name TEXT PRIMARY KEY,   -- <project_id>-<role>
    invocation_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL
);
```

Two coordinators cannot advance the same invocation because the token check
is a database-level atomic update. Two invocations cannot share one profile
because the profile lock is a database-level atomic acquire, with lease
expiry and restart reconciliation.

---

## 5. Revised gap analysis vs. programmer's plan

| Programmer's plan item | Status in revised plan | Change |
|---|---|---|
| S5.0 One-shot spike | ✅ Keep, expanded | Add write-footprint, read-only identity, memory-tool, provider-resolution, egress-topology, ephemeral-policy checks |
| S5.1 Diagnostic types + gating | ✅ Keep as-is | — |
| S5.2 Preflight | ✅ Keep, adapt | Check for Podman (not just bwrap); verify profile dir exists with SOUL.md; verify credential files absent (C7); verify memory-policy mount readiness (C4) |
| S5.3 Truthful identity | ✅ Keep | Container ID from Podman, not bwrap label |
| S5.4 Capability boundary | ⚠️ Revised | Profile is project-scoped, not disposable; memory/sessions PERSIST per policy; SOUL.md baked at creation; identity files read-only over a writable profile (C1) |
| S5.5 Provider networking | ✅ Keep, corrected | Proxy topology must survive netns isolation (C6); `hermes egress` if available; credential env injection as fallback |
| S5.6 Bounded processes | ✅ Keep, extended | Incremental streaming, not `communicate()`; §2.7 profile-state budgets added to aggregate limits |
| S5.7 Durable fencing | ✅ Keep, extended | DB-backed, not in-memory; per-profile mutex added (C5) |
| S5.8 Diagnostic UI | ✅ Keep | — |
| "Sanitized disposable profile" | ❌ **Replaced** | Project-scoped persistent profiles with policy-gated memory |
| "Exclude memory, history, caches" | ❌ **Reversed** | Memory and sessions are KEPT per policy — they are research context; their digests are recorded (C3) |
| "SOUL.md per invocation" | ❌ **Reversed** | SOUL.md baked into profile at creation, not per-run |
| Memory-canary test (S5.4) | ⚠️ **Repurposed** | Canary now verifies *policy enforcement*: present under `persistent`, absent under `ephemeral` |

---

## 6. Implementation sequence

### Phase 1: Foundation (no container, no real model call)

1. **One-shot spike** — Record `hermes -z` behavior (§4.0, extended checklist)
2. **ADR: per-project profile memory model (C10)** — record the change to the
   role-context architecture (persistent project memory with per-role policy)
   before code relies on it
3. **Project profile manager** — Create/clone/scrub/configure per-project
   profiles, memory policies, state digests
4. **OneShotExecutor skeleton** — Build command, run `hermes -z` directly
   (no container), verify task-brief-via-file works
5. **Tests** — Profile creation, credential scrubbing, task brief delivery,
   memory persistence, memory-policy mounts, retention pruning

### Phase 2: Container boundary

6. **Install Podman** — `apt install podman` or equivalent (rootless:
   newuidmap/newgidmap)
7. **ContainerRuntime adapter** — Podman create/start/inspect/kill/logs
8. **OneShotExecutor in container** — Mount workspace + profile with read-only
   identity overlays + memory-policy mounts
9. **Network policy** — Deny-default + egress proxy with verified topology (C6)
10. **Tests** — Isolation (no DB access, no host files), cancellation, restart

### Phase 3: Diagnostic infrastructure

11. **Diagnostic persistence** — Separate tables, state machine
12. **Durable fencing** — DB-backed tokens, leases, and profile mutexes
13. **Diagnostic API + UI** — Loopback diagnostic view
14. **Tests** — Two-coordinator fencing, profile-mutex contention, restart
    adoption, unresolved state

### Phase 4: Evidence and exit gate

15. **Real synthetic task** — Run through the complete path
16. **Failure injection** — Crash at each boundary
17. **Evidence package** — Assemble per S8 of the programmer's plan, plus
    memory-policy attestation and profile-state inventories

---

## 7. What is explicitly deferred

Per the programmer's plan and the dependency order:

- Complete reviewed-basis sealing (WP0 exit gate still open)
- Phase-specific output adapters and validators (WP2)
- Formal Phase 1–5 execution and publication
- Reproducible production role profiles and reviewer no-memory attestation
  (WP4 — §2.8's ephemeral reviewer policy is the hook it will attest)
- Authentication and remote operation (WP5)
- Backup, restore, migration, and release packaging (WP6–WP7)

The diagnostic lane proves the execution boundary. It does not authorize
scientific publication.
