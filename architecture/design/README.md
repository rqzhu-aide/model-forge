# Design

The overview of the entire system from different angles. These documents are
normative: code that disagrees with them is wrong, and changing them is a
specification change (validator must stay green).

## System documents

- [00-system-principles.md](00-system-principles.md) - the invariants every
  other document answers to.
- [01-research-domain-model.md](01-research-domain-model.md) - projects,
  methods, records, generations, phases.
- [02-run-harness.md](02-run-harness.md) - the execution harness.
- [02a-supervised-run-walkthrough.md](02a-supervised-run-walkthrough.md) and
  [02b-phase-run-walkthroughs.md](02b-phase-run-walkthroughs.md) - the run
  lifecycle walked end to end.
- [03-storage-and-authority.md](03-storage-and-authority.md) - content
  addressing, authority chain, receipts.
- [04-ui-contract.md](04-ui-contract.md) - the web UI's contract with the
  backend view models.
- [05-validation-strategy.md](05-validation-strategy.md) - structural vs
  scientific validation, gates, findings.
- [06-implementation-roadmap.md](06-implementation-roadmap.md) - build order
  from contracts outward; the execution program it cites is closed and
  archived.
- [07-contract-traceability.md](07-contract-traceability.md) - the MF rule
  registry binding spec statements to tests.
- [08-role-context-and-communication.md](08-role-context-and-communication.md) -
  role profiles, skills, memory, handoffs.
- [09-control-commands.md](09-control-commands.md) - user-issued control
  commands (start, cancel, correct).

## Subdirectories

- [decisions/](decisions/) - architecture decision records (ADR-001 through
  ADR-019 plus the template). Accepted decisions bind; changing one is a new
  ADR.
- [scenarios/](scenarios/) - the behavioral scenario catalog (S01-S31) the
  system is tested against.

## Related

- Phase-level design: `../phases/` (prose contracts) with the executable
  half in `../contracts/`.
- Forward-looking work lives in [../plan/](../plan/README.md); undecided
  questions in [../issues/](../issues/README.md).
