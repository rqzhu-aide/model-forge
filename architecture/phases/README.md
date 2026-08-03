# Phase Contracts

This directory defines the scientific and operational contract for each phase of the research pipeline. These contracts are written for a new system. They do not describe or preserve the behavior of the existing implementation.

The five phase contracts use the same section structure so that researchers, programmers, and test authors can compare them directly:

1. Purpose
2. User choices
3. Prerequisites
4. Frozen inputs
5. Role order
6. Run-local outputs
7. Machine validation
8. Scientific assessment boundary
9. Promotion rule
10. Formal current record
11. Invalidation effects
12. UI projection
13. Acceptance criteria

## How to use these contracts

Each prose phase contract defines scientific meaning. The matching executable contract under `../contracts/` defines deterministic choices, inputs, role plans, outputs, validators, publication rules, and UI sources. Schemas define persisted shapes, and acceptance tests prove that the implementation follows both representations.

For any proposed implementation:

- Start from the user choices and prerequisites.
- Prepare an immutable run basis from the frozen inputs.
- Execute only the stated roles and role order.
- Permit each role to write only inside its unique role root, then let the harness materialize verified shared outputs.
- Apply machine validation before promotion.
- Promote only through the mode-scoped source-to-target bindings named in the executable contract.
- Derive the Web UI from the formal current records, not from folder existence or free-form prose.
- Test every acceptance criterion, including failure and recovery behavior.

## Rules shared by every phase

- Only the user starts a run or rerun.
- A phase becoming available never starts it automatically.
- Current formal records are loaded by default.
- Historical records are loaded only when the user selects them or a phase contract explicitly requires a fixed historical object.
- The system freezes all selected inputs before role work begins.
- Agents write only within the active run workspace.
- Validation and promotion are system operations, not agent privileges.
- A failed, interrupted, or rejected run cannot replace a valid current record.
- Promotion is atomic. Readers see either the previous complete record or the new complete record.
- Scientific status is separate from authority status. A current record can report a negative, partial, or inconclusive result.
- The lead summarizes evidence and options, but does not choose the next phase or method for the user.
- Stable attention items are formal cumulative objects; run-local notes do not become unresolved project state by folder presence.

## Phase map

| Phase | Scientific responsibility | Update behavior | Primary user decision enabled |
|---|---|---|---|
| [Phase 1](phase-1.md) | Build and maintain the literature basis | Cumulative reference library with a replaceable current synthesis | Whether the literature basis is sufficient or needs a focused update |
| [Phase 2](phase-2.md) | Develop and maintain feasible methods | Full-catalog or focused-method update | Which methods merit later theoretical or empirical work |
| [Phase 3](phase-3.md) | Establish the current theoretical account for one method | Replace the complete current theory record | Whether the theoretical claims and limitations justify further work |
| [Phase 4](phase-4.md) | Build the empirical evidence base for one method | Cumulative immutable evidence with atomically replaced current evidence index, empirical synthesis, implementation record, and phase decision | What the evidence supports and what should be examined next |
| [Phase 5](phase-5.md) | Assemble or revise the current manuscript | Replace the complete current manuscript | Whether to revise, return upstream, defer, or prepare for submission |

## What these contracts do not define

These files do not define JSON field syntax, database technology, queue implementation, UI styling, or agent prompt wording. Those belong in the domain schemas, harness specification, UI contract, and role instruction packages. Phase contracts define the required scientific behavior that those components must implement together.
