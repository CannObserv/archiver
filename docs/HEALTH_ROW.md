# Home Screen - Health Row

**The `/dashboard/` home screen's health row: its badges, what each reports,
and the state ladder behind each.** Needed only when working on that row;
[PAGES.md](PAGES.md) § **Home** stays the inventory line for its routes. Not
the API's unauthenticated `/health` ([API.md](API.md)). The outbox numbers and
the consumer-lag probe behind the Outbox and Consumers badges are
[BUS.md](BUS.md)'s; this file is how the dashboard reports them.

The health row is **Archiver + Redis + Outbox + Consumers** since archiver#147
(the absence of a Watcher badge is deliberate, not an omission), plus **Registry**
since archiver#164. Each badge is
its own `hx-trigger="load"` partial - non-blocking, "checking…" until HTMX
fires. **Every badge is a live route:** the template used to branch on
`ARCHIVER_REDIS_URL` to render a static "not configured" span instead of the
loader, reporting configuration as if it were state (#147).

**GET `/dashboard/health`** - returns `<span class="badge badge--success">ok</span>`.

**GET `/dashboard/health/redis`** - `redis.ping()`. Success "ok"; danger
"error" with the exception message in `title`; the no-client branch below,
which returns before any logging (the other two log a warning).

**The no-client branch** (`_no_client_badge`; the Outbox badge applies the same
split in its own "not draining" vocabulary) splits `app.state.redis_client is None` by *why*: muted "not
configured" when `ARCHIVER_REDIS_URL` is unset (the dev server's bus-dormant
default), danger "init failed" when it is set and bus init raised at startup.
One branch reported both until CR round 1 finding 3 - a broken production bus
wearing the dev server's vocabulary is the same configuration-as-state
conflation #147 exists to remove.

**GET `/dashboard/health/outbox`** - over `src/core/changes/outbox_stats.py`
(archiver#112). The no-client branch splits the same way the other two do:
muted "not draining" with no `ARCHIVER_REDIS_URL` (publisher dormant - dev's
default - so a stale backlog is not ill health), danger "not draining (init
failed)" when the URL is set, which is exactly when a stale backlog *is* ill
health. Otherwise danger "error" if the stats query raises (its message in `title`),
danger "N dead-lettered" if any poison row, warning "backlog" if the oldest live
unpublished row exceeds 300s, else success "ok"; `title` carries `depth=N oldest=Ns
dead_lettered=N` in the drain states.
**Every state is an `<a>` to `/dashboard/bus-triage`** ([BUS_TRIAGE.md](BUS_TRIAGE.md),
archiver#271), so the screen is reachable from the dashboard whatever the badge reads -
including dormant and init-failed, when the no-client branches outrank the count but the
screen's outbox section, a database read, still lists the rows. Its `aria-label` is
`Outbox: <state> - open Bus triage`. The badge clears once every dead-lettered row is
triaged - discarded or rearmed on that screen or through
`/api/v1/tools/outbox/dead-lettered` (archiver#191, runbook in [BUS.md](BUS.md)).

**GET `/dashboard/health/consumers`** - over
`src/core/bus_health.collect_group_lag` (archiver#147). Liveness from
`app.state.{revisions,artifacts}_consumer_task`, no broker call; depths from
`OWNED_GROUPS`, the same list archiver's own bus surface reads (broker-side
alerting is CannObserv/broker's since #193). Ladder, first match wins - the
no-client branch above / muted "gated off" (`ARCHIVER_BUS_CONSUMER` unset, the
dev default) / danger "not started" / danger "stopped" / warning "lag unknown"
(probe raised or timed out) / danger "N dead-lettered" / warning "group
missing" (absent group, not a healthy zero) / warning "lagging" / success
"running". Liveness outranks lag: a stopped consumer is the cause, its lag the
symptom. `title` carries `<name>=<state> pending=N dlq=N` per consumer.
"N dead-lettered" is the sum of each owned topic's `XLEN <topic>.dlq`, every group's
entries, not only archiver's - the entries the triage screen lists. **Every state is an
`<a>` to `/dashboard/bus-triage`** (archiver#271), `aria-label` `Consumers: <state> - open
Bus triage`; the no-client badge links only here, never as the Redis badge, which reports
the broker's reachability rather than a queue.

The probe is bounded by `LAG_PROBE_TIMEOUT_SECONDS` (5s) at the call site
rather than by a socket timeout on the client: the badge borrows the lifespan's
Redis client, and the group consumers issue a blocking `XREADGROUP` on it, so a
socket timeout under that block would break them. Unbounded, a broker that
hangs rather than refuses never reaches "lag unknown" at all (CR round 1,
finding 1). Only `TimeoutError` and `RedisError`/`OSError` become that badge -
a `TypeError` out of the probe is a bug here and is left to 500 rather than
dressed up as a broker condition (finding 2). A timeout titles itself `probe
exceeded <N>s` rather than the bare `TimeoutError()` an empty `str()` produced,
so a wedged broker reads differently from a refused one (round 2, finding 11).

**GET `/dashboard/health/registry`** - over
`src/core/tools/audit_stored_documents.py` (archiver#164): every authored document
(`source_specs` per entry, `watch_spec`, `rep_fields`, RepSpec `document`) re-judged
against the validator its write path applies. Such a document still publishes - the
announcement path checks only the envelope - and cannot be re-saved, so this badge is
the only place it shows before an edit is refused. Warning "N invalid", an `<a>` to
**`/dashboard/registry-audit`** (PAGES.md); success "ok"; danger "error" on a
`SQLAlchemyError` or `OSError`, with the reason in `title`. A *document* the validator
raises on is a finding, not a sweep failure, so anything else reaching the handler is a
sweep bug and is left to 500 - the Consumers badge's line, for its reason. `title` carries `N documents checked`. No Redis, so no
no-client branch. Registry health, not bus health: it stays out of
`archiver-bus-health`, and off the API's `/health` (unauthenticated, DB-free).

**Cost:** one full read of three columns per home-page load - the row loads once and
never polls. The detail notices judge their own row only. Validation measured
20-95 µs per document (2026-10-15; source specs and RepSpecs the dearest), synchronous on
the event loop: today's 16 cost ~1 ms, and ~10k would hold the loop about a second. Past
a few thousand, cache the result rather than cap the scan - a cap turns "N invalid" into
a lower bound.

**`…/health/watcher` retired with archiver#142** - it pinged Watcher over the
SDK, and the no-outbound-HTTP rule left nothing to ping. Its successor signal
is the announced-vs-applied generation drift on the InfoItem detail panel,
which measures whether Watcher is *acting on what we published* - the question
the badge was a proxy for.
