from __future__ import annotations

from method_hub.application.repository_views import RepositoryQueries, row_json
from method_hub.storage.repository import HubRepository


def test_repository_queries_list_project_payloads(tmp_path) -> None:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project(
        "project.example",
        {"name": "Example", "research_question": "What is learned?"},
    )
    queries = RepositoryQueries(repository)

    rows = queries.list_projects()

    assert len(rows) == 1
    assert row_json(rows[0])["name"] == "Example"
