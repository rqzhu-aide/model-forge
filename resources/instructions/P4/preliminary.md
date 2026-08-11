Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Design and execute empirical studies that test the selected
method against the relevant baseline. Pre-register the
experimental design before running simulations: target
distributions, evaluation metrics, parameter grid, and
stopping rules. Implement the method and the baseline under
identical conditions. Report convergence diagnostics, effective
sample sizes, wall-clock comparisons, and sensitivity to
hyperparameters. Distinguish clearly between findings that are
robust across settings and findings that depend on specific
conditions. If the method underperforms, diagnose why. The
results should be reproducible from the recorded code, seeds,
and data.
