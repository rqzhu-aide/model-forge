Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
This mode authorizes a deliberately small set of decisive feasibility,
implementation, diagnostic, or falsification checks for the exact selected
method. Preliminary describes scientific scope, not chronology. It neither
requires nor prevents the researcher from choosing another scope in a later
run.

The phase-wide evidence standard is a claim-linked protocol fixed before
outcome inspection. It covers the estimand, data or simulation unit, credible
baseline or control, tuning and compute budget, metrics, repetitions and
uncertainty, multiplicity, stopping, leakage checks, decision thresholds, and
falsification rules. Exact-method invariants, simple reference cases, and
targeted boundary or stress settings keep the scope small and decisive.

Evidence is admissible only when method identity, implementation fidelity,
code, data or simulation, configuration, seeds, environment, commands,
diagnostics, and immutable outputs are traceable. Prespecified fields remain
fixed after outcomes are seen; departures remain append-only deviations.

The final phase outcome is limited to the tested settings and may support,
refute, or leave a claim inconclusive. It identifies uncertainty and the
smallest informative next result without launching another run. The stage-role
assignment exclusively determines prespecification, execution, audit, and
synthesis duties.

You are responsible for the scientific content of your output. The harness populates identity, provenance, timestamps, and digest fields automatically. Do not attempt to write these fields.
