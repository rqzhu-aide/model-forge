from __future__ import annotations

from fastapi.testclient import TestClient

from method_hub.application.bootstrap import build_application
from method_hub.application.settings import ApplicationSettings


def test_bootstrapped_application_exposes_api(tmp_path) -> None:
    settings = ApplicationSettings(
        data_root=tmp_path / "data",
        architecture_root=__import__("pathlib").Path(__file__).resolve().parents[1]
        / "architecture",
    )
    with TestClient(build_application(settings)) as client:
        response = client.get("/api/v1/projects")

    assert response.status_code == 200
    assert response.json() == []
