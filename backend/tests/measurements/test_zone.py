"""The module's timezone is one constant, never read from settings (ADR-0053 §3)."""

import ast
from pathlib import Path

from app.measurements.zone import ZONE

MODULE_DIR = Path(__file__).resolve().parents[2] / "app" / "measurements"


def _timezone_attribute_reads(source: str) -> list[int]:
    """Lines with `<anything>.timezone` attribute access, e.g. `settings.timezone`."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and node.attr == "timezone"
        # `datetime.timezone` from the standard library is a different thing.
        and not (isinstance(node.value, ast.Name) and node.value.id == "datetime")
    ]


def test_no_module_file_reads_a_timezone_attribute():
    found = {
        str(path.relative_to(MODULE_DIR)): lines
        for path in sorted(MODULE_DIR.rglob("*.py"))
        if (lines := _timezone_attribute_reads(path.read_text(encoding="utf-8")))
    }
    assert found == {}


def test_the_check_sees_a_settings_read():
    assert _timezone_attribute_reads("x = ZoneInfo(settings.timezone)\n") == [1]
    assert _timezone_attribute_reads("x = ctx.settings.timezone\n") == [1]
    assert _timezone_attribute_reads("from datetime import timezone\nx = timezone.utc\n") == []


def test_zone_is_new_york():
    assert ZONE.key == "America/New_York"
