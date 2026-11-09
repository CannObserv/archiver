# Notification subscriptions

**Who hears which events, and how** (archiver#363; design D3: "Watcher monitors and
reports; Archiver decides who hears; Notifier delivers"). Subscriptions replace Watcher's
`notification_templates`. This is the model, the API, the dashboard and the import.
Composition, the preview and the test-send are #367's:
[NOTIFICATION_COMPOSER.md](NOTIFICATION_COMPOSER.md). The `info.watch-events` consumer,
shadow mode, the drain and error reminders are #369's (§ Dispatch on events). The Notifier
credential is #368's (§ The credential).

## The table: `information.notification_subscriptions`

| Column | |
|---|---|
| `id` | ULID. Dispatch's idempotency key is `archiver:{event}:{subscription_id}:{event_id}`, so ids must stay stable. |
| `title` | ≤100. It names the row. Watcher's `channel_hint` is dropped: nothing read it. |
| `scope` | `global`, `domain` or `item`. A CHECK ties it to exactly one ref: `domain_id` for `domain`, `info_item_id` for `item`, neither for `global`. |
| `domain_id` | FK `domains.id`, **`RESTRICT`**. `DELETE /domains/{name}` 409s while any subscription names the row, active or not, as it does for InfoSources ([DOMAINS.md](DOMAINS.md)). |
| `info_item_id` | FK `info_items`, `CASCADE`, like every child of an item. Item delete still records its `revoked` tombstone. |
| `events` | A non-empty subset of `change_detected`, `watch_error` and `watch_recovered`. Enforced by a CHECK and stored in that order. Error reminders (#369) ride on `watch_error`. |
| `content_config` | JSONB. `NULL` means all defaults (see below). |
| `remote_channel_id` | A Notifier channel in **Archiver's** tenant, ULID-shaped and `NOT NULL`. Only the shape is checked; Settings → Notifier lists the real ids (§ The credential). |
| `is_active` | An inactive row matches nothing. |
| `imported_watcher_id` | The Watcher template the row came from. It is unique, set on create only, and keys the importer. |

**The scope and its ref are fixed after create**, which is Watcher's rule: to re-scope, delete
the row and create another. Mutable fields are `title`, `events`, `remote_channel_id`,
`is_active` and `content_config` (`MUTABLE_FIELDS`).

## Who hears: `subscriptions_for`

`src/core/services/notification_subscriptions.py`, `subscriptions_for(session,
info_item_id, event)`, is **the** matcher. Dispatch calls it once per fact, and the item page shows
its answer. The preview doesn't: it renders fixtures, not an item. It follows Watcher's rule (`notify.py` at `ebd1be5`):
every active subscription whose `events` hold the event, across the **union** of three
scopes, each row once and in id order.

- **global** matches every item.
- **domain** matches the items whose **announcing** source's host is the row's
  `Domain.name`. The announcing source is the one on the active binding, and its host is
  `InfoSource.domain_name`. That is not a field on the item: when a binding moves host,
  the old domain's rows stop matching. An item with no active binding, or on a host with no
  Domain row, matches no domain row.
- **item** matches that item.

No scope overrides another, nothing opts out, and there is no channel-level dedup: two
rows on one channel both match (watcher #200 F2). **Archive, pause and host suspension
filter nothing.** Watcher doesn't check those items, so no event arrives, and one already
in flight is still composed (#369 D2): it happened before the state changed. `notified_by` runs the matcher once per event for the
item page.

## Content options: `ContentConfig`

`src/core/notifications/content_config.py` defines Watcher's `ContentConfig`: a `default`
`ContentOptions` plus `overrides` keyed by event. An override replaces the defaults for its
event; it doesn't merge with them.

- `include_diff_snippet` (default on) with `diff_snippet_lines` (1-200, default 25), and
  `include_diff_full`, which wins when both are on.
- `include_temporal_context`, `include_domain`, `include_last_changed_at`,
  `include_description`, and `include_tags`, the item's tags as a `TAGS:` line (#362).
- `title_template` and `body_template`: Jinja.

**Validated at write time, and stricter than Watcher:**

- an unknown key is a 422 at every level, including Watcher's two retired keys
  (`RETIRED_CONTENT_KEYS`);
- an override key must be a known event;
- the toggles are strict booleans;
- each template must **parse** in `jinja2.sandbox.SandboxedEnvironment`. Only syntax is
  checked at write time; the dashboard's preview also names undefined variables.
  **Every render is sandboxed too** ([NOTIFICATION_COMPOSER.md](NOTIFICATION_COMPOSER.md)):
  Watcher's plain `Environment` lets a template reach Python attributes, and here a template
  arrives through an API key.

The API stores what was sent (`exclude_unset`), and the dashboard stores only what differs
from the defaults. Either way, a later default change still reaches rows that never chose
otherwise. `audit_stored_documents` sweeps the column as kind `notification_content`.

## API

| | Route | SDK (5.16.0) |
|---|---|---|
| List | `GET /notification-subscriptions` | `list_notification_subscriptions(scope=, domain=, info_item_id=, is_active=, limit=, offset=)` |
| Create | `POST /notification-subscriptions` | `create_notification_subscription(body)` |
| Get | `GET /notification-subscriptions/{id}` | `get_notification_subscription(id)` |
| Update | `PATCH /notification-subscriptions/{id}` | `update_notification_subscription(id, changes)` |
| Delete | `DELETE /notification-subscriptions/{id}` | `delete_notification_subscription(id)` |

- **The list** is ordered oldest first, in the usual page shape, with a 422 over 500. Its
  filters select rows **by their own scope**: `domain=` returns that host's domain rows, not
  everything that would match an item on it.
- **Create:** `domain` is a hostname that must have a Domain row; `item` takes an
  `info_item_id`. A ref that doesn't fit the scope, or names no row, is a 422 on that field.
  A duplicate `imported_watcher_id` is a 409.
- **`PATCH`** changes only the fields sent. It replaces `content_config` whole, and `null`
  restores the defaults. It refuses `scope`, `domain`, `info_item_id` and
  `imported_watcher_id`, and a `null` on any other field.
- **Nothing publishes.** No write leaves a `changes_outbox` row.

## Dashboard

- **`/dashboard/notifications/`** (sidebar: Registry → Notifications) lists every row,
  grouped Global, Domain, Item, with links to the domain or item. It paginates with the
  dashboard's clamped `limit`/`offset`; each heading counts every row of its scope.
- **`/new` and `/{id}/edit`** are one form, `notifications/form.html`, a plain POST: 303 to the
  list, or the form again with a 422 and the reasons, keeping what was posted.
  - `/new?scope=&domain=&info_item_id=` prefills it.
  - On edit, the scope and its ref show read-only.
  - Content options are one fieldset per block. Fields are named `<block>__<option>`, and
    `override__<event>` turns an event's block on (`src/dashboard/notification_form.py`).
- **`/{id}/delete`** sits in a danger zone with a static confirm.
- **Each block has its Jinja title and body fields, with a live preview beside them** (#367
  D5): `POST /dashboard/notifications/preview` renders the posted form in the sandbox against
  canned fixtures, with no Notifier call. A cleared field clears its template.
- **The edit page's test-send** (#367 D6) makes one dispatch of the saved options to the row's
  channel, behind a static confirm. It's dashboard-only, and on 8000 it's an operator action.
  Both: [NOTIFICATION_COMPOSER.md](NOTIFICATION_COMPOSER.md).
- **The item page's "Notified by" row** (`#ii-notified-by`, a full-width cell in the
  Overview grid) shows `notified_by`: each subscription that hears the item, its scope and
  its events. Each links to its edit page. With none, it links to `/new` with the item
  prefilled.
- **The domain page** lists its domain-scoped rows, inactive ones badged, above the danger
  zone, with an "Add a subscription for this domain" link.

## Dispatch on events (archiver#369)

Design D3 and C-a: Watcher outboxes each observed edge on `info.watch-events`; Archiver
decides who hears and composes; Notifier delivers. **Shadow until F3, Archiver's since T.**

**Consume** (group `archiver.watch-events`, [BUS_CONSUMERS.md](BUS_CONSUMERS.md)). Per fact,
`subscriptions_for` runs once, the diff is read once (only if a row shows one), and each
subscription's text is composed in a worker thread. One row per subscription goes into
`notification_dispatches` ([SCHEMA_BUS.md](SCHEMA_BUS.md)) in one short transaction, the
subscriptions taken `FOR KEY SHARE`, then the ack. A template that fails or passes the render
budget falls back to its event's default; a diff that can't be read names why.

**The cutover instant T** (`ARCHIVER_NOTIFY_CUTOVER_AT`, ISO 8601 UTC) is the one switch. A
row is `send` (`pending`) only when T is set and the fact's `occurred_at` (a reminder's own
instant) is at or after T; otherwise `shadow`, never sent. Unset *is* shadow: the journal says
`notify cutover: unset (shadow)`. T without the Notifier gate, or not an unambiguous UTC
instant, refuses startup. It is `archiver.service`'s own `Environment=` line, set at F3
(`tests/deploy/test_archiver_unit_notifier.py`). A fact before T that arrives late is
shadow-recorded: Watcher sent it.

**The drain** (`src/core/notifications/drain.py`), a lifespan task wherever a Notifier client
exists. It claims the oldest due `pending` row `FOR UPDATE SKIP LOCKED` and calls
`dispatch_composed` with the row's key (30 s timeout: Notifier delivers inline). The row stays
locked across the call, which is what makes a double send impossible; deleting its
subscription (`SET NULL` on that row) waits for it, up to 30 s.

| Outcome | Row |
|---|---|
| `succeeded` | `sent`, with Notifier's dispatch id |
| any other `DispatchOut` | `failed`, with the last attempt's reason. **Final**: the key is permanent per tenant, so a re-POST returns the failed record. Nothing redelivers |
| timeout, connection, 5xx, 429, 401/403, unreadable answer, any error the adapter didn't translate | still `pending` under the same key, retried at 30 s doubling to 1 h; the 8th attempt ends `failed` with the last reason |
| 404 (no channel), 422, other 4xx | `failed` at once |
| subscription deleted or now inactive | `skipped`, never sent |

**Error reminders** (`src/core/notifications/reminders.py`): a lifespan timer every 15 min,
under `ARCHIVER_BUS_CONSUMER`. For each item whose cached `health` is `error` and that Watcher
still checks (not archived, paused or host-suspended), the episode is its newest `watch_error`
row with no newer `watch_recovered` row. Each subscription that still hears `watch_error` and
has a row in the episode is reminded once its newest row there (edge or last reminder) is
`ARCHIVER_ERROR_RENOTIFY_INTERVAL` old (default `24h`), keyed
`archiver:watch_error_reminder:{subscription_id}:{episode_event_id}:{n}` and composed with
`previously_notified_at`. An item in error with no episode row is skipped with an INFO line.
Unlike Watcher, nothing reminds a paused or archived item.
**Residual:** episodes are known only from rows. An item that recovers while no subscription
hears `watch_recovered`, then errors again, can be reminded once on the old episode if its
`info.watch-status` level lands before the new edge fact: a window of one fact's delivery
latency. No field orders the two. The same timer prunes terminal rows
past `ARCHIVER_NOTIFY_RETENTION_DAYS` (90).

**The log** is the dashboard's `/dashboard/notifications/log` ([PAGES.md](PAGES.md)).

**Shadow parity before F3 (D6).** Evidence, not a tool. Archiver's side is a read-role export
of the facts in the window, with each row's Watcher template id:

```bash
psql -d archiver -At -F $'\t' -c "SELECT d.info_item_id, d.event_type, d.reminder,
  to_char(d.occurred_at AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),
  s.imported_watcher_id, d.mode, d.status, d.subscription_id
  FROM information.notification_dispatches d
  LEFT JOIN information.notification_subscriptions s ON s.id = d.subscription_id
  WHERE d.occurred_at >= '<window start>' ORDER BY d.occurred_at, s.imported_watcher_id"
```

Filter on `occurred_at`, the fact's instant, never `created_at`: a replayed fact's row is
written later than the fact. Watcher's coordinator exports its `NOTIFICATION_DISPATCHED`
audits for the same window, one row per template. The join is per fact and subscription for
the three edges: same `archiver_info_item_id`, event type, and template id ↔
`imported_watcher_id`, with Watcher's `created_at` 0–120 s after Archiver's `occurred_at`
(one-sided: Watcher dispatches after the fact). A Watcher row with zero or several candidates
is reported as such, never resolved by nearest. Reminders compare by count per episode. Bodies
compare less their links.

**F3** (CannObserv/watcher#376), cut over 2026-11-06. Parity was 20/20, lag 0.8–1.7 s. T =
`2026-11-06T21:00:00Z`, the operator's: Archiver went live with it in `6f204b7af9bb` at
20:16Z (#465), then Watcher at 20:18Z. Facts before T are Watcher's, at or after it Archiver's.
Expect up to one extra reminder per open episode in the first 24 h: Archiver can't see
Watcher's reminders. Removing T reverts to shadow, and without Watcher's T also coming off,
nobody sends. On 8001, `ARCHIVER_DEV_NOTIFY_CUTOVER_AT` maps beside the dev Notifier pair only.

## Importing Watcher's templates

`python -m src.core.tools.import_watcher_notification_templates` reads the Watcher export
(`schema_version: 1`, `notification_templates`) on stdin and creates rows **through the
SDK**, the operator's own write path. It needs no production-database opt-in.

- **Keyed by Watcher's template id** (`imported_watcher_id`). A template with no row is
  created. One that has a row is `unchanged` or `differs`, and a differing row is reported
  and **never overwritten**: Archiver's copy is the operator's now. Watcher re-exports before
  F3, and a re-run lands on the same subscription ids.
- **`--channel-map WATCHER_ID=ARCHIVER_ID`** (repeatable) translates the Watcher-tenant
  channel. CannObserv/notifier#117 copied the channels into Archiver's tenant under new ids:
  - Slack: `01KQN12MHJJHFETN2XMDF98GHY` → `01M5AX8CE8PBMQZMQ5TBBB9RAP`;
  - Mailgun: `01KQN12MHY05FEGK9BCMJMACW8` → `01M5AX8CEAEKPM7JJ3D0VY20AF`.

  **On a dev server, map onto `dev-sink`** (`01M5APS9R7A0QEDB9522MRA4CT`). A production id
  there is a channel the dev key can't reach.
- `watched_item` becomes scope `item`, on `archiver_info_item_id`. The two retired content
  keys are dropped. `channel_hint` is ignored.
- **The whole file is refused before anything is written**, with every problem listed, if it
  has:
  - an unmapped or null channel;
  - a domain with no Archiver row, or an item not in Archiver;
  - any other unknown content key;
  - anything the API would 422.
- Exit 0 means done, 1 means refused, 2 means an error. Only template ids, channel ids and
  counts are printed: the file holds titles and hints, and these repos are public.

```bash
cd /srv/archiver/live
sudo cat /root/<dir>/watcher-export-YYYY-MM-DD.json \
  | ARCHIVER_API_KEY=… .venv/bin/python -m src.core.tools.import_watcher_notification_templates \
      --base-url http://localhost:8000 \
      --channel-map 01KQN12MHJJHFETN2XMDF98GHY=01M5AX8CE8PBMQZMQ5TBBB9RAP \
      --channel-map 01KQN12MHY05FEGK9BCMJMACW8=01M5AX8CEAEKPM7JJ3D0VY20AF \
      --dry-run
```

Then run the same without `--dry-run`. At the 2026-10-14 export, it creates 2 global rows
and refuses 0. A re-run reports 2 unchanged.

## The credential

**`archiver.service` alone may notify the production tenant** (archiver#368). Watcher's
#277/#278 pattern:
its key sat in an env file that agent shells sourced, and ~1289 fixture notifications
reached production. A notification can't be recalled. `src/core/notifier/gate.py` judges
three things at startup, before any resource is built:

| The process holds | Outcome |
|---|---|
| neither `ARCHIVER_NOTIFIER_BASE_URL` nor `ARCHIVER_NOTIFIER_ENABLED=1` | dormant, `Notifier not configured` |
| the URL, without the flag exactly `"1"` | **refuses to start** |
| the flag, without the URL or without a key | **refuses to start** |
| a key from `ARCHIVER_NOTIFIER_API_KEY` aimed at port 9000 | **refuses to start**: production's key is a credential only |
| both the credential and `ARCHIVER_NOTIFIER_API_KEY` | **refuses to start** |
| all three | one client, `Notifier configured at <url> (key: credential)`. Never the key |

- **The lifespan makes no Notifier call.** An outage must not stop the registry.
- **The adapter is narrow.** `src/core/notifier/client.py` is the only importer of
  `notifier-client` (a git tag, `v0.3.2`; upgrade as for Power Map,
  [DEPLOYMENT.md](DEPLOYMENT.md) § Power Map SDK). It lists channels and makes one kind of
  dispatch, `dispatch_composed`, which passes composed text as variables (#367 D3). A guard
  test pins both, and bans `send_test`, `redeliver` and the channel writes.

| Where | What |
|---|---|
| `deploy/archiver.service` | `Environment=ARCHIVER_NOTIFIER_BASE_URL=http://notifier:9000`, `Environment=ARCHIVER_NOTIFIER_ENABLED=1`, and `LoadCredential=notifier-key:/etc/archiver/notifier.key`, with **no** `SetCredential=` fallback. No other unit holds any of it (`tests/deploy/test_archiver_unit_notifier.py`) |
| `/etc/archiver/notifier.key` | `root:root 0600`, the raw key alone. **Missing, the start fails** (243/CREDENTIALS), so `deploy.sh` refuses, before CI or a build, a deploy to a host without it. It goes in first |
| repo `.env` | `ARCHIVER_DEV_NOTIFIER_BASE_URL=http://notifier:9001` and `ARCHIVER_DEV_NOTIFIER_API_KEY`. `scripts/dev_server.sh` maps the pair onto the gate's variables, sets the flag only beside both, and refuses a dev URL on :9000 |
| `tests/conftest.py` | clears every `ARCHIVER_NOTIFIER_*`, `ARCHIVER_DEV_NOTIFIER_*` and `CREDENTIALS_DIRECTORY` |

**The tenants** (CannObserv/notifier#117). Each key gets 401 on the other port.

| | Production, `:9000` | Development, `:9001` |
|---|---|---|
| tenant `archiver` | `01M5AR46KXYEPMMBVMZ5HQTM66` | `01M5APS4GQBN671G050RD82Y44` |
| key | `archiver-prod` `01M5AR46M4GYRHJFGM4NGSPA8V` | `archiver-dev` `01M5APS4GV1BJPE51B9D6W6WJS` |
| channels | `archiver-slack` `01M5AX8CE8PBMQZMQ5TBBB9RAP`, `archiver-mailgun` `01M5AX8CEAEKPM7JJ3D0VY20AF` | `dev-sink` `01M5APS9R7A0QEDB9522MRA4CT` (syslog, reaches nobody), `dev-sink-failing` `01M5APS9R7A0QEDB9522MRA4CV` |

**Settings → Notifier** (`/dashboard/settings/notifier`) proves the key end to end with zero
sends: one `GET /api/v1/channels` per view, then each channel's name, type (the masked
URL's scheme) and id, or why there is no list. It has no send control: the test-send is on a
subscription's edit page.

### Installing the key (operator, as root, once)

Nothing below prints a key, and none of it goes in argv. The staged files hold four lines:
`tenant_id=`, `key_id=`, `raw_key=`, `environment=`. Paste the block whole: it stops at the
first failed check, before anything is written or shredded. Each check is its own line,
since `set -e` ignores the left side of `&&` and a `!` command.

```bash
(
set -euo pipefail
trap 'echo "stopped at: $BASH_COMMAND" >&2' ERR
F=/root/notifier-117/archiver-production.env D=/root/notifier-117/archiver-development.env
E=/home/exedev/archiver/.env K=/etc/archiver/notifier.key
sudo grep -qx 'environment=production' "$F"
sudo grep -qx 'environment=development' "$D"
[ "$(sudo grep -c '^raw_key=' "$F")" = 1 ]
[ "$(sudo grep -c '^raw_key=' "$D")" = 1 ]
if grep -q '^ARCHIVER_DEV_NOTIFIER_' "$E"; then echo "dev pair already in $E" >&2; exit 1; fi
sudo sh -c "umask 077; sed -n 's/^raw_key=//p' $F > $K"
sudo test -s "$K"
[ "$(sudo stat -c '%U:%G %a' "$K")" = 'root:root 600' ]
[ -z "$(tail -c1 "$E")" ] || echo >> "$E"   # a last line without its newline
sudo sed -n 's/^raw_key=/ARCHIVER_DEV_NOTIFIER_API_KEY=/p' "$D" >> "$E"
echo 'ARCHIVER_DEV_NOTIFIER_BASE_URL=http://notifier:9001' >> "$E"
sudo shred -u "$F" "$D"
sudo rmdir /root/notifier-117
echo "installed $K; staged files shredded"
)
```

To rotate, mint the new key in Notifier, overwrite the file the same way, and
`sudo systemctl restart archiver`.
