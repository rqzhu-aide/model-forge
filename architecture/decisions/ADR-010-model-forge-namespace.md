# ADR-010: Model Forge Product and Protocol Namespace

## Status

Accepted.

## Context

The greenfield implementation was developed inside the Research Hub repository
with temporary Model Forge predecessor names in its Python package, command,
environment, local storage, Web application, schemas, and invariant registry.
Model Forge now has an independent repository and has not released a production
record format.

Publishing the new repository with mixed identities would make package imports,
configuration, schema references, audit records, and formal protocol objects
appear to belong to the legacy application. Keeping aliases would also create a
compatibility obligation before there is a production release to preserve.

## Options considered

### Option A: Rename only user-facing text

Keep the old package, schema, environment, and invariant identifiers while
displaying “Model Forge” in the Web interface.

This is a small edit, but it creates two product identities and makes persisted
protocol objects misleading.

### Option B: Retain aliases for both namespaces

Accept both old and new commands, environment variables, schema identifiers, and
package imports.

This may ease local development, but it creates an unnecessary compatibility
surface and allows two names for one formal representation.

### Option C: Apply one atomic pre-release namespace change

Rename every product and protocol surface before the first Model Forge release
and provide no automatic compatibility alias.

## Decision

Select Option C.

The canonical version 1 identities are:

- product and repository: Model Forge and `rqzhu-aide/model-forge`;
- Python distribution and command: `model-forge`;
- Python package: `model_forge`;
- Web package: `model-forge-web`;
- environment prefix: `MODEL_FORGE_`;
- default local data root: `~/.model-forge`;
- schema base: `https://model-forge.local/architecture/schemas/`;
- invariant IDs: `MF-01` through `MF-60`;
- internal class prefix: `ModelForge`;
- persisted protocol literals and orchestration identities: `model-forge.*`.

The legacy application remains Research Hub at `rqzhu-aide/research-hub`.
Model Forge code must not add fallback imports, environment aliases, or shared
data-root behavior unless a later accepted migration decision requires them.

## Consequences

### Benefits

- Public, code, configuration, and protocol identities agree.
- A schema or audit object can be attributed to Model Forge without inference.
- The first production release begins without avoidable compatibility debt.
- Search-based checks can detect accidental legacy identity reintroduction.

### Costs and risks

- Existing pre-release local Model Forge development data is not discovered at
  the old data root.
- Local scripts using the old command, import, or environment names must change.
- Every schema reference, digest vector, example, test, and generated registry
  must change in one commit.

These costs are accepted because no production Model Forge release or supported
project migration exists.

## Contract changes

Scientific phase behavior, role order, storage semantics, and user control do
not change. Traceability references use `MH-*` instead of `RH-*`. Persisted
Model Forge protocol literals use the new namespace.

## Schema changes

Every schema `$id` and internal `$ref` uses the Model Forge schema base. Schema
versions remain `1.0.0` because represented scientific meaning does not change
and there is no released Model Forge instance to migrate.

## Scenario changes

Scenario behavior and IDs do not change. Package validation, backend tests,
frontend tests, and a repository-wide legacy-identifier scan must pass in the
same change.
