# Storage and Memory Management Review (2026-08-22)

A ground-truth review of (1) the file-system management of everything the
system produces and (2) the memory management of what each role actually
receives as context at every phase / run / stage. Verified against the
live store (`~/.model-forge/`), the SQLite index, and the source
(`harness/inputs.py`, `harness/task_briefs.py`, `executors/hermes.py`,
`harness/execution_context.py`).

## Part 1: File-system management

Three cooperating layers, each with a distinct authority role.

### Layer A - Artifact store (`~/.model-forge/artifacts/objects/`)

Content-addressed immutable bytes (path = sha256 of content). Everything
the system ever handles lands here exactly once: raw command requests,
sealed records, task briefs, role outputs, run manifests. Same content =
same object = automatic dedupe across runs and projects. ~10 MB today.

### Layer B - SQLite index (`model-forge.sqlite3`, 31 tables)

The queryable authority. Four functional groups:

- **Project + run lifecycle**: `projects`, `runs`, `run_manifests`,
  `run_launch_records`, `run_preflight_reports`, `run_events`,
  `run_submissions`, `run_submission_attempts`, `run_validation_reports`,
  `run_validation_attempts`, `run_promotion_records`,
  `publication_receipts`, `sealed_commands`, `raw_command_requests`.
- **Role execution**: `role_execution_intents`, `_heartbeats`,
  `_closures`, `_acknowledgements` - one row per role assignment from
  claim to close; plus fencing (`run_fencing_tokens`,
  `diagnostic_fencing_tokens`, `profile_execution_locks`) that makes
  concurrent execution safe.
- **Record store (the "current truth")**: `formal_generations`
  (every sealed generation of every record, payload inline) +
  `current_slots` (logical slot -> current generation pointer). The
  catalog the UI shows is a join of these two. History is never
  overwritten; "current" is a pointer move.
- **Reference + audit**: `artifacts` (id -> sha256 registry),
  `authority_events`, `profile_mappings`, `cumulative_collection_items`,
  `project_settings`, `diagnostic_invocations`, `run_profile_seals`,
  `project_role_state_locks`.

### Layer C - Run workspaces (`~/.model-forge/runs/<run_id>/`)

One directory per run, split into two trees per role assignment:

```
runs/<run_id>/
  roles/NN-<role>/          # the sealed work surface
    inputs/<sha256>         # materialized frozen inputs (byte-copies from Layer A)
    access.jsonl            # which artifacts were materialized, when, where (audit)
    usage.json              # tokens, cost estimate, model, session id
    <declared outputs>      # e.g. theory-proposal.json, method-changes.json
    <scratch>               # undeclared working files (verify_*.py, logs)
  tasks/NN-<role>/          # the agent session workspace (executor cwd)
```

The split is deliberate: `tasks/` is the live agent session (transcripts,
tool state), `roles/` is the harness-facing surface where only declared
outputs are sealed. Scratch files are retained for inspection but are
NOT sealed - only contract-declared outputs feed validation and
promotion.

### What each phase produces (per contract `run_local_outputs`)

- **P1** (literature): 3 discovery handoffs (lead/theory/empirical),
  `source_changes` (literature sources), `synthesis_candidate` +
  `coverage_candidate` (scientific records), attention items, decision.
- **P2** (methods): 2 proposal handoffs, 2 review handoffs,
  `method_changes` (catalog change set with sealed evaluations),
  attention items, decision.
- **P3** (theory): theory session, handoff, audit, candidate records.
- **P4** (evidence): experimental design, evidence, verification,
  empirical/implementation candidates, attention items, decision
  (numerical code lives here as role scratch + declared evidence files).
- **P5** (manuscript): manuscript records.

### Live sizes

38 MB runs/ (42 runs: 2 P1, 37 P2, 1 P3, 2 P4), 10 MB artifacts/,
16 MB index. Small; no retention/pruning policy exists yet (Finding F4).

## Part 2: Memory management (what enters each role's context)

### Delivery mechanism

Each role assignment is one Hermes kanban task: `--workspace
dir:<run>/tasks/NN-<role>`, `--assignee <profile>`, body = "Read the
complete task brief at <path>; write only the declared outputs; do not
start another phase or role." The agent's context is therefore exactly:
its profile soul + preloaded skills + the brief + whatever it chooses to
read from its materialized `inputs/`. Nothing else exists for it: no
database access, no other runs, no peers' sessions.

### Brief composition (`render_task_brief`)

