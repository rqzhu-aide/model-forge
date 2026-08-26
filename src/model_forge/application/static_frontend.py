"""Static frontend delivery with clean-URL SPA navigation."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Serve ``index.html`` for browser routes, but never for APIs or assets.

    The suffix check must not treat Model Forge's DOTTED ids as file
    extensions: a route like ``projects/project.x.y.<hash>/runs/
    run.p4.p4-preliminary.<hash>`` ends in a segment whose ``.suffix`` is
    the id's hash fragment, and the naive ``not suffix`` rule 404s every
    deep link / refresh on run, project, and method pages (production
    finding 2026-08-25).  Only known static-asset extensions are files.
    """

    _ASSET_SUFFIXES = frozenset({
        ".css", ".csv", ".html", ".ico", ".jpeg", ".jpg", ".js", ".json",
        ".map", ".pdf", ".png", ".svg", ".ttf", ".txt", ".webmanifest",
        ".webp", ".woff", ".woff2",
    })

    async def get_response(self, path: str, scope: dict[str, Any]) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code != 404 or not self._is_browser_route(path, scope):
                raise
        else:
            if response.status_code != 404 or not self._is_browser_route(path, scope):
                return response
        return await super().get_response("index.html", scope)

    @classmethod
    def _is_browser_route(cls, path: str, scope: dict[str, Any]) -> bool:
        normalized = path.replace("\\", "/").lstrip("/")
        suffix = PurePosixPath(normalized).suffix.lower()
        return (
            scope.get("method") in {"GET", "HEAD"}
            and not normalized.startswith("api/")
            and not normalized.startswith("assets/")
            and suffix not in cls._ASSET_SUFFIXES
        )


__all__ = ["SPAStaticFiles"]
