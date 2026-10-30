# Notification composer, preview and test-send

**What a notification says, and the one way to send one by hand** (archiver#367, epic #359;
design D3/A8). Who hears what is [NOTIFICATIONS.md](NOTIFICATIONS.md). The consumer, dispatch on
events, error reminders and shadow mode are #369's. It calls what this page describes.

## The composer: `src/core/notifications/content.py`

Pure: no database, no store, no Notifier. **Inputs:**

- co-core's event as it comes off the wire: `ChangeDetectedEvent`, `WatchErrorEvent` or
  `WatchRecoveredEvent`, unadapted;
- an `ItemFacts`;
- one row's `ContentOptions`, which `resolve_options` picks: the event's override, else
  `default`.

**Output:** `Composed(title, body)`. It's a port of Watcher `3ba20be`'s `content.py`,
`default_templates.py`, `diff.py` and `preview_fixtures.py`, with the same layout, toggles,
diff block and caps, so #369's shadow comparison reads like for like.

**What differs from Watcher, on purpose:**

- **The context is built field by field (D1).** Watcher flattened `event.metadata` into it,
  so a key on the wire could become a template variable. `TEMPLATE_VARIABLES`
  (`default_templates.py`) lists every variable, and a test holds the context equal to it.
  The names are Watcher's, except that `info_item_id` replaces `watched_item_id`.
  `change_revision_id` is gone: the event doesn't carry it.
- **Every render is sandboxed (D2),** defaults included, in `jinja2.sandbox.SandboxedEnvironment`.
  **Nothing returns template source.** Watcher's `render_template` sent an operator's raw Jinja
  to Slack when a template broke. Here:
  - a render raises;
  - `compose()`, the send path, renders **that event's default** for the failed field instead;
  - a WARNING names the subscription, the field and the error's type. It never carries the
    template, or the error's text, which can quote the template.
- **The sandbox is bounded** (CR 1): one `*` builds at most 100 000 items and one `**` takes
  an exponent of at most 100, so a template can't allocate a gigabyte in the one process.
  The preview and the test-send render in a worker thread, off the event loop. Nested loops
  can still burn CPU. A render budget is #369's to choose before saved templates render on
  every event.
- **At send an undefined variable renders empty** (lenient, as in Watcher), and only a raised
  error falls back. The preview renders strict.
- **Links point at Archiver's item page:** `app_url` is the origin
  (`ARCHIVER_PUBLIC_BASE_URL`), and `change_url` on a change is
  `{origin}/dashboard/info-items/{id}`. There's no per-change page.
  - `src/core/public_base_url.py` refuses anything but `http(s)://host[:port]`.
  - Unset or refused means no link, never a guessed host. The change body then drops its
    `ITEM:` line.
  - The API's `dashboard_url` uses the same helper.

**The default text is Watcher's, word for word,** the `[Watcher]` title prefix included:
recipients filter on it, and #369 compares titles. Renaming it is an operator decision.

- **Change:** a Markdown bullet list, in this order:
  - name;
  - `DOMAIN`, if toggled;
  - `URL`;
  - `PREVIOUS CHANGE` and `INTERVAL`, if toggled;
  - `TIMESTAMP`;
  - `ITEM`, with an origin;
  - the `NOTE` when `extraction_changed == "spec"`;
  - `DESCRIPTION` and `TAGS`, if toggled;
  - `DIFF: unavailable (<reason>)`, when a diff was asked for and couldn't be made.

  Then the diff, as a fenced block. The fence outruns any backtick run in the page's text, and
  the whole block is capped at 32 KiB (`MAX_RENDERED_DIFF_BYTES`).
- **Error:** `<url> returned HTTP <status|unknown>`. On a reminder, it adds "Still failing —
  previously notified …". #369 passes `previously_notified_at`; the composer keeps no reminder
  state.
- **Recovered:** `<url> is responding normally again`.

**Variables with no Archiver source:**

