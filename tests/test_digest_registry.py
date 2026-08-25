from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from model_forge.digests import (
    DigestConstructionError,
    DigestContractNotFound,
    DigestContractRegistry,
    DigestMismatchError,
    DigestRegistryError,
)
from model_forge.errors import ModelForgeError
from model_forge.schemas import SchemaCatalog


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
CONTRACTS = ARCHITECTURE / "contracts"
EXAMPLES = ARCHITECTURE / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _registry_document() -> dict:
    return json.loads((CONTRACTS / "digest-contracts.json").read_text("utf-8"))


def _write_registry(tmp_path: Path, document: dict, name: str = "registry.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def schemas() -> SchemaCatalog:
    return SchemaCatalog.load(ARCHITECTURE / "schemas")


@pytest.fixture(scope="module")
def registry(schemas: SchemaCatalog) -> DigestContractRegistry:
    return DigestContractRegistry.load(
        CONTRACTS / "digest-contracts.json",
        schemas,
    )


def test_registry_loads_every_declared_contract(registry: DigestContractRegistry) -> None:
    assert len(registry) == 45
    contract = registry.contract("phase_contract.content")
    assert contract.construction == "rfc8785_sha256"
    assert contract.digest_location.kind == "referenced"
    with pytest.raises(DigestContractNotFound):
        registry.contract("missing.contract")


def test_specialized_research_outputs_have_exact_content_contracts(
    registry: DigestContractRegistry,
) -> None:
    expected = {
        "empirical_protocol.content": "empirical-protocol.schema.json",
        "manuscript_package.content": "manuscript-package.schema.json",
        "review_finding.content": "review-finding.schema.json",
        "review_report.content": "review-report.schema.json",
        "theory_record.content": "theory-record.schema.json",
    }
    for contract_id, schema_file in expected.items():
        contract = registry.contract(contract_id)
        assert contract.schema_file == schema_file
        assert contract.instance_pointer == ""
        assert contract.digest_location.kind == "embedded"
        assert contract.digest_location.json_pointer == "/content_sha256"
        assert contract.construction == "rfc8785_sha256"
        assert contract.payload_pointer == ""
        assert contract.excluded_json_pointers == ("/content_sha256",)


def test_registry_mapping_is_immutable(registry: DigestContractRegistry) -> None:
    assert isinstance(registry.contracts, MappingProxyType)
    with pytest.raises(TypeError):
        registry.contracts["new.contract"] = registry.contract(  # type: ignore[index]
            "attention_item.content"
        )


def test_constructor_rejects_duplicate_contract_ids(
    registry: DigestContractRegistry,
) -> None:
    contract = registry.contract("attention_item.content")
    with pytest.raises(DigestRegistryError, match="duplicated"):
        DigestContractRegistry((contract, contract))


def test_rfc8785_full_object_and_payload_digests(
    registry: DigestContractRegistry,
) -> None:
    method = _load("method.example.json")
    assert registry.require_match("method_record.content", method) == method[
        "content_sha256"
    ]
    assert registry.require_match("method_record.definition", method) == method[
        "identity"
    ]["definition_sha256"]


def test_rfc8785_projection_digest(registry: DigestContractRegistry) -> None:
    prepared = _load("prepared-role-context.example.json")
    assert registry.require_match(
        "prepared_role_context.prepared", prepared
    ) == prepared["prepared_context_sha256"]


def test_projection_supports_numeric_object_keys(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    contract = next(
        item
        for item in document["contracts"]
        if item["contract_id"] == "prepared_role_context.prepared"
    )
    contract["included_json_pointers"] = ["/0"]
    altered = DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)
    value = {"0": {"answer": 42}}
    expected = hashlib.sha256(b'{"0":{"answer":42}}').hexdigest()
    assert altered.compute("prepared_role_context.prepared", value) == expected


def test_hex_concatenation_digest(registry: DigestContractRegistry) -> None:
    event = _load("authority-event.example.json")
    assert registry.require_match("authority_event.content", event) == event[
        "content_sha256"
    ]
    assert registry.require_match("authority_event.root", event) == event[
        "event_root_sha256"
    ]


def test_copy_final_event_digest_and_nested_empty_value(
    registry: DigestContractRegistry,
) -> None:
    run_state = _load("run-state.example.json")
    assert registry.require_match("run_state.journal_root", run_state) == run_state[
        "journal_root_sha256"
    ]
    snapshot = {"access_ledger": {"events": [], "head_sha256": "0" * 64}}
    assert registry.require_match(
        "role_context.access_ledger_head", snapshot
    ) == "0" * 64


def test_run_state_event_wildcard_computes_and_verifies_every_instance(
    registry: DigestContractRegistry,
) -> None:
    run_state = _load("run-state.example.json")
    expected = tuple(event["event_sha256"] for event in run_state["events"])
    assert len(expected) == 8
    assert registry.compute_all("run_state.event", run_state) == expected
    assert registry.require_match_all("run_state.event", run_state) == expected
    assert registry.verify_all("run_state.event", run_state) == expected
    with pytest.raises(DigestConstructionError, match="selected 8 instances"):
        registry.compute_one("run_state.event", run_state)


def test_empty_wildcard_selection_is_explicit(
    registry: DigestContractRegistry,
) -> None:
    run_state = {"events": []}
    assert registry.compute_all("run_state.event", run_state) == ()
    assert registry.require_match_all("run_state.event", run_state) == ()
    with pytest.raises(DigestConstructionError, match="selected 0 instances"):
        registry.compute_one("run_state.event", run_state)


def test_wildcard_verification_detects_one_mutated_instance(
    registry: DigestContractRegistry,
) -> None:
    run_state = _load("run-state.example.json")
    run_state["events"][3]["reason"] = "Changed event reason."
    with pytest.raises(DigestMismatchError) as caught:
        registry.require_match_all("run_state.event", run_state)
    assert caught.value.instance_pointer == "/events/3"
    assert caught.value.pointer == "/events/3"
    assert "/events/3" in str(caught.value)


def test_referenced_wildcard_requires_one_expected_digest_per_instance(
    registry: DigestContractRegistry,
) -> None:
    manifest = _load("run-manifest.example.json")
    computed = registry.compute_all("run_manifest.role_plan_entry", manifest)
    assert len(computed) == len(manifest["role_plan"])
    assert registry.require_match_all(
        "run_manifest.role_plan_entry",
        manifest,
        expected=computed,
    ) == computed
    with pytest.raises(DigestConstructionError, match="requires expected"):
        registry.require_match_all("run_manifest.role_plan_entry", manifest)
    with pytest.raises(DigestConstructionError, match="received 1 expected"):
        registry.require_match_all(
            "run_manifest.role_plan_entry",
            manifest,
            expected=(computed[0],),
        )


def test_referenced_bytes_use_full_document_instance_pointer(
    registry: DigestContractRegistry,
) -> None:
    audit = _load("command-attempt-audit-unauthenticated-rejected.example.json")
    raw = (EXAMPLES / "raw-command-request-malformed.txt").read_bytes()
    expected_uri = audit["raw_request"]["uri"]
    seen: list[str] = []

    def resolve(uri: str) -> bytes:
        seen.append(uri)
        assert uri == expected_uri
        return raw

    assert registry.require_match(
        "command_attempt_audit.raw_request",
        audit,
        resolve,
    ) == audit["raw_request"]["sha256"]
    assert registry.compute(
        "command_attempt_audit.raw_request",
        audit,
        resolve,
    ) == audit["raw_request"]["sha256"]
    assert seen == [expected_uri, expected_uri]


def test_referenced_bytes_require_full_document_and_exact_byte_resolver(
    registry: DigestContractRegistry,
) -> None:
    audit = _load("command-attempt-audit-unauthenticated-rejected.example.json")
    with pytest.raises(DigestConstructionError, match="requires a byte resolver"):
        registry.compute("command_attempt_audit.raw_request", audit)
    with pytest.raises(DigestConstructionError, match="must return bytes"):
        registry.compute(
            "command_attempt_audit.raw_request",
            audit,
            lambda _uri: "not bytes",  # type: ignore[return-value]
        )

    def fail_resolver(_uri: str) -> bytes:
        raise RuntimeError("private resolver detail")

    with pytest.raises(DigestConstructionError, match="byte resolver failed") as failure:
        registry.compute(
            "command_attempt_audit.raw_request",
            audit,
            fail_resolver,
        )
    assert "private resolver detail" not in str(failure.value)

    with pytest.raises(DigestConstructionError, match="instance boundary") as caught:
        registry.compute(
            "command_attempt_audit.raw_request",
            audit["raw_request"],
            lambda _uri: b"bytes",
        )
    assert isinstance(caught.value, ModelForgeError)


def test_referenced_contract_requires_explicit_expected_digest(
    registry: DigestContractRegistry,
) -> None:
    phase = json.loads((CONTRACTS / "phases" / "P4.json").read_text("utf-8"))
    # P4 contract 2.2.0 (F-1c: record_type declared on scientific-record
    # candidate outputs p4.analyst_synthesis / p4.theory_audit) - digest
    # follows the contract; updated when P4 bumps.
    expected = "b13047fe488b8f52fdca6d6404e17401bcc971b7638d7f2899f0f23016870c47"
    assert registry.require_match(
        "phase_contract.content", phase, expected=expected
    ) == expected
    with pytest.raises(DigestConstructionError):
        registry.require_match("phase_contract.content", phase)


def test_embedded_expected_cannot_bypass_stored_digest(
    registry: DigestContractRegistry,
) -> None:
    method = _load("method.example.json")
    with pytest.raises(DigestConstructionError, match="does not accept expected"):
        registry.require_match(
            "method_record.content",
            method,
            expected=registry.compute("method_record.content", method),
        )


def test_mutation_is_detected(registry: DigestContractRegistry) -> None:
    method = _load("method.example.json")
    mutated = copy.deepcopy(method)
    mutated["title"] = "Changed title"
    with pytest.raises(DigestMismatchError):
        registry.require_match("method_record.content", mutated)


def test_pointer_and_jcs_failures_are_stable_construction_errors(
    registry: DigestContractRegistry,
) -> None:
    event = _load("authority-event.example.json")
    del event["prior_event_root_sha256"]
    with pytest.raises(DigestConstructionError) as pointer_error:
        registry.compute("authority_event.root", event)
    assert isinstance(pointer_error.value, ModelForgeError)
    assert pointer_error.value.code == "digest_construction_failed"

    method = _load("method.example.json")
    method["unsupported_number"] = 0.5
    with pytest.raises(DigestConstructionError) as jcs_error:
        registry.compute("method_record.content", method)
    assert isinstance(jcs_error.value, ModelForgeError)
    assert jcs_error.value.code == "digest_construction_failed"


def test_duplicate_contract_ids_are_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    document["contracts"].append(copy.deepcopy(document["contracts"][0]))
    with pytest.raises(DigestRegistryError, match="must be unique"):
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)


