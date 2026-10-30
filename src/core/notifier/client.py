"""The Notifier adapter: the one module that imports the Notifier SDK (archiver#368).

``notifier-client`` is async, generated, and wider than Archiver may use yet: its
facade sends (``dispatch``, ``redeliver``, a channel's test send) and writes the
tenant (channel ``create``/``update``/``delete``). **This adapter lists channels
and nothing else.** Listing proves the credential end to end with zero sends,
which is what the Settings page shows. The first send is archiver#367's, as an
operator action; dispatch is #369's. ``tests/core/notifier/test_sdk_boundary.py``
pins both rules.

Everything that is not a channel list (a rejected key, a 5xx, a refused
connection, a body that is not channels) raises :class:`NotifierUnavailable`.
Its text never carries the key. One attempt per call: a person reloading the
page is the retry, and dispatch's retry policy is #369's to choose.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx
from notifier_client import AuthError, NotifierClient, NotifierError, RetryConfig

from src.core.logging import get_logger
from src.core.notifier.gate import NotifierConfig, resolve

logger = get_logger(__name__)

TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class Channel:
    """One of the tenant's channels, as Settings shows it. Never the masked URL."""

    id: str
    name: str
    #: The masked Apprise URL's scheme (``slack``, ``mailgun``, ``syslog``).
    kind: str


class NotifierUnavailable(Exception):
    """Notifier gave no channel list: why, in words that never name the key."""


class Notifier:
    """A process's one Notifier client, built by the lifespan and closed by it."""

    def __init__(self, config: NotifierConfig, *, timeout: float = TIMEOUT_SECONDS) -> None:
        self.base_url = config.base_url
        self.key_source = config.key_source
        self._client = NotifierClient(
            base_url=config.base_url,
            api_key=config.api_key,
            retry_config=RetryConfig(max_attempts=1),
            timeout=timeout,
        )

    def __repr__(self) -> str:
        return f"Notifier(base_url={self.base_url!r}, key_source={self.key_source!r})"

    async def list_channels(self) -> list[Channel]:
        """The tenant's channels, by name. ``GET /api/v1/channels``: no send, no write."""
        try:
            channels = await self._client.channels.list()
        except AuthError as e:
            raise NotifierUnavailable(
                f"Notifier rejected archiver's key (HTTP {e.status_code})"
            ) from e
        except NotifierError as e:
            raise NotifierUnavailable(f"unexpected HTTP {e.status_code}") from e
        except httpx.HTTPError as e:
            # By type only: the text is httpx's, and the type says enough.
            raise NotifierUnavailable(f"transport error ({type(e).__name__})") from e
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise NotifierUnavailable(f"unreadable channel list ({type(e).__name__})") from e
        return sorted(
            (Channel(id=c.id, name=c.name, kind=_kind(c.apprise_url_masked)) for c in channels),
            key=lambda c: (c.name, c.id),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _kind(masked: str) -> str:
    scheme, sep, _ = masked.partition("://")
    return scheme if sep and scheme.isalnum() else "unknown"


def notifier_from_env(environ: Mapping[str, str]) -> Notifier | None:
    """The process's client, ``None`` when dormant; a gate refusal propagates.

    Says which, once: the URL and where the key came from, never the key. Makes
    no call: a Notifier outage must not stop the registry from starting.
    """
    config = resolve(environ)
    if config is None:
        logger.info("Notifier not configured")
        return None
    logger.info("Notifier configured at %s (key: %s)", config.base_url, config.key_source)
    return Notifier(config)
