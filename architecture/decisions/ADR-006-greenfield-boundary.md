# ADR-006: Greenfield Boundary and Future Existing-Project Adoption

## Status

Accepted.

## Context

Method Hub defines a new authority model based on immutable generations,
ordered authority events, rebuildable projections, sealed run manifests, and
typed commands. The legacy
[Research Hub](https://github.com/rqzhu-aide/research-hub) uses different
records, manifests, event semantics, and concurrency rules.

Partially connecting the two systems would create two possible sources of formal
truth for the same project. A developer could then observe different current
methods, evidence, or manuscripts depending on which system served the request.
That failure would be difficult to diagnose and scientifically unsafe.

The research decision is to treat this architecture as a new system. Version 1
must therefore state what it does not authorize, while leaving a disciplined path
for a later, separately reviewed adoption project.

## Invariants that must remain true

- One project has one formal source of truth at every point in time.
- Existing records cannot silently acquire new authority through file copying or
  partial indexing.
- Conversion cannot rewrite the scientific meaning, provenance, or immutable
  source basis of an existing record.
- A failed adoption attempt cannot leave a project partly governed by each
  authority model.

## Options considered

### Option A: Incremental dual writing

Write each change to Research Hub and Method Hub
during development.

This may appear gradual, but disagreement between the two writes creates an
undefined formal state. Rollback and reconciliation are not well defined.

### Option B: Include a legacy importer in version 1

Specify mappings from Research Hub projects while Method Hub is being built.

This would couple the greenfield domain model to implementation-specific legacy
records before the new model has passed its own acceptance scenarios. It would
also enlarge the first implementation milestone substantially.

### Option C: Keep version 1 greenfield and specify adoption separately

Build and validate the new system only for projects native to this architecture.
Require a later decision record and dedicated conversion package before any
existing project is adopted.

## Decision

Select Option C.

Version 1 defines no Research Hub project importer, dual writer, compatibility
bridge, or partial cutover. Research Hub and Method Hub may be developed or
operated separately, but they must not both claim formal authority for one
project.

Any future existing-project adoption requires a new accepted decision record and
an executable plan that defines:

- the exact source and target schemas;
- one-way field, identity, provenance, and authority mappings;
- unsupported or ambiguous source states and their user-visible disposition;
- a dry-run conversion report with no authority change;
- digest, count, dependency, and current-record reconciliation;
- the single transaction or explicit maintenance boundary that transfers
  authority;
- rollback behavior before that transfer and recovery behavior after it;
- acceptance scenarios using representative archived projects.

Schema upgrades among Method Hub versions are not legacy adoption.
They remain governed by the normal schema-migration rules.

## Consequences

### Benefits

- Programmers can implement one coherent authority model without hidden
  compatibility behavior.
- Researchers never face two competing current records for one project.
- A later adoption effort can be evaluated using actual new-system behavior and
  representative existing data.

### Costs and risks

- Research Hub projects cannot use Method Hub until a separate adoption package
  is designed and validated.
- The two repositories may require short-term development in isolated code paths.
- Future adoption will require explicit scientific mapping decisions rather than
  a generic file migration.

## Contract changes

- The architecture entry point and roadmap state the greenfield boundary.
- No phase contract accepts a legacy record as an implicit input.
- A future adoption proposal must add its own contracts and reconciliation
  scenarios rather than weakening native phase contracts.

## Schema changes

None in version 1. A future importer must define separate source-mapping and
conversion-receipt schemas.

## Scenario changes

None in the native research workflow. Future adoption requires dedicated dry-run,
cutover, reconciliation, failure, and rollback scenarios.
