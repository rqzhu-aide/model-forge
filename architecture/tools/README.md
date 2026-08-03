# Architecture validation tools

After changing a split phase contract, rebuild the aggregate:

```text
python architecture/tools/build_contract_registry.py
```

Then run the package validator from the repository root:

```text
python architecture/tools/validate_package.py
```

`jcs.py` is the fail-closed RFC 8785 reference used by the validator. Its
supported numeric subset is deliberately narrower than normative RFC 8785, so
unsupported values are rejected before hashing.

The current validator checks:

- 37 valid JSON Schema Draft 2020-12 definitions;
- 57 complete valid examples and 16 rejected negative fixtures;
- exact registration of every positive and negative fixture file;
- agreement between advertised package counts and the filesystem, complete schema
  inventory in `schemas/README.md`, and complete accepted-decision inventory in
  `decisions/README.md`;
- the exact expected rejection for every negative fixture, including JSON
  Pointer and validator diagnostics for schema cases and the named prior-state
  failure for the semantic replay case;
- exact equality between the five split phase contracts and `phases.json`;
- independent schema validation of every split phase contract and contiguous
  per-mode stage sequences;
- exact traceability across `INV-001` through `INV-022`, `IT-001` through
  `IT-022`, `MH-01` through `MH-60`, all 12 scenario documents, phase acceptance
  lists, and `M0` through `M9`;
- local Markdown links, forbidden long dash characters, trailing whitespace, and
  unambiguous RFC 8785 wording in schema descriptions;
- fixed phase modes, role order, stage reads and writes, prepared contexts, and
  user-controlled history;
- itemwise validation for collection outputs and exact publication coverage for
  canonical records and cumulative objects;
- one lead attention collection and one append binding in every phase;
- Phase 1 literature append, Phase 2 method upsert, Phase 4 evidence append, and
  Phase 5 review-issue append plus deterministic ledger rebuild;
- publisher prohibition on creating scientific content;
- exact command-to-contract resolution for all eight modes, both Phase 1 search
  scopes, typed required and optional choices, and focused Phase 2 method
  identity;
- exact command-to-manifest equality for the contract identity, selected mode,
  `choice_values`, context policy, and resource limits;
- shared network-policy vocabulary and no-broadening checks for `none`,
  `approved_resources`, and `user_authorized`;
- the machine-readable digest registry, fixed Unicode and numeric RFC 8785
  vectors, and fail-closed unsupported-number behavior;
- exact method-definition hashing plus an exposition-only successor with
  unchanged method identity and changed artifact and whole-record digests;
- canonical run-command, split-contract, manifest, role-plan-entry, cancellation,
  delegation, prepared-context, invocation-start, invocation-closure,
  run-submission, role-context, control-command, publication-receipt, and
  command-attempt-audit content and root digests;
- exact referenced-byte digests for raw command-request artifacts;
- every manifest publication binding, output mapping, formal reducer input,
  named bundle component, and target;
- focused in-memory `INV-020` mutation probes for missing, duplicate,
  mode-inapplicable, and wrong current-slot publication bindings. These semantic
  probes mutate the coherent transaction instead of maintaining large duplicate
  fixture files;
- all role-produced outputs under unique role write roots;
- exact rootless OCI executor binding with private user, process, and mount
  namespaces, read-only root filesystem, no capabilities, no-new-privileges,
  pinned seccomp, one writable role root, broker socket, and declared egress;
- one fully instantiated data-analyst profile and immutable profile artifacts for
  every other role step. It does not claim to validate profile content that is
  not instantiated in the example set;
- role-context capacity and identity accounting, deterministic packing,
  preference-memory binding, on-demand access-ledger closure, and the outside
  reviewer's closed context boundary;
- prepared-context projection continuity, exact manifest-role-plan copying into
  invocation starts, start-to-closure continuity, accepted output and handoff
  verification, and exact downstream successful-closure bindings;
- complete ordered `RunSubmission` closure and artifact coverage, final lead
  closure, exact RunState submission binding, and pre-submission cancellation
  exclusion;
- Phase 5 reviewer isolation and distinct theorist, analyst, and outside-reviewer
  frozen read sets;
- canonical immutable-object, authority-event, record-state, and current-index
  hashes;
- binary authority-event root chaining across the complete six-event receipt
  range;
- receipt accounting for every record change, cumulative object,
  derived-state-only change, authority event, projection digest, and current-index
  replacement;
- exact publication-receipt source binding to the command, run, manifest, and
  immutable `RunSubmission`, plus verified receipt self-digests;
- ordered whole-field event folding for the five Phase 4 state projections;
- checkpoint-seeded subject-history validation that reserves the no-prior full
  evidence form for a genuinely new subject;
- an independent two-event replay vector that carries earlier publication fields
  forward, replaces a later alignment field, verifies the intermediate-state
  digest, and accounts for state-only events;
- deterministic reconstruction of five record or evidence state projections and
  four current-index slots at the final event root;
- resolution of every formal attention reference to a receipt-published immutable
  attention-item version;
- contiguous, uniquely identified, time-ordered run-state events, legal lifecycle
  transitions, canonical event hashes, and final journal-root agreement;
- the cancellation command, its hash-chained `cancellation_requested` journal,
  and the cancellation-versus-immutable-submission boundary;
- all five typed action-descriptor branches, their strict family isolation, and
  the shared command-error envelope;
- exact schema-enforced error-code policy mapping, including category, HTTP
  status, retryability, and violated requirement;
- append-only operational command-audit sequence, RFC 8785 content and binary
  root digests, exact raw-request byte hashes, authorization parity, stable
  embedded errors, and digest-bound durable effects;
- delegation-grant and revocation linkage, action and target scope, and validity
  windows;
- both formal control commands against their specific schemas and the
  `ControlCommand` union;
- exact concurrency heads, legal lifecycle or withdrawal preconditions, and
  absence of research-run fields from formal control commands;
- in-memory method-lifecycle and withdrawal receipt probes against the
  discriminated receipt source and transaction-effect constraints;
- lifecycle method lineage with exact predecessor generation and unchanged method
  identity;
- registration and traceability of S12 disjoint-target publication success and
  same-target optimistic-concurrency rejection.
Passing these checks establishes representation, authority, provenance, and
research-workflow consistency. It does not establish scientific truth.
