Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Reassess exactly the selected stable method ID. Do not add, merge, retire,
or alter another method. Compare the proposed result with the selected
current generation and classify it as no change, editorial change, or
mathematical change.

For no change, explain why no replacement record is warranted. For an
editorial change, preserve the stable ID, mathematical version, and
definition digest. For a mathematical change, preserve the stable ID,
identify every calculation-defining difference, advance the version by
exactly one, produce a new definition digest, and state which downstream
P3, P4, or P5 records require reassessment. A genuinely distinct alternative
may be recorded only as a recommendation for a future full-catalog run.
