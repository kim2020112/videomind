from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Serve the Vue entrypoint for the application's history-mode routes."""

    _SPA_ROUTE_ROOTS = {"workspace", "history"}

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            route_root = path.strip("/").partition("/")[0]
            if exc.status_code != 404 or route_root not in self._SPA_ROUTE_ROOTS:
                raise
            return await super().get_response("index.html", scope)
