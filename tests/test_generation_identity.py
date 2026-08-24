"""F-1: candidates carry no generation identity.

Pins from architecture/plans/f1-candidate-generation-identity-plan-2026-08-23.md:

(a) A source-changes/synthesis/coverage candidate WITHOUT generation_id
    passes closure validation (the fresh-library regression from the failed
    P1 run 2026-08-23).
(b) An agent-supplied generation_id/generation_number is STRIPPED before
    sealing when the run-facts value is empty (fabrication channel closed),
    and overwritten when the run-facts value is non-empty.
(c) Publisher derivation of generation identity at promotion is unchanged
    (digest-bound inputs; candidates never carry it).
"""

from __future__ import annotations

import pytest

from model_forge.harness.envelope import SealedRunFacts, populate_harness_fields
from model_forge.harness.publication import _generation_id
from model_forge.json_io import load_json
from model_forge.schemas import SchemaCatalog

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = REPO_ROOT / "architecture" / "schemas"
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "golden"

GENERATION_ID_DESCRIPTION = (
    "Assigned by the publisher at promotion; candidates must not carry it "
    "(the harness strips it at closure)."
)


def _facts(**overrides) -> SealedRunFacts:
    """Run facts as the harness actually seals them: no generation identity."""
    defaults = dict(
        project_id="proj.test",
        run_id="run.p1.test.0123456789abcdef0123456789abcdef",
        phase="P1",
        mode="p1.literature_update",
        role="research_lead",
        method_identity={},
        generation_id="",
        generation_number=0,
        schema_version="1.0.0",
        manifest_sha256="b" * 64,
        sealed_basis_digest="c" * 64,
        produced_at="2026-08-23T00:00:00Z",
        record_type="",
    )
    defaults.update(overrides)
    return SealedRunFacts(**defaults)


@pytest.fixture(scope="module")
def catalog() -> SchemaCatalog:
    return SchemaCatalog.load(SCHEMA_DIRECTORY)


class TestFreshLibraryClosureWithoutGenerationId:
    """(a) Candidates without generation_id pass closure validation."""

    def test_source_changes_item_without_generation_id_validates(
        self, catalog: SchemaCatalog
    ) -> None:
        candidate = load_json(GOLDEN / "literature-source.example.json")
        del candidate["generation_id"]
        closed = populate_harness_fields(
            candidate,
            _facts(record_type="literature_source"),
            "literature-source.schema.json",
        )
        assert "generation_id" not in closed
        assert catalog.validate("literature-source.schema.json", closed) == ()

    def test_synthesis_candidate_without_generation_id_validates(
        self, catalog: SchemaCatalog
    ) -> None:
        candidate = load_json(GOLDEN / "scientific-record.example.json")
        del candidate["generation_id"]
        del candidate["generation_number"]
        del candidate["method_identity"]
        closed = populate_harness_fields(
            candidate,
            _facts(record_type="literature_synthesis"),
            "scientific-record.schema.json",
        )
        assert "generation_id" not in closed
        assert "generation_number" not in closed
        assert catalog.validate("scientific-record.schema.json", closed) == ()

    def test_coverage_candidate_without_generation_id_validates(
        self, catalog: SchemaCatalog
    ) -> None:
        candidate = load_json(GOLDEN / "scientific-record.example.json")
        del candidate["generation_id"]
        del candidate["generation_number"]
        del candidate["method_identity"]
        closed = populate_harness_fields(
            candidate,
            _facts(record_type="literature_coverage"),
            "scientific-record.schema.json",
        )
        assert "generation_id" not in closed
        assert "generation_number" not in closed
        assert catalog.validate("scientific-record.schema.json", closed) == ()

    @pytest.mark.parametrize(
        "schema_file",
        [
            "literature-source.schema.json",
            "scientific-record.schema.json",
            "method.schema.json",
        ],
    )
    def test_relaxed_schema_keeps_property_but_drops_required(
        self, catalog: SchemaCatalog, schema_file: str
    ) -> None:
        schema = catalog.get(schema_file)
        assert "generation_id" not in schema.get("required", [])
        generation_id_property = schema["properties"]["generation_id"]
        assert generation_id_property["description"] == GENERATION_ID_DESCRIPTION


class TestAgentSuppliedGenerationIdentityStripped:
    """(b) The strip rule closes the fabricated-generation-identity channel."""

    @pytest.mark.parametrize(
        "schema_file",
        [
            "literature-source.schema.json",
            "scientific-record.schema.json",
            "method.schema.json",
        ],
    )
    def test_agent_generation_id_deleted_when_run_facts_empty(
        self, schema_file: str
    ) -> None:
        # The fabrication shape observed in the sealed Aug-22 outputs.
        payload = {"generation_id": "generation.p1.lit_update.026"}
        closed = populate_harness_fields(payload, _facts(), schema_file)
        assert "generation_id" not in closed

    def test_agent_generation_number_deleted_when_run_facts_empty(self) -> None:
        payload = {"generation_id": "generation.p1.lit_update.026", "generation_number": 26}
        closed = populate_harness_fields(
            payload, _facts(), "scientific-record.schema.json"
        )
        assert "generation_id" not in closed
        assert "generation_number" not in closed

    def test_run_facts_value_overwrites_agent_value(self) -> None:
        payload = {"generation_id": "generation.p1.lit_update.026", "generation_number": 26}
        closed = populate_harness_fields(
            payload,
            _facts(generation_id="generation.real.001", generation_number=3),
            "scientific-record.schema.json",
        )
        assert closed["generation_id"] == "generation.real.001"
        assert closed["generation_number"] == 3


class TestPublisherGenerationIdDerivationUnchanged:
    """(c) Generation identity is still derived at promotion from
    digest-bound inputs; this package changes nothing about derivation."""

    _INPUTS = dict(
        project_id="proj.test",
        run_id="run.p1.test.0123456789abcdef0123456789abcdef",
        binding_id="binding.p1.literature",
        slot_key="p1.synthesis.current",
        record_type="literature_synthesis",
        document_sha256="d" * 64,
        artifact_id="artifact.p1.synthesis",
    )

    def test_derivation_is_deterministic(self) -> None:
        assert _generation_id(**self._INPUTS) == _generation_id(**self._INPUTS)

    def test_derivation_uses_generation_prefix(self) -> None:
        assert _generation_id(**self._INPUTS).startswith("generation.")

    @pytest.mark.parametrize("field", sorted(_INPUTS))
    def test_derivation_binds_every_input(self, field: str) -> None:
        altered = dict(self._INPUTS)
        altered[field] = f"altered-{altered[field]}"
        assert _generation_id(**altered) != _generation_id(**self._INPUTS)