def test_duplicate_json_keys_are_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    text = (CONTRACTS / "digest-contracts.json").read_text("utf-8")
    text = text.replace(
        '"contract_id":  "attention_item.content"',
        '"contract_id": "attention_item.content", "contract_id": "duplicate"',
        1,
    )
    path = tmp_path / "duplicate-key.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DigestRegistryError, match="duplicate JSON object key"):
        DigestContractRegistry.load(path, schemas)


def test_nonfinite_registry_number_is_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    text = (CONTRACTS / "digest-contracts.json").read_text("utf-8")
    text = text.replace('"registry_version":  "1.0.0"', '"registry_version": NaN', 1)
    path = tmp_path / "nonfinite.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DigestRegistryError, match="non-finite"):
        DigestContractRegistry.load(path, schemas)


def test_unknown_construction_is_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    document["contracts"][0]["construction"] = "invented_hash"
    with pytest.raises(DigestRegistryError, match="unknown construction"):
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)


def test_registry_is_validated_against_its_schema(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    document["numeric_profile"]["failure_policy"] = "accept anything"
    with pytest.raises(DigestRegistryError, match="does not satisfy") as caught:
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)
    assert caught.value.code == "digest_registry_invalid"


def test_registry_rejects_unknown_primary_schema_file(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    document["contracts"][0]["schema_file"] = "missing.schema.json"
    with pytest.raises(DigestRegistryError, match="missing.schema.json"):
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)