Layered, immutable-first: (1) immutable instruction boundary, (2)
scientific objective (stage text), (3) mode directive, (4) stage-role
assignment, (5) researcher direction (highest scientific priority within
the frozen mode), (6) role stance, (7) **frozen inputs as PATHS, never
inlined content**, (8) parallel-group isolation rule, (9) required
outputs with schema-derived skeletons, constraints, conditional
requirements, and identity-neutralized fixture examples.

### Input resolution (`harness/inputs.py` + contract `reads`)

Each stage declares `reads`. At preparation time the harness resolves
each entry to a current record (`current_slots` join
`formal_generations`) or a prior-stage run-local output, then
materializes byte-copies into the role's `inputs/<sha256>` and logs
`access.jsonl`. Parallel-isolation is therefore physical: a stage-1
proposer cannot read its peer's proposal because the file was never
placed in its workspace.

Measured on the E-1d full-catalog run:

| Role | Inputs | Materialized | Prompt tokens | Cache reads |
|------|--------|--------------|---------------|-------------|
| 01 theorist / analyst | 5 | 192 KiB | 112-123k | 5.3-5.8M |
| 02 reviewers | 7 | 221 KiB | 142-165k | 3.5-7.1M |
| 03 research_lead | 9 | 280 KiB | 189k | 5.3M |

The reading pattern is cumulative: stage 2 = basis + both proposals;
stage 3 = basis + proposals + both reviews. The dominant single input is
the literature library (~133 KiB). Cache-read volume shows agents re-read
inputs repeatedly during a session - the context cost of large inputs is
paid many times per role.

### Correction lane discipline (K-2 / K-3)

Revalidation and normalization closures keep a two-context separation:
the write-context bundle (what the correction may change) vs the shared
read context (what it may consult). Corrections re-enter through the same
validation gates, not around them.

## Findings

- **F1 (by design, worth affirming)**: memory is path-referenced, not
  inlined - briefs stay small and identical inputs dedupe via sha256.
- **F2**: scratch vs declared output distinction is clean on disk, but
  scratch is invisible to validation. The stage-2 reviewers' strongest
  work (verify_*.py, verification-log.md) lives only in scratch; E-1e
  should surface reviewer evaluations as declared content.
- **F3**: no input-size budget. The literature library at 133 KiB is
  fine today; at 10x literature it becomes the context bottleneck,
  multiplied by every stage and every re-read. Consider a per-input size
  guard or a digest/summary tier for very large basis records.
- **F4**: no retention policy for runs/, artifacts/, or the index.
  Everything is append-only forever. Fine at 64 MB total; needs a policy
  before long-running use (e.g. keep sealed outputs + index, prune
  tasks/ transcripts older than N days).
- **F5**: `inputs/` duplicates the same sha256 content per role (up to
  5x per stage). Cheap at current scale; symlinks or a shared
  materialization dir would remove the duplication if it matters.

## Addendum: the tiered-summary design (information layers)

Tez asked whether the designed summary tiers (one-paragraph contribution
per literature work; 1-2 page technical summaries for theory/method) are
still implemented and useful. Verdict: **specified and plumbed, but
hollow - never produced with real content, never consumed for context.**

- The design (03-storage-and-authority.md section 2): every record may
  declare `representations[]` tagged by `information_layer` -
  `primary_artifact` (full detail), `structured_record`
  (machine-addressable claims), `compact_decision_view` (the short
  decision-oriented tier). Layers are retrieval depth, not authority.
- Implemented: the schema enum; sealed records DO declare layers
  (store-wide histogram: 8 primary, 5 structured, 6 compact); read-side
  plumbing extracts the compact view
  (`repository_views._extract_highlight_artifact_id` ->
  `CurrentRecordReference.highlight_artifact_id` -> view models).
- Not implemented: every compact_decision_view in the store is a
  development-executor placeholder (synthetic sha256, no backing file).
  No real run has ever generated one. And the harness never materializes
  a compact view into role inputs - roles always receive the full
  primary artifact (the 133 KiB literature library in the E-1d run).
- Per-literature-work one-paragraph contribution summaries do not exist
  structurally: `literature-source` records carry bibliographic metadata
  only. The nearest real content is the P1 discovery handoffs'
  `completed_work` prose (genuinely useful per-finding paragraphs, but
  unstructured strings, not addressable per-work records).
- Consequence: the tier that would answer F3 (input-size scaling)
  already exists as a design but delivers no memory benefit today.
- Wiring path (small): (a) P1 synthesis stage produces the compact view
  with real content (it already writes the summary artifact id; the
  executor just never generates the bytes in real runs); (b) input
  materialization prefers `highlight_artifact_id` for basis records when
  present; (c) optionally add structured per-work key-contribution
  paragraphs to the literature synthesis so stage-1 proposers receive
  per-work paragraphs instead of raw metadata.
