# WP1 + WP2: Production Execution Boundary and Output Validation

Status: Partially implemented scaffolding (audited 2026-08-03). Both exit gates remain open.

## Implementation audit

At commit `eecc6d1`, the repository contains useful scaffolds for Bubblewrap
execution, capability materialization, project profiles, one-shot command
construction, diagnostic persistence, profile locks, fencing tokens, output
adaptation, and phase-specific validation. These are foundations, not
accepted WP1 or WP2 deliverables.

WP1 remains open because no supported runtime path yet combines exact
project-role profile selection, declared skills, whole-profile memory policy,
rootless containment, provider-only networking, secret-safe delivery, bounded
streaming and resources, durable runtime identity, token-guarded lifecycle,
verified cancellation, and restart reconciliation. The diagnostic script
still exercises Kanban, and no real Bubblewrap or OCI evidence suite has
passed.

The new one-shot implementation must remain unavailable to scientific runs.
It is currently selectable through application settings and is constructed by
the scientific `RunCoordinator`, while the separate diagnostic service is not
composed into an application path. The
[Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)
must correct that boundary first.

WP2 remains open because adapter results are discarded instead of being sealed
into the submission and publication path; companion artifacts are inferred
from filenames; some post-execution validation failures do not preserve raw
output; and several validators inspect fields that do not match the registered
schemas. The fixtures are architecture examples, not a complete set of actual
Hermes outputs for every role and mode.

Keep both `oci` and `oneshot` unavailable to scientific runs. The existing
sections below retain the intended target design, but their earlier completion
labels are superseded by this audit and by the Exit Gates.

## Revision 1 changelog

Revision 1 was reviewed against the pre-`fb326de` source and an
environment-specific passing backend baseline. It also used the
[Phase 0 spike findings](completed/phase-0-spike-findings.md). Its inventory is
retained as design history. The current implementation status is the audit
above. Revision 1 corrections were:

1. **C1 - Gap-table premise wrong: `reconcile()` IS exercised in recovery.**
   `resume_incomplete` (`run_coordinator.py:142`) reschedules every
   nonterminal run; stage execution reaches `execute_or_reconcile`
   (`role_execution.py:67`), which calls `executor.reconcile(external_id)`
   for acknowledged in-flight invocations (`role_execution.py:121`). What is
   actually missing is **fencing** (nothing stops two coordinators advancing
   the same invocation) and a **coordinator-level no-rerun guarantee**.
   Deliverable D1.4 is reframed accordingly; building a second reconciliation
   path on the wrong premise would duplicate an existing one.
2. **C2 - The central WP1 design decision was unspecified: how Hermes runs
   inside the container.** Spike finding 4 confirmed that containerizing a
   kanban-submitting CLI isolates nothing, because the gateway spawns the
   worker. Section "In-container invocation mechanism" now records the
   decision point and a recommendation (one-shot `hermes -z` inside the
   container), since cancellation, reconciliation, log capture, and profile
   mounting all depend on it.
3. **C3 - WP4 dependency was silent.** The Operational Completion Plan
   requires WP4 (reproducible profiles, reviewer isolation) to finish before
   WP2 is accepted. Two items here depend on it: the manifest pinning of
   "role profile + model configuration" (the sealed basis carries profile
   name/version/soul/skills, not model configuration) and WP2's Phase 5
   closed-review-packet validation (needs the reviewer no-memory
   attestation). The implementation sequence now states this.
4. **C4 - Secret injection and network reality added.** `deny_all` cannot run
   a real role - the model provider is remote. Real invocations need
   allowlist mode scoped to the provider endpoint plus runtime injection of
   the minimum API credential, kept out of images, manifests, logs, and
   artifacts (completion-plan WP1 deliverable 9). Added to D1.1/D1.3.
