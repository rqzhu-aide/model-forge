"""Static frontend delivery with clean-URL SPA navigation."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Serve ``index.html`` for browser routes, but never for APIs or assets."""

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

    @staticmethod
    def _is_browser_route(path: str, scope: dict[str, Any]) -> bool:
        normalized = path.replace("\\", "/").lstrip("/")
        return (
            scope.get("method") in {"GET", "HEAD"}
            and not normalized.startswith("api/")
            and not PurePosixPath(normalized).suffix
        )


__all__ = ["SPAStaticFiles"]
