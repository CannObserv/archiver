"""Archiver's edge to Notifier (archiver#368): the gate, and a read-only adapter.

- :mod:`src.core.notifier.gate` decides whether this process may hold a client at
  all. It imports no SDK.
- :mod:`src.core.notifier.client` is the one module that imports
  ``notifier-client``, and it lists the tenant's channels and nothing else. Nothing
  here sends: composition, test-send and dispatch are archiver#367 and #369.
"""