5. **C5 - D1.4 no longer duplicates durable records.** Launch intent,
   acknowledgement, heartbeat, and closure are already persisted
   (`role_execution_*` tables) and already drive recovery. The lease
   deliverable is now scoped to its genuinely new content: fencing token,
   lease expiry, and coordinator-level single-advancement.
6. **C6 - Golden fixtures unblocked from the OCI executor.** Track A (the
   hardened kanban adapter, dev-only) already produces real Hermes output -
   the 0G connectivity test passed. Output *validity* is executor-agnostic;
   D2.3 fixtures can be captured via Track A while WP1 is in flight, then
   re-confirmed on OCI in Phase C.
7. **C7 - Minor:** lifecycle row now includes the `prepared` state; the plan
   now references the spike findings and the Track A/B framing throughout.

---

## Table of Contents

1. [Current State](#current-state)
2. [WP1: Production Execution Boundary](#wp1-production-execution-boundary)
3. [WP2: Output Adapters and Validators](#wp2-output-adapters-and-validators)
4. [Implementation Sequence](#implementation-sequence)
5. [Test Strategy](#test-strategy)
6. [Exit Gates](#exit-gates)

---

## Current State

### Audited current state

| Area | Current status | Acceptance gap |
|---|---|---|
| Development Kanban adapter | Partial, development-only | Synthetic connectivity passed, but archived status does not prove worker termination |
| Bubblewrap executor | Scaffold only | No runtime-resolvable identity, effective cancellation, reconciliation, or real sandbox test |
| Capability and network modules | Scaffold only | Broker paths are not used by the role and provider allowlisting is not enforced |
| Invocation fencing | Scaffold only | State is in memory and is not durable across coordinators |
| Reviewed basis | Partial | Method-bound role resources and the complete executable profile basis are not sealed fail closed |
| Output adapters | Scaffold only | Adapted companion artifacts are discarded before submission and publication |
| Scientific validators | Scaffold only | Several checks do not match the registered schemas and fixtures are not complete actual-Hermes captures |

The development harness, fake executors, generic lifecycle, output planning,
and structural schema validation remain usable. They do not satisfy the WP1 or
WP2 exit gates.

### Original Revision 1 inventory, superseded by the audit above

| Component | Status | Location |
|---|---|---|
| `RoleExecutor` protocol | ✅ Complete | `executors/protocol.py` - execute/cancel/reconcile + ExecutionObserver |
| `DeterministicFakeExecutor` | ✅ Complete | `executors/fake.py` - deterministic output from schema examples |
| `SchemaExampleFakeExecutor` | ✅ Complete | `executors/development.py` - extends fake with architecture examples |
| `HermesKanbanExecutor` (Track A) | Partial, development-only | Status and retry handling, environment filtering, profile preflight, and one synthetic run are verified. Archived status does not prove worker termination. See the [spike findings](completed/phase-0-spike-findings.md). |
| `OutputPlan` + `OutputSpec` | ✅ Complete | `harness/outputs.py` - contract-derived output planning |
| `validate_role_outputs` | ✅ Complete | `harness/outputs.py:139` - structural acceptance (path safety, JSON shape, schema validation) |
| `validate_submission` | ✅ Complete | `harness/submission_validation.py:34` - recheck bytes, provenance, schemas, method identity, phase semantics (`_validate_phase_semantics`, line 312) |
| `RunCoordinator` lifecycle | ✅ Complete | `application/run_coordinator.py` - created→preparing→prepared→running→submitted→validating→promoting→published (plus cancelled/failed/rejected/conflicted) |
| `HarnessExecutionServices` | ✅ Complete | `harness/stage_execution.py` - stage execution, role lifecycle, submission assembly |
| `RoleInvocation` dataclass | ✅ Complete | `executors/protocol.py` - execution_id, workspace, task_brief, expected_output_paths |
| Role context snapshot schema | ✅ Defined | `schemas/role-context-snapshot.schema.json` - not yet materialized at runtime |
| Prepared role context schema | ✅ Defined | `schemas/prepared-role-context.schema.json` - not yet materialized at runtime |
| WP0 sealed basis | Partial | Initial command embedding and checks exist, but the complete method-bound role and executable profile basis is not sealed fail closed. |
| Restart reconciliation | ✅ Complete | `resume_incomplete` → `execute_or_reconcile` → `executor.reconcile` for acknowledged in-flight invocations |

### Original Revision 1 gap list, superseded by the audit above

| Gap | WP | Impact |
|---|---|---|
| Supported rootless OCI executor | WP1 | The Bubblewrap prototype is not a durable or verified production executor |
| Enforced capability boundary | WP1 | Materialized inputs are not the paths given to the role and are not protected as read-only capabilities |
| Network policy enforcement | WP1 | Allowlist mode currently grants the full host network instead of provider-only egress |
| Durable invocation fencing + leases | WP1 | Two coordinators can advance the same invocation because fencing is process-local |
| Coordinator-level no-rerun guarantee | WP1 | Recovery reconciles but nothing formalizes "one invocation, at most one external execution, ever" |
| Integrated per-role output adapters | WP2 | Adapted companion artifacts are discarded before submission and publication |
| Schema-aligned scientific validators | WP2 | Several current checks are no-ops or inspect the wrong registered field shapes |
| Golden actual-Hermes fixtures | WP2 | No real output fixtures for conformance testing (unblockable via Track A - see C6) |
| Complete phase-specific conformance suites | WP2 | Existing tests demonstrate plumbing, not all real scientific role obligations |

---

## WP1: Production Execution Boundary

### Purpose

Replace the direct-process Hermes Kanban executor with a rootless OCI container
executor that isolates each role invocation. The executor must be the only path
between a frozen role invocation and its workspace - no ambient filesystem,
network, or database access.

Track A (the hardened kanban adapter) remains available as a development-only
executor. WP1 is Track B: the production isolation boundary. The Phase 0 plan's
confinement exit criterion is satisfied here, not by Track A.

### In-container invocation mechanism (decision required - C2)

Spike finding 4 established that the kanban dispatcher lives in the gateway and
spawns workers there, so a container around a kanban-submitting CLI confines
nothing. WP1 must state explicitly how the Hermes role executes inside the
container. The two candidates:

- **Option 1 (recommended): one-shot invocation.** The container's entrypoint
  is a single synchronous Hermes run (`hermes -z` or equivalent supported
  one-shot API) against a container-local `HERMES_HOME` carrying the sealed
  role profile. The container process **is** the agent: the container ID is a
  truthful `external_execution_id`, `cancel()` = container kill = genuinely
  confirmed termination, `reconcile()` = container inspect, and there is no
  dispatcher, no circuit breaker, no requeue, and no archived-task idempotency
  hole inside the boundary. The harness already performs orchestration itself;
  kanban's board semantics are not needed inside the container.
- **Option 2: kanban-in-container.** A dedicated gateway runs inside the
  container subscribed to a dedicated board (Phase 0 amendment A1 topology).
  Preserves the Track A adapter shape, but re-imports every kanban recovery
  subtlety the spike documented (requeue, archived-hole, status mapping) into
  the production path, and `external_execution_id` can no longer be the
  container ID.

This plan proceeds on **Option 1**. If Option 2 is chosen, stop and record an
architecture decision first: it changes the executor's identity, cancellation,
and reconciliation semantics (Phase 0 plan §10.3).

### Architecture

```
RunCoordinator
  └─ HarnessExecutionServices
       └─ RoleLifecycleService
            └─ OciExecutor (NEW)
                 ├─ ContainerRuntime (NEW - podman/crun wrapper)
                 ├─ CapabilityBroker (NEW - manifest-authorized file access)
                 ├─ NetworkProxy (NEW - deny-by-default + allowlist)
                 └─ InvocationFence (NEW - fencing token + lease expiry on existing records)
```

### Deliverables

#### D1.1: Container runtime adapter (`executors/oci.py`)

Wraps a rootless OCI runtime (podman + crun). Each role invocation creates one
ephemeral container with:

- **Read-only root filesystem** - the runtime image is mounted read-only
- **Private user namespace** - UID mapping with no host privileges
- **No Linux capabilities** - `--cap-drop=ALL`
- **No-new-privileges** - `--security-opt=no-new-privileges`
- **Pinned seccomp policy** - `--security-opt=seccomp=<profile>`
- **One writable role root** - the invocation workspace, bind-mounted
- **Container-local `HERMES_HOME`** - carries only the sealed role profile;
  no ambient host home directory, no other profiles, no host kanban boards
- **No formal-storage credentials** - no DB path, no artifact store path
- **No ambient project files** - only the capability broker's materialized inputs
- **Runtime secret injection (C4)** - the minimum model-provider credential is
  injected as an environment variable at container launch. It never appears in
  the image, the manifest, the task brief, logs, artifacts, or formal records.
  Captured output passes the same redaction patterns as the Track A adapter
  (`executors/hermes.py:86-104`).

```python
@dataclass(frozen=True, slots=True)
class OciExecutorSettings:
    runtime: str = "podman"          # or "crun" directly
    image_digest: str = ""           # pinned sha256 image digest
    executor_profile_digest: str = "" # pinned profile content digest
    poll_interval_seconds: float = 5.0
    default_timeout_seconds: int = 14_400
    network_policy: str = "deny_all"  # or "allowlist"

class OciExecutor:
    """Rootless OCI container executor implementing RoleExecutor protocol."""

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult: ...

    async def cancel(self, external_execution_id: str) -> None: ...
    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None: ...
```

**Container lifecycle:**
1. Materialize the role context (capability broker writes frozen inputs to workspace)
2. Build container command from `RoleInvocation` (image, mounts, env, one-shot command)
3. Launch container → record container ID as `external_execution_id`
4. Poll container status until terminal (succeeded/failed/cancelled/timeout)
5. Capture bounded stdout/stderr (same streaming + cap + redaction pattern as
   the Track A adapter)
6. Return `RoleExecutionResult`

**Pinning requirements (stored in manifest):**
- Runtime image digest (sha256)
- Executor profile digest (the OciExecutorSettings content hash)
- Hermes version (from the image label)
- Role profile + model configuration (from the sealed basis **plus WP4 profile
  metadata** - see C3; the sealed basis alone does not carry model config)
- Resource limits (CPU, memory, PID)
- Network policy (deny_all or allowlist with proxy config)
- Process/mount/user/security settings

#### D1.2: Capability broker (`capabilities/broker.py`)

Resolves manifest-authorized logical references into materialized files inside
the role root. The role agent never sees a path outside its workspace.

```python
class CapabilityBroker:
    """Materialize manifest-declared inputs inside the role workspace."""

    def materialize_context(
        self,
        *,
        workspace: Path,
        invocation: RoleInvocation,
        recipe: PreparedRunRecipe,
        repository: HubRepository,
        artifacts: ArtifactStore,
    ) -> RoleContextSnapshot:
        """Write frozen inputs, skill bundles, and task brief into the workspace.

        - Verifies content digests on every read
        - Records every file materialized in an access log
        - Writes only inside the role root (workspace/inputs/, workspace/skills/)
        - Never exposes the artifact store path or DB path
        """

    def read_artifact(
        self,
        *,
        workspace: Path,
        artifact_id: str,
        expected_sha256: str,
        artifacts: ArtifactStore,
    ) -> Path:
        """Materialize one artifact on demand, verifying its digest."""
```

**Access log:** Every `materialize_context` and `read_artifact` call records
`{artifact_id, sha256, byte_length, materialized_path, timestamp}` in the
invocation's workspace access log. This becomes part of the role invocation
closure record.

#### D1.3: Network policy enforcement (`capabilities/network.py`)

```python
@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    mode: Literal["deny_all", "allowlist"]
    allowed_hosts: tuple[str, ...] = ()
    proxy_port: int = 0  # 0 = assigned dynamically

class NetworkProxy:
    """Start a local HTTP/HTTPS proxy that enforces the network policy.

    The container's network namespace routes through this proxy. When
    mode=deny_all, no traffic leaves the container. When mode=allowlist,
    only declared hosts are forwarded; everything else returns 403.
    """
```

**Reality constraint (C4):** `deny_all` is the correct default for dummy and
structural tests, but every real role invocation needs the model provider
endpoint in allowlist mode. The proxy must support per-invocation allowlists
derived from the execution policy, record the effective policy (without
credentials), and deny-and-record everything else. Implementation note:
rootless podman user-mode networking (slirp4netns) requires the proxy to be
reachable from inside the container (host gateway address or a shared
namespace); the chosen mechanism must be covered by an integration test, not
assumed.

#### D1.4: Invocation fencing (`harness/invocation_fencing.py`) - rescoped (C1, C5)

Recovery reconciliation already exists and works. The new content is fencing
and a formal no-rerun guarantee, built on the **existing** `role_execution_*`
durable records (intent, acknowledgement, heartbeat, closure) - not a parallel
lease store:

- **Fencing token**: a monotonically increasing token issued per coordinator
  advancement of an invocation; stored alongside the existing execution
  records. A stale token cannot launch, heartbeat, cancel, or close.
- **Coordinator lease**: advancing an invocation requires holding a
  time-boxed lease keyed to the invocation; lease expiry plus fencing prevents
  two coordinators (e.g., after a restart while a old process lingers) from
  both acting on the same invocation.
- **No-rerun invariant**: once an invocation has a terminal closure, or an
  acknowledgement with a confirmed-terminal external execution, no code path
  may call `execute()` for that invocation_id again. This invariant already
  holds structurally through `execute_or_reconcile`; D1.4 makes it explicit,
  tested, and enforced at the coordinator level rather than by convention.

On restart, `resume_incomplete` continues to reconcile through the existing
path, now under lease + fencing:

- If the external execution is still running → adopt it (continue polling)
- If it has terminated → record the result
- If it is gone (evicted) → mark as failed, never re-create

#### D1.5: Settings extension

```python
# application/settings.py
executor_kind: Literal["disabled", "fake", "hermes_kanban", "oci"] = "disabled"
```

When `executor_kind == "oci"`:
- `development_mode` is not required (production executor)
- Must validate that the OCI runtime binary exists
- Must validate that the image digest is non-empty
- Must validate that secret injection is configured without persisting the
  secret

### Files to create/modify

| File | Action | Description |
|---|---|---|
| `src/method_hub/executors/oci.py` | **NEW** | OciExecutor + OciExecutorSettings + ContainerRuntime |
| `src/method_hub/capabilities/__init__.py` | **NEW** | Package init |
| `src/method_hub/capabilities/broker.py` | **NEW** | CapabilityBroker |
| `src/method_hub/capabilities/network.py` | **NEW** | NetworkPolicy + NetworkProxy |
| `src/method_hub/harness/invocation_fencing.py` | **NEW** | Fencing token + coordinator lease over existing execution records |
| `src/method_hub/application/settings.py` | Modify | Add `"oci"` to executor_kind literal |
| `src/method_hub/application/bootstrap.py` | Modify | Wire OciExecutor when executor_kind=="oci" |
| `src/method_hub/application/run_coordinator.py` | Modify | Acquire lease/check fencing in execute loop |
| `src/method_hub/harness/stage_execution.py` | Modify | Integrate capability broker context materialization |
| `architecture/schemas/role-context-snapshot.schema.json` | Verify | Already defined; broker produces instances |
| `tests/test_oci_executor.py` | **NEW** | Unit + integration tests |
| `tests/test_capability_broker.py` | **NEW** | Path traversal, digest, access-log tests |
| `tests/test_invocation_fencing.py` | **NEW** | Fencing, lease expiry, two-coordinator tests |

---

## WP2: Output Adapters and Validators

### Purpose

Move from schema-example structural conformance to real phase execution. Each
role's free-form agent output must be extracted, validated, and bound to formal
records - without allowing filename inference or prose parsing to create formal
content.

### Architecture

```
Role agent produces files in workspace
  └─ OutputAdapter (NEW - per role × phase × mode)
       ├─ Extract structured output from declared files
       ├─ Bind linked human-readable artifacts (PDFs, markdown, code)
       └─ Produce ValidatedOutput with provenance
  └─ ScientificValidator (NEW - per phase × mode)
       ├─ Verify required fields and cross-references
       ├─ Check method identity, input provenance, closure
       ├─ Reject cross-method, stale-version, untraceable output
       └─ Preserve unfavorable conclusions as valid
```

### Deliverables

#### D2.1: Output adapter interface (`harness/output_adapters.py`)

```python
class OutputAdapter(Protocol):
    """Extract structured output from one role's workspace files."""

    def adapt(
        self,
        *,
        spec: OutputSpec,
        workspace: Path,
        validated: ValidatedOutput,
    ) -> AdaptedOutput:
        """Transform raw validated JSON into formal-record-ready content.

        - Read the declared output file (already validated by validate_role_outputs)
        - Extract linked human-readable artifacts (if any) from adjacent paths
        - Verify artifact digests
        - Return structured content + artifact bindings
        """
```

The existing `validate_role_outputs` already handles structural validation (path
safety, JSON shape, schema conformance). The adapter layer adds:

1. **Linked artifact binding** - when an output references human-readable
   companions (e.g., a proof PDF alongside the structured theory record), the
   adapter reads, digests, and registers them
2. **Field normalization** - ensure mathematical notation, assumptions, and
   uncertainty are preserved in the structured fields
3. **Negative-finding preservation** - ensure "method failed under condition X"
   passes through as a valid scientific outcome

#### D2.2: Phase-specific scientific validators

The existing `validate_submission` has `_validate_phase_semantics` with basic
checks (P1 duplicate source identity, P3/P4/P5 method identity). WP2 extends
this to full phase-specific validation:

**Phase 1 - Literature basis:**
- Deduplication: no stable literature identity repeats
- Correction: source changes cite their prior generation
- Cumulative synthesis: synthesis references every included source
- Coverage: coverage record addresses the declared scope

**Phase 2 - Method development:**
- Full-catalog: method records cover every declared method
- Focused-method: exact version + definition digest matches the selected method
- Lineage: method changes cite their prior version

**Phase 3 - Theory development:**
- Complete replacement: theory record covers all declared theorem statements
- Proof map: every claim in the theory record has a proof or explicit conjecture
- Assumption preservation: all assumptions from the method record are addressed

**Phase 4 - Empirical development:**
- Evidence applicability: evidence references the exact method version
- Four-slot atomic update: evidence_index, empirical_synthesis, implementation_record,
  and phase_decision all update together
- Reproducibility: implementation record contains reproducible protocol

**Phase 5 - Manuscript assembly:**
- Exact aligned basis: manuscript references the exact theory, evidence, and method
- Closed review packet: all review issues are dispositioned
- Issue disposition: every open issue has a resolution or explicit deferral
- Complete replacement manuscript: one manuscript replaces the prior

Note (C3): the Phase 5 closed-review-packet checks can be implemented now, but
WP2 acceptance for Phase 5 additionally requires WP4's reviewer no-memory
attestation - the validator cannot certify "closed packet" without executor
evidence that the reviewer session was isolated.

Each validator is a function:

```python
def validate_p1_literature(
    *,
    plan: ResolvedPhasePlan,
    outputs: Mapping[str, RegisteredValidatedOutput],
    repository: HubRepository,
    project_id: str,
    selected_method: MethodIdentity | None,
    findings: list[ValidationFinding],
) -> None: ...
```

#### D2.3: Mutation test fixtures - capture path corrected (C6)

Golden fixtures do **not** need to wait for the OCI executor. Track A already
produces real Hermes output (0G passed), and output validity is
executor-agnostic. Capture fixtures via Track A in development mode, labelled
with the capturing executor; Phase C re-confirms the same suites on OCI.

For each phase mode, create golden fixtures and mutations:

**Golden fixtures (positive):**
- Complete, valid output from every role in every phase mode
- Negative results (method fails, evidence contradicts theory) - must pass
- Inconclusive outcomes (insufficient evidence) - must pass

**Mutation fixtures (negative):**
- Remove a required assumption from theory record → reject
- Alter method identity version → reject
- Cite an undeclared input → reject
- Omit a required output → reject
- Mix sibling outputs (data_analyst output attributed to theorist) → reject
- Cross-method contamination (P4 evidence from a different method) → reject

#### D2.4: Raw output preservation

```python
# harness/stage_execution.py - RoleLifecycleService
def preserve_raw_output(
    self,
    *,
    invocation: RoleInvocation,
    workspace: Path,
    artifacts: ArtifactStore,
) -> str:
    """Copy the entire role workspace into the immutable run artifact store.

    Called even when validation fails. Failed output never becomes current,
    but is preserved for debugging and audit.
    """
```

### Files to create/modify

| File | Action | Description |
|---|---|---|
| `src/method_hub/harness/output_adapters.py` | **NEW** | OutputAdapter protocol + base implementations |
| `src/method_hub/harness/scientific_validators.py` | **NEW** | Phase-specific validation functions |
| `src/method_hub/harness/submission_validation.py` | Modify | Extend `_validate_phase_semantics` to call new validators |
| `src/method_hub/harness/stage_execution.py` | Modify | Add raw output preservation |
| `tests/fixtures/golden/` | **NEW** | Golden output fixtures per phase/mode/role (captured via Track A, labelled) |
| `tests/fixtures/mutations/` | **NEW** | Negative mutation fixtures |
| `tests/test_output_adapters.py` | **NEW** | Adapter unit tests |
| `tests/test_scientific_validators.py` | **NEW** | Phase-specific validator tests |
| `tests/test_output_conformance.py` | **NEW** | End-to-end golden + mutation suites |

---

## Implementation Sequence

WP1 and WP2 share a dependency: WP2's fixtures need a real executor, but the
executor's correctness (WP1) must be verified first. Track A relaxes this -
fixture capture and adapter development can proceed against the hardened
kanban adapter while the OCI boundary is built. **WP0 remains partially implemented. WP4
(reproducible profiles and reviewer isolation) starts after WP0 is complete and must finish
before WP2 is accepted** (completion-plan dependency order; see C3).

### Phase A: WP1 core (executor + broker + fencing)

```
D1.2 CapabilityBroker        ← no deps, pure logic
D1.1 OciExecutor             ← depends on D1.2 for context materialization;
                               decision on in-container mechanism (C2) comes first
D1.4 InvocationFencing       ← no deps, extends existing execution records
D1.3 NetworkProxy            ← depends on D1.1 (shares container lifecycle)
D1.5 Settings + bootstrap    ← wire everything together
```

### Phase B: WP2 core (adapters + validators + fixtures)

```
D2.1 OutputAdapter interface ← no deps; test with fake executor
D2.2 Scientific validators   ← depends on D2.1 for structured input
D2.3 Golden fixtures         ← capture via Track A (dev) in parallel with WP1;
                               re-confirm on OCI in Phase C
D2.4 Raw output preservation ← Track A workspace lifecycle first, OCI after
```

### Phase C: Integration (requires both WP1 + WP2)

```
End-to-end OCI runs for all 8 phase modes
Mutation test suites pass
Recovery tests (crash, restart, cancellation, fencing)
WP4 acceptance evidence for profile metadata + reviewer attestation
```

### Parallelism

D1.2 and D1.4 can be built in parallel (both are pure logic with no container
dependency). D2.1 and D2.2 can be built and tested with the existing fake
executor; D2.3 fixture capture runs against Track A concurrently. The only
hard blocking dependency is Phase C.

---

## Test Strategy

### WP1 tests

| Test | What it verifies |
|---|---|
| `test_capability_broker_materializes_inputs` | Frozen inputs written to workspace, digests verified |
| `test_capability_broker_rejects_path_traversal` | Symlink/hardlink/traversal attempts blocked |
| `test_capability_broker_access_log` | Every read recorded |
| `test_oci_executor_success` | Container runs, produces output, returns succeeded |
| `test_oci_executor_failure` | Container exits non-zero, returns failed |
| `test_oci_executor_timeout` | Wall-time limit enforced, container killed |
| `test_oci_executor_cancellation` | Cancel kills container, confirms terminated |
| `test_oci_executor_no_ambient_access` | Container cannot read DB, artifact store, project files, host home, or host kanban boards |
| `test_oci_executor_oneshot_identity` | Container ID is the external execution ID; no second agent process exists inside |
| `test_network_deny_all` | No outbound traffic in deny_all mode |
| `test_network_allowlist` | Only declared hosts reachable; provider endpoint works; denies recorded |
| `test_secret_injection` | API credential present in container env, absent from image/manifest/logs/artifacts/formal records |
| `test_fence_prevents_duplicate` | Same invocation never runs twice |
| `test_lease_two_coordinators` | Stale coordinator cannot launch, heartbeat, cancel, or close after lease takeover |
| `test_restart_adopts_running_container` | Restart → reconcile → adopt running container |
| `test_restart_terminates_orphaned_container` | Restart → container gone → mark failed, never re-create |
| `test_secret_scanning` | No secrets in logs, artifacts, or formal records |

### WP2 tests

| Test | What it verifies |
|---|---|
| `test_adapter_extracts_structured_output` | Declared file → structured content |
| `test_adapter_binds_linked_artifacts` | Companion PDF/markdown registered with digest |
| `test_adapter_preserves_negative_findings` | "Method failed" is a valid outcome |
| `test_p1_deduplication_rejects_duplicates` | Repeated source identity rejected |
| `test_p2_method_identity_rejects_mismatch` | Wrong version/digest rejected |
| `test_p3_proof_map_completeness` | Every claim has proof or conjecture |
| `test_p4_evidence_applicability` | Evidence bound to exact method version |
| `test_p4_four_slot_atomic_update` | All four records update together |
| `test_p5_claim_traceability` | Every claim traces to accepted artifact |
| `test_p5_issue_disposition_complete` | Every review issue resolved |
| `test_mutation_missing_assumption` | Removed assumption → reject |
| `test_mutation_cross_method` | Wrong method output → reject |
| `test_raw_output_preserved_on_failure` | Failed output in artifact store |
| `test_fixtures_labelled_with_capture_executor` | Every golden fixture records Track A vs OCI provenance |

---

## Exit Gates

### WP1 exit gate

One dummy role and then one real Hermes role execute in the rootless OCI
boundary. Restart, timeout, or cancellation cannot duplicate work, broaden
access, or change prior formal state. The in-container invocation mechanism is
documented and matches the implemented identity, cancellation, and
reconciliation semantics.

### WP2 exit gate

Every phase can complete with actual Hermes output, and every formal field can
be traced to an accepted role artifact, exact frozen input, and publication
receipt. Phase 5 acceptance additionally requires WP4's reviewer no-memory
attestation evidence (C3).
