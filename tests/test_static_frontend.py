from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from method_hub.application.bootstrap import build_application
from method_hub.application.settings import ApplicationSettings


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_static_frontend_supports_clean_browser_routes_only(tmp_path: Path) -> None:
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<!doctype html><title>Method Hub test shell</title>", encoding="utf-8"
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
    assert "Method Hub test shell" in browser_route.text
    assert missing_asset.status_code == 404
    assert missing_api.status_code == 404
    assert "Method Hub test shell" not in missing_api.text
