"""Archiver's edge to Notifier (archiver#368, #367): the gate, and a narrow adapter.

- :mod:`src.core.notifier.gate` decides whether this process may hold a client at
  all. It imports no SDK.
- :mod:`src.core.notifier.client` is the one module that imports
  ``notifier-client``. It lists the tenant's channels and makes one kind of
  dispatch, composed text as variables (#367 D3). Its one sender today is the
  dashboard's test-send; dispatch on events is #369's.
"""
