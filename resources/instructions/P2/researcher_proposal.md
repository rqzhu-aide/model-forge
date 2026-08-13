Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Evaluate the single researcher-proposed method supplied in the frozen run
basis. Do not propose alternative methods. Use checks appropriate to the
method class and mark a check not applicable with a reason when necessary.

Assess: (1) whether the target and calculation are well-defined and the
assumptions support the intended claims; (2) whether the algorithm is
implementable, testable, and feasible under the project constraints; and
(3) whether the contribution is distinct from the closest formal Phase 1
sources and current catalog methods. Lack of coverage is not evidence of
novelty; create a literature-gap attention item when the basis is
insufficient.

Classify the outcome as viable now, viable after specified revision,
insufficient evidence, or not viable. Register a new method only when it is
viable now, sufficiently specified, and supported as distinct. Otherwise
state the smallest correction or evidence needed and do not fabricate a
complete method record.

You are responsible for the scientific content of your output. The harness populates identity, provenance, timestamps, and digest fields automatically. Do not attempt to write these fields.
