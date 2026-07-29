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
- **Driver supports `rediss://` + URL-embedded auth.** Verify co-core-aio's
  `AsyncBusPublisher` passes TLS + auth through, even though activation is on
  plaintext localhost. This is what makes the managed migration config-only.
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
- **Retention:** the producer XADDs with an approximate cap (`MAXLEN ~ N`) so the
  stream cannot grow unbounded before a consumer exists. Mechanism is an open
  item (below).
- **Version floor ≥7.0** (live: 7.0.15, passes) for the consumer path's
  `XAUTOCLAIM`/`claim_stale`. Runbook documents it plus a lightweight
  startup/monitoring assertion so a distro downgrade fails loud, not
  silent-broken.

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

## Open items (resolve during implementation)

1. **`MAXLEN` enforcement mechanism** — whether co-core's `BusPublish` /
   `AsyncBusPublisher` exposes a trim arg. If not: Archiver runs a periodic
   `XTRIM` sweep, or we upstream a co-core change. Needs a co-core API check.
2. **TLS/auth passthrough verification** in the co-core-aio bus driver (for the
   future managed migration).
3. **Version-floor assertion mechanism** — `ExecStartPre` check vs. monitoring-only.

## Out of scope

- Managed/remote Redis migration (deferred; trigger = multi-VM / HA).
- Cluster-infra-repo extraction (deferred; trigger = 3rd consuming service).
- uv-workspace modularization of the clients (tracked separately in #110).
