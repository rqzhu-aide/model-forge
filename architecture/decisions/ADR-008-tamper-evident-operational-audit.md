# ADR-008: Tamper-Evident Operational Command Audit

- Status: accepted
- Date: 2026-08-02

## Context

The system must explain every attempt to start or cancel a run, change a method's lifecycle, or withdraw a formal generation. Successful formal operations already append scientific authority events, but rejected commands and pre-publication run controls do not belong in that journal. Treating them as scientific authority would let an operational failure appear to change the research record.

Malformed and unauthenticated requests also need an audit identity even when no schema-valid command ID, trusted user, or exact target can be resolved.

## Decision

Maintain a project-scoped append-only `CommandAttemptAuditEvent` journal that is separate from the scientific authority-event journal and from each run-state journal.

Each event records:

- its monotone sequence, event ID, project, action family, check stage, and service time;
- an immutable artifact pointer, byte length, and SHA-256 for the exact request bytes received before parsing;
- the validated command ID and canonical command digest when validation succeeds;
- either the exact action-specific target or an explicitly unresolved target for a rejected acceptance-stage request;
- either an authenticated user and optional delegated operator, or an unauthenticated requester with only an optional untrusted presented identity;
- separate authentication and delegation checks, including project, action, exact target, time-window, and revocation results;
- an accepted or rejected result, the exact durable RunState event or publication receipt ID and digest for accepted pre-commit events, and the complete stable `CommandError` for rejected events.

Authorization is checked and recorded at two boundaries. The `acceptance` event records the first decision. The `pre_commit` event records the final check immediately before run creation, a cancellation fence, or a formal control transaction becomes durable. A command that does not reach pre-commit has no fabricated second event.

The event content digest is SHA-256 over RFC 8785 canonical JSON with `content_sha256` and `audit_root_sha256` omitted. The audit root is

\[
H_i = \operatorname{SHA256}\!\left(H_{i-1} \mathbin{\|} C_i\right),
\]

where `H_{i-1}` and `C_i` are decoded 32-byte values. The first event uses 32 zero bytes. The raw request digest is SHA-256 over the exact referenced bytes.

An accepted cancellation's run-state event binds the cancellation command ID and digest and complete requesting identities. The accepted pre-commit audit event then binds that exact run-state event ID and digest. This direction avoids a digest cycle and remains operational rather than scientific authority.

## Consequences

- Rejected, malformed, and unauthenticated attempts are auditable without inventing a trusted command or user identity.
- Web and remote clients can reconstruct the same stable error, message, and smallest corrective action.
- Remote authorization decisions show which individual scope, time, or revocation check failed.
- Recovery verifies sequence continuity, request artifacts, content digests, and the audit-root chain before accepting another command.
- Audit events never publish, supersede, withdraw, align, or otherwise change scientific records.
