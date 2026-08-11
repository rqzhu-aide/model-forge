Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Develop the theoretical foundations for the selected method.
Derive the key mathematical properties: convergence, mixing time,
bias-variance tradeoffs, and any theoretical guarantees or
limitations. State assumptions precisely and prove or disprove
the central claims that determine whether the method works as
intended. Identify conditions under which the method succeeds
and conditions under which it fails. The output should be
rigorous enough to guide empirical implementation — the data
analyst should know exactly what to test. If the theory reveals
the method cannot work as hoped, state that clearly rather than
overstating results.
