# Method Hub Completion Roadmap

> **Scope:** A gap analysis and pragmatic work-order plan to bring Method Hub
> from its current development baseline to a fully functioning research harness
> on Hermes — feature-comparable with the legacy Research Hub, while preserving
> Method Hub's stronger authority/storage/execution model.

**Goal:** Deliver a working, user-facing research orchestration system on
Method Hub that can run real Hermes agent research, with a UI experience at
least as complete as the legacy Research Hub.

**Reference comparison:**
- **Research Hub** (legacy, working): 45,621 lines of core Python, 893 tests
  passing, Flask + Jinja server-rendered UI, file-system-based state, direct
  `subprocess` Hermes invocation via `hermes kanban` and `hermes --profile X
  chat`, knowledge graph subsystem (6,511 lines), empirical/theory promotion
  (5,891 lines), profile memory viewer, live run supervision.
- **Method Hub** (new baseline): 20,220 lines of backend Python + 7,857 lines
  of React/TypeScript frontend, 244 tests passing, FastAPI + React SPA,
  event-sourced authority model, typed contracts, deterministic digest
  registry, isolated role execution protocol — **but the production Hermes
  executor is development-only and real scientific output validation has never
  run.**

---

## Part 1 — What Method Hub Already Has (Stronger Than Research Hub)

These are architectural advantages Method Hub already holds. The roadmap
should not re-litigate them:

1. **Typed contract system** — 37 JSON schemas, 57 valid examples, 16 rejected
   fixtures, 5 executable phase contracts with versioned digests
   (`architecture/contracts/`, `architecture/schemas/`).
2. **Event-sourced authority model** — append-only authority events,
   deterministic replay, content-addressed immutable generations,
   tamper-evident operational audit journal. Research Hub has no equivalent.
3. **RFC 8785 deterministic digests** — canonical JSON serialization with
   Unicode and numeric test vectors (`src/method_hub/digests/`).
4. **Strict run-command model** — typed `RunCommand`, `RunManifest`,
   `RoleInvocationStart/Closure`, `RunSubmission` with idempotency and
   cancellation-first semantics.
5. **Role isolation protocol** — frozen role-context snapshots, per-role write
   roots, broker-mediated storage access, declared access ledgers.
6. **React SPA frontend** — modern component-based UI with run timeline, method
   table, profile configuration, run form with local drafts. Research Hub uses
   server-rendered Jinja.
7. **Domain-driven module boundaries** — `domain/`, `harness/`,
   `orchestration/`, `application/`, `api/`, `storage/`, `executors/` with
   inward-pointing dependencies.
8. **Executor protocol abstraction** — `RoleExecutor` Protocol with
   `execute`/`cancel`/`reconcile`, enabling the fake, development, and future
   OCI executors to share one harness.

---

## Part 2 — Feature Gap Analysis (What Method Hub Lacks)

### Category A: Production Hermes Execution (Critical — Nothing Runs Today)

| Gap | Research Hub (works) | Method Hub (missing/incomplete) |
|---|---|---|
| **Real agent execution** | `hermes kanban create` + `hermes --profile X chat` via `subprocess`, with timeout, output capture, process-tree kill | `HermesKanbanExecutor` exists but is **development-only** (`settings.py:51` blocks it unless `development_mode=True`). Has never run real research. |
| **Profile resolution** | `profile_skills.resolve_hermes_root()`, configured-profile existence checks, per-role profile mapping | `configuration/profiles.py` has typed mapping but does not verify on-disk Hermes profile existence or resolve `HERMES_HOME` |
| **Run supervision** | `launch_supervision.py` — cleanup, process-tree termination (Windows job objects + Linux), bounded output capture | `harness/execution_observer.py` has heartbeat protocol but no bounded-output or process-tree-kill implementation |
| **Timeout and cancellation** | Configurable per-phase timeout minutes, cooperative + forced kill | `RoleInvocation.timeout_seconds` exists; `HermesKanbanExecutor.cancel()` calls `kanban archive` but no forced process kill |
| **Output capture and logging** | `launch_process._run_logged_command()` with bounded stdout/stderr, merged streams | No equivalent — executor writes to role workspace but harness does not capture `hermes` subprocess stdout/stderr into run logs |

### Category B: Scientific Output Validation (Critical — No Real Science Can Publish)

