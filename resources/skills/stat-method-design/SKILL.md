---
name: stat-method-design
description: Method construction for computational statistics — deriving a new procedure from stated desiderata with an explicit mechanism and falsifiable predictions. Use when proposing a method, writing or revising a method definition, checking that a candidate method is actually new relative to the literature, or stress-testing a design before theory or simulation work begins.
---

# Method Design

A method is not an idea; it is a procedure with a mechanism. Design work is
done when the procedure is specified exactly enough that a stranger could
implement it, the mechanism says precisely why it should help, and the
predictions are stated sharply enough that the theory and the simulations
can each prove them false.

## Procedure

1. **State the desiderata first.** What must the method achieve (the target
   property), under what constraints (equal cost, same information, same
   guarantees), and relative to what baseline? A desideratum without a
   baseline is a wish.
2. **Construct from the mechanism, not toward it.** Name the phenomenon the
   method exploits (variance cancellation, information sharing, curvature
   matching) and derive the procedure so that the phenomenon does the work.
   If the construction does not route through the mechanism, the mechanism
   is decoration.
3. **Specify the procedure completely.** Update equations, tuning
   parameters with their roles, initialization, stopping rule. Ambiguity at
   this stage becomes silent divergence between the theory object and the
   simulated object later.
4. **Predict before testing.** Write the falsifiable predictions the design
   makes: where it must win, where it must not hurt, and the regime where
   the mechanism says it degenerates. These predictions are the contract
   the theory phase and the empirical phase are each paid to check.
5. **Differentiate from the nearest neighbors.** For each of the two or
   three closest existing methods, state the exact point of departure and
   what it buys. "Ours is more general" without the departure point named
   is marketing.

## Failure modes to check before handing off

- The method needs information the setting does not provide (an oracle in
  disguise).
- The equal-cost accounting is wrong: the method spends more per effective
  sample than the baseline.
- The mechanism's regime of validity is narrower than the intended
  application — say so, and narrow the claim, not the experiment.

## Output discipline

The method definition record carries: desiderata with baselines, the exact
procedure, the mechanism statement, the prediction list, and the nearest-
neighbor differentiation. Each downstream phase reads all five; an
incomplete record sends the design back, not forward.
