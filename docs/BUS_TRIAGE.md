# Bus Triage Screen

**`/dashboard/bus-triage` (archiver#271): the operator's screen for dead-lettered
`changes_outbox` rows and archiver's DLQs.** [PAGES.md](PAGES.md) keeps the inventory
line for its routes; the badges that link here are [HEALTH_ROW.md](HEALTH_ROW.md). The
screen is a UI over the existing rules, not a new policy: [BUS.md](BUS.md) § triaging
dead-lettered outbox rows, and [BUS_CONSUMERS.md](BUS_CONSUMERS.md) § DLQ triage.

**GET `/dashboard/bus-triage`** (`bus_triage/index.html`) - the page the
Outbox and Consumers badges link to in their "N dead-lettered" state; no sidebar entry. One
section for the outbox (`bus_triage/_outbox_section.html`, `#triage-outbox`) and one per
queue in `dlq_triage.TRIAGE_DLQS` (`bus_triage/_dlq_section.html`,
`#triage-dlq-<dlq with dots as dashes>`), so a new owned group appears by itself. All
sections render server-side on load; each is also its own partial, which its Re-list and
Previous / Next buttons and its row actions swap whole (`hx-swap="outerHTML"`). Every
partial response renders with `swapped`, so its focus script moves focus to the section's
`<h2 tabindex="-1">` (SCREENS.md § HTMX mutations): each swap removes the button clicked.
The page's own render never moves focus. Routes in
`src/dashboard/routes/bus_triage.py`, messages in `src/dashboard/bus_triage.py`; both call
the core triage modules directly, with no API route between.

- **GET `/dashboard/bus-triage/outbox`** - `outbox_triage.list_dead_lettered`, oldest
  first: row id, dead-lettered and created times, topic and `event_type`, `last_error`,
  attempts, the payload in a `<details>` (`tojson`, never `|safe`). A database read, so it
  renders bus-dormant. Empty state "No dead-lettered outbox rows."
- **POST `/dashboard/bus-triage/outbox/{row_id}/rearm`** - rendered only where
  `REARMABLE_TOPICS` holds the topic (else a disabled button titled why).
  **POST `.../outbox/{row_id}/discard`** - `hx-confirm` naming the row and topic.
- **GET `/dashboard/bus-triage/dlq/{dlq}`** - `dlq_triage.list_dead_letters`, oldest
  first: entry id and time; the parking group with an "archiver" / "not archiver" badge,
  or "no provenance"; `parked_as`, `source_id`, `reason`; `event_type` with a "decodes" /
  "does not decode" badge and `decode_error`; the fields in a `<details>`. A "parked twice"
  badge on entries sharing `(provenance.group, provenance.source_id)` on the page. The read
  is bounded by `BROKER_READ_TIMEOUT_SECONDS` (5s, the lag probe's reason). States that are
  never an empty table: "dormant" (no `ARCHIVER_REDIS_URL`), "init failed" (URL set, no
  client), "unreadable" (`RedisError` / `OSError` / timeout, its class-only text shown).
  Empty state "No dead letters." A queue outside `TRIAGE_DLQS` is the 404 page.
- **POST `.../dlq/{dlq}/{entry_id}/reprocess`** - rendered only on `owned` entries (else
  disabled). **POST `.../dlq/{dlq}/{entry_id}/discard`** - offered on every entry, as the
  API does (discard does not filter; deciding is archiver's role); its `hx-confirm` names
  the foreign group, or says no provenance proves whose it is.

Every action is per row, re-renders its section at the page it was taken on
(`?limit=&offset=` ride the POST URL), and reports through `showFlash` at 200: one message
per core outcome - rearm `rearmed` / `not_found` / `refused` / `rejected`; reprocess
`reprocessed` / `not_found` / `not_owned` / `deferred` / `undecodable` / `rejected` /
`failed`; discard `discarded` / `not_found`. A broker failure mid-discard or mid-reprocess
flashes the progress, the id in doubt and "re-list before retrying". A malformed row id or
an inexact stream id, or a DLQ action with no broker client, is an error flash that
reaches no core function. Each action that does reach one writes a `Dashboard bus triage
action` journald line: `app_user_id` (never the email), `action`, `queue`
(`changes_outbox` or the DLQ), `ids`, `outcome` (`interrupted` for a mid-way broker
failure, `error` when the core call raised - the crash itself still reaches the error
handler).
