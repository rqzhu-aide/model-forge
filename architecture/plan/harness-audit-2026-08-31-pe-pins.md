# Implementation Pins: Pkg E (R11, R12, R32, R33, R34, R35)

Status: PINNED 2026-09-01 (coordinator). Every finding below was re-probed
against the live tree before pinning. Source of truth for findings:
[../harness-audit-2026-08-31.md](../harness-audit-2026-08-31.md).

## Probe facts (verified 2026-09-01 against the live tree)

1. R11 confirmed: `_materialize_writes` (publication.py:992-1009) verifies
   `prepared.source_output_sha256` only; `source_input_sha256` is never
   compared to `binding.source_input_ids`. `_validate_bindings` accepts
   `source_input_ids` (:609) without checks. The coordinator-side check
   `_verify_transform_inputs` (run_coordinator.py:1063-1081) builds
   `expected` only from input ids present in the recipe's frozen_inputs,
   so a recipe MISSING the declared frozen input passes with `{} == {}`.
   First-run constraint (probe): `frozen_inputs` contains only resolved
   run inputs (preparation.py:93-112); a declared source input is simply
   absent when no prior current record exists. An UNCONDITIONAL
   set-equality check would fail every legitimate first-run index build
   (existing test test_harness_publication_plan_source.py publishes
   exactly that shape). The check is therefore conditioned on the slot
   having a prior generation, matching the audit's danger clause.
2. R12 confirmed: `_prior_items` (index_reducers.py:215-218) returns []
   for a non-dict prior or a missing/non-list field, with no
   format/format_version check. No test file imports index_reducers
   today.
3. R32 confirmed: `_bundle_document` (publication.py:1090-1093) returns
   component-1's `output.artifact` as the bundle generation's artifact.
   `ContractPublicationService.__init__` takes only `repository`; the
   coordinator owns `self.artifacts` and calls publish at
   run_coordinator.py:418 and validate_materialization at :492.
   `repository.record_artifact` is idempotent on identical metadata
   (repository.py:1156-1162). `_materialize_writes` runs BEFORE the
   publication transaction (publication.py:305 vs :350), so artifact
   registration there mirrors the preparation-time registration in
   prepare_index_transforms (index_reducers.py:86-114). No
   architecture/examples fixture pins bundle artifact ids (grep:
   'deterministic-bundle' appears only in examples/README.md), so no
   example digest cascade is expected.
4. R33 confirmed and scoped: EVERY real contract binding declares a
   non-empty `applicable_modes` (all 22 bindings across
   architecture/contracts/phases/P1-P5.json), so rejecting the field at
   the publication layer would break all publication. Mode filtering
   happens at contract resolution (phases.py:849). The enforceable
   fail-loud check is: when the binding source carries a mode
   (ResolvedPhasePlan.mode_id; PreparedRunRecipe document["mode"],
   sealed at preparation.py:142), each binding's applicable_modes must
   contain it. Raw binding sequences (test-only) carry no mode context
   and stay unenforced. `upsert_each` (publication.py:918-972) builds
   slot keys from the template directly, bypassing `_resolve_slot`; the
   only keyed binding is P2's, and P2 is not a method phase
   (publication_basis.py:14), so keyed+scope never co-occurs today.
   Pin rejects the combination fail-loud instead of silently ignoring
   the scope.
5. R34 confirmed: `capture_publication_basis` issues `get_project`
   (repository.py:163, own connection) and `list_current_records`
   (repository.py:1403, own connection); sqlite3 implicit
   autocommit-on-read means the two reads are not one snapshot.
   `recover_publication_head` (publication_basis.py:77) silently
   defaults a missing `current_generations` to {}.
6. R35 confirmed with a correction to the audit's stated symptom:
   `_literature_key` (index_reducers.py:221-235) returns values[0], the
   lexicographically smallest identifier. The pinned fix (key on the
   full sorted identifier tuple) changes behavior for the COLLISION
   case: two distinct items sharing the smallest identifier (prior
   [doi:X], change [doi:X, isbn:Y]) currently fold into ONE entry
   (silent loss of the prior item); post-fix they yield two entries.
   The audit's named enrichment case ([isbn:Y] prior vs
   [doi:X, isbn:Y] change) yields two entries BOTH pre- and post-fix:
   full-tuple keying does not make enrichment update in place. That
   requires identifier-overlap identity resolution, a design decision
   beyond this audit fix. The regression test therefore pins the
   collision case (the behavior the pinned fix actually changes), and
   this discrepancy is recorded in the audit doc per program rules.

## Allowed files

