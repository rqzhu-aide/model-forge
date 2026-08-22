"""Schema-valid deterministic executor for local harness development only."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..json_io import load_json
from .development_examples import (
    adapt_dedicated_example,
    load_dedicated_examples,
)
from .fake import DeterministicFakeExecutor
from .protocol import RoleInvocation


_EXAMPLES = {
    "attention-item.schema.json": "attention-item.example.json",
    "compact-view.schema.json": "compact-view.example.json",
    "decision-record.schema.json": "decision-record.example.json",
    "evidence.schema.json": "evidence.example.json",
    "handoff.schema.json": "handoff.example.json",
    "literature-source.schema.json": "literature-source.example.json",
    "method.schema.json": "method.example.json",
    "review-issue.schema.json": "review-issue.example.json",
    "scientific-record.schema.json": "scientific-record.example.json",
    "statement.schema.json": "statement.example.json",
}

# ADR-017 (P2 contract 2.1.0): every change-set method record carries the
# lead's three-axis evaluation. The development executor emits a clearly
# labeled conformance placeholder, not a research assessment.
_DEVELOPMENT_METHOD_EVALUATION: dict[str, Any] = {
    "theoretical_validity": {
        "score": 5,
        "justification": "Development conformance placeholder; not a research assessment.",
        "issue_refs": [],
    },
    "literature_positioning": {
        "score": 5,
        "justification": "Development conformance placeholder; not a research assessment.",
        "issue_refs": [],
    },
    "empirical_feasibility": {
        "score": 5,
        "justification": "Development conformance placeholder; not a research assessment.",
        "issue_refs": [],
    },
    "adjudicated_at": "2026-01-01T00:00:00+00:00",
    "review_basis_ids": ["report.development.example"],
}


class SchemaExampleFakeExecutor(DeterministicFakeExecutor):
    """Produce bundled conformance examples without claiming scientific work."""

    def __init__(self, architecture_root: Path) -> None:
        example_root = architecture_root.resolve() / "examples"
        self._documents = {
            schema: load_json(example_root / filename)
            for schema, filename in _EXAMPLES.items()
        }
        dedicated = load_dedicated_examples(example_root)
        self._documents.update(dedicated)
        self._dedicated_schema_files = frozenset(dedicated)
        super().__init__(self._example_output)

    def _example_output(self, invocation: RoleInvocation, offset: int) -> Any:
        expected = invocation.metadata.get("expected_outputs")
        if type(expected) is not list or not 1 <= offset <= len(expected):
            raise ValueError("Development invocation lacks exact output metadata.")
        specification = expected[offset - 1]
        if type(specification) is not dict:
            raise ValueError("Development output metadata must be an object.")
        schema_file = str(specification["schema_file"])
        try:
            document = copy.deepcopy(self._documents[schema_file])
        except KeyError as error:
            raise ValueError(
                f"No development example is registered for {schema_file!r}."
            ) from error
        if schema_file == "method.schema.json" and "evaluation" not in document:
            document["evaluation"] = copy.deepcopy(_DEVELOPMENT_METHOD_EVALUATION)
        if schema_file in self._dedicated_schema_files:
            document = adapt_dedicated_example(
                schema_file=schema_file,
                document=document,
                invocation=invocation,
            )
        application = specification["schema_application"]
        if application == "object":
            return document
        if application == "each_item":
            return [document]
        raise ValueError(f"Unsupported schema application {application!r}.")


__all__ = ["SchemaExampleFakeExecutor"]
