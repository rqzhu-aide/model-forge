# S01: First Project Through P1 and P2

## Purpose

Verify the first cumulative literature record and first method catalog.

## Initial state

- Project exists with a research brief.
- No formal literature record or method catalog exists.
- No run is active.

## User action

The user launches `p1.literature_update` with instructions, optional source
context, and `p1.scope` set to `broad_update` or `focused_update`. Run this
scenario once for each scope value.

## Expected behavior

1. The command binds the exact Phase 1 contract and preserves the selected scope,
   instruction, and history under their phase-specific choice IDs.
2. The harness freezes the brief, user instruction, and selected context.
3. Lead, theorist, and analyst perform role-specific discovery in parallel.
4. The lead synthesizes the candidate sources and literature assessment.
5. All outputs remain in the P1 run folder until validation.
6. Validation checks source identities, card structure, synthesis presence, and
   decision and handoff records.
7. Promotion creates the first formal literature collection and synthesis.
8. The UI reports the current evidence base, coverage gaps, and user options.

The user then launches P2 in full-catalog mode.

1. The exact P1 collection and synthesis are frozen.
2. The research roles generate independent ideas and cross-review them.
3. The lead publishes a method catalog but does not select a downstream method.
4. Promotion creates permanent method IDs and formal method records.
5. The UI lists methods and lets the user decide whether to rerun P2 or select a
   method in P3 or P4.

## Prohibited behavior

- P1 does not launch P2.
- Both Phase 1 scope values resolve to one mode; no second generic scope field is
  accepted.
- Agents do not write directly to formal literature or method paths.
- P2 does not choose a method for P3 or P4.
- Formal records do not appear before validation succeeds.
