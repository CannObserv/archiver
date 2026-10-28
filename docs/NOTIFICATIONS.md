# Notification subscriptions

**Who hears which events, and how** (archiver#363; design D3: "Watcher monitors and
reports; Archiver decides who hears; Notifier delivers"). Subscriptions replace Watcher's
`notification_templates`. **Nothing sends yet.** This is the model, the API, the dashboard
and the import. Composition, preview and test-send are #367. The `info.watch-events`
consumer, shadow mode and dispatch are #369. The Notifier credential is #368.

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
| `remote_channel_id` | A Notifier channel in **Archiver's** tenant, ULID-shaped and `NOT NULL`. Only the shape is checked until #368. |
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
  dashboard's clamped `limit`/`offset`.
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