- src/model_forge/harness/publication.py (R11, R32, R33)
- src/model_forge/harness/index_reducers.py (R12, R35)
- src/model_forge/harness/publication_basis.py (R34)
- src/model_forge/storage/repository.py (R34 snapshot method)
- src/model_forge/application/run_coordinator.py (R32 call-site wiring)
- tests/test_harness_publication.py (R11, R32, R33b tests + migrate the
  two bundle tests at :283 and :340 to pass an artifact store)
- tests/test_harness_publication_plan_source.py (R33a test)
- tests/test_index_reducers.py (NEW; R12, R35 tests)
- tests/test_publication_basis.py (NEW; R34 tests)

No other files. No architecture/ edits in the fix commit.

## R11 pin (publication.py)

In `_materialize_writes`, in the `replace` + `deterministic_index`
branch, immediately after the existing `source_output_sha256` check
(currently :1003-1007):

```python
declared_inputs = {
    str(value) for value in binding.get("source_input_ids", ())
}
if prior is not None and {
    str(key) for key in prepared.source_input_sha256
} != declared_inputs:
    raise _fail(
        "publication.transform_input_missing",
        f"Prepared transform for {binding_id!r} did not consume the "
        "declared frozen prior inputs.",
    )
```

`prior` is already in scope (computed at :982-984). The condition on
`prior is not None` is load-bearing (probe fact 1): a first run with no
prior generation legitimately consumes nothing.

## R12 pin (index_reducers.py)

Replace `_prior_items` with a fail-closed version:

```python
def _prior_items(
    prior: Any | None, field: str, expected_format: str
) -> list[dict[str, Any]]:
    if prior is None:
        return []
    if type(prior) is not dict:
        raise ValueError(f"Prior {expected_format} index is not a JSON object.")
    if (
        prior.get("format") != expected_format
        or prior.get("format_version") != "1.0.0"
    ):
        raise ValueError(
            f"Prior index format does not match {expected_format} 1.0.0."
        )
    items = prior.get(field)
    if type(items) is not list:
        raise ValueError(f"Prior {expected_format} index lacks the {field} array.")
    result: list[dict[str, Any]] = []
    for item in items:
        if type(item) is not dict:
            raise ValueError(
                f"Prior {expected_format} index contains a non-object item."
            )
        result.append(dict(item))
    return result
```

Update the three callers: `_literature_library` passes
("sources", "model-forge.literature-library-index"), `_method_catalog`
passes ("methods", "model-forge.method-catalog-index"),
`_review_issue_ledger` passes
("issues", "model-forge.review-issue-ledger"). ValueError matches the
module's existing failure style (:52-62, :143-146).

## R32 pin (publication.py + run_coordinator.py)

1. `publish` and `validate_materialization` gain a keyword-only
   parameter `artifacts: ArtifactStore | None = None`, passed through to
   `_materialize_writes`. Import: `from ..storage import ArtifactStore`
   (same import path index_reducers.py:11 uses).
2. `_materialize_writes` gains keyword-only `artifacts` (same type) and
   is called with `repository=self.repository`... no: the service passes
   `self.repository` internally; signature gains `artifacts` only, and
   the bundle branch uses `self`-provided repository via a new
   keyword-only `repository: HubRepository` parameter that both public
   methods pass as `repository=self.repository`.
3. Bundle branch (currently :1018-1019): if `artifacts is None`, raise
   `_fail("publication.bundle_artifact_store_required", ...)`. Otherwise
   call the rewritten `_bundle_document`:

```python
def _bundle_document(
    binding: Mapping[str, Any],
    outputs: Mapping[str, RegisteredValidatedOutput],
    *,
    repository: HubRepository,
    artifacts: ArtifactStore,
    project_id: str,
    run_id: str,
) -> tuple[dict[str, Any], RegisteredArtifactMetadata]:
    # ... existing bundle assembly unchanged ...
    payload = canonicalize(bundle)
    stored = artifacts.put_bytes(payload)
    digest = str(stored.sha256)
    binding_id = str(binding["binding_id"])
    artifact_id = _deterministic_id(
        "artifact",
        {
            "kind": "publication_bundle",
            "project_id": project_id,
            "run_id": run_id,
            "publication_binding_id": binding_id,
            "content_sha256": digest,
        },
    )
    repository.record_artifact(
        artifact_id,
        project_id,
        digest,
        stored.size,
        "application/json",
        f"artifact://sha256/{digest}",
        {
            "kind": "publication_bundle",
            "run_id": run_id,
            "publication_binding_id": binding_id,
            "storage_relative_path": stored.relative_path,
            "source_output_sha256": {
                str(component["output_id"]): outputs[
                    str(component["output_id"])
                ].document_sha256
                for component in binding["components"]
            },
        },
    )
    return (
        bundle,
        RegisteredArtifactMetadata(
            artifact_id=artifact_id,
            sha256=digest,
            byte_length=stored.size,
            media_type="application/json",
            storage_uri=f"artifact://sha256/{digest}",
        ),
    )
```

