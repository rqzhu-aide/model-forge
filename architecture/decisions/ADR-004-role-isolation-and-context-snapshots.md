# ADR-004: Role Isolation and Context Snapshots

## Status

Accepted

## Context

A role can use model tools, filesystem operations, or command-line programs that
do not obey prompt-level access instructions. Context preparation can also
silently change when model capacity, tokenization, current records, or optional
inputs change. The architecture therefore needs an enforcement boundary and an
exact account of what each role received and read.

## Invariants that must remain true

- A role reads only artifacts authorized for its exact run stage.
- A role writes only inside its unique run-local role root.
- A role process has no project-store or formal-store credential.
- Required or user-selected context is never silently truncated.
- The exact supplied inputs and on-demand reads remain reconstructable.
- Reviewer isolation is enforced by capabilities, not prompt wording.
- Reproducibility concerns inputs and access history, not deterministic model
  output.

## Options considered

### Option A: Prompt-only access rules

Describe allowed files and context in the role instruction, while giving the
role ordinary filesystem and project-storage access. This is portable but does
not prevent accidental or tool-mediated access outside the declared scope.

### Option B: Direct read-only mounts

Mount each allowed artifact into the role process and mount its output root as
writable. This provides operating-system enforcement, but exposes storage
layout, complicates per-artifact revocation, and does not create a complete read
ledger.

### Option C: Capability broker with process isolation

Give the role opaque, stage-bound artifact capabilities served by a broker. The
role has no project-storage credentials. When arbitrary filesystem or
command-line tools are available, also run the role inside an operating-system
or process sandbox that exposes only its run-local root and explicit runtime
resources.

## Decision

Select Option C. The capability broker is the portable storage boundary. It
checks every read and write against the frozen role plan, resolves immutable
artifacts, and records authorized on-demand reads in an append-only hash-chained
ledger. A role process receives no direct credential or path for project or
formal storage.

Linux is the version 1 execution platform. Each CLI-capable role runs in its
own rootless OCI container with private user, process, and mount namespaces, a
read-only root filesystem, no Linux capabilities, `no_new_privileges`, and a
pinned seccomp profile. Only the exact role root is writable. Runtime resources
are read-only, and the broker is available through one private Unix socket.
Project storage, formal storage, credentials, and other role roots are not
mounted. Network egress is absent or passes only through the broker-managed
allowlist proxy.

`RoleInvocationStart` freezes the executor-profile artifact and OCI image
manifest digest. The harness refuses to start a role when the realized
container differs from either binding. Another platform is unsupported until
an executor profile passes the same denial and escape tests. A broker alone is
sufficient only for an executor whose callable interfaces cannot access the
host filesystem, network, process table, environment secrets, command line, or
external storage.

The harness freezes a deterministic prepared context before the role starts.
The packing contract binds model capacity, tokenizer identity, token and byte
budgets, ordered items, omissions, frozen compactions, role profile, and
preference memory. Required and user-selected material either fits exactly,
uses an explicitly permitted frozen compaction, or causes preparation to fail.
No content is cut silently. The same budgets apply to later broker reads. The
broker supplies an authorized artifact whole or refuses it when its capability
limit or the remaining capacity would be exceeded.

At role closure, the harness seals a RoleContextSnapshot containing the
unchanged prepared context and the complete access ledger. Its digest is the
SHA-256 digest of the RFC 8785 canonical JSON object with snapshot_sha256
omitted. This digest identifies the ordered supplied inputs and ordered reads.

The outside reviewer receives one scientific artifact,
`p5.review_packet`. Its execution metadata follows a closed allowlist, project
preference memory is disabled, and on-demand project-artifact access is empty.

## Consequences

### Benefits

- Prompt injection or tool error cannot by itself grant broader storage access.
- Context overflow has an explicit and reproducible result.
- A later investigator can reconstruct every artifact supplied to or read by a
  role.
- Reviewer isolation is testable at both the broker and process boundaries.
- Model or tokenizer changes cannot silently alter a previously frozen context.

### Costs and risks

- The harness needs a capability broker and append-only access ledger.
- CLI-capable roles require Linux sandbox configuration and escape testing.
- Token counts must use the exact frozen tokenizer implementation.
- Frozen compaction requires its own versioned artifact and provenance.
- The system can reproduce inputs but cannot guarantee identical stochastic
  model output.

## Contract changes

- The role-context contract defines deterministic packing, context closure, and
  the storage enforcement boundary.
- A run role step binds the prepared-context digest before execution and the
  final RoleContextSnapshot digest after closure.
- Reviewer execution metadata uses a closed allowlist.

## Schema changes

- Add `role-context-snapshot.schema.json`.
- Add one valid closed-snapshot example with an immutable read ledger.

## Scenario changes

- Role-isolation tests attempt reads, writes, credential discovery, path escape,
  network escape, and process escape outside the declared capabilities.
- Capacity tests cover exact fit, explicit optional omission, permitted frozen
  compaction, preparation failure, and refusal of an oversized on-demand read.
- Reviewer tests reject every scientific input other than
  `p5.review_packet` and every metadata field outside the closed allowlist.
