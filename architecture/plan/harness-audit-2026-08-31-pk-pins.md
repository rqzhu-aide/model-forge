# P-K Pins: Schema helper root and failure signal (R8)

Status: READY FOR DISPATCH. Written 2026-09-02 by the coordinator after
re-probing the live tree (post-P-I, HEAD 31a8bb2). One finding, one
commit. Source finding:
[../harness-audit-2026-08-31.md](../harness-audit-2026-08-31.md) R8.

## Probe facts (verified on the live tree)

1. The three helpers hardcode
   `Path(__file__).resolve().parents[3] / "architecture" / "schemas"`:
   - `_schema_record_type_const` (role_execution.py:1040, root at :1055)
   - `_schema_info` (:1071, root at :1078)
   - `_stableid_positions` (:1237, root at :1263-1264)
2. Silent swallows: `:1060-1061` (returns `""`), `:1106-1107` (returns
   `_empty_schema_info()`), `:1352-1353` (heuristic fallback).
3. Module logger already exists: `logger = logging.getLogger(__name__)`
   at role_execution.py:50. Use it; do not add a new logger.
4. `_STABLEID_POSITIONS_CACHE` (:1234) is keyed by `schema_file` only.
   R25 (P-I) made it store successes only; that stays. The key MUST gain
   the resolved directory or a non-default dir call can poison the cache
   for the default dir (and vice versa).
5. Threading paths, both with a configured SchemaCatalog in scope:
   - `_apply_disclosed_mechanical_repairs` (:67) is called at :2066 and
     :2790, both inside `RoleLifecycleService`, which holds
     `self.schemas` (SchemaCatalog; `.directory` is the resolved,
     configured schemas dir - catalog.py:124, set by
     `SchemaCatalog.load`, catalog.py:131-132).
   - `apply_normalize_transformations` (:465) is called at
     correction_execution.py:532 and :875; both enclosing functions take
     `schemas: SchemaCatalog` (signatures at :464 and :805).
6. Direct test callers pass only the filename
   (test_generation_identity.py:97-100, test_harness_repairs.py:352-373,
   test_id_sanitization.py:151-193, test_p3_hardening_harness.py:204-218),
   so the new parameter MUST be optional with today's resolution as the
   default.
7. theory-record.schema.json declares `created_at` in properties AND in
   required; `_TIMESTAMP_FIELDS = ("created_at", "updated_at")`
   (role_execution.py:1464); `record_type` const is `"theory_record"`;
   additionalProperties is false.
8. A lightweight monolith fixture pattern exists at
   tests/test_normalize_transformations.py:205-270 (OutputSpec +
   ResolvedPhasePlan + OutputPlan construction) - mirror it for the
   wiring test; do not invent a new fixture stack.

## Pinned implementation

### Edit 1: default-dir helper (role_execution.py, near the three helpers)

```python
def _default_schemas_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "architecture" / "schemas"
```

`Path` is already imported at module level (used in existing
signatures). The local `from pathlib import Path as _Path` imports
inside the helpers may be dropped or kept; behavior is what matters.

### Edit 2: `_schema_record_type_const(schema_file, *, schemas_dir=None)`

- Resolve `directory = Path(schemas_dir) if schemas_dir is not None
  else _default_schemas_dir()`.
- Missing file: return `""` silently (unchanged - legitimate
  no-schema-pinned degrade).
- Existing file that fails to read/parse:
  `logger.error("schema record_type const unreadable for %s: %s",
  schema_path, exc)` then return `""`.
- Structure: hoist the path resolution and exists check out of the try;
  the try wraps only the read/parse; downstream const extraction is
  unchanged.

### Edit 3: `_schema_info(schema_file, *, schemas_dir=None)`

Same pattern. Missing file: `_empty_schema_info()` silently. Existing
but unreadable/unparseable: `logger.error(...)` naming the path, then
`_empty_schema_info()`. The info-dict computation on a successfully
parsed schema is NOT inside the broad try anymore (it is pure dict
work; the realistic failure was the read/parse).

### Edit 4: `_stableid_positions(schema_file, *, schemas_dir=None)`

- Resolve `directory` as above; the cross-file `$ref` loader
  (`_resolve_ref`, :1280) uses the same `directory`.
- Cache key becomes `(str(directory), schema_file)` - both the lookup
  (:1255) and the store (:1351). Do NOT force `.resolve()` on the dir
  for the key (production callers pass the already-resolved
  `SchemaCatalog.directory`; tests pass absolute tmp paths).
- Missing file: keep the current `FileNotFoundError` -> silent
  heuristic fallback (audit's target is parse failure of EXISTING
  files). Split the except:
  - `except FileNotFoundError:` -> heuristic, no log.
  - `except Exception as exc:` -> `logger.error(...)` naming the path,
    then heuristic.
- R25 invariant preserved: cache store stays inside the success branch
  only.

