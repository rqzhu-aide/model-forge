# H0-B Evidence Index: Rootless OCI Runtime Gate

## Status: HISTORICAL OCI FEASIBILITY EVIDENCE; OPTIONAL HARDENING DEFERRED

Recorded: 2026-08-04
Source commit: `009a50a`
Platform: Linux 7.0.0-27-generic (x86_64)
Runtime: Podman 5.7.0 (rootless)
Image tag used: `localhost/model-forge-runtime:latest`
Observed image digest:
`sha256:c93fe9e3d5dd05960b5d0fcf00dd6f8e5d841a6a9f7c802f46211d7d7f5007ac`
Reported suite result: 441 passed, 2 skipped, 0 failed
Reported H0-B test file result: 22 passed

The reported tests remain useful observations, but H0-B is no longer a Version
1 exit gate under ADR-012. They also do not satisfy the optional OCI gate.
Most exercise hand-built Podman commands or isolated components.
None runs the complete public path
`diag CLI -> DiagnosticService -> OciExecutor -> Hermes`, and the required
27-case Linux matrix was not executed.

## What the current evidence supports

1. Rootless Podman can start a container on the tested host.
2. A container can use a read-only image root and dropped capabilities. The
   OCI executor emits CPU, memory, and process-limit options, but exhaustion
   enforcement was not verified.
3. Explicit bind mounts can make one test workspace writable and one identity
   file read-only.
4. A hand-built Podman command can run a real Hermes one-shot invocation.
5. The fixed diagnostic output validator rejects several malformed component
   cases independently of process exit code.
6. Basic manual termination and image-digest checks are feasible.

These findings establish OCI feasibility. They do not establish that Method
Hub's diagnostic composition, exact profile policy, lifecycle, cancellation,
reconciliation, memory promotion, network policy, secret delivery, and formal
state isolation work together.

## Scope of the committed P1 through P8 tests

| Group | What was observed | H0-B interpretation |
|---|---|---|
| P1 | Direct Podman commands for root, capability, and simple mount behavior | Useful host observation |
| P2 | Real Hermes through a hand-built command that mounts the full host Hermes home read-write | Connectivity only; exact profile isolation not shown |
| P3 | Writable state and cross-profile denial through separate hand-built mount arrangements | Does not test the production executor mount set |
| P4 | Component-level fixed-output validation and canary scanning | Useful validator tests; not integrated execution evidence |
| P5 | Basic termination commands and a partial executor cancellation check | Does not prove awaited tree termination and output quiescence |
| P6 | `--network none` blocks access and `--network host` permits access | Does not prove provider-only egress; host networking is unrestricted |
| P7 | OCI executor component launch and simple reconcile checks | Does not run real Hermes through the diagnostic service |
| P8 | Image digest retrieval and one mismatch check | Useful foundation; immutable launch provenance remains incomplete |

## Required claims that are not yet established

- The public diagnostic CLI composes and uses `OciExecutor`.
- A blocked request creates zero containers, and an accepted idempotency key
  creates exactly one.
- Scientific execution cannot reach the diagnostic executor.
- Only the exact selected runtime profile and declared skills are visible.
- The canonical profile, sibling profiles, and formal scientific storage are
  absent or read-only as required.
- The exact container identity and immutable image identity are persisted before
  Hermes begins work.
- Every mutation and promotion requires a current fencing token and live lease.
- Persistent, read-only, and ephemeral memory policies behave as declared.
- Cancellation, timeout, lease loss, and restart recovery control the same
  container, never relaunch, and verify quiescence.
- Output, process, file, workspace, profile, log, and retained-evidence growth
  are bounded across the complete invocation.
- The configured provider is reachable while arbitrary Internet, host-local,
  LAN, and metadata-service access are denied.
- Credentials are absent from arguments, environment, OCI inspection, logs,
  crash output, database state, snapshots, and retained evidence.
- Exit-zero internal failure, incorrect basis, and inconsistent usage are
  rejected through the integrated path.
- Formal scientific state is identical before and after every scenario.

## Exit gate mapping

| Parent-plan criterion | Current evidence | Status |
|---|---|---|
| Rejected request creates zero external work | Missing-mount component check only | Open |
| Exact selected profile and skills | Full host Hermes home is mounted in the real-Hermes test | Open |
| Only declared roots are writable | Simple mount probes use a different command | Open |
| Canonical profile never directly writable | Current executor mounts the host Hermes home read-write | Open |
| Durable identity and no relaunch | Launcher PID checks only | Open |
| Fenced lifecycle and promotion | Not exercised through OCI | Open |
| Correct memory policies | Not exercised through OCI | Open |
| Awaited cancellation and quiescence | Basic termination only | Open |
| Provider works and arbitrary egress fails | `none` versus unrestricted `host` network only | Open |
| No credential in process metadata | Standalone canary string scan only | Open |
| Independent outcome validation | Component validator cases only | Open |
| Formal scientific state unchanged | No retained before-and-after inventory | Open |
| Complete real Linux matrix | 22 narrower tests, including 2 component executor cases | Open |

## Evidence handling rule

Retain the 22 passing tests as partial feasibility evidence. Do not delete or
reinterpret them. They may be cited for the narrow observations above, but they
must not be used to label H0-B, Phase 0, or WP1 complete.

The optional OCI follow-on work is
[End-to-End OCI Diagnostic Closure](../plans/completed/next-block-end-to-end-oci-diagnostic-closure.md).
H0-B can be relabeled `PASSED` only after the complete required matrix passes
without skips through the public diagnostic service and production OCI
executor, with a machine-readable evidence bundle tied to exact source and
image digests.
