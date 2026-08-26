from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from model_forge.application.bootstrap import build_application
from model_forge.application.settings import ApplicationSettings


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_static_frontend_supports_clean_browser_routes_only(tmp_path: Path) -> None:
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><title>Model Forge test shell</title>", encoding="utf-8"
    )
    settings = ApplicationSettings(
        data_root=tmp_path / "data",
        architecture_root=ARCHITECTURE,
        frontend_dist=frontend,
    )

    with TestClient(build_application(settings)) as client:
        browser_route = client.get("/projects/project.demo/phases/P1")
        missing_asset = client.get("/assets/missing.js")
        missing_api = client.get("/api/v1/not-a-route")

    assert browser_route.status_code == 200
    assert "Model Forge test shell" in browser_route.text
    assert missing_asset.status_code == 404
    assert missing_api.status_code == 404
    assert "Model Forge test shell" not in missing_api.text


def test_static_frontend_serves_shell_for_dotted_id_routes(tmp_path: Path) -> None:
    """Production finding 2026-08-25: Model Forge ids are dotted
    (``project.x.y.<hash>``, ``run.p4.p4-preliminary.<hash>``), so any
    browser route ENDING in an id has a ``PurePosixPath.suffix`` - the
    naive extension heuristic 404'd deep links and refreshes on run,
    project, and method pages while in-app navigation kept working."""
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><title>Model Forge test shell</title>", encoding="utf-8"
    )
    settings = ApplicationSettings(
        data_root=tmp_path / "data",
        architecture_root=ARCHITECTURE,
        frontend_dist=frontend,
    )

    with TestClient(build_application(settings)) as client:
        project_root = client.get("/projects/project.demo.abc123")
        run_page = client.get(
            "/projects/project.demo.abc123/runs/run.p4.p4-preliminary.def456"
        )
        method_page = client.get("/projects/project.demo.abc123/methods/method.anel")
        real_asset = client.get("/favicon.ico")

    for response in (project_root, run_page, method_page):
        assert response.status_code == 200
        assert "Model Forge test shell" in response.text
    assert real_asset.status_code == 404
    assert "Model Forge test shell" not in real_asset.text
