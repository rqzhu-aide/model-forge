from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from model_forge.executors.development_examples import (
    adapt_dedicated_example,
    load_dedicated_examples,
)
from model_forge.schemas import SchemaCatalog


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "architecture"


@pytest.mark.parametrize(
    "schema_file",
    [
        "theory-record.schema.json",
        "empirical-protocol.schema.json",
        "manuscript-package.schema.json",
        "review-finding.schema.json",
        "review-report.schema.json",
    ],
)
def test_dedicated_development_examples_validate(schema_file: str) -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    examples = load_dedicated_examples(ARCHITECTURE / "examples")

    assert catalog.validate(schema_file, examples[schema_file]) == ()


@pytest.mark.parametrize(
    ("schema_file", "mode", "role"),
    [
        ("theory-record.schema.json", "p3.theory_revision", "theorist"),
        (
            "empirical-protocol.schema.json",
            "p4.comprehensive",
            "data_analyst",
        ),
        (
            "manuscript-package.schema.json",
            "p5.review_revision",
            "research_lead",
        ),
        (
            "review-finding.schema.json",
            "p5.review_revision",
            "theorist",
        ),
        (
            "review-finding.schema.json",
            "p5.review_revision",
            "data_analyst",
        ),
    ],
)
def test_mode_and_role_adaptations_remain_schema_valid(
    schema_file: str,
    mode: str,
    role: str,
) -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    examples = load_dedicated_examples(ARCHITECTURE / "examples")
    adapted = adapt_dedicated_example(
        schema_file=schema_file,
        document=examples[schema_file],
        invocation=SimpleNamespace(mode=mode, role=role),
    )

    assert catalog.validate(schema_file, adapted) == ()