### Edit 5: `_apply_disclosed_mechanical_repairs` gains keyword

`schemas_dir: Path | None = None` (append after
`canonical_source_lookup`). Pass it to all three helper calls (:157,
:173, :231).

### Edit 6: `apply_normalize_transformations` gains keyword

`schemas_dir: Path | None = None`. Pass it at :501 (`_schema_info`)
and :552 (`_stableid_positions`).

### Edit 7: RoleLifecycleService call sites

Both `_apply_disclosed_mechanical_repairs` calls (:2066, :2790) gain
`schemas_dir=self.schemas.directory`.

### Edit 8: correction_execution.py call sites

Both `apply_normalize_transformations` calls (:532, :875) gain
`schemas_dir=schemas.directory` (`schemas` is the enclosing function's
SchemaCatalog parameter at :464 and :805).

### Edit 9: new test file `tests/test_schema_helper_root.py`

Ten tests. Tests 1-8 and 10 fail on pre-fix code with
`TypeError: ... unexpected keyword argument 'schemas_dir'`; test 9
fails identically (monolith keyword). Predicted pre-fix failure mode
for every test is that TypeError - the coordinator verifies.

1. `test_schema_record_type_const_honors_non_default_root`: copy
   theory-record.schema.json into tmp_path, rewrite the record_type
   const to `"probe_record"`;
   `_schema_record_type_const("theory-record.schema.json",
   schemas_dir=tmp_path) == "probe_record"`; default call still
   `"theory_record"`.
2. `test_schema_info_honors_non_default_root`: copy
   theory-record.schema.json into tmp_path, remove `created_at` from
   properties AND required; `_schema_info(..., schemas_dir=tmp_path)`
   has no `created_at` in `timestamps` or `properties`; the default
   call still has it in both.
3. `test_stableid_positions_honors_non_default_root`: tmp_path holds a
   hand-written minimal `probe.schema.json` (draft 2020-12, one
   property `probe_id` with `"$ref": "#/$defs/stableId"`, local
   `$defs.stableId` string pattern);
   `_stableid_positions("probe.schema.json", schemas_dir=tmp_path)`
   returns `scalar_keys == {"probe_id"}`, `heuristic` False; the same
   name against the default dir returns `heuristic` True (file
   missing).
4. `test_stableid_positions_cache_isolated_by_schemas_dir`: two tmp
   dirs A and B each holding `probe.schema.json` with different
   coverage (A: `probe_id`; B: `other_id`); call A then B; B's result
   reflects B. Catches cache-key poisoning.
5. `test_malformed_existing_schema_logs_error_record_type` (caplog):
   tmp_path holds `theory-record.schema.json` containing invalid JSON;
   result is `""` and caplog has at least one ERROR record from logger
   `model_forge.harness.role_execution` naming the file.
6. `test_malformed_existing_schema_logs_error_schema_info` (caplog):
   same malformed file; result equals `_empty_schema_info()` and an
   ERROR record is present.
7. `test_malformed_existing_schema_logs_error_stableid` (caplog): same
   malformed file; result has `heuristic` True and an ERROR record is
   present.
8. `test_missing_schema_file_degrades_without_error_log` (caplog):
   empty tmp dir; all three helpers degrade (`""` /
   `_empty_schema_info()` / heuristic True) with ZERO error records.
   Behavior-preservation pin for the missing-file path.
9. `test_repair_monolith_uses_threaded_schemas_dir`: mirror the
   fixture at tests/test_normalize_transformations.py:205-270
   (theory-record spec, run_root with output.json). tmp schemas dir
   holds theory-record.schema.json with `created_at` removed from
   properties and required. Run `_apply_disclosed_mechanical_repairs`
   with `schemas_dir=<tmp>` on a doc missing `created_at`; assert the
   repaired doc does NOT gain `created_at`. Control: the same fixture
   without `schemas_dir` DOES inject `created_at`.
10. `test_normalize_transformations_threads_schemas_dir`: codes =
    `{"timestamp_injection"}`, spec SimpleNamespace(schema_file=
    "theory-record.schema.json", relative_path="output.json") (mirror
    tests/test_normalize_transformations.py THEORY_SPEC); same
    created_at-stripped tmp dir; assert `created_at` not injected with
    `schemas_dir=<tmp>`, injected by default.

Expected suite delta: 1388 -> 1398 (+10).

## Boundaries

- No behavior change for the default resolution, the missing-file
  degrade, or the R25 cache-stores-success rule.
- No new error codes, no architecture/ doc edits besides this pins doc
  and the plan's DONE line (coordinator-owned).
- The audit's "or fail closed" alternative is NOT taken: ERROR log +
  existing degrade, per the plan's first option. Rationale: repair
  helpers must never turn a previously-closing run into a crash; the
  signal is the fix.
- `harness_owned_fields` (envelope.py:219) is a static in-memory map,
  no filesystem access - out of scope, confirmed not affected by R8.
