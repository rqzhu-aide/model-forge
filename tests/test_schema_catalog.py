from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_forge.errors import SchemaCatalogError, SchemaValidationError
from model_forge.json_io import load_json
from model_forge.schemas import SchemaCatalog


NEW_VERSION = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = NEW_VERSION / "architecture" / "schemas"
EXAMPLES = NEW_VERSION / "architecture" / "examples"


@pytest.fixture(scope="module")
def catalog() -> SchemaCatalog:
    return SchemaCatalog.load(SCHEMA_DIRECTORY)


def test_catalog_loads_all_47_draft_2020_12_schemas(
    catalog: SchemaCatalog,
) -> None:
    assert len(catalog) == 47
    assert len(catalog.schema_names) == 47
    assert len(catalog.schema_ids) == 47
    assert catalog.schema_names == tuple(sorted(catalog.schema_names))
    assert catalog.schema_ids == tuple(sorted(catalog.schema_ids))


def test_catalog_resolves_by_filename_and_exact_id(catalog: SchemaCatalog) -> None:
    name = "method.schema.json"
    schema_id = "https://model-forge.local/architecture/schemas/method.schema.json"
    assert name in catalog
    assert schema_id in catalog
    assert catalog.get(name) == catalog.get(schema_id)
    assert catalog.resolve(name) == catalog.resolve(schema_id)


def test_catalog_validates_representative_schema_with_registered_refs(
    catalog: SchemaCatalog,
) -> None:
    method = load_json(EXAMPLES / "method.example.json")
    assert catalog.validate("method.schema.json", method) == ()
    catalog.require_valid(
        "https://model-forge.local/architecture/schemas/method.schema.json",
        method,
    )


def test_validation_issues_are_deterministic_and_pointer_addressed(
    catalog: SchemaCatalog,
) -> None:
    invalid = {
        "schema_version": "1.0.0",
        "stable_id": "INVALID",
        "version": True,
        "definition_sha256": "short",
    }
    first = catalog.validate("method.schema.json", invalid)
    second = catalog.validate("method.schema.json", invalid)
    assert first == second
    assert first == tuple(
        sorted(
            first,
            key=lambda issue: (
                issue.json_pointer,
                issue.schema_pointer,
                issue.code,
                issue.message,
            ),
        )
    )
    assert first
    assert all(issue.code.startswith("schema.") for issue in first)
    assert all(issue.json_pointer == "" or issue.json_pointer.startswith("/") for issue in first)
    assert all(issue.schema_pointer.startswith("/") for issue in first)


def test_require_valid_raises_stable_error_with_issues(
    catalog: SchemaCatalog,
) -> None:
    with pytest.raises(SchemaValidationError) as raised:
        catalog.require_valid("method.schema.json", {})
    error = raised.value
    assert error.code == "schema.invalid_document"
    assert error.schema_ref == "method.schema.json"
    assert error.issues
    assert str(error).startswith("schema.invalid_document:")


def test_unknown_schema_reference_fails_closed(catalog: SchemaCatalog) -> None:
    with pytest.raises(SchemaCatalogError) as raised:
        catalog.validate("missing.schema.json", {})
    assert raised.value.code == "schema.unknown"


def test_catalog_rejects_duplicate_schema_ids(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://model-forge.local/test/duplicate",
        "type": "object",
    }
    (tmp_path / "a.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (tmp_path / "b.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(SchemaCatalogError) as raised:
        SchemaCatalog.load(tmp_path)
    assert raised.value.code == "schema.duplicate_id"


def test_catalog_rejects_unregistered_external_reference(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://model-forge.local/test/root",
        "$ref": "missing.schema.json",
    }
    (tmp_path / "root.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    with pytest.raises(SchemaCatalogError) as raised:
        SchemaCatalog.load(tmp_path)
    assert raised.value.code == "schema.unregistered_reference"

def test_catalog_rejects_missing_local_reference_fragment(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://model-forge.local/test/root.schema.json",
        "$defs": {"present": {"type": "string"}},
        "$ref": "#/$defs/missing",
    }
    (tmp_path / "root.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    with pytest.raises(SchemaCatalogError) as raised:
        SchemaCatalog.load(tmp_path)
    assert raised.value.code == "schema.unregistered_reference"


def test_catalog_resolves_fragments_in_nested_id_scope(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://model-forge.local/test/root.schema.json",
        "$defs": {
            "scoped": {
                "$id": "nested.schema.json",
                "$defs": {"value": {"type": "integer"}},
                "$ref": "#/$defs/value",
            }
        },
        "$ref": "nested.schema.json#/$defs/value",
    }
    (tmp_path / "root.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    catalog = SchemaCatalog.load(tmp_path)
    assert catalog.validate("root.schema.json", 3) == ()
    assert catalog.validate("root.schema.json", "three")


def test_reference_like_values_in_annotations_are_not_resolved(
    tmp_path: Path,
) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://model-forge.local/test/root.schema.json",
        "type": "object",
        "examples": [{"$ref": "not-a-schema-reference.schema.json"}],
    }
    (tmp_path / "root.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    assert len(SchemaCatalog.load(tmp_path)) == 1


# ---------------------------------------------------------------------------
# ADR-015: broadcast handoff addressing + failing-property naming (K5-1)
# ---------------------------------------------------------------------------


def test_broadcast_handoff_without_to_role_validates(
    catalog: SchemaCatalog,
) -> None:
    handoff = load_json(EXAMPLES / "handoff.example.json")
    handoff.pop("to_role", None)
    assert catalog.validate("handoff.schema.json", handoff) == ()


def test_invalid_to_role_still_rejected(catalog: SchemaCatalog) -> None:
    handoff = load_json(EXAMPLES / "handoff.example.json")
    handoff["to_role"] = "nobody"
    issues = catalog.validate("handoff.schema.json", handoff)
    assert any(
        issue.code == "schema.enum" and issue.failing_property == "to_role"
        for issue in issues
    )


def test_failing_property_names_root_required_field(
    catalog: SchemaCatalog,
) -> None:
    handoff = load_json(EXAMPLES / "handoff.example.json")
    handoff.pop("phase")
    issues = catalog.validate("handoff.schema.json", handoff)
    assert any(
        issue.code == "schema.required" and issue.failing_property == "phase"
        for issue in issues
    )


def test_failing_property_is_none_for_nested_errors(
    catalog: SchemaCatalog,
) -> None:
    handoff = load_json(EXAMPLES / "handoff.example.json")
    handoff["handoff_artifact"].pop("sha256")
    issues = catalog.validate("handoff.schema.json", handoff)
    required = [issue for issue in issues if issue.code == "schema.required"]
    assert required
    assert all(issue.failing_property is None for issue in required)
