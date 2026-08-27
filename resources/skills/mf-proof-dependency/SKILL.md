---
name: mf-proof-dependency
description: Dependency mapping for formal theory accounts — theorems, lemmas, assumptions, and proofs. Use when establishing or revising a theory record, auditing which assumptions each result actually needs, checking that proof steps discharge their dependencies, or tracing a claim to its minimal assumption set.
---

# Proof Dependency Analysis

Every formal result carries an implicit dependency set: the assumptions,
definitions, and earlier results its proof actually uses. Making that set
explicit is what separates a trustworthy theory account from a plausible one.

## Procedure

1. **List results in dependency order.** Definitions first, then lemmas,
   then theorems, then corollaries. Each entry names its statement in one
   line.
2. **Annotate each proof with its used premises.** For every proof step,
   record which assumptions, definitions, and prior results it invokes. A
   step that invokes nothing new is prose, not a proof obligation — compress
   it.
3. **Compute the minimal assumption set per theorem.** An assumption that no
   proof path reaches is decorative: remove it from the theorem's statement
   or prove that it is necessary (a counterexample without it).
4. **Check for circularity.** The dependency graph must be acyclic. A lemma
   whose proof cites a downstream corollary is a defect, not a style issue.
5. **Stress each assumption.** For every assumption in the minimal set,
   state whether it is standard (cite), mild (argue plausibility), or strong
   (flag as a limitation and consider a conditional statement of the
   result).

## Revision discipline

When revising a theory account, repair gaps statement by statement: weaken,
narrow, condition, or retract — never silently patch. Every changed
statement gets a fresh dependency pass; a repaired lemma can invalidate
downstream minimal sets.

## Output discipline

The theory record's claim list must name, for each formal claim, the exact
assumptions and prior results it depends on. If two claims share a proof
skeleton but differ in one premise, say so explicitly — that difference is
usually the scientifically interesting part.
