# ADR-003: Deterministic Digest Contracts

## Status

Accepted

## Context

Model Forge uses digests for immutable records, commands, manifests, method
identity, authority events, and replay projections. Ordinary key-sorted JSON is
not a cross-language canonicalization standard. Number formatting, Unicode key
ordering, and escaping can differ between implementations even when the parsed
scientific object is the same.

Method identity has a second risk. Hashing a Markdown artifact makes an
expository edit appear to change the calculation. Hashing an incompletely
specified subset can miss a real change to the estimand, equation, algorithm,
constraint, tuning rule, or defining assumption.

## Invariants that must remain true

- The same supported JSON value produces identical digest bytes in every
  conforming implementation.
- An implementation never guesses how to hash an unregistered object.
- Unsupported numbers, invalid Unicode, and malformed JSON fail before a digest
  is accepted.
- Calculation-changing revisions change exact method identity.
- Exposition-only revisions preserve exact method identity while remaining
  distinguishable as new artifacts and whole records.

## Options considered

### Option A: Implementation-defined sorted JSON

Each service sorts object keys and uses its language's default JSON number and
string serializer. The method digest is the hash of the displayed definition
artifact.

This is simple but does not define interoperable bytes. It also couples method
identity to document layout and prose.

### Option B: RFC 8785 with registered payloads

Use RFC 8785 for every hashed JSON preimage. Maintain a machine-readable
registry that identifies each digest location, exact payload subtree or included-field projection, excluded
fields, and non-JSON construction. Define one complete structured mathematical
payload for method identity, separate from its presentation artifact.

## Decision

Select Option B. `contracts/digest-contracts.json` is the authoritative digest
registry. A persisted JSON digest is valid only when a registry entry identifies
its construction. RFC 8785 and SHA-256 are normative for JSON payloads.

New top-level structured-object self-digests use the canonical field names
`content_sha256`, `manifest_sha256`, `prepared_context_sha256`,
`snapshot_sha256`, `start_sha256`, `closure_sha256`, or
`submission_sha256`. The package validator derives required registry coverage
from those schema fields and from the three named root-chain fields. A new
nested or custom digest producer requires an explicit registry entry, focused
validator rule, and architecture decision; it cannot rely only on the manually
listed contract IDs.

The bundled Python reference is intentionally restricted to integers in the
closed interval $[-(2^{53}-1), 2^{53}-1]$. It rejects floating-point values and
integers outside that interval until a separately tested ECMAScript-compatible
binary64 serializer is provided. Production implementations may use a complete
RFC 8785 library, but they must pass the fixed interoperability vectors.

`definition_sha256` hashes only
`mathematical_definition.canonical_definition`. That payload contains the
definition schema version, target or estimand, objective or estimating equation,
ordered algorithm, constraints, normalization, tuning definitions, and
calculation-defining assumptions. Artifact pointers, locators, summaries, and
other exposition remain outside it and inside the whole method-record digest.

## Consequences

### Benefits

- Digests have one reviewable payload contract rather than scattered implicit
  exclusions.
- Unicode ordering and supported numeric serialization are testable across
  languages.
- A restricted implementation fails closed instead of writing plausible but
  incompatible hashes.
- Method identity follows the calculation rather than the presentation.
- Editorial method generations remain auditable through artifact and
  whole-record digests.

### Costs and risks

- Every digest-writing implementation needs an RFC 8785 implementation and must
  pass the shared vectors.
- Floating-point JSON cannot be hashed by the bundled Python reference. It must
  be encoded by a fully conforming implementation or rejected.
- A change to a registered payload or exclusion rule changes persisted meaning
  and requires a new ADR and migration rule.
- Structured mathematical strings remain exact content. Producers must review
  notation and code points before sealing them.

## Contract changes

- The research domain model defines the exact method-identity payload.
- Storage and authority requires registry resolution, RFC 8785, SHA-256, and
  fail-closed numeric behavior.
- MF-57 tracks implementation of the registry and interoperability tests.

## Schema changes

- `digest-contract-registry.schema.json` validates the registry.
- `digest-vectors.schema.json` validates accepted and rejected reference vectors.
- `method.schema.json` requires the complete canonical mathematical payload.
- `method-exposition-revision.schema.json` validates the editorial-revision test
  vector.

## Scenario changes

- Fixed Unicode and safe-integer vectors verify cross-language canonical bytes.
- Rejected vectors verify that unsupported binary64 and unsafe-integer inputs
  fail closed.
- The method exposition vector constructs a schema-valid successor generation
  with the same method identity and different artifact and whole-record digests.
