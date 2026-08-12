Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Build an auditable catalog change set grounded in the current formal
literature basis and current catalog. Deliberately search across
mechanism-level alternatives, including changes to the target, model or
representation, inferential principle, objective, algorithm, or structural
assumptions. Treat options as distinct only when their calculations or
scientific implications differ materially from the current catalog. The
roles should search from complementary scientific, mathematical, and
empirical perspectives rather than independently reproducing the same
conventional idea.

Seek a balanced set of defensible options: the strongest existing baseline
or conservative extension, complementary moderate-risk directions, and a
credible high-risk, high-value direction when evidence supports one. This
is not a quota. Validity, relevance, and feasibility take priority over
novelty. Do not claim novelty from absence in the current catalog alone,
and allow a documented conclusion that no genuinely useful new option was
found.

For every candidate, state the target, authoritative mathematical
definition, assumptions, intended scope, closest prior work, contribution
boundary, mechanism-level difference, why that difference could matter,
falsifiable advantage, decisive downstream investigation, and principal
theoretical, empirical, and computational risks. Compare options under the
stated decision criteria. You may identify dominated or nonviable options,
but do not choose a P3 or P4 branch for the user.
