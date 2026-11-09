import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

MAIN_PATH = Path(__file__).resolve().parents[2] / "app" / "main.py"


def load_app(enabled: bool) -> FastAPI:
    """Executes a private copy of app/main.py with the flag set.

    `sys.modules["app.main"]` stays untouched, so other tests keep their app.
    """
    module_name = f"_measurements_main_{'on' if enabled else 'off'}"
    spec = importlib.util.spec_from_file_location(module_name, MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"MEASUREMENTS_ENABLED": "true" if enabled else "false"}):
        spec.loader.exec_module(module)
    return module.app


def measurements_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Walks `app.routes`, including routes hidden from OpenAPI.

    Recent FastAPI keeps an `_IncludedRouter` wrapper in `app.routes` for each
    included router and exposes its real routes through
    `effective_route_contexts()`; older versions flatten them into APIRoute.
    """
    found: list[tuple[str, str]] = []
    for route in app.routes:
        contexts = (
            route.effective_route_contexts()
            if hasattr(route, "effective_route_contexts")
            else [route]
        )
        for context in contexts:
            path = getattr(context, "path", None)
            if path and path.startswith("/measurements"):
                methods = set(getattr(context, "methods", None) or ())
                found.extend((path, method) for method in sorted(methods - {"HEAD", "OPTIONS"}))
    return found
