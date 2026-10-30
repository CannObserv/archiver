# Notification subscriptions

**Who hears which events, and how** (archiver#363; design D3: "Watcher monitors and
reports; Archiver decides who hears; Notifier delivers"). Subscriptions replace Watcher's
`notification_templates`. **Nothing sends yet.** This is the model, the API, the dashboard
and the import. Composition, preview and test-send are #367. The `info.watch-events`
consumer, shadow mode and dispatch are #369. The Notifier credential is #368 (§ The credential).

## The table: `information.notification_subscriptions`

| Column | |
|---|---|
| `id` | ULID. #369's idempotency key is `archiver:{event}:{subscription_id}:{event_id}`, so ids must stay stable. |
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
info_item_id, event)`, is **the** matcher. #367's preview and #369's dispatch call it, and
the item page shows its answer. It follows Watcher's rule (`notify.py` at `ebd1be5`):
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
filter nothing.** Watcher doesn't check those items, so no event arrives. What to do with
an in-flight event is #369's call. `notified_by` runs the matcher once per event for the
item page.

## Content options: `ContentConfig`

`src/core/notifications/content_config.py` defines Watcher's `ContentConfig`: a `default`
`ContentOptions` plus `overrides` keyed by event. An override replaces the defaults for its
event; it doesn't merge with them.

- `include_diff_snippet` (default on) with `diff_snippet_lines` (1-200, default 25), and
  `include_diff_full`, which wins when both are on.
- `include_temporal_context`, `include_domain`, `include_last_changed_at`,
  `include_description`, and `include_tags`, which stays inert until tags exist (#362).
- `title_template` and `body_template`: Jinja.

**Validated at write time, and stricter than Watcher:**

- an unknown key is a 422 at every level, including Watcher's two retired keys
  (`RETIRED_CONTENT_KEYS`);
- an override key must be a known event;
- the toggles are strict booleans;
- each template must **parse** in `jinja2.sandbox.SandboxedEnvironment`. Only syntax is
  checked, because the variables are #367's render context. **#367 renders in the sandbox
  too:** Watcher's plain `Environment` lets a template reach Python attributes, and here a
  template arrives through an API key.

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
- **The Jinja fields stay API-only** until #367 ships the preview beside them. Without a
  preview, an edit couldn't be checked before something sends. The form therefore **carries
  stored templates over**, and refuses to turn off an override that holds one rather than
  erase it.
- **No send or test control.** When #367 adds one, a test-send to a production channel is an
  operator action.
- **The item page's "Notified by" row** (`#ii-notified-by`, a full-width cell in the
  Overview grid) shows `notified_by`: each subscription that hears the item, its scope and
  its events. Each links to its edit page. With none, it links to `/new` with the item
  prefilled.
- **The domain page** lists its domain-scoped rows, inactive ones badged, above the danger
  zone, with an "Add a subscription for this domain" link.

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
- **The adapter is read-only.** `src/core/notifier/client.py` is the only importer of
  `notifier-client` (a git tag, `v0.3.2`; upgrade as for Power Map,
  [DEPLOYMENT.md](DEPLOYMENT.md) § Power Map SDK). It lists channels and nothing else, and a
  guard test pins that. Test-send is #367's and dispatch #369's.

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
URL's scheme) and id, or why there is no list. It has no send control.

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
