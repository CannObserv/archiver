---
title: Durable registry announcement channel — replace the best-effort Watcher HTTP push
date: 2026-08-10
status: approved
---

# Registry announcement channel — design

**Issue:** archiver#140 · **Epic:** archiver#137 step 4 · **Children:** archiver#150, cannobserv#302, archiver#141, watcher#254, cannobserv#321, watcher#264, archiver#151, archiver#142

## Problem

Watcher caches `source_specs` on its WatchedItem rows (watcher#185, which removed a per-cycle Archiver SDK call for good reason). Archiver keeps that copy fresh by PATCHing Watcher over HTTP — `sync_on_spec_update` in `src/core/watcher_provisioning.py`, which catches every exception, logs, and moves on. No retry, no outbox, no reconciliation, and since watcher#185 no read-through to correct it. **A spec edit whose PATCH fails leaves Watcher extracting against the old spec permanently while the dashboard shows the new one, and nothing detects it.** That is not a latent risk; it is the current design. Step 5 of the epic makes registry state more load-bearing still, so this is the moment to fix the delivery model rather than harden the push.

## Approach

Archiver broadcasts **desired registry state** on a new durable stream, `info.registry`, and Watcher reconciles its `watched_items` against it. One announcement per InfoItem, keyed `info_item_id`, carrying the active primary InfoSource inline plus a resolved scheduling policy. Last-write-wins per key, ordered by a monotonic `generation` counter. Deltas are written to `changes_outbox` **in the mutation's own transaction** — that single property is the entire fix — and drained by the existing publisher. A separate timer republishes the full key set directly (not via the outbox), so a consumer converges regardless of stream trimming. Consumers tail grouplessly from `0-0`, following the `content.fetch-policy` precedent (cannobserv#285) rather than inventing a second config/state shape.

Because that channel is one-way and the teardown deletes Archiver's only reverse read of Watcher, the design carries a **return leg**: `info.watch-status`, on which Watcher broadcasts the generation it has *applied* plus scheduler state and observation freshness. Archiver tails it, renders the watched-item panel from local state, records `last_observed_at` durably on `info_sources`, and alerts on announced-vs-applied divergence. That is a broadcast fact, not an ack — nothing blocks on it — and it is strictly stronger than the HTTP push ever was, which confirmed receipt and never application. Both directions are then level-triggered, which is the property that makes the whole channel self-healing; leaving the return leg edge-triggered would have reintroduced the lossiness the outbound leg exists to remove.

Two things must move before any of it can be announced: **Archiver does not currently own cadence or active/paused state** (no such columns on `info_items`; Watcher owns them and the dashboard round-trips over the SDK), and there is no ordering token on the registry rows. Both are prerequisites, not payload questions.

## Tradeoffs / alternatives

### The delivery model

| Option | Failure mode | Tax on Archiver | Watcher→Archiver HTTP |
|---|---|---|---|
| (a) Status quo HTTP push | silent permanent drift | ~0 | none |
| (b) Push + periodic pull reconcile | bounded drift | scales with items × poll rate | reintroduced |
| **(c) Durable announcements (chosen)** | bounded drift | scales with **mutation** rate | none |
| (d) Read-through per cycle | none | scales with fetch cadence | worst; watcher#185 removed this |

Registry mutations are operator-driven and rare; fetch cycles are frequent and grow with the corpus. Pull-based coupling taxes Archiver in proportion to Watcher's *activity*, push-based in proportion to *operator edits*. That decides it.

### Choices within (c)

- **Per-InfoSource grain** — rejected. More normalized, but a primary swap becomes two messages that must be applied in order, reintroducing ordering dependence into a design whose point is that ordering does not matter. Per-InfoItem matches the consumer's unit of work (Watcher schedules per WatchedItem). Fan-out on a shared InfoSource is what `sync_on_spec_update` already does today.
- **Deltas alone, replay from `0-0` to reconcile** — rejected. `info.changes` is trimmed; "a log is not state". Snapshot **and** delta.
- **Two streams (deltas group-consumed, snapshots groupless)** — rejected. Buys `XPENDING` lag monitoring on half the traffic at the cost of two reconcile paths, and the groupless posture below gives that half up anyway.
- **Consumer group** — rejected. Every consumer needs every message; a group accumulates a PEL nothing drains. Cost taken deliberately: `XPENDING` is permanently blind here, so health is last-entry age plus a producer heartbeat. Same ruling and same cost as `content.fetch-policy`.
- **`updated_at` as the LWW ordering token** — rejected, for a producer-side reason that is concrete rather than clock-skew-theoretical: `src/core/changes/publisher.py:238-303` selects unpublished rows in `created_at` order but a transient publish failure `continue`s the loop, so row N publishes *after* N+1…N+k on a later drain. Timestamp LWW would let a stale announcement win. Secondary: `info_sources` has no `updated_at` at all, and the payload joins three tables so no single row's timestamp is authoritative.
- **Absence-from-snapshot as the delete signal** — rejected. A producer that dies mid-republish emits a partial set, so absence-as-revocation turns a producer restart into a cluster-wide deprovision. Making it safe needs a generation marker *plus* an end-of-set sentinel *plus* consumer-side buffering — three mechanisms to avoid one boolean. Explicit `revoked` tombstone, republished in every full set. (co-core's `FetchPolicyState` already argues exactly this.)
- **Snapshots through the outbox** — rejected. There is no pruner on `changes_outbox`; a periodic full republish through it grows the table without bound and taxes the drain's `published_at IS NULL` scan. The snapshot carries no transactional obligation — it is an idempotent read of current state, and the next period corrects a lost one.
- **An applied-ack from Watcher over HTTP** — rejected. That is the coupling being removed. A broadcast applied-generation is not an ack path and delivers more.
- **A general Watcher telemetry stream** — rejected as over-scoped. The return leg carries level signals only; per-event activity stays on the content streams.
- **Deriving observation freshness from `content.blobs`** — rejected, having first been chosen. It moves the per-cycle cost rather than removing it, couples liveness to replicator#17, and above all reports that *bytes arrived* rather than that the *item was observed* — extraction failures land after `blob_available`, so a broken item reads as freshly and healthily checked. See "What Archiver does not consume".
- **Making `source_revision_observed` fire on no-change** — rejected. It would make a fact stream activity-rate-scaled, and it cannot work anyway: the envelope key is `info_source_id:extracted_fingerprint`, so a no-change republish re-emits an identical key that the consumer's dedup cannot distinguish from redelivery.

## Design

### `info.registry` — the announcement

Config/state stream kind (cannobserv#285's third kind): broadcast, LWW per key, groupless, full set republished on a timer. Two-segment name in the `info.` namespace, the registry/domain layer.

**No DLQ.** The same answer `content.fetch-policy` gives, for the same reason: a state message has nothing to close and no fact to publish back, so quarantine *is* its terminal state. Applies to both streams in this design.

```
schema_version: int
event_type: Literal["registry_announcement"]
occurred_at: OccurredAt
info_item_id: str          # the LWW slot
generation: int            # monotonic per key
info_source_id: str
url: str
source_specs: list
spec_fingerprint: str | None
watch_spec: dict           # resolved scheduling policy
revoked: bool = False      # tombstone
```

- **`url` is in scope** — immutable per InfoSource *row*, but mutable at *item* grain via a primary swap, and the grain here is the item.
- **`spec_fingerprint`** is co-core's `pure.extract.spec_fingerprint` over the announced spec. Carrying it makes the announcement directly comparable to the field `source_revision_observed` already lands on `content.revisions`, which is what lets the registry distinguish "Watcher is behind on announcements" from "the spec changed" — the exact ambiguity `SourceRevisionObservedEvent`'s docstring names when it points here.
- **RepSpecs are out.** Step 5 makes Archiver the replication issuer; Watcher never needs them. `name` / `description` / `owner` / `rep_fields` are out too — no consumer.

**Three states, all distinct.** `revoked: true` means gone from the registry (delete the WatchedItem). `watch_spec.active: false` means registered and deliberately paused (keep the row, stop scheduling). `watch_spec.active: true` means schedule. Collapsing paused into revoked loses the pause on the next reconcile.

### WatchSpec — the ownership move (archiver#150)

`info_items.watch_spec`, a validated JSONB document, with a `src/core/watch_spec_schema/` module alongside the three that exist. **Singular document, not a plural list** — `source_specs` is plural because Watcher walks it as a fallback loop; a WatchSpec has no fallback semantics. Initial surface stays small: `{"interval": "1d", "active": true}`, using the vocabulary already in `src/dashboard/cadence.py`.

The wire carries a **resolved document, never a reference.** The reusable-policy version — a `watch_specs` table plus an effective-dated join, mirroring RepSpec — is a plausible future want (bulk cadence policy is why RepSpec got that shape), and a resolved document makes that upgrade an Archiver-internal change with zero consumer impact. Do not build the join now; do not leak the column into the contract either.

**WatchSpec is per-item cadence; `content.fetch-policy` is per-host spacing.** Different key, stream, owner, and consumer. Both answer "how often do we hit things" and will attract merge proposals; the boundary belongs in the schema docstring.

### Generation counter

`info_items.announcement_generation BIGINT NOT NULL DEFAULT 0`, bumped in the same transaction as any mutation that changes announced state. Consumers apply iff `generation > stored`.

**Bump it with an atomic `UPDATE … SET announcement_generation = announcement_generation + 1 RETURNING`, never read-modify-write in Python.** Two concurrent mutations to one item would otherwise both read N and write N+1, and the second announcement would be silently discarded by every consumer as a duplicate — the exact failure this token exists to prevent, reintroduced by the obvious implementation.

A mutation on an InfoSource bound to N items bumps N generations and emits N announcements. That is the fan-out `sync_on_spec_update` already performs.

### Producer (archiver#141)

**Deltas** — a `ChangesOutboxRow(topic="info.registry", …)` written in the mutation's transaction. Emit sites: InfoSource create, `update_info_source_specs`, primary-binding swap, binding deactivation, WatchSpec change, pause/resume (currently `patch_watched_item(is_active=…)` at `src/dashboard/routes/info_items.py:1431`), InfoItem deletion/deactivation. Verify against the code; that list is a starting point.

**Snapshots** — a separate timer task reading current state and publishing directly. **Period: 1 hour** (ratified), configurable, plus an operator "republish now" control. The period is not the convergence guarantee for a healthy delta (that is outbox latency, sub-second); it bounds the failure cases only — consumer down past retention, dead-lettered row, trim. It is also the staleness bound a spec edit inherits when its delta is lost.

**Retention rides on the publish.** `publisher.py:306-323` applies one global `ARCHIVER_REDIS_STREAM_MAXLEN` to every topic in `seen_topics`, so `info.registry` would be silently subjected to the fact stream's cap the moment its first delta drains. co-core is explicit that a config/state stream's retention is a *consumer contract* carried by `BusPublish.maxlen`, because the consumer boots by replaying from `0-0`. Exclude `info.registry` from the periodic `XTRIM` loop and set `maxlen` on its publishes, sized from key count × periods retained — never from the `info.changes` number.

Durability asymmetry to record in the streams table: deltas retry indefinitely through the outbox; **snapshots do not retry at all.** A snapshot lost to a broker outage is corrected by the next period.

### Consumer (watcher#254)

Groupless tail via `AsyncBusTailReader`, replay from `0-0` at boot, then tail. Reconcile — do not apply: create, spec update, cadence change, and deactivation all fall out of one loop. Watcher-local columns the registry has no opinion on (health, `last_checked_at`, fetch history, notification config) survive reconciliation. Keep a local fallback cadence for an absent or unparseable `watch_spec` — a consumer that cannot parse the policy must not stop scheduling, and it reports that via `applied_active` rather than diverging silently.

### `info.watch-status` — the return leg (cannobserv#321, watcher#264, archiver#151)

Same mechanics, opposite direction: LWW per `info_item_id`, groupless, periodic republish. Hyphen rather than a third dot segment, for the reason `content.fetch-policy` gives verbatim — `info.watch.status` would read as a sub-stream of an `info.watch` that does not exist and get swept up by ops globs.

```
schema_version: int
event_type: Literal["watch_status"]
occurred_at: OccurredAt
info_item_id: str            # the LWW slot
applied_generation: int      # the announcement generation Watcher has applied
applied_active: bool         # what the scheduler is actually doing
last_attempt_at: OccurredAt | None   # every outcome advances this
last_observed_at: OccurredAt | None  # only a successful extraction advances this
health: Literal["ok", "error"]
revoked: bool = False
```

Publish `applied_generation` **after** the reconcile commits; a premature stamp makes the drift detector lie in the one direction that matters.

#### Level, not edge — and why that makes the publish rate a free variable

Every field here is a **level** signal: it answers "as of when / what is true now", not "how many times". Level signals can be coalesced without loss of meaning, which is what keeps this stream off the activity-rate cost curve *without* pushing the fields onto a stream that costs the same.

Publish on: reconcile (generation change), health transition, `applied_active` change, and the periodic republish. **Not per cycle.** A steadily-healthy item publishes once per republish period no matter how often it is fetched, and its timestamps converge within that period. Under-reporting is the safe direction — the registry never claims content is fresher than it is.

#### `last_attempt_at` and `last_observed_at` are different facts

Watcher's existing `last_checked_at` ([watched_item.py:68](../watcher/src/core/models/watched_item.py#L68)) advances on **every** outcome including failures — it is a scheduling anti-thrash device ([fetch_commands.py:76](../watcher/src/workers/fetch_commands.py#L76), [:120](../watcher/src/workers/fetch_commands.py#L120)). That is `last_attempt_at` here, and it is what next-due derives from.

`last_observed_at` advances **only** when extraction succeeded — changed or unchanged, both count. **Watcher does not have this column today and gains one.** That is the single new column this design puts in Watcher, and it exists because a provenance claim must not rest on a cross-service inference: Archiver could derive it (health `ok` at the moment `last_attempt_at` was stamped implies that attempt observed), but the derivation silently breaks the day Watcher lets health lag the stamp, and it would be underwriting a durable registry column with an assumption about another service's internals.

**Not on the payload, deliberately:** `consecutive_failures` and `last_error` — neither exists in Watcher (`health_status` is a binary enum; error text goes to the audit log). Inventing two columns to carry them is scope this design has not justified. `health: error` plus Watcher's audit log is enough for an operator; add them when someone needs more than "it is failing."

`next_due_at` stays absent — derived from `last_attempt_at + watch_spec.interval`. Note it must derive from *attempt*, not *observation*: a failing item attempts on schedule while `last_observed_at` stands still, and deriving from the latter would render every failing item as wildly overdue.

#### `info_sources.last_observed_at` — a durable registry column

Archiver writes `last_observed_at` through to `info_sources`, not just to the status cache. This is a **provenance fact, not a dashboard convenience**: "this source was verified current as of T" is the most common true statement about any tracked regulatory document, and it is materially stronger than "we have no record of a change" — which conflates *verified same* with *never looked*.

That claim is only available because Watcher distinguishes the two cases and always has: [fetch_commands.py:110-117](../watcher/src/workers/fetch_commands.py#L110-L117) audits `CHECK_NO_CHANGE` against `CHECK_SNAPSHOT_CREATED` on every cycle. The information existed and never left the service. Requires `docs/SCHEMA.md` and a `CHANGELOG.md` entry (migration path).

#### What Archiver does *not* consume

**No `content.blobs` consumer.** An earlier draft derived last-checked from `blob_available` / `fetch_failed`; that was wrong on three counts, and the third is disqualifying:

1. It moved the per-cycle cost rather than removing it — one message per fetch either way, now with an extra service in the path.
2. It coupled liveness to replicator#17 (conditional GET must still publish an outcome).
3. **`content.blobs` reports that bytes arrived, not that the item was observed.** Extraction failures happen *after* `blob_available` ([pipeline.py:246](../watcher/src/workers/pipeline.py#L246) raises `ExtractionError`), so a broken item appears freshly and healthily checked on that stream — the exact silent-failure class this epic exists to remove.

Archiver consumes exactly two streams: `content.revisions` (facts it records) and `info.watch-status` (liveness it renders and stores). The epic's "Archiver does not consume `content.blobs`" stays unqualified, with no read-only exception carved into it — role boundaries erode through exactly those.

`content.revisions` carries last-**changed** only. An unchanged re-observation returns early at [pipeline.py:300](../watcher/src/workers/pipeline.py#L300) (`if last_rev.content_fingerprint == outcome.content_fingerprint: return WatchedItemResult(cache_hit=True)`) — no `ChangeRevision`, no `PendingArchiverSync`, nothing published. archiver#139's re-observation handling covers a *redelivered* observation or an A→B→A content flip, not a fresh no-change poll; do not read it as evidence of the latter.

That early return is **correct and stays.** `content.revisions` is a stream of revisions and a no-change cycle produced none. It also structurally could not carry them: the envelope key is `info_source_id:extracted_fingerprint`, so a no-change republish re-emits a byte-identical key, indistinguishable from redelivery and swallowed by the consumer's dedup. What was missing was never a revision event — it was a liveness level, which is what this stream now carries.

#### Consumer side

Archiver tails into a persisted `watch_status` table so restart is a delta, not a full `0-0` replay, and renders the panel from local state with zero SDK calls. Announced generation (`info_items.announcement_generation`) against applied generation is the drift detector whose absence this issue opens by describing.

**"No status yet" must render distinctly from paused and from healthy.** It is a fourth state alongside the panel's existing `not_watching` / `watching` / `degraded`.

## Steps

1. **archiver#150 — WatchSpec.** Migration, schema module, API surface, dashboard rewiring (pause/resume becomes a local UPDATE; cadence reads `item.watch_spec`; registration applies an Archiver default). **Run the one-time import of Watcher's `default_schedule_config` + `is_active` first** — the SDK is the only way to read them and #142 deletes it. Four rows in production. *Verifiable: no dashboard path reads cadence or active state over the SDK; imported values match the live WatchedItems.*
2. **cannobserv#302 — contract**, plus co-core release and Archiver's pin bump. The bump ships *with* the producer or ahead of it: the outbox's build phase dispatches through `payload_from_dict` and dead-letters an unknown `event_type` on the first attempt, so a producer merged ahead of the contract fails quietly rather than loudly. *Verifiable: `payload_from_dict` round-trips a `registry_announcement` in Archiver's venv.*
3. **archiver#141 — producer.** Generation column with atomic bump, delta emit at every mutation site, snapshot timer, `XTRIM` exclusion, `deploy/README.md` streams table. *Verifiable: a test asserts rolling back the mutation rolls back the announcement; a trimmed stream still converges a fresh consumer.*
4. **watcher#254 — consumer.** Reconcile loop, generation ordering, cold start from a snapshot alone. *Verifiable: cold start against a **trimmed** stream produces correct `watched_items`; an out-of-order announcement is ignored; Watcher-local columns survive.*
5. **Return leg**, startable from step 2 and parallel to 3–4: **cannobserv#321** → **watcher#264** ∥ **archiver#151**. #264 is cheapest built alongside #254 — its payload is what the reconcile loop just computed — and it adds Watcher's one new column, `last_observed_at`. #151 adds the durable `info_sources.last_observed_at` (migration, `docs/SCHEMA.md`, `CHANGELOG.md`) alongside the `watch_status` cache. **Step 7 gates on this.** *Verifiable: panel renders with zero SDK calls; announced-vs-applied divergence is visible; a no-change cycle advances `info_sources.last_observed_at` while leaving the latest `source_revisions` row untouched.*
6. **Dual-run.** Both paths live and idempotent. Disable the HTTP push by config, edit a real spec, confirm it propagates via the announcement and that `applied_generation` catches up. *Verifiable: that observation, in production, not in a test.*
7. **archiver#142 — teardown. Gated on step 5** (see Resolved, below): the SDK is not deleted until the panel renders from `info.watch-status`. Removes the SDK, `client-drift`'s watcher half, `watcher-live-drift.timer` and its scripts, `watcher_provisioning.py`, `WATCHER_BASE_URL` / `WATCHER_API_KEY`, and `info_items.watcher_item_id` (after the cut-over — step 1's import joins on it). Confirm `_clear_stale_watcher_link` and the 409-adoption recovery are genuinely subsumed by reconcile plus the status stream rather than assuming it.

## Resolved

Settled 2026-08-10; recorded here so the child issues inherit the decision rather than re-deriving it.

- **#142 gates on #151.** The teardown waits; the panel never regresses. A half-deleted SDK is the worst of both.
- **Stream names ratified:** `info.registry` and `info.watch-status`.
- **Snapshot period: 1 hour**, configurable.
- **`next_due_at` dropped** from the status payload — derived from `last_attempt_at + watch_spec.interval`. It is redundant, which is what makes dropping it free; `last_observed_at` moves at the same rate but is irreplaceable, so it stays. Both are level signals, so publish rate is a coalescing knob rather than an intrinsic cost — the reasoning that let the return leg keep the field it needs without tracking fetch activity.
- **`info_sources.last_observed_at` is a durable registry column**, not only a dashboard cache. "Verified current as of T" is a provenance fact about a regulatory document, and it is the claim a change-only pipeline can never make.
- **No DLQ on either stream**, matching `content.fetch-policy`.
- **A dead-lettered announcement leaves its key stale until the next snapshot** — accepted. Bounded by the republish period and visible as generation drift on the panel.
- **archiver#147 sequences with this work.** Both streams' health primitive is last-entry age; the bus panel that currently reports configuration rather than liveness is its natural home.

## Open questions / risks

No open questions remain — the seven above were settled on review. What is left is carried risk.

- **Observation freshness has exactly one source: Watcher's own claim on `info.watch-status`.** No cross-check exists — if Watcher stamps `last_observed_at` wrongly, the registry records it wrongly, and `docs/SCHEMA.md` should say the column is a reported value rather than a locally-verified one. That is the accepted cost of not deriving it from a second stream; the alternatives were worse (see the tradeoffs).
- **Coalescing means `last_observed_at` under-reports by up to the republish period.** Safe direction — the registry never claims content is fresher than it is — but any downstream that treats the column as exact freshness rather than a lower bound will be subtly wrong. Document it as a lower bound.
- **Concurrent mutations to one InfoItem** silently lose an announcement unless the generation bump is an atomic `UPDATE … RETURNING`. The obvious read-modify-write implementation reintroduces exactly the failure the token prevents.
- **`info.registry` inherits the fact stream's `XTRIM` cap by default** the moment its first delta drains, because the delta path puts the topic in `seen_topics`. Exclusion is a required change, not a tuning knob.
- **Snapshots do not retry.** One lost to a broker outage is corrected only by the next period — a deliberate asymmetry with the delta path, and one the streams table must state rather than imply.
