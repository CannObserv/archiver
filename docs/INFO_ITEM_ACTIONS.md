# Dashboard - the Information Item detail screen's action routes

**The InfoItem hub's action-route contracts: the shared Watcher-POST contract,
the routes retired with the SDK, and the always-200 always-flash replication
outcome rule.** Split out of [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md), which
keeps the screen's sections, partials and swap targets, when that file passed
its context budget. [PAGES.md](PAGES.md) keeps the inventory line for each
route; a behaviour change updates both, in the same commit.

## Action-route contracts

Moved here from [PAGES.md](PAGES.md), which keeps the inventory line for each of
these routes. This is the behaviour behind them.

**The Watcher action POSTs share a contract.** `toggle-watch-active` and
`watch-cadence` each re-render a Watcher partial and set `HX-Trigger:
{"watcherUpdated":{}}`. Their forms use `hx-swap="none"`, so the rendered body is
discarded and the trigger is what refreshes `#watcher-section` - swapping the
response in *and* firing the trigger would render twice. On failure each adds a
`showFlash` error to that trigger rather than 500ing (#60, #61). Each also carries
`hx-on::after-request` moving focus to `#watcher-heading` (archiver#181): the
refresh destroys the control that was clicked, and the `<h2>` is the nearest
thing that survives it, living in `detail.html` outside the swapped region. The
focus-script-in-the-response trick the domain notes row uses cannot work here -
`hx-swap="none"` discards the body a script would ride in.

**There were five.** `begin-watching`, the SDK's `check-now`, and `resync-watcher` were
SDK-backed and retired with it in archiver#142, along with the stale-link
reconcile they triggered (a `WatcherNotFound` NULLed `watcher_item_id` so the
panel could re-offer "Begin Watching"). Nothing replaces them individually:
reconciliation is level-triggered off `info.registry`, so there is no per-item
push to retry, no remote id to go stale, and no provisioning gesture to repeat.
The two survivors are *local* writes
that announce and let Watcher converge; the route entries in [PAGES.md](PAGES.md) name only what each adds.

**`toggle-watch-active`.** The re-render still shows applied state, so the button flips only once Watcher reports back on `info.watch-status` - the lag window is the announcement round-trip and stays visible as generation drift. The affordance is gated on `has_active_source` - as the cadence editor is, and as the panel's own state now is (archiver#142): mutating policy on an item that cannot announce live would emit a *tombstone* and burn a generation for nothing. **The route enforces the same gate** (archiver#167), for a stale tab whose binding was deactivated after render, or a script: on an unannounceable item it writes nothing, flashes "no active source with extraction specs", and re-renders, which shows `not_watching` and corrects the tab. `watch-cadence` does the same, before its vocabulary check. A failed local write rolls back, flashes "the change was not saved", and renders `degraded` **from the path id** - reading through the rolled-back ORM object would emit IO from the template and raise `MissingGreenlet`.

**`check-now`** (archiver#370, epic #359 A11). The Watcher-POST contract, with an empty body: the form swaps nothing, `watcherUpdated` re-renders the section, and focus moves to `#watcher-heading`. It commands rather than announces: `request_check` (`src/core/services/watch_check.py`) locks the item, then outboxes one `WatchCheckCommandEmit` on `info.watch-check` beside a `watch_check_commands` row, `requested_at` stamped at that write. **Live since F4 (#482).** Off (`ARCHIVER_WATCH_CHECK_ENABLED` unset), the button is absent and this route and `GET …/watch-check` 404, enqueueing nothing. **One open command per item** (D4): a click while the latest is pending writes nothing and flashes a warning, sparing the round trip to Watcher's `fetch_open`. A failed write flashes an error. **Not gated on announceability:** Watcher's pre-flight is the authority, and its `check_rejected` reason is the answer the block shows.

**The block** (`info_items/_watch_check.html`, `#watch-check`) sits below the Temporal profile row, on the cadence editor's gate (`has_active_source`), in `watching` and `no_status`. Its poll swaps only itself, so the panel's other cells, Health included, refresh on the next `watcherUpdated`. Its state is derived at render, never stored as success (D2), first match wins:

1. a rejection recorded on the command → **Check rejected: `<reason>`**, verbatim (the vocabulary is Watcher's, opaque here);
2. `watch_status.last_full_fetch_at` > `requested_at` → **Checked**, plus the `watch_health` macro (`_macros.html`, archiver#371), which the panel's Health cell shares so the two cannot drift: the badge, then only when `health != "ok"` the `health_reason` verbatim and ` · <health_status_code>` when set, or muted "reason not reported" when the reason is None (absent and null alike, cannobserv's rule). A 200 whose extraction then failed is done + ERROR;
3. older than `ARCHIVER_WATCH_CHECK_TIMEOUT_SECONDS` (15 min) → **No answer yet**, naming `info.watch-check.dlq`;
4. otherwise **Check pending**: the button is disabled and the block polls.

Rungs 1 to 3 re-enable the button, and the next click mints a fresh `command_id` and `requested_at`. **No answer is not a verdict** (D5): a later completion still flips it to done. Three causes reach it: Watcher dead-lettered the command (5 failed attempts, no `check_rejected`), Watcher is down, or the fetch is silent on Replicator's side. Watcher reaps a silent fetch at 1800 s and errors the item only after 3 re-issues, about 2 h. A click after no answer separates the cases: Watcher rejects it `fetch_open` while the first fetch is still open, and accepts it after a dead letter. **Any full fetch after `requested_at` completes the check**, a scheduled one included: the content is fresh either way. **The clocks differ:** `requested_at` is Archiver's and `last_full_fetch_at` is Watcher's, on separate VMs, compared with no slack. A revoked item's `watch_status` row is deleted, so its command ends `rejected: unknown_item` or as no answer. `check_rejected` is never a notification.

**`archive` / `restore`** (archiver#361). Not HTMX actions: plain POST→303 to the detail page, so the Overview's `archived` badge re-renders with the panel - the Domain archive's shape (SCREENS.md § *Allowed variant*). Both call `src/core/services/info_item_lifecycle.py`, which locks the item `FOR UPDATE`, writes only on a real transition (archive keeps its first timestamp) and announces through `announce_policy_change`, so an unannounceable item stores the state and emits nothing (#167). **Not gated on `has_active_source`**, unlike the toggle: archiving an unannounceable item burns no generation, and the next binding announces with the archive in place. `toggle-watch-active` is not refused on an archived item (D3): it stores intent, which restore applies.

**`watch-cadence`.** Whole-document replacement, never a merge - a merge would make "delegate" unreachable once an interval had been set, the same reasoning the API's `PUT /watch-spec` gives. Validated against `src/dashboard/cadence.py`'s offered vocabulary, which is deliberately narrower than the schema's `^[0-9]+[smhd]$`; a hand-posted value outside it re-renders with a flash and writes nothing (the API route is the escape hatch for the full grammar).

**`temporal-profile`, `temporal-profile/delete`** (archiver#365). The Watcher action contract above: re-render the section, `watcherUpdated`, `hx-swap="none"`. Save parses the row's form (`src/dashboard/temporal_profile_form.py`: rules as `30:6h, 7:1h`, or a bare `2h` for seasonal; only the chosen type's dates are read) and calls `put_temporal_profile`, the service behind `PUT /api/v1/info-items/{id}/temporal-profile`. Unparseable text, or anything `ProfileInvalid` names (an ended window included), flashes "Profile not saved" with each problem and writes nothing. Save shares the cadence editor's announceability gate; Delete does not, because removing a profile changes nothing on an unannounceable item's wire and must stay possible.

### Replication actions

**Every outcome is a 200, and every outcome flashes** via `HX-Trigger: showFlash` - issued at `success` naming the rendered destination, a recorded `skipped` row at `warning` naming its reason (it also renders as state in the Replication column), and a refusal the service will not record - `not_active`, `no_active_source`, `no_revision`, `assignment_unreachable` - at `error`. Refusals are 200s rather than 422s because htmx discards a 4xx body (see HTMX.md § **Inline validation errors** and the STYLE.md rule it points at). The outcome→flash translation is `src/dashboard/replication_actions.py`, shared with the RepSpec-scoped twin ([REP_SPEC_PAGES.md](REP_SPEC_PAGES.md)).

It exists because a new assignment on *stable* content otherwise never replicates - issuance is triggered by a new revision, and a stable InfoItem may never produce one.

Every issue button - both scoped tables and the picker's prompt (archiver#308) - is guarded twice: `hx-confirm` because the target is a permanent store, `hx-disabled-elt="this"` because htmx does not deduplicate concurrent requests from an element.

"Every outcome flashes" also depends on the poll yielding to the click (archiver#220): unsynced, a poll that landed first swapped the section out from under the action and discarded its response - swap, focus and toast - so the operator saw nothing on a fresh button, and a second click is a second occasion. Hence the `drop` sync (HTMX.md § *A section that polls and takes actions*).
