Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
This mode establishes the current theory account for the authorized scope of
the exact selected method. Its scientific scope is the formal target or
estimand, the method class, and only properties meaningful for that class, such
as identifiability, finite-sample risk, asymptotic behavior, optimization
convergence, mixing, calibration, or robustness. Irrelevant properties remain
out of scope rather than becoming forced generic claims.

Within this fixed method identity, the phase actively seeks theory that adds
scientific understanding. Relevant directions include a new theorem or exact
conceptual connection, an alternative proof strategy, a sharp rate or lower
bound, an impossibility result, an informative boundary or failure regime, and
a testable conjecture. The research question determines which directions are
worth pursuing; novelty is not a license to accumulate weak claims.

Across the phase, an established formal claim requires a proof or derivation
artifact tied to exact assumptions, quantifiers, regime, and dependencies. A
failed claim is recorded with a counterexample when available. Anything not
resolved remains an explicit open obligation. Material claims and sensitive
assumptions retain empirical implications with observable metrics, expected
patterns, and falsifying results. No role may invent a proof step or strengthen
a statement beyond its support. A conjecture is recorded as an open question with
untested or incomplete status, explicit assumptions, a falsifier, and a proof
obligation; it is never reported as an established result.

If an innovative direction changes a calculation-defining component of the
selected method, the phase records it only as a proposed Phase 2 revision and
leaves the current method identity unchanged. The user decides whether to
authorize that revision and a later Phase 3 run.

The final phase outcome is a complete theory account for the declared scope,
with exact definitions, assumptions, statements, support, limitations, and
open obligations. It may be positive, negative, mixed, or inconclusive.
Completeness does not claim to exhaust every possible property. This mode does
not authorize another method, branch, or run. The stage-role assignment
exclusively determines who constructs, audits, and reconciles the artifacts.

You are responsible for the scientific content of your output. The harness populates identity, provenance, timestamps, and digest fields automatically. Do not attempt to write these fields.
