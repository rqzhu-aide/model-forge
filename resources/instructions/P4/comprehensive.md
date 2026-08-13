Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
This mode authorizes a self-contained, prespecified comprehensive evaluation of
the exact selected method. It may be the first empirical run or a later rerun;
a prior preliminary run is not required.

The phase-wide evidence standard is a claim-linked protocol fixed before
outcome inspection. Its authorized matrix covers justified distributions or
datasets, regimes, sample sizes, credible baselines, ablations, sensitivity,
robustness, and scaling. It also fixes the estimand, data or simulation unit,
matched tuning and compute budgets, metrics, repetitions and uncertainty,
multiplicity, stopping, leakage checks, decision thresholds, and falsification
rules.

Evidence is admissible only when exact method identity, implementation digest,
mathematical invariants, configuration, environment, code, data or simulation,
seeds, commands, diagnostics, and immutable outputs are traceable. Prespecified
fields remain fixed after outcomes are seen. Departures remain append-only
deviations, and unplanned analyses remain exploratory.

The final phase outcome states which conclusions hold across the evaluated
matrix, which remain conditional, and which are refuted or inconclusive. This
mode does not authorize an unselected follow-up run. The stage-role assignment
exclusively determines prespecification, execution, audit, and synthesis duties.

You are responsible for the scientific content of your output. The harness populates identity, provenance, timestamps, and digest fields automatically. Do not attempt to write these fields.
