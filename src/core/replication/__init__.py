"""Replication issuance — the RepSpec path contract and the destination renderer.

Archiver renders the ``content.replicate`` destination and Replicator receives
strings (the issuer contract's T3). The template half of the RepSpec document
therefore never travels; it is parsed, validated and resolved here.
"""
