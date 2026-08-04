# ADR-011: Per-project Hermes profile memory and session model

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

## Options considered

### Option A: formal snapshots only

Disable persistent Hermes memory and sessions. This preserves the simplest
frozen-context model, but removes useful project-local working continuity for
author roles.

### Option B: directly writable canonical profiles

Let Hermes update the canonical project profile during execution. This is
simple, but failed, cancelled, stale, or concurrent invocations could corrupt
or silently change later context.

### Option C: policy-specific isolated runtime profiles

Clone or create one invocation-specific runtime profile, apply an explicit role
policy, and promote only eligible persistent state after validated success and
verified quiescence. This option is selected because it preserves useful
continuity without making mutable agent memory a scientific authority.

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

3. **Accessible runtime context is reconstructible.** A digest identifies
   content but cannot reconstruct it. Each invocation record therefore captures:
   - an immutable content-addressed memory-before snapshot reference and digest;
   - an inventory and SHA-256 digest of every memory and session-state file the
     role could read;
   - the role's runtime memory policy and policy version;
   - the canonical profile revision;
   - a verified session-state snapshot reference and digest, or an attestation
     that prior-session access was disabled; and
   - an immutable runtime-after snapshot reference, inventory, and digest
     whenever a launched invocation reaches a readable closure, including
     failed, cancelled, timed-out, lease-lost, and unresolved outcomes.

   Runtime-after evidence is retained for diagnosis. It is promoted only for a
   validated persistent success under a current token and lease.

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
- Memory snapshots are evidence. They are sealed and retained for audit.

## Contract changes

- The existing formal role-memory contract remains authoritative for research
  context. The `persistent`, `read_only`, and `ephemeral` value is a separate
  diagnostic-runtime policy and must not be stored in or interpreted as the
  existing formal role-memory object.
- Diagnostic profile manifests and invocation records carry runtime-policy
  version, canonical revision, snapshot references and digests, accessible-file
  inventory, session-state evidence, and promotion disposition.
- Architecture 08 continues to prohibit private memory from replacing sealed
  inputs, formal scientific records, or explicit role handoffs.
- A later ADR is required before this diagnostic-runtime policy becomes
  load-bearing for scientific Phase 1 through Phase 5 execution.

## Schema changes

- Add versioned diagnostic schemas for the profile manifest, memory-state
  evidence, process identity, usage report, lifecycle record, and fixed output.
- Distinguish immutable before, runtime-after, and promoted canonical snapshot
  references.
- Record whether prior-session access was enabled and, if so, the verified
  snapshot method and digest.
- Preserve compatibility by leaving the existing formal role-profile memory
  representation unchanged.
- Register new schemas, valid examples, rejected fixtures, digest payloads, and
  traceability entries together before implementation relies on them.

## Scenario changes

Add or update acceptance scenarios for:

1. two validated persistent runs with reconstructible continuity;
2. read-only execution with no canonical mutation;
3. a fully fresh outside-reviewer profile with no prior memory or sessions;
4. failed, cancelled, timed-out, lease-lost, and unresolved closures with sealed
   runtime-after evidence and no promotion;
5. stale-token and expired-lease promotion, cleanup, and lock-release rejection;
6. session browsing through a verified snapshot, plus fail-closed behavior when
   no safe snapshot can be created;
7. explicit inspect, export, clear, and policy-reconfiguration operations; and
8. retention that preserves active and unresolved evidence and removes only
   ownership-verified closed state.
