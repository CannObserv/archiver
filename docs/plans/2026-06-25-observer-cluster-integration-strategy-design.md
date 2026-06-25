# Observer Cluster Integration Strategy — Design

**Date:** 2026-06-25
**Status:** Approved (brainstorming output)
**Scope:** Archiver, Watcher, Replicator (the "A/W/R cluster") + the shared `cannobserv` / co-core library.
**Out of scope:** Notifier (domain-agnostic product; own SDK; untouched).
**Tracking issue:** [#72](https://github.com/CannObserv/archiver/issues/72)
**Companion doc:** `docs/plans/2026-06-25-replicator-mvp-design.md` (handoff for CannObserv/replicator)

---

## Problem

Three sister services are in flight with cross-cutting concerns, and progress has stalled on the seams between them:

- **Coupling tax.** Every edge is synchronous HTTP through generated SDKs with committed OpenAPI snapshots and drift-detection CI (archiver #66, the #70 live-drift timer, the `client-drift` gate). Keeping moving targets in lockstep is burdensome.
- **A half-hearted bus.** Archiver produces the Redis Stream `info.changes` via a transactional outbox, but nothing consumes it. The decoupling leap was never taken.
- **An unpursued shared library.** Content-acquisition code (`fetchers`, `extractors`, `simhash`, `extraction_defaults`, `logging`) is copy-pasted between archiver and watcher under "mirror discipline." A real shared async library is viable now but hasn't been adopted.

## Goal

A strategy + incremental plan so the cluster fits together with **clear boundaries**, a **shared substrate** instead of copy-paste + brittle SDKs, and a **principled sync/async communication split** over the existing Redis bus — shipped phase by phase, each phase independently valuable and low-risk.

---

## Key finding: the substrate already exists

`CannObserv/cannobserv` is not greenfield. It is the original Cannabis Observer core library, already refactored (issue #129+) into a **uv workspace** with a functional-core / effects architecture:

- **`co-core`** — pure: Pydantic domain models, workflows (state-machine step functions), and typed **effect** dataclasses (`HttpGet`/`HttpPost`, GCS, Drive). Strictly I/O-free; enforced by import-linter contracts + a pytest purity sentinel.
- **`co-core-sync`** — synchronous drivers + service facades (for the Click CLIs).
- **`co-core-aio`** — **asynchronous drivers + service facades over `httpx.AsyncClient`, explicitly "for web service consumers."**
- **`cannobserv`** — frozen legacy package, shrinking to a re-export shim.

Its own workspace design doc (`2026-05-18-co-core-workspace-design.md`) names the destination outright: *"Enables async web service consumers (Watcher, Archiver, Replicator, future) sharing a common business-logic library."* And its AGENTS.md Phase 3+ plan lists *"bring Watcher / Archiver / Replicator into `co_core.workflows.*` as downstream consumers materialize."*

**So the "shared async library" is `co-core-aio`, and it is half-built and waiting.** This strategy is about *adopting* it, not inventing it.

The `ext/` adapter layer already contains the storage providers Replicator needs: `google_cloud_storage`, `google_drive`, `http_io`, `local` (plus `trello`, `wordpress`, `ffmpeg`, `google_cloud_speech`, `audacity`).

---

## Approved decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Keystone | **Communication paradigm first.** Boundaries + shared resources hang off how the edges talk. |
| 2 | Communication split | **Synchronous commands → HTTP. Asynchronous/job commands → bus command streams. Facts → bus fact streams.** Archiver remains the control-plane **coordinator** (orchestration, not choreography). |
| 3 | Shared substrate | **Adopt the existing `cannobserv` uv workspace** (`co-core` pure + `co-core-aio` async drivers). No new repo. |
| 4 | Distribution | **Path-install for dev** (VM-co-located, edit-once-all-see-it) + **pinned git tag in the lockfile for CI**; `tool.uv.sources` diverges dev vs CI. Monorepo-grade iteration, boundaries intact. |
| 5 | Adoption depth | **Route A now** (shared utilities + bus contracts). **Route B** (canonical shared domain model; archiver persists co-core models) is the **intended trajectory** — every A decision kept B-compatible. **Route C** (functional-core all the way; FastAPI as thin shell; Postgres as effect) deferred, maybe never. |
| 6 | Notifier | **Out of cluster.** Domain-agnostic, reusable, own published SDK. Untouched. |
| 7 | Replicator | **Seams only now.** Separate repo `CannObserv/replicator`, A/W/N pattern, stood up independently. **Owns content fetching + temporary storage + fingerprinting** (target boundary). |
| 8 | Byte handoff | **Durable handoff direction.** Replicator fetches → temp-stores (configurable backend) → fingerprints → emits a `blob_available` fact. Retires the VM-idiosyncratic `WATCHER_CACHE_*` local-cache dependency. |
| 9 | Fetch re-homing | **Target captured in strategy; MVP proves the loop standalone.** Watcher's cutover (delegating fetch to Replicator) is a later, separate phase. |

---

## 1. Boundaries (who owns what)

| Service | Role | Consumes | Produces |
|---|---|---|---|
| **Archiver** | Control plane + **registry / system-of-record** (InfoItem, InfoSource, SourceRevision, RepSpec). Owns the canonical fact stream. | Sync commands (create item, provision, writebacks) | Facts → `info.changes` |
| **Watcher** | Monitor. **Scheduling + change-decision + orchestration.** Today fetches to detect change; *target* = delegates fetching to Replicator. | Provisioned by archiver; (target) `blob_available` facts | (Target) `content.fetch` commands; SourceRevision writes → archiver |
| **Replicator** | **Retrieval + temporary storage + fingerprinting**, then durable replication. | `content.fetch` commands | `blob_available` facts; bytes → storage; (later) writebacks → archiver |
| **Notifier** | Out of cluster. Domain-agnostic dispatch via own SDK. | — | — |
| **co-core** (`cannobserv`) | **Shared substrate, not a service.** Pure models + workflows + effect types; sync/aio drivers. | — | — |

**The fetch reallocation (target).** Today watcher fetches bytes, fingerprints, and POSTs SourceRevisions with a `content_cache_uri` pointing at its transient VM-local cache. The target re-homes the network-bound, byte-handling work to Replicator: watcher decides *when* to check and issues a `content.fetch` command; Replicator fetches, temp-stores (configurable backend), fingerprints, and emits `blob_available`; watcher reacts to that fact for its change-decision.

**Payoff — the parity problem dissolves.** With a *single* fetcher+fingerprinter, there is nothing to keep "in parity." The shared content-acquisition code still belongs in co-core (Replicator imports it as the canonical impl), but the mirror-discipline anxiety in archiver/watcher CLAUDE.md goes away.

---

## 2. Shared substrate: co-core (`cannobserv`)

**Distribution.** Each service depends on `co-core` + `co-core-aio`:
- **Dev:** path/editable install (`tool.uv.sources` → `{ path = "../cannobserv/packages/co-core", editable = true }`). Edit co-core once; all three services see it instantly. Zero version-bump ceremony for daily work.
- **CI / reproducibility:** pinned git tag in the lockfile (`git+https://github.com/CannObserv/cannobserv@<tag>#subdirectory=packages/co-core`). Reproducible, machine-independent.

**Route-A scope of what moves in (the purity line cuts cleanly):**

| Lands in | Content |
|---|---|
| `co-core` (pure) | `simhash`, extractor transforms, `extraction_defaults`, **fingerprint logic**, **bus payload models** (commands + facts). |
| `co-core-aio` (drivers) | `fetchers` (HTTP I/O), **Redis Streams bus driver**, storage adapters (`ext/`: gcs/gdrive/http_io/local; add Internet Archive). |
| `co-core` (effects) | new `effects/bus.py` (`BusPublish` / `BusConsume`); reuse existing GCS/Drive effects for storage. |

**Purity guard.** co-core's import-linter + purity sentinel already forbid HTTP/cloud SDKs/asyncio in the pure layer. `fetchers` are I/O → they belong in `co-core-aio`, never in `co-core`. This is a hard constraint, already enforced.

**B-positioning (without committing to B).** Bus payload models live in a `co_core.pure.models` event namespace, named/shaped toward the eventual canonical vocabulary (so today's `source_revision_captured` / `blob_available` evolve into B's canonical Source/Replication types). Keep ORM ↔ co-core mapping thin and explicit at the service edges, so co-core models can later *become* canonical and archiver can persist them.

---

## 3. Communication paradigm

Three message classes, each with a natural transport:

| Class | "Sender needs…" | Transport | Examples |
|---|---|---|---|
| **Synchronous command** | an answer **now** | HTTP / SDK | create InfoItem, provision/patch WatchedItem, dispatch notification, `set_public_url` |
| **Asynchronous / job command** | nothing now; outcome arrives later as a fact | **bus command stream** | `content.fetch` ("go fetch + store this") |
| **Fact** (state change) | nothing; broadcasts that something happened | **bus fact stream** | `source_revision_captured`, `info_item_primary_changed`, `blob_available` |

**Two stream kinds over Redis Streams** (same primitive, different intent):
- **Command/job stream** (e.g. `content.fetch`) — typically **one** consumer group (the Replicator workers); commands distributed across workers (competing consumers / work queue). Each command handled once by the group.
- **Fact stream** (`info.changes`, and a new content/blob fact stream) — **many** independent consumer groups, each receiving all events (broadcast); each group processes at-least-once.

**Delivery + correctness:**
- **Transactional outbox stays** as the producer-side guarantee (archiver already has `changes_outbox`; watcher already has `pending_archiver_sync`). Producers write the message in the same DB transaction as the state change; a drain publishes to the stream.
- **At-least-once** delivery ⇒ consumers must be **idempotent**. The content-addressed model makes this natural (storage key = fingerprint; re-processing = no-op).
- **`schema_version`** on every payload (already a convention). Bump only on incompatible reshape; consumers tolerate additive fields (`ConfigDict(extra="ignore")`); branch on version before destructuring.
- **Bus I/O is a co-core effect** — one home for serialization, idempotency keys, headers, ack/retry/DLQ, and replay.

**Coupling reduction (the point).** As fact edges move to shared, typed co-core contracts, the OpenAPI-snapshot + drift machinery on those edges (#66, #70 live-drift, `client-drift`) shrinks and eventually retires. Synchronous command edges keep lightweight clients, sourced from co-core types where shared.

---

## 4. Sequencing (the plan)

Each phase is independently shippable. Earlier phases de-risk later ones.

| Phase | Work | Proves / unblocks |
|---|---|---|
| **0 — Wiring** | archiver + watcher declare `co-core` / `co-core-aio` deps (path-dev / pin-CI). Adopt one trivial pure util to validate the toolchain end-to-end. | A FastAPI/async service consumes co-core; co-core-aio maturity gaps surface early. |
| **1 — Content-acquisition → co-core** | `simhash` / extractors / `extraction_defaults` → `co-core` pure; `fetchers` → `co-core-aio`. De-dupe archiver + watcher; retire mirror discipline. | Copy-paste dies; the **canonical fetch + fingerprint impl** lives in co-core, ready for Replicator. |
| **2 — Bus contracts + driver** | Command/fact payloads → co-core models; `effects/bus.py` + co-core-aio Redis Streams driver (producer + consumer-group). Archiver outbox publisher emits via shared models. Establish stream taxonomy + conventions (groups, ack, retry/DLQ, `schema_version`). | Contracts shared; fact-edge drift machinery starts shrinking. |
| **3 — Replicator MVP** *(separate repo; handoff doc)* | Consume `content.fetch` → fetch (aio) → temp-store (configurable) → fingerprint (co-core) → emit `blob_available`. | **First real consumer; the bus earns its keep.** Validates command→fact loop standalone. |
| **4 — Watcher cutover** | Watcher delegates fetching: issues `content.fetch`, consumes `blob_available` for change-decision. Retire watcher's own fetch path + `WATCHER_CACHE_*`. | Fetch reallocation realized; **fingerprint-parity problem dissolves**. |
| **5 — Trim coupling + revisit B** | Retire fact-edge OpenAPI-snapshot/drift machinery; consolidate command clients on co-core types; evaluate Route B (canonical domain model; archiver persists co-core models). | Coupling tax paid down; B on deck. |

---

## 5. Risks, out-of-scope, open questions

**Risks**
- **co-core-aio maturity.** The async wrapper is the least-exercised package; adopting it into FastAPI services may surface missing drivers/facades. *Mitigation:* Phase 0 validates cheaply; extend co-core-aio as needed before deeper phases.
- **Purity-boundary leakage.** `fetchers` must never land in `co-core` pure. *Mitigation:* import-linter + purity sentinel already enforce; respect them.
- **Version ripple.** A breaking co-core change ripples to all consumers via lockfile bumps. *Mitigation:* path-dev neutralizes daily friction; tag discipline + `schema_version` for the wire.
- **Bus operations.** Redis durability/persistence config, consumer-group lag monitoring, DLQ, replay are new operational surface. *Specified in Phase 2.*

**Out of scope**
- **Persistence unification (Route C).** Each service keeps its own Postgres; co-core stays persistence-agnostic. WordPress-vs-Postgres is not reconciled now.
- **Notifier** changes of any kind.
- **Route B** implementation (canonical domain model; archiver persisting co-core models) — trajectory only; not built in this plan.

**Open questions**
- Temp-storage backend abstraction for Replicator (local FS for MVP → object store → own infra). *Owned by the Replicator MVP doc.*
- Does `source_revision_captured` (emitted by archiver) and `blob_available` (emitted by Replicator) coexist, or does the former subsume into the latter after Phase 4? *Reconcile in Phase 4.*
- Who issues `content.fetch` during the MVP, before watcher cutover (seed/test harness vs an early watcher hook vs archiver)? *Owned by the Replicator MVP doc.*
- Final stream names + group conventions, fixed in co-core during Phase 2.
