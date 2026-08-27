# S13: Exact Role Setup Through Configuration

`scenario_id: s13.role_setup_configuration`

## Purpose

Verify that every role is defined exactly by configuration-managed assets
(SOUL, base configuration, recommended and custom skills, library guidance),
that an update never silently overwrites a customization, and that
provisioning is atomic with rollback.

## Contract under test

- ADR-012 items 3 and 4 (role assets and project state are separate; every
  invocation gets a private runtime profile): [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 2 and fixed rule 1 (configuration controls role
  identity): [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MF-61
  (configuration-managed role setup), MF-34 (exact role-profile freezing),
  MF-35 (missing assets block preparation), MF-38 (role definition and
  project-role state remain distinct objects). Invariants INV-003 and INV-012.

## Setup

- A fresh Model Forge data root with no role definitions.
- The Hermes executable and a base profile are installed.
- One role (research lead) has a customized SOUL or configuration file with a
  known digest, and a customized skill.

## Steps

1. Provision the research lead definition from the configuration interface:
   SOUL, base configuration, recommended skills, one custom skill, and
   library guidance.
2. Inspect the resulting role definition; verify every installed asset is
   reported with version, source, and digest, and customization status.
3. Request an update of a recommended skill whose files the researcher
   customized. The service must present the conflict and require an explicit
   user choice; it must not write over the customization.
4. Choose "keep customization" and verify the customized file is unchanged.
5. Repeat the update and choose the replacement; verify the asset is replaced
   atomically and the definition re-digests.
6. Inject a partial provisioning failure (for example an unavailable skill
   bundle) and verify the previous complete definition is restored.
7. Seal and launch one run; verify the run profile is an exact copy of the
   configured role assets and that no canonical role file changes during or
   after the run.

## Expected evidence

- All four role definitions can be created and inspected with exact installed
  assets.
- A conflicting update is blocked until an explicit user choice is recorded;
  no silent overwrite occurs.
- Provisioning is atomic: a partial failure rolls back to the previous
  definition and leaves no half-written role.
- The run profile digest matches the role definition; canonical SOUL,
  configuration, and skills are byte-identical after the run.
- Missing or invalid role files surface a clear status instead of a weakened
  role.

## Failure conditions

- An update overwrites a customization without an explicit user choice.
- Partial provisioning leaves a mixed definition.
- A run writes back to the canonical role definition.
- A missing skill or invalid role file silently weakens the role.
