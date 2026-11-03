"""``get_database_url``'s refusal names where the URL lives, not a recipe (#452 D5)."""

import pytest

from src.core.database import get_database_url


def test_a_missing_url_points_at_the_env_files_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARCHIVER_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        get_database_url()
    message = str(excinfo.value)
    assert "AGENTS.md § Environment Files" in message
    assert "/etc/archiver/.env" in message, "production's is the units'"
    assert ". .env" not in message, "no shell recipe to copy"
