# E-2e Plan: P2 canonical_artifact pointers made real (2026-08-23)

Status: PLANNED (Tez approved 2026-08-23 as item 6b, "planned package,
not a hotfix"). Parent program: e2-information-layers-plan-2026-08-22.md.

## Problem (evidence: k5-production-re-run-2026-08-23.md, "New residual")

The P2 method record's REQUIRED
`mathematical_definition.canonical_artifact` (an artifactPointer, per
method.schema.json) is agent-authored with no harness support: the lead
cannot know sealed digests, so it invents them. Verified live on run
`run.p2.p2-full-catalog.e13a6b3761684126af5729794be9262e`:

- SGEL: `artifact://theory_proposal/p2/theory-proposal.json` claims
  sha256 7b17e46c... - present nowhere in the artifact store or the
  artifacts table (the run's sealed p2.theory_proposal is 63f8e7ae...).
- AREL: `generation://...` claims ff076ea6... - the target generation's
  real content_sha256 is d3c6ff99....

Same failure class as the E-2c residual gap that E-2d closed for P1/P3
primary_artifact pointers. E-2d's stamping + validation covers the
coverage/theory/analyst call sites only; no P2 call site validates
canonical_artifact, so policy 1.11.0 passes invented pointers.

## Acceptance (one sentence)

P2 method records' canonical_artifact pointers are closure-stamped to
hash-verified sealed bytes, and unstamped or degenerate pointers fail
validation as correctable `p2.canonical_pointer_invalid`.

## Verified code facts (probed 2026-08-23 on 1f0b240)

- Repair pass: `_apply_disclosed_mechanical_repairs`
  (src/method_hub/harness/role_execution.py:62) runs per closure BEFORE
  structural validation; `_fix_self_referential_hashes` (line 744)
  recurses into nested record arrays including the method-changes list,
  and already stamps `identity.definition_sha256` on method records
  (case 3, line 806).
- run_root at the repair call site (line 2402) is the RUN directory
  (`workspace.for_read(f"runs/{run_id}")`); output path =
  run_root / spec.relative_path = roles/<NN>-<role>/<file>.json, so the
  role's materialized inputs directory is `path.parent / "inputs"`.
- Materialized inputs are content-named by sha256[2:] of their sealed
  source bytes (verified against the K-5 run workspaces: sealed
  63f8e7ae... -> inputs/f8e7ae1a...). The filename tail plus a re-hash
  of the bytes identifies the source artifact exactly.
- No artifacts-table query by sha256 exists; all current queries are by
  artifact_id. The closure class at line 2402 has repository access via
  `self.repository.database.connect()` (pattern at lines 2716-2720).
- Sealed role outputs carry the true artifact identity, e.g. the K-5
  run's p2.theory_proposal row: artifact_id artifact.7672f84c...,
  sha256 63f8e7ae..., kind validated_role_output.
- Validation: `_validate_p2` (harness/scientific_validators.py:150)
  iterates p2.method_changes records and calls
  `_validate_method_definition` (line 300) per record. The E-2d pointer
  check `_validate_compact_view_pointers` (line 1354) is the mirror
  template: unstamped scheme OR single-repeated-char 64-hex sha256 ->
  finding.
- Validation codes register in src/method_hub/domain/validation.py near
  lines 340-348 as (code, phase) tuples with
  CORRECTABLE_CONTRACT_ERROR, correction_class "packaging",
  deterministic_repair=True. POLICY_VERSION = "1.11.0" (line 38).
- Fixture hazards (both carry "1"*64 in canonical_artifact.sha256):
  tests/fixtures/golden/method.example.json and
  architecture/examples/method.example.json (byte-identical copies;
  executors/development.py maps method.schema.json ->
  method.example.json, so dev-executor P2 e2e paths run these through
  _validate_p2). tests/test_digest_registry.py loads
  method.example.json at lines 103/289/299/316 - the example digest
  chain may need recompute; follow
  references/example-digest-chain-maintenance.md if the validator
  reports chain breaks.
- No test asserts canonical_artifact pointer values today (grep clean),
  so no boundary tests pin the old behavior.
- The P2 lead instruction file
  resources/instructions/P2/p2.lead_reconciliation.research_lead.md
  never mentions canonical_artifact - agents invent the whole pointer.

## Design pins (PRE-PINNED; the implementer executes, does not design)

### P1 - Declaration convention (agent-facing)

In the method record, `mathematical_definition.canonical_artifact` is
declared as:

```json
"canonical_artifact": {
  "uri": "input://<materialized input filename>",
  "media_type": "application/json",
  "path": "<the same input filename>",
  "locator": "<where in the source the definition appears>"
}
```

with NO artifact_id and NO sha256 (the closure stamps both). The
materialized input filename is the exact content-named file in the
role's inputs/ directory (e.g. inputs/f8e7ae1a085f44...) of the
proposal or record the canonical definition was taken from. An
unresolvable or missing declaration is left for validation to reject;
the agent must NOT invent digests. (Mirrors the E-2d output://
convention: the artifactPointer schema requires artifact_id/uri/sha256
and its uri pattern rejects input://, so an unstamped pointer fails
structural validation AND the scientific validator emits the
actionable correctable finding - stamping happens before both.)

### P2 - Stamping mechanism (role_execution.py)

1. `_OutputPointerContext` gains an optional
   `canonical_source_lookup: Callable[[str], str | None]` (digest ->
   artifact_id) and resolves input pointers: new method
   `locate_input(filename) -> Path | None` returning
   `self._role_dir / "inputs" / filename` when it exists. The role dir
   is derived per output as `path.parent` at the stamping call site
   (inputs/ is a sibling of the output files inside roles/<NN>-<role>/).
2. New helper `_stamp_canonical_artifact(method_record, *, inputs_dir,
   lookup) -> bool`: when
   `mathematical_definition.canonical_artifact.uri` starts with
   `input://`, read the named input file bytes, digest = sha256, stamp
   sha256 = digest, uri = `artifact://sha256/<digest>`, artifact_id =
   lookup(digest) or, when the lookup returns None (dev-fixture
   contexts without artifact rows),
   `deterministic_id("artifact", project_id, run_id, "canonical_source",
   digest)`. Preserve the agent's path and locator fields. Return True
   only when a field changed. Unresolvable input names are left
   untouched for validation.
3. `_fix_self_referential_hashes` case 5: method records (objects with
   both `identity` and `mathematical_definition` dicts - the case-3
   discriminator) with a `canonical_artifact` dict get
   `_stamp_canonical_artifact` applied. The existing recursion into the
   method-changes list covers p2.method_changes automatically.
4. Call-site wiring (line 2402 caller): pass a lookup closure built on
   `self.repository.database.connect()`:
   `SELECT artifact_id FROM artifacts WHERE sha256 = ? AND project_id =
   ? ORDER BY rowid LIMIT 1` with str(self.context.project_id). No new
   repository method; use the raw-SQL pattern of lines 2716-2720.
   `_apply_disclosed_mechanical_repairs` threads the lookup into the
   `_OutputPointerContext` constructor (new optional kwarg; all
   existing call sites unchanged).

### P3 - Validation (scientific_validators.py + domain/validation.py)

1. New `_validate_canonical_artifact_pointer(method, *, offset,
   findings)` called from `_validate_p2`'s per-record loop right after
   `_validate_method_evaluation`: emit code
   `p2.canonical_pointer_invalid` at
   `/mathematical_definition/canonical_artifact` when uri starts with
   `input://` (unstamped) OR sha256 is a 64-hex single-repeated-char
   string. Message: "Canonical artifact pointers must reference sealed
   input bytes; the closure stamps input:// pointers mechanically."
2. Register the code in domain/validation.py next to
   ("p1.primary_pointer_invalid", "P1") / ("p3.primary_pointer_invalid",
   "P3"): ("p2.canonical_pointer_invalid", "P2"),
   CORRECTABLE_CONTRACT_ERROR, deterministic_repair=True.
3. POLICY_VERSION "1.11.0" -> "1.12.0" with a one-line changelog comment
   above the constant (the E-2d pattern; no test pins the literal).

### P4 - Instruction patch

resources/instructions/P2/p2.lead_reconciliation.research_lead.md: in
the Required outputs / method-record guidance, state the P1 convention
mechanically - declare canonical_artifact with uri
"input://<materialized input filename>" naming the inputs/ file the
canonical definition was taken from, with no artifact_id and no
sha256, and never invent digests. One focused paragraph; follow the
file's existing style.

### P5 - Fixtures

- tests/fixtures/golden/method.example.json AND
  architecture/examples/method.example.json (keep byte-identical):
  replace the canonical_artifact "1"*64 sha256 with a non-degenerate
  64-hex value (sha256 of the artifact_id string, the E-2d fixture
  method). The uri (artifact://artifact.method_definition) does not
  start with input:// so only the degenerate-sha rule bites.
- If validate_package.py reports example digest-chain breaks after the
  fixture edit, follow references/example-digest-chain-maintenance.md
  (chain order, canonical_sha256 reuse, spy-capture for
  validator-computed receipt digests).
- architecture/examples/method-exposition-revision.example.json also
  contains canonical_artifact: P4 exposition revisions are OUT OF SCOPE
  for this package (no p4 validator touches the field); do not edit it
  beyond what the digest chain requires.

### P6 - Tests (new, in tests/)

- Stamping: input:// pointer resolves to the input file's digest and
  the lookup-provided artifact_id; lookup-None falls back to the
  deterministic_id derivation; unresolvable input name left untouched;
  non-input:// pointers untouched; path/locator preserved.
- Validation: input:// uri -> p2.canonical_pointer_invalid;
  repeated-char sha256 -> same code; properly stamped pointer (sha256
  of real bytes, artifact://sha256/ uri) -> no finding.
- Integration: the golden method.example.json passes the extended
  _validate_p2 without the new finding.

## Out of scope / boundaries

- P4 method-exposition-revision canonical_artifact (no evidence of a
  production P4 authoring path hitting this yet; revisit when P4 runs).
- No submission-time artifact-store byte-resolution recheck (the E-2d
  boundary stands: submission_validation stays document-level).
- Existing sealed records keep their legacy pointers (immutable
  history); the publisher transform carries pointers forward unchanged.
- No ADR needed: this extends the ADR-014 validation policy (policy
  version bump) and the E-2 stamping mechanism to one more field; no
  invariant, schema shape, or phase contract changes (the schema
  already requires canonical_artifact; the input:// convention is an
  agent-facing declaration rule, exactly like E-2d's output://).

## Verify

- Baseline: suite 1222 passed at 1f0b240 (2026-08-23).
- After: full suite green + `.venv/bin/python
  architecture/tools/validate_package.py` exit 0.
- Docs under architecture/ use ASCII hyphens only (the validator
  rejects em dashes).
- One commit, message starting "E-2e:".
- Production probe (follow-up exercise): the next P2 run's method
  records carry canonical_artifact pointers that resolve to
  hash-verified artifact-store bytes.