- `last_changed_at` is this change on a change, and empty on the other events.
- `tags` is empty until #362.
- A null `status_code` is left **undefined**, so `| default('unknown')` works.
- Every other absent value is `""`, never `None`.

## Item facts: `src/core/notifications/item_facts.py`

`load_item_facts(session, info_item_id)` reads:

- the name and description from the InfoItem;
- the URL and `domain_name` from the **announcing** source (the active binding), the rule
  `subscriptions_for` routes domain scope by;
- `check_interval` from `resolve_interval` (profile, then item, then domain), the cadence
  Watcher is told.

It returns `None` for an unknown item.

## The processor-text reader: `src/core/notifications/diff_loader.py`

A change notification's diff compares the two texts the event names (`previous_text_uri`,
`current_text_uri`). `load_change_diff(reader, event)` **never raises.** A failure is
`ChangeDiff(unavailable=<reason>)`, and the notification still goes out.

| Guard | Reason shown when it fails |
|---|---|
| `previous_text_uri` is null (a revision older than the processor) | `previous text not stored` |
| The URI names another bucket or scheme: no read at all | `<side> text not in the processor bucket` |
| The object's `size` is over the cap; the download is ranged too | `content too large` |
| A 404 (a lifecycle rule may reap old text; unmeasured): INFO, no retry | `<side> text unreadable` |
| Any other read error: WARNING, by error type | `<side> text unreadable` |
| The bytes don't hash to the fingerprint (the fingerprint *is* the text's digest) | `<side> text failed its hash check` |
| The texts differ only in whitespace | `whitespace-only change` |
| No reader | `previous text unreadable` |

Reads and `difflib` run in a thread, because the SDK is synchronous. No text reaches a log.

- **The identity:** its own service account with `roles/storage.objectViewer` on
  `gs://co-gcs-processor` **only**, so it can't read raw blobs (the `content.blobs` boundary).
  It isn't Watcher's `co-gcs-blob-reader`.
- **The key:** a unit credential, `LoadCredential=processor-text-reader:/etc/archiver/processor-text-reader.json`,
  **with** the empty `SetCredential=` fallback. The client is built from that file explicitly,
  never through `GOOGLE_APPLICATION_CREDENTIALS`, which would make it ambient for every GCS
  call.
- **Configuration:** `archiver.service` alone sets `ARCHIVER_PROCESSOR_TEXT_BUCKET`.
  `ARCHIVER_DIFF_MAX_INPUT_BYTES` (default 1 MiB) caps each side. A pin test keeps both on
  that unit alone.
- **Degrade, don't refuse.** The lifespan builds one reader after the gates, makes no request,
  and closes it at shutdown. The journal says which case applies:

  | Startup | Journal |
  |---|---|
  | configured | `processor text reader configured (bucket co-gcs-processor)` |
  | a bucket without a usable key | one WARNING, `… change diffs are unavailable` |
  | no bucket (dev server, suite) | INFO only |

  It also says `links point at <origin>`, or that there are none.

### Provisioning (operator, off-host, once)

As for the backup's account ([BACKUP.md](BACKUP.md)), with `gcloud` on a workstation. Nothing
below prints the key.

```bash
P=<project>; SA=archiver-processor-text-reader
gcloud iam service-accounts create "$SA" --project "$P" \
  --display-name "Archiver: read processor texts (archiver#367)"
gcloud storage buckets add-iam-policy-binding gs://co-gcs-processor \
  --member "serviceAccount:$SA@$P.iam.gserviceaccount.com" --role roles/storage.objectViewer
gcloud iam service-accounts keys create ./processor-text-reader.json \
  --iam-account "$SA@$P.iam.gserviceaccount.com"
```

Copy the file to the host, then install it as root, without printing it:
`sudo install -o root -g root -m 0600 processor-text-reader.json /etc/archiver/processor-text-reader.json`,
then shred the copies. Skipping this only leaves diffs unavailable. To rotate, create a new key,
overwrite the file, `sudo systemctl restart archiver`, and delete the old key.

