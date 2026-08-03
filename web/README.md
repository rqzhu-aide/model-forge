# Method Hub web interface

This folder contains the researcher-facing React interface for the new Method Hub architecture. The interface presents backend-projected research state and submits explicit, typed commands. It does not infer scientific eligibility, silently approve results, or start a phase automatically.

## Run locally

Requirements: a recent Node.js release and the Method Hub API.

```bash
npm install
npm run dev
```

Vite serves the interface and proxies `/api` to `http://127.0.0.1:8765` by default. Set `METHOD_HUB_API_ORIGIN` before starting Vite to use another API origin. Vite runs as a single-page application server, so direct navigation to a frontend route works during development and preview. The bundled FastAPI server applies the same `index.html` fallback for non-API browser routes in a production build.

```bash
npm run build
npm run preview
```

## Interface behavior

- Every phase remains visible. The backend decides whether a particular command is enabled and explains why.
- Choosing a method, run scope, context item, profile, or skill never launches a research run.
- A run begins only after the researcher reviews and submits the exact command.
- Phase 2 displays the current method catalog and only exposes lifecycle controls supplied by the backend.
- Phase 3 and Phase 4 use the same active method catalog. The researcher selects an exact method identity before either phase can be launched.
- Phase 4 scope is represented by backend-provided run modes, including preliminary and comprehensive modes when available.
- Run-local work is displayed separately from validated formal project state.
- Role profiles and recommended skills are installed only through explicit configuration commands.

## Expected API

The interface uses `/api/v1` and expects these endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET`, `POST` | `/projects` | List or create projects |
| `GET` | `/projects/{project_id}/overview` | Read the projected project overview |
| `GET` | `/projects/{project_id}/phases/{phase}` | Read a phase view and its action descriptors |
| `GET` | `/projects/{project_id}/methods` | Read the current method catalog |
| `POST` | `/projects/{project_id}/methods/{method_id}/lifecycle` | Submit a supplied retire or reactivate command |
| `GET`, `POST` | `/projects/{project_id}/runs` | List runs or submit a supplied start command |
| `GET` | `/projects/{project_id}/runs/{run_id}` | Read current run state |
| `POST` | `/projects/{project_id}/runs/{run_id}/cancel` | Submit a supplied cancellation command |
| `GET` | `/projects/{project_id}/runs/{run_id}/events` | Poll append-only progress events |
| `GET` | `/projects/{project_id}/runs/{run_id}/events/stream` | Stream progress events with SSE |
| GET | /projects/{project_id}/artifacts/{artifact_id} | Read or download an immutable project artifact |
| GET | /projects/{project_id}/publications/{receipt_id} | Inspect one validated publication receipt |
| `GET` | `/projects/{project_id}/configuration/profiles` | Read role profiles and skill status |
| `PATCH` | `/projects/{project_id}/configuration/profiles/{role_id}` | Save a supplied profile command |
| `POST` | `/projects/{project_id}/configuration/profiles/{role_id}/skills/{skill_id}/install` | Submit a supplied skill installation command |

Phase views accept optional `mode` and `method_id` query parameters. Event endpoints accept `after_sequence`. The complete frontend response and request shapes are defined in `src/api/types.ts`.

The run start body is:

```json
{
  "action_descriptor_id": "action-id",
  "phase": "P4",
  "mode": "p4.preliminary",
  "choice_values": {},
  "context_policy": "current_only",
  "selected_context_option_ids": []
}
```

The server remains authoritative. It should reject stale action descriptors, invalid method identities, unmet dependencies, and conflicting publication attempts with a structured researcher-facing error.