`digest` equals `_canonical_digest(bundle, binding_id)` because
`_canonical_digest` is `sha256(canonicalize(value))` (:1286-1293) and
`put_bytes` hashes the same canonical bytes, so the existing
`document_sha256` computation at :1020 stays unchanged and consistent.
Registration is idempotent (probe fact 3), so the validate path calling
it first is safe; artifact rows are storage metadata, not formal state.

4. run_coordinator.py: pass `artifacts=self.artifacts` at the publish
   call (:418-428) and the validate_materialization call (:492-501).

## R33 pin (publication.py)

1. Mode enforcement in `_extract_bindings`: capture the mode when the
   source carries one (`source.mode_id` for ResolvedPhasePlan;
   `document.get("mode")` when it is a str for PreparedRunRecipe; None
   for raw sequences). After `_validate_bindings(exact)`:

```python
if mode is not None:
    for binding in validated:
        declared = binding.get("applicable_modes")
        if declared is None:
            continue
        if (
            isinstance(declared, (str, bytes))
            or not isinstance(declared, Sequence)
            or mode not in {str(item) for item in declared}
        ):
            raise _fail(
                "publication.binding_mode_inapplicable",
                f"Binding {binding['binding_id']!r} is not applicable to "
                f"mode {mode!r}.",
            )
```

2. Keyed scope rejection at the top of `_materialize_writes` (after the
   coverage checks, before the binding loop):

```python
if (slot_scope_prefix is not None or slot_resolver is not None) and any(
    str(binding["operation"]) == "upsert_each" for binding in bindings
):
    raise _fail(
        "publication.keyed_scope_unsupported",
        "Keyed upsert_each bindings do not support slot scope or a resolver.",
    )
```

## R34 pin (publication_basis.py + repository.py)

1. repository.py: extract the current-records SQL from
   `list_current_records` into a module-level `_CURRENT_RECORDS_SQL`
   constant used by both methods, and add:

```python
def capture_head_and_current_slots(
    self, project_id: str
) -> tuple[sqlite3.Row, tuple[sqlite3.Row, ...]]:
    """Read the project head and the full slot inventory in one transaction."""
    project_id = _text(project_id, "project_id")
    with self._database.immediate_transaction() as connection:
        project = self._require_project(connection, project_id)
        rows = tuple(
            connection.execute(_CURRENT_RECORDS_SQL, (project_id,)).fetchall()
        )
    return project, rows
```

(`_require_project` already raises for unknown projects; see
publication_transaction at :1475 for the pattern.)

2. publication_basis.py `capture_publication_basis`: replace the two
   calls with one
   `project, current_rows = repository.capture_head_and_current_slots(project_id)`
   and build `current` from `current_rows`.

3. `recover_publication_head`: after the existing
   `complete_current_slot_inventory` check, replace
   `generations = dict(basis.get("current_generations", {}))` with:

```python
sealed = basis.get("current_generations")
if not isinstance(sealed, Mapping):
    raise ValueError(
        "Publication basis lacks the sealed current-slot inventory."
    )
generations = dict(sealed)
```

## R35 pin (index_reducers.py)

In `_literature_key`, replace `return values[0]` with a collision-free
encoding of the full sorted identifier tuple (canonicalize is already
imported at :9 and returns bytes):

```python
if values:
    return canonicalize(values).decode("utf-8")
```

The fallback chain (`source_id`, `record_id`, then `document_sha256`)
is unchanged. Add a short comment: distinct items that share only their
smallest identifier must not fold together; enrichment of an item's
identifier set still produces a separate entry (recorded as a residual
design item in the audit doc).

## Regression tests (each must FAIL on pre-fix code)

tests/test_harness_publication.py (mirror existing fixtures:
`_repository`, `_run`, `_output`, `_replace_binding`, `_bundle_binding`,
`FrozenPublicationHead`, `ZERO_SHA256`, `NOW`; ArtifactStore via
`ArtifactStore(WorkspacePaths(tmp_path / "workspace", create=True))` -
verify the exact WorkspacePaths constructor against
tests/test_correction_execution.py:85):

