Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Build on the validated preliminary implementation and evidence.
Design and execute a comprehensive empirical study that tests the
selected method across a wide range of conditions. The preliminary
run established the working implementation and validated it on a
simple test case — this run extends that foundation to publication
quality. Reuse the validated code; do not reimplement from scratch.
Pre-register the full experimental design before running simulations: target
distributions, evaluation metrics, parameter grid, ablation
studies, and stopping rules. Implement the method and all
baselines under identical conditions. Report convergence
diagnostics, effective sample sizes, wall-clock comparisons,
sensitivity to hyperparameters, and scaling behavior. Distinguish
clearly between findings that are robust across settings and
findings that depend on specific conditions. If the method
underperforms, diagnose why. The results should be fully
reproducible from the recorded code, seeds, and data.