### Proving the read (operator, on the live release)

`src/core/tools/check_processor_text.py` reads one `uri` + `fingerprint` pair through the
service's own reader and prints `ok <bytes>` or `unavailable: <reason>`. **It never prints the
text.** The run below uses the unit's credential, user and bucket, so it proves the unit's
path, not a root read:

```bash
sudo systemd-run --pipe --wait --quiet -p User=archiver -p WorkingDirectory=/srv/archiver/live \
  -p LoadCredential=processor-text-reader:/etc/archiver/processor-text-reader.json \
  -p Environment=ARCHIVER_PROCESSOR_TEXT_BUCKET=co-gcs-processor \
  /srv/archiver/live/.venv/bin/python -m src.core.tools.check_processor_text \
  'gs://co-gcs-processor/blobs/<hex>.bin' 'sha256:<hex>'
```

The pair is a completed `process_commands` row's `output_uri` + `output_digest`, from Watcher.
Exit 0 means ok, 1 unavailable, 2 no reader.

## The preview (D5)

The subscription form (`/dashboard/notifications/new` and `/{id}/edit`) gives each content
block its Jinja **title** and **body** fields, with a live preview beside them.

- **How it renders:** `POST /dashboard/notifications/preview` takes the posted form and an
  event, renders it **strict in the sandbox** against `preview_fixtures` (one co-core event per
  kind, an example item, two canned texts diffed by the real algorithm), and returns
  `notifications/_preview.html`. It makes **no Notifier call** and touches no database.
- **One validator.** The preview and the save path both run `ContentOptions` (`content_config`'s
  sandbox parse), so a syntax error shows in both places, naming its block and field.
  Strict rendering adds undefined-variable errors **to the preview only**. A default-block body
  that names `status_code` is right for errors and undefined on a change, so it still saves.
- **The form is the whole truth.** A cleared field clears its template, and an override holding
  one can be turned off. #363's carry-over went in the same change.
- **Fidelity:** the fixtures are co-core's own models through the composer's own context, so
  the preview shows no variable a real send lacks. A test renders every documented variable
  strict against each fixture.

## The test-send (D6)

**`POST /dashboard/notifications/{id}/test-send`**, a button on the edit page only, behind a
static confirm that names the channel id. It does the following:

1. renders the row's **saved** options against the `change_detected` fixture, whichever events
   the row hears, through `compose()`;
2. prefixes the title with `[Test] `;
3. makes **one** dispatch to the row's `remote_channel_id`, with idempotency key
   `archiver:test:{subscription_id}:{ULID}` (so each press is its own dispatch) and metadata
   `{"test": true, "subscription_id": …}`;
4. answers in `#test-send-result` and as a flash:

   | Outcome | Flash |
   |---|---|
   | `succeeded` | success, with the dispatch id |
   | `partial` or `failed` | warning, with the id and the status |
   | refused, or no Notifier configured | error, with the reason |

5. logs one INFO line with the subscription id, channel id, dispatch id and status, never the
   text or the key.

- **Dashboard only.** There's no API route and no SDK method, so an API key, and an agent
  holding one, can't post to Slack or an inbox. The dashboard needs an exe.dev login.
- **D3: text travels as variables.** `Notifier.dispatch_composed`
  (`src/core/notifier/client.py`) is the adapter's one dispatch. It sends
  `title_template="{{ title }}"`, `body_template="{{ body }}"` and
  `variables={"title": …, "body": …}`. Notifier renders both template fields as Jinja
  (StrictUndefined, no escaping) and never evaluates a variable's value, so text holding `{{`
  or `{%` arrives as written. `tests/core/notifier/test_sdk_boundary.py` pins the shape and
  the single call site. #369 dispatches through the same function.
- **On 8001** it reaches the dev tenant, whose channels (`dev-sink`) reach nobody. **On 8000 it
  reaches the Slack channel or the inbox. That's the operator's action, never an agent's.**
