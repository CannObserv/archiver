# Home Screen - Health Row

**The `/dashboard/` home screen's health row: its badges, what each reports,
and the state ladder behind each.** Needed only when working on that row;
[PAGES.md](PAGES.md) § **Home** stays the inventory line for its routes. Not
the API's unauthenticated `/health` ([API.md](API.md)). The outbox numbers and
the consumer-lag probe behind the Outbox and Consumers badges are
[BUS.md](BUS.md)'s; this file is how the dashboard reports them.

The health row is **Archiver + Redis + Outbox + Consumers** since archiver#147
(the absence of a Watcher badge is deliberate, not an omission). Each badge is
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
health. Otherwise danger "N dead-lettered" if any poison row, warning
"backlog" if the oldest live unpublished row exceeds 300s, else success "ok";
`title` carries `depth=N oldest=Ns dead_lettered=N` in the drain states.

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

**`…/health/watcher` retired with archiver#142** - it pinged Watcher over the
SDK, and the no-outbound-HTTP rule left nothing to ping. Its successor signal
is the announced-vs-applied generation drift on the InfoItem detail panel,
which measures whether Watcher is *acting on what we published* - the question
the badge was a proxy for.
