"""Replication providers Replicator cannot write yet: one list for the API and the dashboard.

The envelope schema names ``gcs``, ``gdrive`` and ``ia``; Replicator's replicate
loop refuses the last two ``provider_disabled``, since no conditional-create
writer exists (CannObserv/replicator#29; ``KNOWN_PROVIDERS = ("gcs",)`` in its
``src/worker/aliases.py``). A RepSpec authored against one would freeze on
assignment (#83) and then fail every occasion with a fact this service cannot
repair, so every writer refuses them:

- the API's ``POST /rep-specs`` (via ``create_rep_spec``) and both assignment
  writers (via ``check_document_assignable``) raise
  :class:`ProviderUnwritableError`, a 422 ``provider_unwritable`` (archiver#153);
- the dashboard's RepSpec form and Add-a-spec picker keep the options visible
  but disabled, and their routes refuse them server-side too (archiver#202,
  #308; a template-only gate is the #167 defect class).

Lifting an entry here is the whole change when a writer lands.
"""

UNWRITABLE_PROVIDERS: dict[str, str] = {
    "gdrive": "Replicator has no Google Drive writer yet",
    "ia": "Replicator has no Internet Archive writer yet",
}


class ProviderUnwritableError(Exception):
    """The provider is on :data:`UNWRITABLE_PROVIDERS`; ``reason`` says why."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.reason = UNWRITABLE_PROVIDERS[provider]
        super().__init__(f"provider {provider!r} is unavailable: {self.reason}")


def check_provider_writable(provider: str) -> None:
    """Raise :class:`ProviderUnwritableError` if Replicator cannot write ``provider``."""
    if provider in UNWRITABLE_PROVIDERS:
        raise ProviderUnwritableError(provider)