def test_registry_rejects_unknown_reference_schema_file(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    referenced = next(
        item
        for item in document["contracts"]
        if item["contract_id"] == "phase_contract.content"
    )
    referenced["digest_location"]["reference_schema_files"] = [
        "missing.schema.json"
    ]
    with pytest.raises(DigestRegistryError, match="missing.schema.json"):
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)


def test_pointer_schema_matches_runtime_wildcard_grammar(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    invalid_selector = _registry_document()
    invalid_selector["contracts"][0]["instance_pointer"] = "/items/foo*bar"
    issues = schemas.validate(
        "digest-contract-registry.schema.json",
        invalid_selector,
    )
    assert any(issue.code == "schema.pattern" for issue in issues)

    literal_pointer = _registry_document()
    literal_pointer["contracts"][0]["payload_pointer"] = "/literal*key"
    assert not schemas.validate(
        "digest-contract-registry.schema.json",
        literal_pointer,
    )
    altered = DigestContractRegistry.load(
        _write_registry(tmp_path, literal_pointer, "literal-star.json"),
        schemas,
    )
    instance = {
        "literal*key": {
            "content_sha256": "0" * 64,
            "value": 1,
        }
    }
    expected = hashlib.sha256(b'{"value":1}').hexdigest()
    assert altered.compute("attention_item.content", instance) == expected


def test_malformed_registry_pointer_is_a_registry_error(
    tmp_path: Path,
    schemas: SchemaCatalog,
) -> None:
    document = _registry_document()
    document["contracts"][0]["instance_pointer"] = "/items/not*selector"
    with pytest.raises(DigestRegistryError, match="malformed JSON pointer") as caught:
        DigestContractRegistry.load(_write_registry(tmp_path, document), schemas)
    assert isinstance(caught.value, ModelForgeError)
    assert caught.value.code == "digest_registry_invalid"