| Gap | Status |
|---|---|
| **Phase 1 literature validation** | Contract exists (`architecture/phases/phase-1.md`) but `harness/submission_validation.py` only checks schema shape. No deduplication, source-identity, or cumulative-synthesis validation against real Hermes output. |
| **Phase 2 method catalog** | Method lifecycle commands (`method_lifecycle.py`) exist. No real full-catalog or focused-method run has validated identity, lineage, or version advancement. |
| **Phase 3 theory replacement** | Contract defined. No real proof-record validation. `theory_promotion.py` equivalent does not exist. |
| **Phase 4 empirical evidence** | Contract defined with 4-slot atomic update. No real evidence-index, empirical-synthesis, implementation-record, or phase-decision validation. `empirical_promotion.py` equivalent does not exist. |
| **Phase 5 manuscript assembly** | Contract defined with review-revision mode. No real manuscript, review-packet, or issue-disposition validation. |
| **Negative/inconclusive results** | Architecture says these should publish when structurally complete. No conformance suite tests this with real output. |

### Category C: Researcher-Facing UI Features (Important — Usability Gap)

The React frontend has the structural skeleton. These Research Hub features
are missing or incomplete:

| Feature | Research Hub | Method Hub |
|---|---|---|
| **Run log viewer** | `/project/<id>/phase/<slug>/run/<id>/log` — streams captured subprocess output | `RunPage.tsx` shows events but no captured stdout/stderr log viewer |
| **Run summary / decision brief** | `phase_summary()` returns structured completion + decision options | `DecisionBrief.tsx` exists but is a stub; no rich scientific summary |
| **Phase progress polling** | HTMX-driven `_run_progress.html` partial, live-updating | `useRunEvents.ts` hooks exist with SSE streaming — **structurally better but untested with real runs** |
| **Profile memory viewer** | `/profiles/<name>/memory` — reads `MEMORY.md` from Hermes profile home | `ProfilesPage.tsx` shows profile config but no memory viewer |
| **Skill installation UI** | `/agent/<id>/skills/install` — installs recommended skills to Hermes profiles | `application_skill_install.py` + API route exist; UI button present but untested end-to-end |
| **Project settings / workspace** | `/project/<id>/settings`, `/settings/workspace` — configure workspace, open folder | `SystemSettingsPage.tsx` exists but minimal |
| **Run approve / revision request** | `approve_run()`, `request_revision()` — researcher gates publication | Method Hub architecture **explicitly rejects** post-run approval (no automatic retry). This is a **deliberate design difference**, not a gap. |
| **Branch retire** | `retire_branch()` — retires a phase branch | Method Hub uses method lifecycle (retire/reactivate) instead — **deliberate redesign** |
| **Retry/recover cleanup** | `retry_cleanup()`, `recover_cleanup()` — manual recovery after failed runs | `run_coordinator.py` has restart recovery but no UI button for admin cleanup |

### Category D: Domain Subsystems (Large — Research Hub Has 12K+ Lines Method Hub Lacks)

| Subsystem | Research Hub LOC | Method Hub Equivalent |
|---|---|---|
| **Knowledge graph** | 6,511 lines (`knowledge_graph.py`, `knowledge_fragments.py`, `knowledge_heads.py`, `knowledge_events.py`, `knowledge_content.py`, `knowledge_basis.py`, `knowledge_schema.py`, `knowledge_event_diff.py`) | **None.** Method Hub has no knowledge-graph or fragment-level knowledge management. The architecture mentions "knowledge resources" as a role-input category but does not implement a graph. |
| **Empirical records/promotion** | 3,452 lines (`empirical_promotion.py`, `empirical_records.py`, `empirical_schema.py`) | Contract-defined in `phase-4.md` but **no implementation**. The harness publishes whatever the role submits if it passes schema validation. |
| **Theory records/promotion** | 2,439 lines (`theory_promotion.py`, `theory_records.py`) | Contract-defined in `phase-3.md` but **no implementation**. |
| **Literature records** | `literature_records.py` + `literature_schema.py` | Handled generically by `harness/publication.py` — no literature-specific dedup or source-identity logic. |
| **Manuscript records** | `manuscript_records.py` | No manuscript-specific record management. |
| **Method menu / phase options** | `method_menu.py` (559 lines), `phase_options.py` | `application/method_lifecycle.py` (377 lines) covers method lifecycle but lacks the method-menu browse/select UI logic. |
| **Phase 5 projection** | `phase5_projection.py` | No Phase 5 specific projection logic. |
| **Promotion journal/recovery** | `promotion_journal.py`, `promotion_recovery.py` | `harness/publication.py` handles publication atomically but has no promotion journal (the event journal serves a similar purpose). |

