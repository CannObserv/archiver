"""Replication providers the dashboard offers, and the ones it cannot yet (archiver#202).

Shared by the two screens that put a provider in front of an operator: the
RepSpec create form and the InfoItem screen's Add-a-spec picker (archiver#308).
One place, so lifting an entry when a writer lands is one change.
"""

# Providers the envelope schema names but Replicator cannot write yet. Its
# replicate loop refuses them ``provider_disabled`` - no conditional-create
# writer exists (CannObserv/replicator#29; ``KNOWN_PROVIDERS = ("gcs",)`` in its
# ``src/worker/aliases.py``) - so a RepSpec authored against one would freeze on
# assignment (#83) and then fail every occasion with a fact this service cannot
# repair. Both screens keep such options visible but disabled, and their routes
# refuse them server-side so a direct POST cannot bypass the template (a
# template-only gate is the #167 defect class). Lifting an entry here is the
# whole change when a writer lands; the sub-schema question is #153. The API's
# ``POST /rep-specs`` is deliberately untouched: the contract still accepts the
# envelope's full enum.
UNWRITABLE_PROVIDERS: dict[str, str] = {
    "gdrive": "Replicator has no Google Drive writer yet",
    "ia": "Replicator has no Internet Archive writer yet",
}
