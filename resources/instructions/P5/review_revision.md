Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Revise the manuscript based on the review feedback. Address each
reviewer point substantively — either by changing the manuscript
or by providing a reasoned rebuttal. Track all changes and
ensure the final manuscript is internally consistent, correctly
references all proofs and experiments, and meets the standards
of the target venue. The output should be a submission-ready
manuscript with a clear response-to-reviewers document.