### Category E: Operational and Infrastructure (Needed for Real Use)

| Gap | Priority | Notes |
|---|---|---|
| **Reviewed-basis sealing** | 🔴 Critical | `10-open-implementation-gaps.md` documents this: the accepted command does not seal exact input generations/digests. A user could review one basis and get a manifest prepared on a different one. This is the WP0 gate. |
| **Hermes profile existence verification** | 🔴 Critical | Method Hub cannot confirm the configured Hermes profiles actually exist on disk before launching. |
| **Bounded subprocess output** | 🟡 High | Research Hub's `_run_process_with_bounded_output()` caps stdout/stderr. Method Hub executor has `output_limit_bytes` check post-hoc but no streaming bound. |
| **Process-tree kill on timeout** | 🟡 High | Research Hub has Windows job-object + Linux process-group kill. Method Hub only calls `kanban archive`. |
| **Database migrations** | 🟡 High | `storage/migrations.py` (401 lines) exists but is untested against real schema evolution. |
| **Backup and restore** | 🟡 Medium | Not implemented. Architecture plan calls for it in WP6. |
| **Concurrent-run protection** | 🟡 Medium | `run_coordinator.py` has per-run `asyncio.Lock` but no cross-process fencing. |
| **Authentication** | 🟢 Lower | Local-only use does not need this now. Remote operation (WP5) is post-v1. |

---

## Part 3 — Recommended Work Order (Pragmatic Priority)

This reorders the architecture's WP0→WP9 sequence into a **pragmatic path**
that prioritizes getting real research running on Hermes as fast as possible,
while not skipping the integrity gates that makes Method Hub worth building.

### Phase 0: Unblock Real Execution (1–2 weeks)

**Goal:** Make `hermes_kanban` executor actually run a real Hermes role and
capture its output, development-mode-only, on this machine.

0.1. **Hermes profile verification** — before any run, confirm the configured
     Hermes profiles exist on disk. Port `profile_skills.resolve_hermes_root()`
     and the configured-profile-existence check from Research Hub.
     - Files: `src/method_hub/configuration/profiles.py`,
       `src/method_hub/configuration/resources.py`
     - Test: reject a run when a mapped profile does not exist on disk.

0.2. **Bounded output capture** — port Research Hub's
     `_run_process_with_bounded_output()` into the Hermes executor path. Capture
     `hermes` subprocess stdout/stderr into per-run log artifacts.
     - Files: `src/method_hub/executors/hermes.py`,
       `src/method_hub/harness/execution_records.py`
     - Test: a long-running role's output is truncated at the configured byte
       limit, not allowed to exhaust memory.

0.3. **Process-tree kill** — implement forced cancellation that kills the
     Hermes process tree, not just the kanban archive call. Port the Linux
     process-group kill from `launch_process.py`.
     - Files: `src/method_hub/executors/hermes.py`
     - Test: cancelling a run terminates the Hermes process within seconds.

0.4. **Run log storage and viewer** — store captured output as an immutable
     run artifact. Add an API route and UI panel to view it.
     - Files: `src/method_hub/api/router.py`, `web/src/pages/RunPage.tsx`
     - Test: after a fake run, the log artifact is retrievable via the API and
       visible in the UI.

0.5. **Enable `hermes_kanban` for a real single-role test** — with
     `development_mode=True`, configure one real Hermes profile and run one
     real role task through the full harness. This is the first real
     end-to-end execution on Method Hub.
     - Validation: one real Hermes role task completes, produces output in the
       role workspace, and the harness records the closure.

### Phase 1: Reviewed-Basis Sealing (1 week) — The Integrity Gate

**Goal:** Close the gap in `10-open-implementation-gaps.md` before any real
multi-role research runs.

