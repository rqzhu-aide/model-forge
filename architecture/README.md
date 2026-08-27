# Model Forge Architecture Specification

## Purpose

This directory is the normative architecture for the Model Forge implementation
in this repository. It is greenfield relative to the legacy
[Research Hub](https://github.com/rqzhu-aide/research-hub), which uses a different
storage and authority model.

Version 1 does not define legacy-project import, dual writing, or cutover from
Research Hub. Programmers must not create two sources of formal truth by
partially connecting the applications. Any later adoption path for existing
projects requires a separate accepted decision record, a one-way audited
importer, reconciliation tests, and a rollback boundary.

This boundary is recorded in
[ADR-006: Greenfield Boundary and Future Existing-Project Adoption](design/decisions/ADR-006-greenfield-boundary.md).
The one-time product and protocol identity change is recorded in
[ADR-010: Model Forge Product and Protocol Namespace](design/decisions/ADR-010-model-forge-namespace.md).

## Directory map

Human-facing documents are organized by their job:

- [design/](design/README.md) - the overview of the entire system from
  different angles: principles, domain model, harness, storage, UI contract,
  validation, traceability, role context, control commands, the decision
  records (ADRs), and the behavioral scenario catalog.
- [plan/](plan/README.md) - active implementation plans. A plan does not
  change an invariant, schema, phase contract, or acceptance scenario by
  itself; update the specification or decision record first.
- [issues/](issues/README.md) - living problem documents: the open-decisions
  memo and open audit findings.
- [archive/](archive/README.md) - completed and superseded records: the
  closed work programs, landed plans, and the completed-record index.

Machine-read specification assets stay at the top level because code and the
validator resolve them by fixed relative paths:

- `contracts/` - executable phase contracts (JSON) plus the generated
  registry (`phases.json`, built by `tools/build_contract_registry.py`).
- `phases/` - the prose half of the phase contracts; each contract JSON pins
  its prose file by the `prose_contract` path.
- `schemas/` - record, command, and example JSON schemas.
- `examples/` - golden and invalid example documents the validator folds and
  cross-checks.

For the machine-readable inventory: `schemas/` contains 47 machine-validatable schemas, while `examples/` contains 64 valid examples and 16 focused invalid fixtures.
- `evidence/` - the living audit trail: production verification records for
  completed gates. Individual records retire to `archive/` when superseded.
- `tools/` - the package validator and the contract registry builder.

## Reading order for a new contributor

1. [System principles](design/00-system-principles.md)
2. [Research domain model](design/01-research-domain-model.md)
3. [Run harness](design/02-run-harness.md) with the
   [supervised](design/02a-supervised-run-walkthrough.md) and
   [phase](design/02b-phase-run-walkthroughs.md) walkthroughs
4. [Storage and authority](design/03-storage-and-authority.md)
5. [Role context and communication](design/08-role-context-and-communication.md)
6. [Validation strategy](design/05-validation-strategy.md) and
   [contract traceability](design/07-contract-traceability.md)
7. [Open decisions memo](issues/open-decisions-memo-2026-08-25.md) for what
   is currently undecided

Every document change must keep `tools/validate_package.py` at exit 0.
