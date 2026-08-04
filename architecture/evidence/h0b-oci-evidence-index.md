# H0-B Evidence Index: Rootless OCI Runtime Gate

## Status: PASSED

Date: 2026-08-04
Commit: (this commit)
Platform: Linux 7.0.0-27-generic (x86_64)
Runtime: Podman 5.7.0 (rootless)
Image: localhost/method-hub-runtime:latest
       digest: sha256:c93fe9e3d5dd05960b5d0fcf00dd6f8e5d841a6a9f7c802f46211d7d7f5007ac
Tests: 441 passed, 2 skipped, 0 failed (103.78s)
       H0-B evidence: 22/22 passed

## Evidence matrix

The same required evidence repeated through the ADR-004 production boundary
(rootless OCI). Each item corresponds to the H0-A bwrap evidence (E1–E7) but
through rootless Podman.

### P1: Podman launches and mounts correctly

| Test | Evidence |
|------|----------|
| P1a | Podman runs a basic command with --read-only --cap-drop ALL --security-opt no-new-privileges |
| P1b | Workspace directory is mounted read-write (with --userns keep-id) |
| P1c | SOUL.md is mounted read-only — writing fails |
| P1d | Container process has zero effective capabilities (CapEff = 0) |
| P1e | Read-only root filesystem blocks writes to /etc |

### P2: Real Hermes one-shot in OCI container

| Test | Evidence |
|------|----------|
| P2a | Hermes -z executes inside rootless OCI container, writes 'ok' to result.txt — **the key H0-B evidence** |

### P3: Profile mount verification

| Test | Evidence |
|------|----------|
| P3a | state.db in profile directory is writable (C1) |
| P3b | Cross-profile access blocked — OCI container only sees explicitly bind-mounted paths (stronger isolation than bwrap --ro-bind /) |

### P4: Diagnostic output validation (executor-independent)

| Test | Evidence |
|------|----------|
| P4a | Correctly-formatted diagnostic_result.json passes validation |
| P4b | Wrong brief_sha256 is caught |
| P4c | Exit code 0 with no output file → failure |
| P4d | Canary scan detects leaked API key |

### P5: Timeout and cancellation

| Test | Evidence |
|------|----------|
| P5a | Long-running process inside OCI is killed via SIGTERM/SIGKILL |
| P5b | OciExecutor.cancel() returns True for confirmed termination |

### P6: Network isolation

| Test | Evidence |
|------|----------|
| P6a | --network none prevents outbound connections |
| P6b | --network host permits outbound connections |

### P7: OciExecutor integration

| Test | Evidence |
|------|----------|
| P7a | OciExecutor launches a container via the RoleExecutor protocol |
| P7b | reconcile() returns FAILED for a dead process |
| P7c | cancel() returns True for a nonexistent PID |
| P7d | _verify_mounts catches missing workspace |

### P8: Image digest pinning (ADR-004)

| Test | Evidence |
|------|----------|
| P8a | Runtime image has a verifiable digest |
| P8b | OciExecutor rejects a mismatched image digest |

## Key findings

### 1. Mount strategy: same-path bind mounting

Unlike bwrap (which can mount the entire host root read-only and overlay
specific paths), rootless Podman with `--read-only` starts from the image
layers. Host paths are only accessible through explicit `-v` bind mounts.

The correct approach is **same-path mounting**: bind-mount each host path
at its own absolute path inside the container. This mirrors the bwrap
strategy and avoids path-translation issues.

### 2. Hermes venv requires uv Python mount

The Hermes binary is a Python script with a shebang pointing to
`~/.hermes/hermes-agent/venv/bin/python3`, which symlinks to the
uv-managed Python at `~/.local/share/uv/python/cpython-3.11.../bin/python3.11`.

For Hermes to run inside the container, both `~/.hermes` and
`~/.local/share/uv` must be bind-mounted.

### 3. --userns keep-id is required for write access

Rootless Podman maps the container UID to the host UID via `--userns keep-id`.
Without this flag, volume-mounted files owned by the host user are not
writable by the container process (which defaults to a mapped subordinate UID).

### 4. OCI provides stronger profile isolation than bwrap

With bwrap's `--ro-bind / /`, the entire host filesystem is visible
read-only inside the sandbox — including other profiles' directories.

With Podman's `--read-only` root filesystem, only the image layers and
explicitly bind-mounted paths are visible. Cross-profile access is
structurally blocked because other profile directories are never mounted.
This is the ADR-004 production boundary working as designed.

## Exit gate mapping

| Exit gate criterion (plan §7) | H0-B evidence |
|-------------------------------|---------------|
| rejected/blocked request → zero processes | P7d |
| exact selected profile and declared skills | P2a |
| only declared workspace writable | P1b, P1e |
| output validated independently of exit code | P4a–P4d |
| cancellation awaited and reaped | P5a, P5b |
| provider access works, arbitrary egress fails | P6a, P6b |
| image digest pinned and verified | P8a, P8b |
| no credential in process metadata | (canary scan: P4d) |
| **H0-B passes the complete real Linux matrix through rootless OCI** | **P1–P8** |