1.1. **Seal input generation IDs and digests** in the accepted `RunCommand`.
     Bind the current authority head, exact formal input generation IDs, and
     artifact digests at command acceptance time.
     - Files: `src/method_hub/harness/commands.py`,
       `src/method_hub/harness/preparation.py`, `src/method_hub/domain/runs.py`

1.2. **Reject stale basis** — if any sealed input changes between acceptance
     and preparation, reject with a stable `stale-basis` error. No role starts.
     - Test: concurrent basis-change rejection for formal inputs, methods, and
       profiles (acceptance tests 1–8 from the gaps document).

1.3. **Idempotent replay** — replaying the same idempotency key must return
     the original sealed basis, never resolve newer objects.

### Phase 2: Real Five-Phase Execution (3–4 weeks)

**Goal:** Validate all five phase contracts with real Hermes output. This is
where Method Hub starts doing actual research.

**Approach:** Do not port Research Hub's `empirical_promotion.py`,
`theory_promotion.py`, etc. directly. Instead, build thin validation adapters
that check real Hermes output against the existing phase contracts. The
contracts are the source of truth; Research Hub's promotion logic was
contract-less and should not be imported.

2.1. **Phase 1 pilot** — run a real literature review with 2–3 sources.
     Validate: deduplication, source-identity stability, cumulative synthesis
     replacement. Build the literature-specific validation rules in
     `harness/submission_validation.py`.
     - Pilot: entangled Langevin literature (reuse Research Hub project-004
       context).

2.2. **Phase 2 pilot** — run a real method-development phase. Validate:
     method identity, version advancement, definition digest change, lineage.
     Full-catalog and focused-method modes.

2.3. **Phase 3 pilot** — run a real theory phase. Validate: complete proof
     record replacement, exact method binding.

2.4. **Phase 4 pilot** — run a real empirical phase. Validate: 4-slot atomic
     update (evidence index, empirical synthesis, implementation record, phase
     decision). This is the most complex validation.
     - Files: extend `harness/submission_validation.py` with Phase 4-specific
       rules. Do NOT create an `empirical_promotion.py` equivalent — the
       contract + validation adapter is the Method Hub way.

2.5. **Phase 5 pilot** — run a real manuscript assembly + review-revision.
     Validate: aligned basis, closed review packet, issue disposition, draft
     replacement.

2.6. **Negative-result fixture** — validate that a complete-but-negative
     scientific result publishes correctly. This is a core Method Hub
     invariant.

### Phase 3: UI Completion (2 weeks, parallel with Phase 2)

**Goal:** Bring the researcher-facing UI to feature parity with Research Hub
for daily use.

3.1. **Run log viewer** — `RunPage.tsx` panel showing captured subprocess
     output with scroll, search, and download. (Depends on Phase 0.4.)

3.2. **Rich decision brief** — replace the `DecisionBrief.tsx` stub with a
     structured scientific summary: what changed, what is current, what remains
     uncertain, what action is available. Pull from view models, not raw JSON.

3.3. **Profile memory viewer** — port Research Hub's
     `/profiles/<name>/memory` feature. Read `MEMORY.md` from the Hermes
     profile home and display it. Add a new API route and UI page.
     - Files: `src/method_hub/api/router.py`,
       `src/method_hub/application/profile_views.py`,
       `web/src/pages/ProfilesPage.tsx`

3.4. **Skill installation end-to-end** — verify the existing
     `application_skill_install` path works with real Hermes profiles. Add UI
     feedback for install/drift/outdated states.

3.5. **Admin recovery controls** — add a safe UI action for inspecting a stuck
     run and triggering operational cleanup (the Method Hub equivalent of
     Research Hub's `retry_cleanup` / `recover_cleanup`, adapted to the
     event-sourced model). No "approve" or "auto-retry" buttons.

3.6. **SSE run streaming validation** — `useRunEvents.ts` is structurally
     superior to Research Hub's HTMX polling. Validate it works end-to-end
     with real runs and displays live progress.

### Phase 4: Operational Hardening (2–3 weeks)

4.1. **Startup reconciliation** — on server restart, adopt or terminate exact
     prior runs/invocations. Never launch a duplicate.
4.2. **Concurrent-run fencing** — cross-process lock at every mutable
     operational boundary.
4.3. **Database migration tooling** — test `storage/migrations.py` against
     real schema evolution. Forward migration + preflight + backup requirement.
