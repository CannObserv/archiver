# Redis change-bus operational ownership — design

**Issue:** archiver#109
**Date:** 2026-07-29
**Status:** approved
**Parent epic:** #72 · Bus layer: cannobserv#261 (Phase 2) / archiver#106 (Phase 2b producer swap) · First consumer: Phase 3 (Replicator)

## Goal

Assign a concrete operational owner to the Redis change bus before Phase 3
(Replicator) makes `info.changes` load-bearing. Today no application service
operates `redis-server`: it runs as the stock distro unit
(`/usr/lib/systemd/system/redis-server.service`), bootstrapped once by a
now-superseded watcher plan and left un-owned through the producer role
migrating Watcher → Archiver. See #109 (and its first comment) for the full
history trace.

## Decision

**Archiver owns and operates the local Redis broker**, as the change-bus
*producer* and cluster control-plane. The status quo ("nobody owns it") is
rejected. Managed/remote Redis is the deferred escalation path, not built now.

Rationale for Archiver over the alternatives:

- **Archiver-owned (chosen).** Archiver is the producer and the closest thing to
  a cluster control-plane; it already owns the transactional outbox and adopted
  the co-core bus contracts. No blocking dependency on unbuilt code.
- **Replicator-owned (rejected).** Replicator is the service that makes the bus
  load-bearing, but it is not built. Homing ownership there blocks the ownership
  decision on Phase 3 exactly when the bus goes live.
- **Shared cluster-infra repo (deferred).** Correct at larger scale, but premature
  at one shared VM / two services; it relocates the ownership question and adds a
  second deploy pipeline. Trigger to revisit: a *third* consuming service, or
  another repo's deploy pipeline needing to `git`-consume the artifacts.
- **Managed/remote Redis (deferred).** The right *eventual* escalation. Overkill
  for one VM; adds latency + a provider dependency. Trigger to revisit: multi-VM
  or HA requirement.

## Design

The design is layered so a future migration to a managed provider is a
config-only change. The connection string is the one and only switch.

### Layer 1 — App-side contract (provider-independent, permanent)

- **`ARCHIVER_REDIS_URL` is the only switch.** Local-prod
  `redis://localhost:6379/0`; managed later `rediss://user:pass@host:port/0` —
  no code change.
- **Driver supports `rediss://` + URL-embedded auth — already satisfied
  (resolved open item 2).** The co-core-aio driver is *injection-only*
  (`AsyncBusPublisher(client)`; it never constructs or closes a connection), and
  Archiver builds the client via `RedisAsync.from_url(ARCHIVER_REDIS_URL)` at
  `src/api/main.py:88`. `redis.asyncio.Redis.from_url` natively handles the
  `rediss://` TLS scheme, `user:pass@` userinfo auth, and `?ssl_ca_certs=` for a
  private CA. So the managed migration is a connection-string swap with **no code
  change**; the only migration-time task is trusting the provider's CA. No work
  in this issue.
- **Degradation stays soft.** Publisher is disabled when `ARCHIVER_REDIS_URL` is
  unset; the outbox tolerates broker downtime within its retry window. No
  hard-fail coupling to the broker.

### Layer 2 — Local-broker operational artifacts (disposable on managed migration)

All under `deploy/`, explicitly labeled "local-broker deployment; replaced by a
provider connection string on migration."

- **Tracked systemd drop-in** `deploy/redis-server.dropin.conf` →
  `/etc/systemd/system/redis-server.service.d/`. Tunes the *stock* distro unit,
  does not replace it. Sets `appendonly yes` / `appendfsync everysec`, asserts
  `maxmemory-policy noeviction` (already live — a stream broker must never evict).
- **Ordering on `archiver.service`:** `Wants=redis-server.service` +
  `After=redis-server.service` — **soft, not `Requires=`/`BindsTo=`.** Hard-binding
  would defeat the outbox's downtime tolerance and cascade restarts. Replicator
  adds the same when it lands.
- **Retention: Archiver-side periodic `XTRIM` (resolved open item 1).** co-core
  exposes **no trim arg** — `BusPublish` is `topic` + `fields` only and
  `AsyncBusPublisher.execute` does a bare `xadd(topic, fields)`. Rather than block
  on a co-core release, Archiver (the operator) caps the stream itself: the
  outbox publisher loop issues a periodic `XTRIM info.changes MAXLEN ~ N`
  (approximate) every K drains, using the long-lived client the lifespan already
  owns (threaded into `outbox_publisher.run`). Upstreaming a `maxlen` field on
  `BusPublish` — folding the trim into each XADD — is a later optional
  optimization, not on this issue's critical path.
- **Version floor ≥7.0 via `ExecStartPre` on `archiver.service` (resolved open
  item 3).** (Live: 7.0.15, passes.) The floor is a *consumer*-path requirement
  (`XAUTOCLAIM`/`claim_stale`'s three-element reply), but Archiver as operator
  asserts it loud: an `ExecStartPre` on its own unit checks `redis_version` of the
  server behind `ARCHIVER_REDIS_URL` and refuses to start the producer if `< 7.0`.
  This fails loud on a distro downgrade without gating the broker itself (the
  broker stays up; only the producer refuses). Skipped when `ARCHIVER_REDIS_URL`
  is unset. Runbook documents the floor.

### Activation (this issue turns the producer on)

- Set `ARCHIVER_REDIS_URL=redis://localhost:6379/0` in `/etc/archiver/.env`;
  restart `archiver`; confirm the outbox drains in the logs. With no consumer
  yet, entries accumulate on the stream — bounded by the retention cap above and
  made durable by AOF.

### Dev/prod isolation

- Prod uses `/0`, dev uses `/1` (separate logical DB), **plus a guard in
  `scripts/dev_server.sh`** that refuses to start if the resolved dev Redis URL
  equals prod's — mirroring the Postgres `_test`/`_dev` guard. Belt-and-suspenders
  against a repeat of the 2026-07-18 dev-writes-to-prod class of incident, now for
  the bus.

### Monitoring ownership (documented now, split by role)

- **Producer-side (outbox depth) — Archiver, now.**
- **Consumer-group lag / DLQ / replay — Replicator, Phase 3.** Documented now;
  not built against a non-existent consumer.

### Docs

- This design note (linked from #109).
- **AGENTS.md (archiver + watcher):** state that Archiver operates `redis-server`;
  strike watcher's vestigial `REDIS_URL` framing.

## Resolved open items (verified against installed co-core / co-core-aio)

1. **`MAXLEN` enforcement mechanism → Archiver-side periodic `XTRIM`.** co-core
   `BusPublish` (`co_core/effects/bus.py`) carries only `topic` + `fields`;
   `AsyncBusPublisher.execute` (`co_core_aio/bus.py`) does a bare
   `xadd(topic, fields)` — no trim support. Archiver caps the stream from its own
   publisher loop; upstreaming a `maxlen` arg is deferred. (See Layer 2 →
   Retention.)
2. **TLS/auth passthrough → already satisfied, no change.** Driver is
   injection-only; Archiver's `RedisAsync.from_url` handles `rediss://` + auth +
   `?ssl_ca_certs=`. (See Layer 1.)
3. **Version-floor assertion → `ExecStartPre` on `archiver.service`.** (See
   Layer 2 → Version floor.)

## Out of scope

- Managed/remote Redis migration (deferred; trigger = multi-VM / HA).
- Cluster-infra-repo extraction (deferred; trigger = 3rd consuming service).
- uv-workspace modularization of the clients (tracked separately in #110).
