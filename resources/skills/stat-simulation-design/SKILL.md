---
name: stat-simulation-design
description: Simulation study design for evaluating statistical methods — data-generating processes, estimands, equal-cost baselines, replicates and seeds, and honest variance reporting. Use when planning an empirical evaluation, checking that a comparison is fair at equal computational cost, sizing a study within an iteration budget, or writing the empirical record so every number can be regenerated.
---

# Simulation Design

A simulation study is an experiment, and it is judged like one: the question
is fixed in advance, the comparison is fair, the budget is accounted, and
every reported number can be regenerated bit-for-bit.

## Procedure

1. **Fix the estimands before the DGPs.** What quantity does each number
   estimate (variance ratio at equal cost, bias, coverage, wall-clock)?
   The estimand decides the design, never the other way around.
2. **Design the baseline comparison as equal-cost.** Define cost precisely
   (gradient evaluations, wall-clock, effective samples) and hold it fixed
   across arms. A comparison at unequal cost answers a question nobody
   asked. Report the measured cost of every arm, not the intended cost.
3. **Choose DGPs that span the mechanism's regimes.** At minimum: a regime
   where the method must win (its mechanism is active), one where it must
   not hurt (mechanism neutral), and one where it may degenerate (mechanism
   breaks). A study that only samples friendly regimes is an advertisement.
4. **Size replicates from the variance of the comparison.** The Monte Carlo
   error on the reported ratio must be small relative to the effect being
   claimed. State the replicate count, the per-replicate cost, and the
   total budget against the iteration allowance before running; if the
   budget cannot support the precision, narrow the claim, not the standard
   error.
5. **Pin the randomness.** Every arm, every replicate: recorded seed.
   Shared seeds across arms reduce comparison variance and must be declared;
   independent seeds are the honest default when sharing is not justified.

## Reporting discipline

Report point estimates with Monte Carlo standard errors, the measured cost
per arm, and the regeneration recipe (code version, seeds, environment).
A table without standard errors is a mood. If an arm fails or diverges,
it is reported as a failure with its frequency — never deleted.

## Output discipline

The empirical record separates: the design (estimands, DGPs, arms, budget,
seeds), the raw measurements, and the derived comparisons. A reader must be
able to recompute every derived number from the raw ones, and to regenerate
the raw ones from the design.
