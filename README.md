# Method Hub

Method Hub is a user-directed Web interface and research harness for coordinating
Hermes agents through reproducible statistical and scientific method development.

This repository is an independent successor to the legacy
[Research Hub](https://github.com/rqzhu-aide/research-hub). It uses a new storage,
authority, and execution model. The two applications must not share formal
project state or write to the same project directory. Import of an older project
will require the separate audited migration path described in the architecture.

## Current development baseline

Method Hub currently provides:

- a FastAPI service and React researcher interface;
- explicit user commands for all five research phases;
- exact method identity and phase-contract resolution;
- durable run preparation, stage progress, cancellation, and restart recovery;
- isolated role write areas, verified outputs, immutable submissions, and no
  automatic scientific retry;
- phase-specific validation, deterministic cumulative reducers, and atomic
  publication into formal current records;
- researcher-facing current-state projections, phase navigation, controlled
  brief and method-lifecycle changes, and publication receipts;
- versioned role souls and pinned recommended writing or review skills.

The default executor is `disabled`. This allows safe inspection and
configuration without starting role work. The `fake` executor is a development
conformance fixture. It exercises the complete harness and UI with schema-valid
examples, but it does not perform research. Direct `hermes_kanban` execution is
also development-only.

Production agent execution remains disabled until the reviewed run basis,
trusted local execution boundary, authentication, recovery, and deployment
requirements are complete. See the
[Trusted Local Execution Program](architecture/plans/trusted-local-execution-program.md)
for the ordered implementation program and release gates.

## Research workflow

Every run is one controlled operation:

```text
Researcher reviews phase, mode, method, instructions, and context
  -> researcher submits one run command
  -> harness freezes the exact authorized basis and role plan
  -> declared role groups run in contract order
  -> harness validates one immutable submission
  -> valid, unconflicted outputs publish atomically
  -> system waits for the researcher's next decision
```

The researcher decides whether to run or rerun every phase. Phase 3 and Phase 4
are parallel research choices after Phase 2. Neither starts the other. Phase 5
is available only from a complete and exactly aligned Phase 1 through Phase 4
basis. Contract-declared parallel role groups share one frozen starting basis
and cannot inspect one another's in-group work.

## Local development

Requirements are Python 3.11 or later and a current Node.js release. Run from
the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cd web
npm ci
npm run build
cd ..
```

On Windows, replace the activation command with
`.venv\Scripts\Activate.ps1`.

Start the safe application with role execution disabled:

```bash
method-hub serve
```

To exercise the development harness with schema examples in PowerShell:

```powershell
$env:METHOD_HUB_EXECUTOR_KIND = "fake"
$env:METHOD_HUB_DEVELOPMENT_MODE = "true"
method-hub serve
```

The application listens on `http://127.0.0.1:8765` by default and stores local
state under `~/.method-hub`. The production frontend build supports direct
navigation to clean application URLs.

For frontend development, run `npm run dev` inside `web`. Vite proxies `/api`
to port `8765`.

## Validation

The specification, backend, and frontend are independent gates:

```bash
python architecture/tools/validate_package.py
python -m pytest
cd web
npm test
npm run build
```

The fake-executor end-to-end tests establish harness, storage, recovery, and
publication behavior. They do not establish scientific correctness.

## Repository map

| Path | Purpose |
|---|---|
| [`architecture/`](architecture/README.md) | Normative architecture, schemas, contracts, examples, decisions, and implementation plans |
| [`role and files/`](role%20and%20files/README.md) | Cross-checked file, phase, and role read/write guide |
| `resources/team/` | Role definitions and phase-aware scientific souls |
| `resources/skills/` | Pinned recommended writing and reviewer skill bundles |
| `src/method_hub/` | Storage, harness, orchestration, application, and API code |
| `web/` | React researcher interface |
| `tests/` | Unit, contract, recovery, and end-to-end tests |

## Deliberate boundaries

Method Hub does not yet claim production readiness. The remaining work includes
exact command-to-basis sealing, closed-packet reviewer attestation, a rootless
Hermes executor and capability broker, real-output phase validation,
authentication and bounded remote operation, backup and restore, failure
injection, supported deployment, and real scientific pilots.

New code must not import the legacy Research Hub application, use its database,
or write its project folders. A future importer requires its own accepted
decision, dry-run report, reconciliation tests, and rollback boundary.