1. R11 `test_index_transform_missing_declared_prior_input_fails`: first
   publish a replace+deterministic_index binding declaring
   source_input_ids ["p1.current_library"] with a transform whose
   source_input_sha256 carries that input (slot prior None, succeeds);
   then a second run publishes the same binding with a transform whose
   source_input_sha256 is EMPTY while the slot now has a prior
   generation. Assert PublicationError with code
   publication.transform_input_missing. Pre-fix: the second publish
   succeeds, so the pytest.raises assertion fails.
2. R32 `test_bundle_generation_registers_own_artifact`: publish
   `_bundle_binding()` with slot_scope_prefix as in the existing bundle
   test, passing the artifact store. Assert the sealed generation's
   artifact_id differs from component-1's artifact_id, an artifact row
   with payload kind publication_bundle exists, and its sha256 equals
   hashlib.sha256(canonicalize(bundle_document)).hexdigest() where
   bundle_document is json.loads(current["payload_json"]). Pre-fix: the
   generation carries component-1's artifact_id, assertion fails.
3. R33b `test_keyed_binding_with_slot_scope_is_rejected`: an
   upsert_each binding (mirror P2's keyed_current_slots shape:
   item_key_pointer, slot_template with one {item_key}) published with
   slot_scope_prefix set. Assert PublicationError code
   publication.keyed_scope_unsupported. Pre-fix: publish succeeds.
4. Migrate the two existing bundle tests (:283, :340) to pass
   `artifacts=` (required for bundle operations post-fix); assertions
   unchanged except that nothing may assume the generation artifact is
   component-1's.

tests/test_harness_publication_plan_source.py:

5. R33a `test_plan_binding_outside_run_mode_is_rejected`: mirror the
   existing test's plan loading, then
   `dataclasses.replace(plan, publication_bindings=...)` with one
   binding's applicable_modes replaced by a mode the run is not in
   (e.g. ["p5.assembly"]). Publish and assert PublicationError code
   publication.binding_mode_inapplicable. Pre-fix: publish succeeds.

tests/test_index_reducers.py (NEW; import the private reducer helpers
directly - no existing fixtures needed):

6. R12 `test_malformed_prior_index_raises`: `_literature_library` with a
   prior that is (a) a list, (b) a dict with the wrong format string,
   (c) a dict whose sources field is not a list. Each raises ValueError
   post-fix; pre-fix all three silently reduce to an empty index, so the
   raises assertions fail.
7. R35 `test_shared_smallest_identifier_does_not_merge`: prior item with
   identifiers [doi:X] and a change item with identifiers
   [doi:X, isbn:Y] produce TWO sources post-fix (pre-fix: one, the
   change silently overwrote the prior at key "doi:x"). Companion
   no-regression assertion in the same test: identical identifier sets
   still fold to one entry with the change winning.

tests/test_publication_basis.py (NEW):

8. R34 `test_recover_publication_head_requires_sealed_inventory`: basis
   {"complete_current_slot_inventory": True, "authority_sequence": 0,
   "authority_root_sha256": ZERO_SHA256, "current_revision": 0} (no
   current_generations) with a plan stub
   (SimpleNamespace(identity=SimpleNamespace(phase_id="P1"),
   publication_bindings=())) and outputs {} raises ValueError post-fix;
   pre-fix returns a head with empty generations.
9. R34 `test_capture_publication_basis_single_snapshot`: on a fresh
   repository (mirror _repository from test_harness_publication.py),
   capture with the same plan stub and method=None; assert the basis
   carries authority_sequence/authority_root_sha256/current_revision
   from the project row, complete_current_slot_inventory is True, and
   current_generations is {}. (Behavior-preservation smoke for the
   single-transaction refactor; the atomicity itself is verified by
   code inspection of the one-connection implementation.)

## Boundaries

- No architecture/ file edits in the fix commit (the validator runs
  separately and the plan update is the coordinator's own commit).
- No changes to binding validation order or to existing error codes.
- Do not add error-registry entries: publication.* codes are internal
  to PublicationError and are not cross-registered (probe: no
  publication.* codes in validate_package.py error policies).
- Suite baseline before this package: 1358 passed. Expected delta: +9
  new tests (R12's test is one test with three sub-cases asserted in
  sequence, or split into three - either is acceptable; report the
  exact final count).
- Gates: `.venv/bin/python -m pytest tests -q` exit 0 and
  `.venv/bin/python architecture/tools/validate_package.py` exit 0.
- Every regression test MUST be observed failing on pre-fix code (stash
  or git stash the src changes, run the new tests, confirm the
  predicted failures, restore). Report the pre-fix failure output.
