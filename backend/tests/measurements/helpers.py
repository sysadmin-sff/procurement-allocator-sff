import importlib.util
import os
import warnings
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
    # Each execution repeats the `on_event` deprecation warning that the real
    # import of app/main.py has already reported once.
    with (
        patch.dict(os.environ, {"MEASUREMENTS_ENABLED": "true" if enabled else "false"}),
        warnings.catch_warnings(),
    ):
        warnings.filterwarnings("ignore", r"\s*on_event is deprecated", DeprecationWarning)
        spec.loader.exec_module(module)
    return module.app


def _measurements_contexts(app: FastAPI) -> list:
    """Walks `app.routes`, including routes hidden from OpenAPI.

    Recent FastAPI keeps an `_IncludedRouter` wrapper in `app.routes` for each
    included router and exposes its real routes through
    `effective_route_contexts()`; older versions flatten them into APIRoute.
    """
    found = []
    for route in app.routes:
        contexts = (
            route.effective_route_contexts()
            if hasattr(route, "effective_route_contexts")
            else [route]
        )
        found.extend(
            context
            for context in contexts
            if (getattr(context, "path", None) or "").startswith("/measurements")
        )
    return found


def measurements_routes(app: FastAPI) -> list[tuple[str, str]]:
    return [
        (context.path, method)
        for context in _measurements_contexts(app)
        for method in sorted(set(getattr(context, "methods", None) or ()) - {"HEAD", "OPTIONS"})
    ]


def _depends_on(dependant, target) -> bool:
    return any(
        dependency.call is target or _depends_on(dependency, target)
        for dependency in dependant.dependencies
    )


def assert_every_route_guarded(app: FastAPI, guard) -> None:
    """Fails naming each /measurements* route with no `guard` in its dependency chain.

    A route with no dependency information at all (a mount, a plain Starlette
    route) counts as unguarded.
    """
    contexts = _measurements_contexts(app)
    assert contexts, "no /measurements routes found"
    unguarded = [
        context.path
        for context in contexts
        if getattr(context, "dependant", None) is None or not _depends_on(context.dependant, guard)
    ]
    assert not unguarded, f"routes without {guard.__name__}: {unguarded}"
