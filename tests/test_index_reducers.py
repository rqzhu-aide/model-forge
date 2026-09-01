from __future__ import annotations

import pytest

from model_forge.harness.index_reducers import _literature_library


def test_malformed_prior_index_non_object_raises() -> None:
    with pytest.raises(ValueError):
        _literature_library(["not", "an", "object"], [])


def test_malformed_prior_index_wrong_format_raises() -> None:
    prior = {
        "format": "model-forge.unrelated-index",
        "format_version": "1.0.0",
        "sources": [],
    }
    with pytest.raises(ValueError):
        _literature_library(prior, [])


def test_malformed_prior_index_missing_array_raises() -> None:
    prior = {
        "format": "model-forge.literature-library-index",
        "format_version": "1.0.0",
        "sources": {"not": "a list"},
    }
    with pytest.raises(ValueError):
        _literature_library(prior, [])


def test_shared_smallest_identifier_does_not_merge() -> None:
    prior = {
        "format": "model-forge.literature-library-index",
        "format_version": "1.0.0",
        "sources": [
            {
                "identifiers": [{"kind": "doi", "value": "X"}],
                "title": "prior record",
            }
        ],
    }
    changes = [
        {
            "identifiers": [
                {"kind": "doi", "value": "X"},
                {"kind": "isbn", "value": "Y"},
            ],
            "title": "change record",
        }
    ]

    merged = _literature_library(prior, changes)

    assert merged["source_count"] == 2
    assert {item["title"] for item in merged["sources"]} == {
        "prior record",
        "change record",
    }

    # Companion no-regression: identical identifier sets still fold to one
    # entry with the change winning.
    same_key_changes = [
        {
            "identifiers": [{"kind": "doi", "value": "X"}],
            "title": "change record",
        }
    ]
    folded = _literature_library(prior, same_key_changes)
    assert folded["source_count"] == 1
    assert folded["sources"][0]["title"] == "change record"
