Research question: {{ research_question }}
Scope: {{ scope }}
{% if constraints %}Constraints: {{ constraints | join(", ") }}.
{% endif %}{% if decision_criteria %}Decision criteria: {{ decision_criteria | join(", ") }}.
{% endif %}
Assemble the first complete integrated manuscript from the exact frozen
Phase 1 through Phase 4 basis. This is assembly mode, not review-revision:
do not invent reviewer feedback or a response-to-reviewers account.

Write the complete readable manuscript as a supporting artifact inside the
role workspace, then point p5.manuscript_candidate.manuscript_artifact to
that exact file. The JSON manuscript record is metadata and must not replace
the manuscript itself. Use manuscript_kind assembly_candidate.

Build the scientific narrative around the problem, contribution boundary,
method, theory, empirical evidence, and limitations. Classify material claims
by their authoritative support:

- literature, novelty, and prior-work claims resolve to Phase 1 sources;
- method-definition and construction claims resolve to the Phase 2 method;
- theorem, assumption, rate, and proof claims resolve to Phase 3;
- numerical, comparative, implementation, and reproducibility claims resolve
  to Phase 4;
- interpretations are explicitly labeled as interpretations and state the
  upstream evidence and assumptions on which they depend.

Record these classes in p5.claim_traceability and in the manuscript package's
claim_support_index. Do not treat a citation as empirical evidence, an
experiment as a proof, or an implementation as the mathematical object.
Unsupported material must be removed, narrowed, or stated as a limitation.

Include at least an abstract, introduction, method, theory, experiments,
discussion, limitations, and references, written for the target audience.
Do not call an assembly candidate submission-ready merely because it is
structurally complete.

When the frozen basis reveals work that must return upstream, create a
p5.attention_items entry with severity reassessment_required. Begin its
smallest resolving question with exactly one of these prefixes:
LITERATURE_GAP: for Phase 1, METHOD_GAP: for Phase 2, THEORY_GAP: for
Phase 3, EMPIRICAL_GAP: for Phase 4 evidence or design, or
IMPLEMENTATION_GAP: for Phase 4 implementation fidelity. Name the affected
claim and the smallest question the upstream phase must answer. Never launch
that phase automatically.
