Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Propose a catalog of distinct feasible methods grounded in the
current literature. Each role brings a different perspective —
the resulting catalog should present genuinely different approaches
to the same question, giving the user a clear choice for
downstream phases. Do not select a method for the user — present
the options fairly.
