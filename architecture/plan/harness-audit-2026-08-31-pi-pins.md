# P-I Pins: P3 Sweep (R18-R25, R27-R31, R36)

Coordinator probe record for the P-I package of the 2026-08-31 harness
audit fix program. Every site below was re-probed against the live tree on
2026-09-01 (post P-H, head e29a112); audit line numbers have drifted, so
each section pins the CURRENT location and the exact edit. Program plan:
[harness-audit-2026-08-31-fix-program.md](harness-audit-2026-08-31-fix-program.md).

Conventions: one package commit (coordinator commits after gates; the
implementing dispatches leave the tree uncommitted). Regression tests live
in two NEW files so the two implementation lanes cannot collide:

- Lane A: tests/test_p3_hardening_harness.py (R18, R19, R24, R25, R29,
  R30, R31)
- Lane B: tests/test_p3_hardening_submission.py (R20, R21, R27, R28, R36)

Current suite count: 1373. Predicted delta: +13 -> 1386.

## R18: pre-resolve symlink check (outputs.py)

Live site: `validate_role_outputs` loop, outputs.py:177-213.
`path.resolve(strict=True)` fully resolves symlinks, so
`resolved.is_symlink()` at :204 is always False; a symlinked output that
resolves to a regular file inside the run root is silently accepted.

Pinned edit: immediately after `path = run_root.joinpath(...)` (:179),
before the try block:

```python
        if path.is_symlink():
            findings.append(
                _finding(
                    "output.not_regular_file",
                    f"Output {spec.contract_output_id!r} must be a regular JSON file.",
                    spec,
                    method_bound=method_bound,
                )
            )
            continue
```

(Pre-resolve check: `Path.is_symlink()` does not follow the final
component, so this catches the symlink itself. The existing post-resolve
`resolved.is_symlink()` clause stays; it is now dead but harmless - leave
it untouched to keep the diff minimal. NO: remove nothing else.)

Regression test `test_symlinked_output_is_not_regular_file`: construct an
`OutputSpec` directly (dataclass fields: contract_output_id, output_id,
output_kind, producer, stage_id, stage_sequence, schema_application
"object", schema_file, relative_path, required=True, record_type=""), an
`OutputPlan((spec,))`, stage as `SimpleNamespace(stage_id=spec.stage_id)`,
run_root=tmp_path with the declared relative_path present as a SYMLINK to
a real JSON file (also under run_root) containing `{}`, and a stub schema
catalog whose `validate(...)` returns []. Assert: no accepted outputs and
exactly one finding with code `output.not_regular_file`. Pre-fix: the
symlink resolves cleanly, the document is accepted, zero findings - the
test fails.

## R19: input:// basename/containment check (role_execution.py)

Live site: `_stamp_canonical_artifact`, role_execution.py:798-856; the
unguarded join is at :833 (`candidate = inputs_dir / uri[len("input://"):]`).
`input://../../x` reads outside the sandboxed inputs dir and stamps its
digest into a sealed record.

Pinned edit: replace the candidate computation (:833) with:

```python
    name = uri[len("input://"):]
    # Basename-only, containment-checked: anything else is left untouched
    # for validation to reject (R19).
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
    ):
        return False
    candidate = inputs_dir / name
    try:
        candidate.resolve().relative_to(inputs_dir.resolve())
    except (OSError, ValueError):
        return False
```

The following `if not candidate.is_file(): return False` stays unchanged.

Regression test `test_canonical_input_pointer_rejects_traversal`: module
function, called directly. inputs_dir = tmp_path/"inputs" (mkdir); a
secret file tmp_path/"secret.txt" with known bytes; method_record =
{"mathematical_definition": {"canonical_artifact": {"uri":
"input://../secret.txt"}}}. Call with lookup=None, project_id="p",
run_id="r". Assert returns False and the uri is unchanged. Pre-fix:
returns True and stamps sha256 of the outside file - the test fails. Add
a positive control in the same test: a real file inputs_dir/"real.bin"
with uri "input://real.bin" returns True and stamps
"artifact://sha256/<digest of real.bin>".

## R20: dedicated operational code for unreadable sealed submission payloads

Live site: submission_validation.py:66-71 - a JsonLoadError on the sealed
submission row surfaces `json.*` codes, registered as
CORRECTABLE_CONTRACT_ERROR/packaging (domain/validation.py:247-251), so
harness-side corruption routes into the correction lane until exhaustion.

Pinned edits:

1. domain/validation.py: register `submission.payload_unreadable` as
   FindingClass.OPERATIONAL_FAILURE, with rationale ("The sealed
   submission payload in the run repository could not be parsed; this is
   a harness-side storage fault no correction lane can repair.") and
   guidance ("Investigate the run repository storage; the correction lane
   cannot repair a corrupt sealed payload."). Place the `_register` call
   immediately after the `correction.blast_radius_violated` block
   (:180-191) with a short comment referencing R20.
2. Bump POLICY_VERSION to "1.13.0" with a changelog comment line:
   `# 1.13.0 (R20): unreadable sealed submission payloads are operational`
   `# failures (submission.payload_unreadable), not correctable json.*`
   `# findings.` (wrap to match the existing comment style).
3. submission_validation.py:66-71: replace `_finding(error.code,
   error.message, run_id)` with
   `_finding("submission.payload_unreadable", f"The sealed submission
   payload could not be parsed: {error.message}", run_id)`.

Probe fact: the suite REQUIRES the registration -
tests/test_validation_policy_registry.py::test_registry_covers_all_submission_validator_codes
extracts code literals from submission_validation.py and asserts
registration. POLICY_VERSION is asserted only to be a non-empty string.

Regression test `test_unreadable_submission_payload_is_operational`
(Lane B): minimal stub repository with `get_latest_submission_attempt`
-> None and `get_submission` -> {"payload_json": "{not json",
"submission_sha256": "0"*64}. `validate_submission` returns before any
other repository/schema access, so the remaining arguments can be
SimpleNamespace stubs. Assert the single finding has code
"submission.payload_unreadable" and finding_class
FindingClass.OPERATIONAL_FAILURE and correction_class "none". Pre-fix:
code is "json.decode_error" with class correctable_contract_error - the
test fails.

## R21: schema_file/failing_property for run-submission schema findings

Live site: submission_validation.py:93-96 passes neither, so ADR-015
reclassification (`reclassify_harness_owned_finding`, envelope.py:229)
never applies to run-submission schema findings; the module `_finding`
(:413-436) already accepts both kwargs (P-D).

Pinned edit:

```python
    for issue in schemas.validate("run-submission.schema.json", submission):
        findings.append(
            _finding(
                issue.code,
                issue.message,
                run_id,
                issue.json_pointer,
                schema_file="run-submission.schema.json",
                failing_property=issue.failing_property,
            )
        )
```

Probe fact: `harness_owned_fields` falls back to _COMMON_HARNESS_FIELDS
for unregistered schemas (envelope.py:219-226); run-submission.schema.json
requires `schema_version` (verified against the schema), which is in the
common set, so a missing/invalid schema_version finding reclassifies.

Regression test
`test_run_submission_schema_finding_reclassifies_harness_owned` (Lane B):
real catalog `SchemaCatalog.load(Path(__file__).resolve().parents[1] /
"architecture" / "schemas")`; stub repository as in R20 but with a VALID
payload: build a submission dict with all required fields EXCEPT
schema_version (see run-submission.schema.json required list: schema_version,
submission_id, run_id, project_id, phase, mode, manifest_binding,
closure_chain, lead_closure, submitted_artifacts, submitted_at,
submission_sha256), with closure_chain=[] and submitted_artifacts=[];
set payload["submission_sha256"] = document_sha256 of the dict minus that
field (import document_sha256 from harness.execution_records) and the
row's submission_sha256 to the same value. plan stub:
SimpleNamespace(identity=SimpleNamespace(phase_id="PX"), mode_id="m",
publication_bindings=()) and matching phase "PX"/mode "m" in the document
("PX" is not a known phase, so validate_phase_scientific is a no-op).
output_plan stub: SimpleNamespace with by_contract_id() returning {}.
selected_method=None. Assert: a finding with code "schema.required" and
finding_class OPERATIONAL_FAILURE exists. Pre-fix: that finding stays
CORRECTABLE_CONTRACT_ERROR - the test fails.

## R23: to_role comment correction (docs only, no test)

Live sites: envelope.py:63 (`to_role: str = ""  # next stage's role
(handoffs); empty when terminal`) and the computation at
role_execution.py:2657-2663 (to_role stays "" when the next stage has
MULTIPLE roles, not only when terminal).

Pinned edits:

1. envelope.py:63 -> `to_role: str = ""  # next stage's sole role
   (handoffs); empty when terminal or when the next stage has multiple
   roles`
2. role_execution.py, directly above `to_role = ""` (:2657), insert:

```python
        # to_role names the single role of the next stage. When the next
        # stage fans out to multiple roles there is no unique successor,
        # so to_role stays empty - it is not only empty when terminal
        # (R23).
```

No regression test (comment-only; the behavior is unchanged and already
covered by envelope construction tests).

## R24: compact-view fallback skips summary-less JSON envelopes

Live site: `_materialize_compact_views`, role_execution.py:2452-2460:
when the compact-view envelope lacks `summary_markdown`, the FULL raw
artifact bytes are written as the "compact" markdown.

Pinned edit: replace the fallback (:2459-2460)

```python
                if not markdown.strip():
                    markdown = raw.decode("utf-8", errors="replace")
```

with:

```python
                if not markdown.strip():
                    # R24: a summary-less envelope has no compact content;
                    # skip it instead of dumping raw bytes into the brief.
                    continue
```

(`continue` skips the write, the access-log entry, and the compact dict
entry for this representation, moving to the next representation/input.)

Regression test `test_compact_view_skips_summary_less_envelope` (Lane A):
instance via `RoleLifecycleService.__new__(RoleLifecycleService)`; set
`.artifacts` to a stub with `read_bytes(sha256)` returning
`json.dumps({"format": "x"})` bytes (a JSON envelope WITHOUT
summary_markdown). inputs = {"inp": SimpleNamespace(path=str(record))}
where record (tmp_path file) contains {"representations":
[{"information_layer": "compact_decision_view", "artifact": {"sha256":
"a"*64, "uri": "artifact://sha256/" + "a"*64, "artifact_id": "art"}}]}.
Call `_materialize_compact_views(role_root=tmp_path/"role",
inputs=inputs, input_ids=["inp"],
access_log_path=tmp_path/"access.jsonl")`. Assert the returned dict is
empty and no `inputs/compact/inp.md` exists. Pre-fix: the raw envelope
bytes are written and "inp" is in the dict - the test fails. Positive
control in the same test: a second input whose envelope DOES carry
summary_markdown materializes normally.

## R25: cache only successful parses in _STABLEID_POSITIONS_CACHE

Live site: role_execution.py:1337-1339 - the heuristic fallback (any
load/parse failure) is permanently cached, so one transient failure
poisons coverage for the process lifetime.

Pinned edit: move the cache store into the try block so only the exact
result is cached:

```python
        _walk(schema, schema, frozenset())
        result = {
            "scalar_keys": frozenset(scalar_keys),
            "array_keys": frozenset(array_keys),
            "heuristic": False,
        }
        _STABLEID_POSITIONS_CACHE[schema_file] = result
    except Exception:
        result = {"scalar_keys": frozenset(), "array_keys": frozenset(), "heuristic": True}
    return result
```

Regression test `test_stableid_positions_cache_stores_successes_only`
(Lane A): probe schema name "zz-r25-probe.schema.json" under
architecture/schemas (the function resolves `_Path(__file__).parents[3] /
"architecture" / "schemas"`). Sequence, all inside try/finally that
unlinks the probe file and pops the cache key:

1. pop the cache key; file absent -> `_stableid_positions(name)` returns
   heuristic True (and post-fix is NOT cached).
2. write a valid schema: {"$defs": {"stableId": {"type": "string"}},
   "type": "object", "properties": {"probe_id": {"$ref":
   "#/$defs/stableId"}}}.
3. call again WITHOUT popping the cache -> must return heuristic False
   with "probe_id" in scalar_keys.

Pre-fix: step 1 cached the heuristic result, so step 3 returns heuristic
True - the test fails.

## R27: honest classification of promote-time re-validation failure

Live site: run_coordinator.py:404 raises a bare ValueError, which
`_handle_error` (:1181) records as `run.coordination_failed` - a
misleading class for a deterministic re-check flip.

Pinned edit: replace the bare raise with

```python
            raise PublicationError(
                "publication.revalidation_failed",
                "Validated submission changed before publication.",
            )
```

and import PublicationError from ..harness.publication (check the existing
import block; recover_publication_head/prepare_index_transforms are
already imported from that module family).

Regression test `test_promote_revalidation_failure_is_classified`
(Lane B): coordinator via `RunCoordinator.__new__(RunCoordinator)`
(pattern: tests/test_run_advancement_guarantee.py); stub
`repository = SimpleNamespace(get_publication_receipt_for_run=lambda
run_id: None)` and `_publication_plan = lambda run_id:
(SimpleNamespace(passed=False), None, None, None, None)`. Assert
`pytest.raises(PublicationError)` and `excinfo.value.code ==
"publication.revalidation_failed"`. Pre-fix: bare ValueError, which is
not a PublicationError - the test fails.

## R28: isinstance-guard declared method identity

Live site: `_validate_phase_semantics`, submission_validation.py:373-386:
`declared = output.document.get("method_identity") or
output.document.get("identity")`; a truthy NON-OBJECT declared value
AttributeErrors at `declared.get(...)` (:383), escaping the
(PublicationError, ValueError) catch upstream and stalling the run in
`validating`.

Pinned edit: between :373 and :374 insert:

```python
            if declared is not None and type(declared) is not dict:
                findings.append(
                    _finding(
                        "submission.method_identity_mismatch",
                        f"Published output {output_id!r} declares a method identity that is not an object.",
                        output_id,
                    )
                )
                continue
```

(reuses the registered mismatch code: a non-object identity cannot equal
the exact selected method.)

Regression test `test_phase_semantics_guards_non_object_identity`
(Lane B): call `_validate_phase_semantics` directly with plan stub
SimpleNamespace(identity=SimpleNamespace(phase_id="P3"),
publication_bindings=[{"target": {"record_type": "theory_record"},
"output_ids": ["output.x"]}]), selected_method stub with `to_dict()`
returning {"stable_id": "m", "version": 1, "definition_sha256": "d"},
outputs={"output.x": SimpleNamespace(document={"method_identity":
"not-an-object"})}, findings=[]. Assert: returns normally and findings
contains exactly one submission.method_identity_mismatch. Pre-fix:
AttributeError - the test fails.

## R29: iterative DFS in _has_cycle

Live site: scientific_validators.py:1523-1539; recursion depth is
agent-controlled (`statements` has no maxItems), so a ~1000-deep
dependency chain raises RecursionError instead of a finding.

Pinned edit: replace the recursive inner function with an explicit-stack
iterative DFS preserving three-color semantics exactly:

```python
def _has_cycle(graph: Mapping[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()
    for start in graph:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                visiting.discard(node)
                visited.add(node)
                continue
            if node in visiting:
                return True
            if node in visited:
                continue
            visiting.add(node)
            stack.append((node, True))
            for dependency in graph.get(node, ()):
                if dependency not in visited:
                    stack.append((dependency, False))
    return False
```

Regression tests (Lane A, import `_has_cycle` directly):
`test_has_cycle_deep_chain_iterative`: chain of 5000 nodes (n -> n+1),
assert returns False with no RecursionError. Pre-fix: RecursionError.
`test_has_cycle_deep_cycle_detected`: same 5000-chain plus an edge from
the last node back to node 0, assert returns True. Pre-fix:
RecursionError.

## R30: hasattr feature-check for put_bytes

Live site: output_adapters.py:142-152: the try/except AttributeError
around `artifacts.put_bytes(data)` masks GENUINE bugs raised inside
put_bytes (they silently fall through to the private-path fallback).

Pinned edit:

```python
    # Use put_bytes when the store provides it; genuine failures inside
    # put_bytes propagate (R30).
    put_bytes = getattr(artifacts, "put_bytes", None)
    if callable(put_bytes):
        stored = put_bytes(data)
        return str(stored.sha256)
    # Fallback: store via the artifact hash directly
    sha256 = hashlib.sha256(data).hexdigest()
    artifacts_path = artifacts._paths.root / "raw-outputs" / sha256[:2] / sha256[2:4] / f"{sha256}.tar.gz"
    artifacts_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_path.write_bytes(data)
    return sha256
```

(The fallback path itself is unchanged - out of scope for R30.)

Regression tests (Lane A; workspace = a tmp dir with one file):
`test_preserve_raw_output_propagates_put_bytes_failures`: stub artifacts
with a `put_bytes` method whose body raises AttributeError("genuine
bug"); assert AttributeError propagates out of preserve_raw_output.
Pre-fix: the fallback swallows it and returns a digest - the test fails.
`test_preserve_raw_output_fallback_when_put_bytes_missing`: stub with NO
put_bytes attribute and `_paths.root` = tmp_path/"store"; assert the
fallback writes the tarball and returns its sha256 (passes pre- and
post-fix; guards the fallback).

## R31: companion-scan relative_to guard + stale-leftover skip

Live site: `DefaultOutputAdapter.adapt`, output_adapters.py:91-110.
Two defects: (1) `sibling.relative_to(workspace.resolve())` (:104) is
unguarded - when the workspace is not an ancestor of the output dir it
raises ValueError mid-scan; (2) same-stem leftovers from a PRIOR attempt
(the retry/correction workspace carries old files) are registered as
linked artifacts of the current output.

Pinned interpretation (recorded per the program's ambiguity rule; the
audit does not define "stale"): a companion is STALE when its mtime is
strictly older than the validated output's mtime - files from a prior
attempt predate the current output, while same-attempt companions are
written alongside it. Probe fact: the existing companion tests
(tests/test_wp1_wp2_modules.py:153-195, test_wp1_wp2_integration.py:155)
write the companion at or after the output, so strict-less-than keeps
them green. Latency note: adapt's result is currently discarded at the
single call site (role_execution.py:2804), so this fix hardens latent
machinery only.

Pinned edit inside the sibling loop, after the `suffix in
_MEDIA_TYPE_MAP` check passes and before `data = sibling.read_bytes()`:

```python
                    try:
                        relative = str(sibling.relative_to(workspace.resolve()))
                    except ValueError:
                        # R31: the sibling is not inside the workspace;
                        # skip it instead of crashing the scan.
                        continue
                    if sibling.stat().st_mtime < validated.path.stat().st_mtime:
                        # R31: predates the current output - a stale
                        # leftover from a prior attempt.
                        continue
                    data = sibling.read_bytes()
                    linked.append(
                        LinkedArtifact(
                            source_path=relative,
                            ...
                        )
                    )
```

(i.e. compute `relative` once, guarded; use it in LinkedArtifact.)

Regression tests (Lane A; mirror the OutputSpec/ValidatedOutput
construction from tests/test_wp1_wp2_modules.py:127-145):
`test_companion_scan_skips_outside_workspace`: validated.path under
tmp_path/"elsewhere", a companion .md beside it, workspace =
tmp_path/"unrelated" (mkdir). Assert adapt returns with zero
linked_artifacts and does not raise. Pre-fix: ValueError - the test
fails.
`test_companion_scan_skips_stale_leftovers`: normal in-workspace layout;
two companions, one aged via os.utime to (output_mtime - 100), one
fresh. Assert only the fresh companion is linked. Pre-fix: both are
linked - the test fails.

## R36: dead raise + messageless StopIteration (run_coordinator.py)

Live sites: (a) run() except block :166-169 - `_handle_error` returns
True on every path (:1155-1184 verified), so the trailing `raise` is
dead; (b) `_execution_components` :525-529 - `next(...)` over the
`.instructions` choice raises a messageless StopIteration when absent.

Pinned edits:

(a) Replace :166-169 with:

```python
                except Exception as error:
                    # _handle_error always returns True: every path seals
                    # a terminal state or recognizes the error as settled
                    # (R36).
                    self._handle_error(run_id, error)
                    return
```

(b) Replace the next() lookup with:

```python
        instruction = next(
            (
                str(value)
                for key, value in plan.choice_values.items()
                if key.endswith(".instructions")
            ),
            None,
        )
        if instruction is None:
            raise ValueError("Prepared plan carries no .instructions choice.")
```

Regression test `test_execution_components_reports_missing_instructions`
(Lane B): coordinator via `RunCoordinator.__new__(RunCoordinator)`; stub
`_load_recipe` returning SimpleNamespace(document={"role_resources":
{"role": {"soul_text": "s", "soul_sha256": sha256("s"),
"skills": []}}}), stub `_plan_from_recipe` returning
SimpleNamespace(choice_values={"other.choice": "x"}, stages=(),
<whatever build_output_plan needs - stages=() yields an empty output
plan>). Assert pytest.raises(ValueError, match="instructions"). Pre-fix:
messageless StopIteration (not a ValueError) - the test fails. No
behavioral test for (a) - dead code has no observable behavior; the
source simplification is covered by the suite's existing advancement
tests.

## Environmental (in scope per run directive): version-probe timeout

`LocalHermesExecutor._get_hermes_version` probes `hermes --version` with
`asyncio.wait_for(..., timeout=10)` (local_hermes.py:700-702); under
full-suite load the probe can exceed 10 s, the executor records
"unknown", and tests/test_block4_local_hermes.py::TestHermesVersion::
test_version_cached flakes on `v1 != "unknown"`. Pinned edit: bump the
constant to 30 (single literal at :701). No test depends on the value
(test_version_probe_timeout_kills_child patches wait_for entirely).
No new test; not an R-number; call it out in the commit message as an
environmental fix.
