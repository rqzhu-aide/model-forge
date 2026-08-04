# ADR-005: Per-project Hermes profile memory and session model

Status: Accepted (2026-08-03, diagnostic lane scope)

## Context

Architecture 08 defines a frozen per-run context snapshot model: each role
invocation receives only the sealed basis and frozen prepared contexts as its
authoritative context. Hermes profiles currently retain persistent memory
(MEMORY.md, USER.md) and session history (state.db) across invocations.

The revised diagnostic lane plan introduces per-project Hermes profiles where
author-role memory accumulates across runs within the same project. This
changes the role-context model from a purely frozen-snapshot model to one
where supplementary agent-managed context also exists.

## Decision

1. **Formal records remain the sole scientific authority.** No assumption,
   method definition, result, conclusion, or user decision may exist only in
   Hermes memory. Memory is supplementary working context.

2. **Memory policy is per-role:**
   - `persistent` (default for authors): memories and session state
     accumulate across runs within the project. On validated success, runtime
     changes are atomically promoted to the canonical profile.
   - `read_only`: the agent reads the selected immutable memory snapshot but
     cannot modify it. All runtime changes are discarded.
   - `ephemeral` (default for `outside_reviewer`): each invocation starts
     with no prior memory, sessions, or state. Runtime state is discarded
     after closure.

3. **Memory content is reconstructible.** Each invocation record captures:
   - SHA-256 of MEMORY.md and USER.md at invocation start (the canonical
     snapshot digest);
   - the role's memory policy and version;
   - the profile revision; and
   - the memory-state-after snapshot for validated successful runs.

4. **The canonical profile is never directly writable by Hermes.** A
   per-invocation runtime profile is created from a consistent canonical
   snapshot. Hermes writes only to that isolated runtime state. On validated
   success and verified quiescence, allowed changes are atomically promoted
   back to the canonical profile while the fencing token and lease remain
   current. Failed, cancelled, or timed-out changes are never promoted.

5. **Prior-session browsing** requires a verified SQLite backup or checkpoint
   procedure while the profile mutex is held. If unavailable, session browsing
   is disabled.

6. **User operations are explicit and audited:** memory inspect, export,
   clear, and policy reconfiguration are versioned operations that never
   occur as side effects of starting or closing a diagnostic.

7. **Scope:** This decision is accepted for the diagnostic lane only. It
   becomes load-bearing for scientific execution only after the full exit
   gate passes and a subsequent decision removes the diagnostic-only scope.

## Consequences

- Profile provisioning must create per-invocation runtime profiles, not
  mount the canonical profile directly.
- Canonical promotion must be atomic, token-guarded, and conditional on
  validated success.
- The reviewer profile always receives a fully fresh mutable profile state.
- Memory snapshots are evidence — they are sealed and retained for audit.
