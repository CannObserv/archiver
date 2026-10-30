"""The Notifier adapter: the one module that imports the Notifier SDK (archiver#368, #367).

``notifier-client`` is async, generated, and wider than Archiver may use: its
facade sends (``dispatch``, ``redeliver``, a channel's test send) and writes the
tenant (channel ``create``/``update``/``delete``). **This adapter lists channels
and makes one kind of dispatch, nothing else.**

- :meth:`Notifier.list_channels` proves the credential end to end with zero
  sends, which is what the Settings page shows.
- :meth:`Notifier.dispatch_composed` (#367 D3) is the one send. The composed
  text goes as **variables**, ``{"title": ..., "body": ...}``, under the fixed
  templates ``{{ title }}`` and ``{{ body }}``. Notifier renders both
  ``*_template`` fields as Jinja, and a value is never evaluated, so text that
  holds ``{{`` or ``{%`` (a watched page's diff can) arrives as written. Its
  caller today is the dashboard's test-send, an operator action; #369's dispatch
  inherits it.

``tests/core/notifier/test_sdk_boundary.py`` pins both rules. Every failure (a
rejected key, a refusal, a 5xx, a refused connection, an unreadable body) raises
:class:`NotifierUnavailable`, whose text never carries the key. One attempt per
call: a person pressing again is the retry, and dispatch's retry policy is
#369's to choose.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from notifier_client import (
    AuthError,
    NotifierClient,
    NotifierError,
    RetryConfig,
    ValidationError,
)

from src.core.logging import get_logger
from src.core.notifier.gate import NotifierConfig

logger = get_logger(__name__)

TIMEOUT_SECONDS = 5.0
#: D3: Notifier's templates are these constants, never composed text.
TITLE_TEMPLATE = "{{ title }}"
BODY_TEMPLATE = "{{ body }}"


@dataclass(frozen=True, slots=True)
class Channel:
    """One of the tenant's channels, as Settings shows it. Never the masked URL."""

    id: str
    name: str
    #: The masked Apprise URL's scheme (``slack``, ``mailgun``, ``syslog``).
    kind: str


@dataclass(frozen=True, slots=True)
class Dispatched:
    """A dispatch Notifier accepted: its id, and ``succeeded``, ``partial`` or ``failed``."""

    id: str
    status: str


class NotifierUnavailable(Exception):
    """Notifier didn't give the answer asked for: why, in words that never name the key."""


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

    async def dispatch_composed(
        self,
        *,
        channel_id: str,
        title: str,
        body: str,
        idempotency_key: str,
        metadata: dict[str, object],
    ) -> Dispatched:
        """Send composed text to one channel: ``POST /api/v1/dispatch``, one attempt.

        The text travels as variables under :data:`TITLE_TEMPLATE` and
        :data:`BODY_TEMPLATE` (D3), so Notifier delivers it exactly as written.
        """
        try:
            out = await self._client.dispatch(
                title_template=TITLE_TEMPLATE,
                body_template=BODY_TEMPLATE,
                variables={"title": title, "body": body},
                channel_ids=[channel_id],
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        except AuthError as e:
            raise NotifierUnavailable(
                f"Notifier rejected archiver's key (HTTP {e.status_code})"
            ) from e
        except ValidationError as e:
            raise NotifierUnavailable(
                f"Notifier refused the dispatch (HTTP {e.status_code})"
            ) from e
        except NotifierError as e:
            if e.status_code == 404:
                raise NotifierUnavailable(
                    "Notifier has no such channel in this tenant (HTTP 404)"
                ) from e
            raise NotifierUnavailable(f"unexpected HTTP {e.status_code}") from e
        except httpx.HTTPError as e:
            raise NotifierUnavailable(f"transport error ({type(e).__name__})") from e
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise NotifierUnavailable(f"unreadable dispatch answer ({type(e).__name__})") from e
        return Dispatched(id=out.id, status=str(out.status.value))

    async def aclose(self) -> None:
        await self._client.aclose()


def _kind(masked: str) -> str:
    scheme, sep, _ = masked.partition("://")
    return scheme if sep and scheme.isalnum() else "unknown"


def announce(config: NotifierConfig | None) -> None:
    """Say once, at startup, which: the URL and where the key came from, never the key."""
    if config is None:
        logger.info("Notifier not configured")
        return
    logger.info("Notifier configured at %s (key: %s)", config.base_url, config.key_source)