4.4. **Backup and restore** — consistent backup of database, immutable
     generations, authority journals, run artifacts. Verify restore reproduces
     the same state digest.
4.5. **Failure injection suite** — crash at each write/commit boundary, process
     kill during each run state, same-target and disjoint-target concurrency.

### Phase 5: Knowledge Graph Decision (Open Question)

Research Hub has a 6,511-line knowledge graph subsystem. Method Hub's
architecture mentions "knowledge resources" as a role-input category but does
not implement a graph.

**This is a design decision, not an implementation task.** Options:
- **(a)** Do not build a knowledge graph. Rely on role-facing context snapshots
  and frozen inputs. The contract system makes this viable.
- **(b)** Build a minimal knowledge-resource registry (no graph traversal,
  just content-addressed references) for future proof/optimization/biological
  libraries.
- **(c)** Port a subset of Research Hub's knowledge graph adapted to the
  event-sourced model.

**Recommendation:** Defer this decision until after Phase 2 pilots. The
pilots will reveal whether role-facing context is sufficient or whether a
structured knowledge layer is needed.

### Deferred / Out-of-Scope for v1

These items from the architecture's operational completion plan are explicitly
**not** needed for a functioning local research harness:

- **Rootless OCI executor** (WP1) — the development `hermes_kanban` executor
  with profile verification and bounded output is sufficient for single-host
  local use. OCI isolation is a production-hardening concern.
- **Authentication and remote operation** (WP5) — local loopback use does not
  need auth. Add when remote access is required.
- **Legacy Research Hub importer** (WP8) — the entangled Langevin project
  should be re-run natively on Method Hub rather than imported.
- **Supported deployment / OS qualification** (WP7) — this machine is the
  deployment target for now.

---

## Part 4 — Summary: What Makes Method Hub "Complete"

A functioning Method Hub that matches Research Hub's utility needs:

| Criterion | Status Today | Target |
|---|---|---|
| Real Hermes execution | ❌ Development-only | ✅ `hermes_kanban` runs real roles, captures output, handles timeout/cancel |
| Reviewed-basis integrity | ❌ Gap documented | ✅ Command seals exact basis; stale-basis rejection |
| Five-phase real validation | ❌ Schema examples only | ✅ All five phases run real Hermes research and validate real output |
| Researcher UI parity | 🟡 Structural skeleton | ✅ Run logs, decision briefs, profile memory, skill install, live progress |
| Operational recovery | 🟡 Basic restart recovery | ✅ Startup reconciliation, fencing, backup/restore, failure injection |
| Knowledge management | ❌ Not implemented | ⏸ Deferred pending pilot feedback |
| Tests | 244 passing | ✅ 500+ with real-execution conformance suites |

**Estimated timeline to functioning v1 (local, single-host):**
- Phase 0 (unblock execution): 1–2 weeks
- Phase 1 (reviewed-basis): 1 week
- Phase 2 (five-phase real runs): 3–4 weeks
- Phase 3 (UI completion): 2 weeks (parallel)
- Phase 4 (operational hardening): 2–3 weeks

**Total: ~8–12 weeks of focused implementation**, with the first real research
run possible after Phase 0 (~2 weeks).

---

## Part 5 — Key Design Principles to Preserve

Throughout implementation, these Method Hub principles must not be violated:

1. **No automatic scientific retry.** Every run is user-started. Infrastructure
   reconciliation may reconnect, but a new agent call requires a new run.
2. **No post-run approval gate.** Method Hub deliberately rejects Research
   Hub's `approve_run` / `request_revision` pattern. Validated output publishes
   automatically; the user decides the *next* run.
3. **Contracts are the source of truth.** Do not port Research Hub's
   contract-less promotion logic. Build validation adapters against the
   existing phase contracts.
4. **No dual-writing.** Method Hub must not import Research Hub code, use its
   database, or write its project folders.
5. **Operational state ≠ scientific outcome.** The UI must never derive status
   from file existence or conflate a failed run with a negative scientific
   result.
6. **Negative results publish when structurally complete.** A validator must
   not convert "method failed under this condition" into an operational
   failure.

---

*Prepared: 2026-08-03*
*Baseline: method-hub@a0798ef (244 tests), research-hub HEAD (893 tests)*
