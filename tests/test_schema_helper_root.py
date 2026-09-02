"""P-K (R8): configured schemas dir threading + parse-failure ERROR signal.

Covers the three schema helpers in ``model_forge.harness.role_execution``
(``_schema_record_type_const``, ``_schema_info``, ``_stableid_positions``)
and the two production entry points
(``_apply_disclosed_mechanical_repairs``, ``apply_normalize_transformations``):

1. A non-default ``schemas_dir`` is honored by every helper.
2. The stableId coverage cache is keyed by (directory, schema_file) so a
   non-default dir call cannot poison the default dir (and vice versa).
3. An EXISTING but unparseable schema file degrades exactly as before
   ("" / empty info / heuristic fallback) AND emits an ERROR log record
   naming the path.
4. A MISSING schema file still degrades silently (no ERROR record).
5. Both production entry points thread ``schemas_dir`` down to the
   helpers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from model_forge.harness.role_execution import (
    _apply_disclosed_mechanical_repairs,
    _empty_schema_info,
    _schema_info,
    _schema_record_type_const,
    _stableid_positions,
    apply_normalize_transformations,
)

TS = "2026-01-01T00:00:00+00:00"
LOGGER_NAME = "model_forge.harness.role_execution"

DEFAULT_SCHEMAS = (
    Path(__file__).resolve().parents[1] / "architecture" / "schemas"
)
THEORY_SCHEMA_FILE = "theory-record.schema.json"


def _copy_theory_schema(target_dir: Path) -> dict:
    schema = json.loads((DEFAULT_SCHEMAS / THEORY_SCHEMA_FILE).read_text())
    (target_dir / THEORY_SCHEMA_FILE).write_text(json.dumps(schema))
    return schema


def _strip_created_at(schema: dict) -> dict:
    schema["properties"].pop("created_at", None)
    if "created_at" in schema.get("required", []):
        schema["required"] = [f for f in schema["required"] if f != "created_at"]
    return schema


def _probe_schema(scalar_key: str) -> str:
    return json.dumps({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {scalar_key: {"$ref": "#/$defs/stableId"}},
        "$defs": {
            "stableId": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
            },
        },
    })


def _error_records(caplog) -> list:
    return [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME and record.levelno >= logging.ERROR
    ]


def test_schema_record_type_const_honors_non_default_root(tmp_path: Path) -> None:
    schema = _copy_theory_schema(tmp_path)
    schema["properties"]["record_type"]["const"] = "probe_record"
    (tmp_path / THEORY_SCHEMA_FILE).write_text(json.dumps(schema))

    assert (
        _schema_record_type_const(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
        == "probe_record"
    )
    # Default resolution is unchanged.
    assert _schema_record_type_const(THEORY_SCHEMA_FILE) == "theory_record"


def test_schema_info_honors_non_default_root(tmp_path: Path) -> None:
    schema = _strip_created_at(_copy_theory_schema(tmp_path))
    (tmp_path / THEORY_SCHEMA_FILE).write_text(json.dumps(schema))

    info = _schema_info(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
    assert "created_at" not in info["timestamps"]
    assert "created_at" not in info["properties"]

    default_info = _schema_info(THEORY_SCHEMA_FILE)
    assert "created_at" in default_info["timestamps"]
    assert "created_at" in default_info["properties"]


def test_stableid_positions_honors_non_default_root(tmp_path: Path) -> None:
    (tmp_path / "probe.schema.json").write_text(_probe_schema("probe_id"))

    coverage = _stableid_positions("probe.schema.json", schemas_dir=tmp_path)
    assert coverage["scalar_keys"] == {"probe_id"}
    assert coverage["heuristic"] is False

    # The same filename does not exist in the default dir: heuristic fallback.
    default_coverage = _stableid_positions("probe.schema.json")
    assert default_coverage["heuristic"] is True


def test_stableid_positions_cache_isolated_by_schemas_dir(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "probe.schema.json").write_text(_probe_schema("probe_id"))
    (dir_b / "probe.schema.json").write_text(_probe_schema("other_id"))

    coverage_a = _stableid_positions("probe.schema.json", schemas_dir=dir_a)
    assert coverage_a["scalar_keys"] == {"probe_id"}
    coverage_b = _stableid_positions("probe.schema.json", schemas_dir=dir_b)
    assert coverage_b["scalar_keys"] == {"other_id"}


def test_malformed_existing_schema_logs_error_record_type(
    tmp_path: Path, caplog
) -> None:
    (tmp_path / THEORY_SCHEMA_FILE).write_text("{ not valid json")
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = _schema_record_type_const(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
    assert result == ""
    errors = _error_records(caplog)
    assert errors
    assert any(THEORY_SCHEMA_FILE in record.getMessage() for record in errors)


def test_malformed_existing_schema_logs_error_schema_info(
    tmp_path: Path, caplog
) -> None:
    (tmp_path / THEORY_SCHEMA_FILE).write_text("{ not valid json")
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = _schema_info(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
    assert result == _empty_schema_info()
    errors = _error_records(caplog)
    assert errors
    assert any(THEORY_SCHEMA_FILE in record.getMessage() for record in errors)


def test_malformed_existing_schema_logs_error_stableid(
    tmp_path: Path, caplog
) -> None:
    (tmp_path / THEORY_SCHEMA_FILE).write_text("{ not valid json")
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        result = _stableid_positions(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
    assert result["heuristic"] is True
    errors = _error_records(caplog)
    assert errors
    assert any(THEORY_SCHEMA_FILE in record.getMessage() for record in errors)


def test_missing_schema_file_degrades_without_error_log(
    tmp_path: Path, caplog
) -> None:
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        const = _schema_record_type_const(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
        info = _schema_info(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
        coverage = _stableid_positions(THEORY_SCHEMA_FILE, schemas_dir=tmp_path)
    assert const == ""
    assert info == _empty_schema_info()
    assert coverage["heuristic"] is True
    assert _error_records(caplog) == []


def _monolith_fixture(run_root: Path) -> tuple:
    """Mirror of tests/test_normalize_transformations.py:205-270."""
    from model_forge.contracts import (
        ResolvedPhasePlan,
        ResolvedRoleStep,
        ResolvedStage,
    )
    from model_forge.domain import PhaseContractIdentity
    from model_forge.harness.outputs import OutputPlan, OutputSpec

    spec = OutputSpec(
        contract_output_id="test.output",
        output_id="test.output.v1",
        output_kind="record",
        producer="data_analyst",
        stage_id="test",
        stage_sequence=1,
        schema_file=THEORY_SCHEMA_FILE,
        schema_application="",
        relative_path="output.json",
        required=True,
    )
    plan = ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id="P2",
            contract_version="1.0.0",
            phase_contract_sha256="a" * 64,
        ),
        mode_id="p2.method_changes",
        choice_values={},
        context_policy="current_only",
        stages=(ResolvedStage(
            sequence=1,
            stage_id="test",
            execution="serial",
            objective="test",
            role_steps=(ResolvedRoleStep(
                role="data_analyst", input_ids=(), output_ids=("test.output",),
            ),),
            writes=(),
            handoff_required=False,
            isolation_rule=None,
        ),),
        output_contracts=(),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )
    return spec, OutputPlan(specs=(spec,)), plan.stages[0]


def test_repair_monolith_uses_threaded_schemas_dir(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    stripped = _strip_created_at(_copy_theory_schema(schemas_dir))
    (schemas_dir / THEORY_SCHEMA_FILE).write_text(json.dumps(stripped))

    spec, output_plan, stage = _monolith_fixture(tmp_path)

    # Non-default root: created_at is not in the stripped schema, so the
    # repair pass must NOT inject it.
    run_root = tmp_path / "run_threaded"
    run_root.mkdir()
    (run_root / "output.json").write_text(json.dumps({"record_id": "rec-1"}))
    _apply_disclosed_mechanical_repairs(
        run_root=run_root,
        output_plan=output_plan,
        stage=stage,
        role="data_analyst",
        run_facts=None,
        schemas_dir=schemas_dir,
    )
    repaired = json.loads((run_root / "output.json").read_text())
    assert "created_at" not in repaired

    # Control: default resolution DOES inject created_at.
    control_root = tmp_path / "run_default"
    control_root.mkdir()
    (control_root / "output.json").write_text(json.dumps({"record_id": "rec-1"}))
    _apply_disclosed_mechanical_repairs(
        run_root=control_root,
        output_plan=output_plan,
        stage=stage,
        role="data_analyst",
        run_facts=None,
    )
    control = json.loads((control_root / "output.json").read_text())
    assert "created_at" in control


def test_normalize_transformations_threads_schemas_dir(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    schemas_dir.mkdir()
    stripped = _strip_created_at(_copy_theory_schema(schemas_dir))
    (schemas_dir / THEORY_SCHEMA_FILE).write_text(json.dumps(stripped))

    spec = SimpleNamespace(
        schema_file=THEORY_SCHEMA_FILE,
        relative_path="output.json",
    )

    doc = {"record_id": "rec-1"}
    changed = apply_normalize_transformations(
        doc,
        spec=spec,
        codes={"timestamp_injection"},
        ts=TS,
        path=tmp_path / "output.json",
        schemas_dir=schemas_dir,
    )
    assert changed is False
    assert "created_at" not in doc

    control = {"record_id": "rec-1"}
    changed_control = apply_normalize_transformations(
        control,
        spec=spec,
        codes={"timestamp_injection"},
        ts=TS,
        path=tmp_path / "output.json",
    )
    assert changed_control is True
    assert control["created_at"] == TS
