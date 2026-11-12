"""The module's timezone, a constant shared by the worker and the backend (ADR-0053 §3).

Not a setting: the backend receives only MEASUREMENTS_ENABLED (ADR-0051 §5), so
an override in the worker's config would split the day of a visit between the
worker and the metrics.
"""

from zoneinfo import ZoneInfo

TIMEZONE_NAME = "America/New_York"
ZONE = ZoneInfo(TIMEZONE_NAME)
