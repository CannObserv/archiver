"""Watcher fetch-cadence vocabulary shared across the dashboard.

Single source of truth for the cadence options offered at registration and the
human-readable labels used to display a Watcher ``default_schedule_config``.
Values are Watcher interval strings (see watcher ``parse_interval``: s/m/h/d).
"""

from __future__ import annotations

# Ordered mapping of Watcher interval string → human-readable label. Order is
# the display order in the registration dropdown.
CADENCE_LABELS: dict[str, str] = {
    "1h": "Hourly",
    "6h": "Every 6 hours",
    "1d": "Daily",
    "7d": "Weekly",
}

# Interval strings offered as registration options.
CADENCE_OPTIONS: tuple[str, ...] = tuple(CADENCE_LABELS)

# Visual default selected in the registration dropdown.
DEFAULT_CADENCE = "1d"
