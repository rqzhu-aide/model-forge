# Hermes v0.19.0 Host One-Shot Reconnaissance

Status: Completed host observations. The reproducible sandbox spike and Phase
0 diagnostic exit gate remain open.

This record reports observed behavior only. It is not containment evidence.

Date: 2026-08-03
Hermes: v0.19.0, `/home/tez/.local/bin/hermes`
Host: Linux 7.0.0-27-generic, bwrap 0.11.1

## Verified results

### 1. Exit code semantics ✓

- **Success:** exit code 0. stdout contains ONLY the final response text.
- **Agent-internal failure** (e.g., task tool failed): exit code 0 - the agent
  reported the failure in its response but still exited cleanly. This means
  **exit code 0 ≠ task succeeded**. The output adapter must inspect declared
  output files, not rely on exit code alone.
- **SIGTERM:** exit code 143 (128 + 15). Process terminates immediately.
- **Timeout:** the `timeout` wrapper returns 124. File writes via tools may
  still have succeeded before the timeout fires.

### 2. stdout/stderr separation ✓

- stdout: final agent response text only.
- stderr: empty on clean runs. May contain Python tracebacks on crash.

### 3. `--usage-file` JSON structure ✓

Verified fields: `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `reasoning_tokens`, `total_tokens`, `api_calls`,
`model`, `provider`, `session_id`, `completed`, `failed`, `cost_status`.

### 4. Signal handling ✓

- SIGTERM to the main `hermes` process kills it immediately (exit 143).
- No orphaned child processes observed.
- `start_new_session=True` + `os.killpg` works for clean process-tree kill.

### 5. Write footprint (C1) ✓

Files Hermes writes during one `-z` run:

| File | Required writable? |
|---|---|
| `state.db`, `state.db-shm`, `state.db-wal` | **Yes** - session state |
| `logs/agent.log`, `logs/errors.log` | **Yes** - logging |
| `auth.lock` | **Yes** - credential lock |
| `/tmp/*` (temp files) | **Yes** - working temp |

Conclusion: the selected profile's mutable runtime state must be writable.
This does not justify exposing the entire Hermes root. Identity files
(`SOUL.md`, `config.yaml`, `skills/`) are read by Hermes but must be protected
by read-only bind overlays rather than making all profile state read-only.

### 6. Memory persistence ✓

- `MEMORY.md` changes persist across `-z` invocations.
- The memory tool is available in one-shot mode (confirmed: agent saved
  `SPIKE_MARKER_20260803` to memory during a `-z` run).
- md5sum changed between runs, confirming the file is re-read and re-written.

### 7. Session creation ✓

- Each `-z` run creates a new session (recorded in `state.db`, not as a
  separate `.json` file - sessions are tracked internally).
- `state.db` is the authoritative session store, not `sessions/` directory
  (which holds `request_dump_*.json` files).

### 8. Task brief via file reference ✓

- `hermes -z "Read /path/to/brief.md and do what it says."` works.
- The agent reads the file via `read_file` tool and follows instructions.
- **Important:** complex multi-step briefs take longer than simple prompts.
  The executor must allow generous timeouts (the default 14,400s = 4h is fine).

### 9. Profile cloning (C7) ✓

- `hermes profile create <name> --clone-from <source> --no-alias` copies:
  `config.yaml`, `.env`, `SOUL.md`, `skills/`.
- **C7 confirmed: `.env` IS copied with live credentials.** Provisioning
  must delete `.env` and `auth.json` from the new profile immediately.
- `auth.json` is NOT copied by `--clone` (only `--clone-all` copies state).

### 10. Provider override resolution ✓

- `-m <model> --provider <provider>` overrides the profile's config.
- Custom providers use `custom:<name>` in config.yaml.
- Without `-m`, the profile's configured `model.default` is used.


## Unverified completion checks

The following remain open and are assigned to the active runtime plan:

- a committed, reproducible one-shot spike script;
- exact `-p` profile selection inside the sandbox;
- access to only the selected project-role profile and declared skills;
- successful execution with read-only identity resources;
- output quiescence and descendant-process stress tests;
- persistent, read-only, and fully ephemeral memory/session policies;
- provider-only egress and secret-safe injection;
- one complete real Bubblewrap or OCI diagnostic invocation.

## Design decisions driven by the spike

1. **Profile directory is writable; identity files are read-only overlays (C1).**
2. **Exit code 0 is insufficient - the output adapter must inspect declared outputs.**
3. **`.env` scrubbing is mandatory after `--clone-from` (C7).**
4. **Task brief must be a mounted file, not inline (ARG_MAX + ps visibility).**
5. **`--usage-file` provides per-invocation cost tracking.**
6. **SIGTERM terminated the observed process tree (exit 143); the final
   supervisor must still verify termination and output quiescence.**
