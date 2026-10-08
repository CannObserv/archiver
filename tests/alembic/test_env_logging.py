"""``alembic/env.py`` leaves loggers that already exist enabled (archiver#327 CR 2).

``fileConfig`` defaults to ``disable_existing_loggers=True``. The test session
runs ``alembic upgrade head`` once at start (``tests/conftest.py``), after
collection has imported every ``src`` module, so the default silenced each
module's logger for the rest of the run: no record was ever built, and a
logging call that raises (#327's reserved ``extra`` key) passed the suite.
"""

import asyncio
import logging
from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _upgrade() -> None:
    alembic_command.upgrade(AlembicConfig(str(_INI)), "head")


async def test_an_upgrade_leaves_existing_loggers_enabled(test_engine):
    """``test_engine`` has already migrated, so this upgrade is a no-op on the schema.

    In a thread: ``env.py`` calls ``asyncio.run`` itself.
    """
    probe = logging.getLogger("src.archiver327.probe")
    probe.disabled = False

    await asyncio.get_running_loop().run_in_executor(None, _upgrade)

    assert not probe.disabled
