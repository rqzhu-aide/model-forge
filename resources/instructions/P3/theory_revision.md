Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Revise and strengthen the established theory for the selected
method. The prior establishment run produced a complete theory
record; this run refines it. Address specific gaps identified
in the analyst audit: mend incomplete proofs, tighten assumptions,
close boundary cases, and resolve any identifiability or
testability concerns. Where the audit or subsequent reflection
suggests stronger results are achievable, explore those stronger
claims — tighter convergence rates, broader applicability, or
sharper guarantees. If any prior claim cannot be salvaged,
state that clearly and adjust the theoretical position. The
output should be a revised theory record that is strictly
stronger or more complete than the one it replaces.
