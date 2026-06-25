# Replicator MVP — Design / Plan (handoff)

**Date:** 2026-06-25
**Status:** Handoff draft for a new `CannObserv/replicator` repo
**Parent strategy:** `archiver/docs/plans/2026-06-25-observer-cluster-integration-strategy-design.md`
**Audience:** the team/agent standing up Replicator. Copy this doc into the new repo as its founding plan.

---

## Purpose

Replicator is the Cannabis Observer **retrieval + fingerprinting + storage** layer. In the target architecture it **owns content fetching, temporary storage, and fingerprinting** for the cluster — the network-bound, byte-handling work re-homed out of Watcher. It is driven by **commands** on the Redis bus and reports outcomes as **facts**.

The MVP's job is narrow: **prove the command → fetch → temp-store → fingerprint → fact loop** standalone, with co-core as the shared substrate, *without* requiring the Watcher cutover.

## Why a fact, not a synchronous reply

Fetching is network-dependent, slow, and retry-prone — a classic **asynchronous/job command**. The issuer doesn't block for an answer; it learns the outcome later from the `blob_available` fact. This is the bus's reason for existing in the cluster (see parent strategy §3).

---

## Repo shape (A/W/N pattern)

Stand up `CannObserv/replicator`, cloned on the VM, mirroring the archiver/watcher/notifier conventions:

- Python ≥3.12, **uv**, **ruff**, **pytest**; **TDD required** (Red → Green → Refactor).
- **Worker-first.** The primary process is a **bus consumer** (a co-core-aio consumer group), not an HTTP API. A thin optional FastAPI app may expose `/health` + status later; not required for the MVP loop.
- systemd unit (`replicator.service`) + a dev port if/when an API exists; `/etc/replicator/.env` for prod secrets, gitignored `.env` for dev.
- SocratiCode index (`.socraticodecontextartifacts.json`), skills submodules, SessionStart hooks — same as siblings.
- Consumes **co-core** via path-dev / pin-CI (see parent strategy §2).

## co-core dependencies the MVP uses

- `co-core` (pure): **fingerprint** (`sha256`, + `simhash` for near-dup if needed) — the canonical impl, the parity anchor.
- `co-core-aio`: **fetcher** (httpx async), **Redis Streams bus driver** (consumer-group consume + producer publish).
- `co-core` `ext/`: **storage adapters** (`local`, `google_cloud_storage`, `google_drive`, `http_io`); add Internet Archive when permanent replication lands.

> If co-core's bus driver (parent strategy Phase 2) is not yet merged when Replicator starts, the MVP may stub the command/fact models + a minimal Redis consumer locally, then swap to co-core once available. Coordinate stream names + payload shapes with Phase 2 so the stub is forward-compatible.

---

## The MVP core loop

```
content.fetch (command)         co-core-aio consumer group "replicator"
        │  consume
        ▼
   fetch bytes                  co-core-aio fetcher (httpx GET)
        │
        ▼
   temp-store bytes             configurable backend, key = content fingerprint
        │                       MVP backend = local FS (REPLICATOR_BLOB_DIR)
        ▼
   fingerprint                  co-core sha256 (canonical)
        │
        ▼
   blob_available (fact)        publish to the content/blob fact stream
```

### Contracts

**Consume — `content.fetch` command** (one consumer group `replicator`; competing consumers; ack on success; retry w/ backoff; DLQ after N attempts). Payload (co-core model, illustrative):

```
{ command_id, info_source_id, url, requested_by, requested_at,
  schema_version, hints?: { media_type?, headers? } }
```

**Emit — `blob_available` fact** (broadcast; interested groups = watcher, archiver). Payload (co-core model, illustrative):

```
{ info_source_id, url, content_fingerprint: "sha256:<hex>",
  media_type, size_bytes, backend_uri, captured_at, schema_version,
  command_id?  # correlation back to the triggering command }
```

### Temp-storage backend

- An **interface** (`store(bytes, fingerprint, media_type) -> backend_uri`, `open(fingerprint)`, `exists(fingerprint)`), with the **first impl = local filesystem** under `REPLICATOR_BLOB_DIR`.
- Designed for swap to an object store (then own infra) without touching the loop. The `backend_uri` is opaque to consumers.
- **"Temporary"** = the bytes live long enough for downstream durable replication (later phase) to pick them up; retention policy is out of MVP scope.

### Idempotency & fidelity

- Storage key = `sha256` fingerprint ⇒ re-processing the same command (at-least-once redelivery) is a **no-op**.
- Fidelity is structural: the fingerprint is computed by the single fetcher at fetch time, so there is no parity/drift problem (unlike re-fetch-from-URL, which could capture changed bytes).

---

## MVP scope cuts (explicitly OUT)

- **Permanent/durable replication** per RepSpec provider (gcs/gdrive/ia), `path_template`, `credentials_alias`. MVP uses the local temp backend only.
- **Writeback to archiver** (recording a SourceRevision, `content_cache_uri`/`public_url`). The `blob_available` fact is sufficient to prove the loop; archiver-writeback is MVP+.
- **RepSpec resolution / reads from archiver.** Not needed for the loop.
- **Watcher cutover** (issuing `content.fetch`, consuming `blob_available`) — parent strategy Phase 4.
- Re-replication policy, blob GC/retention, cross-source dedup, robots/rate-limit/auth niceties.

## Build sequence (within the MVP)

1. Repo scaffold (A/W/N pattern) + co-core wiring (path-dev / pin-CI); validate `import co_core` / `co_core_aio` in CI.
2. Define (or stub) the `content.fetch` command + `blob_available` fact co-core models; align with parent Phase 2.
3. Bus consumer loop (co-core-aio consumer group) with ack / retry / DLQ; TDD.
4. Fetch → temp-store (local backend) → fingerprint; TDD each step.
5. Emit `blob_available`.
6. Seed/test harness that issues a `content.fetch`; integration test the full loop end-to-end.

## Open questions for the Replicator team

- Temp-storage backend interface shape + the local-FS first impl details (layout, `backend_uri` scheme).
- Command issuer during the MVP window (seed script vs early watcher hook vs archiver) — until Phase 4 cutover.
- Whether the MVP stops at the fact, or also writes a SourceRevision back to archiver (MVP+).
- Stream names + group conventions — must match what co-core fixes in parent strategy Phase 2.
