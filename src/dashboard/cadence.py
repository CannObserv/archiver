"""Fetch-cadence options offered by the dashboard.

The cadence **values** offered at registration and their human-readable labels.
Deliberately narrower than what is valid: the grammar an interval must satisfy
(``^[0-9]+[smhd]$``, what Watcher's ``parse_interval`` accepts) is owned by
``src/core/watch_spec_schema/v1.json``, and a WatchSpec may legitimately hold an
interval that is not offered here — an imported per-domain default, say. This
module is the UI subset, not the vocabulary.

Cadence itself became Archiver-owned in archiver#150 (``info_items.watch_spec``);
until the control-plane cutover the dashboard still displays Watcher's
``default_schedule_config``.
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
