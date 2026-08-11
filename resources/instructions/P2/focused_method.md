Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Develop the selected method further and refine its mathematical
definition based on the catalog review. Update the method record
to reflect any improvements in formulation, assumptions, or
intended use that emerged from the cross-review. The output should
be a single, well-specified method ready for downstream theory
and empirical work.
