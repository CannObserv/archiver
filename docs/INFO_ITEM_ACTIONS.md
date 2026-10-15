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

**The two Watcher action POSTs share a contract.** `toggle-watch-active` and
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

**There were five.** `begin-watching`, `check-now`, and `resync-watcher` were
SDK-backed and retired with it in archiver#142, along with the stale-link
reconcile they triggered (a `WatcherNotFound` NULLed `watcher_item_id` so the
panel could re-offer "Begin Watching"). Nothing replaces them individually:
reconciliation is level-triggered off `info.registry`, so there is no per-item
push to retry, no remote id to go stale, and no provisioning gesture to repeat.
The two survivors are *local* writes
that announce and let Watcher converge; the route entries in [PAGES.md](PAGES.md) name only what each adds.

**`toggle-watch-active`.** The re-render still shows applied state, so the button flips only once Watcher reports back on `info.watch-status` - the lag window is the announcement round-trip and stays visible as generation drift. The affordance is gated on `has_active_source` - as the cadence editor is, and as the panel's own state now is (archiver#142): mutating policy on an item that cannot announce live would emit a *tombstone* and burn a generation for nothing. **The route enforces the same gate** (archiver#167), for a stale tab whose binding was deactivated after render, or a script: on an unannounceable item it writes nothing, flashes "no active source with extraction specs", and re-renders, which shows `not_watching` and corrects the tab. `watch-cadence` does the same, before its vocabulary check. A failed local write rolls back, flashes "the change was not saved", and renders `degraded` **from the path id** - reading through the rolled-back ORM object would emit IO from the template and raise `MissingGreenlet`.

**`watch-cadence`.** Whole-document replacement, never a merge - a merge would make "delegate" unreachable once an interval had been set, the same reasoning the API's `PUT /watch-spec` gives. Validated against `src/dashboard/cadence.py`'s offered vocabulary, which is deliberately narrower than the schema's `^[0-9]+[smhd]$`; a hand-posted value outside it re-renders with a flash and writes nothing (the API route is the escape hatch for the full grammar).

### Replication actions

**Every outcome is a 200, and every outcome flashes** via `HX-Trigger: showFlash` - issued at `success` naming the rendered destination, a recorded `skipped` row at `warning` naming its reason (it also renders as state in the Replication column), and a refusal the service will not record - `not_active`, `no_active_source`, `no_revision`, `assignment_unreachable` - at `error`. Refusals are 200s rather than 422s because htmx discards a 4xx body (see HTMX.md § **Inline validation errors** and the STYLE.md rule it points at). The outcome→flash translation is `src/dashboard/replication_actions.py`, shared with the RepSpec-scoped twin ([REP_SPEC_PAGES.md](REP_SPEC_PAGES.md)).

It exists because a new assignment on *stable* content otherwise never replicates - issuance is triggered by a new revision, and a stable InfoItem may never produce one.

Every issue button - both scoped tables and the picker's prompt (archiver#308) - is guarded twice: `hx-confirm` because the target is a permanent store, `hx-disabled-elt="this"` because htmx does not deduplicate concurrent requests from an element.

"Every outcome flashes" also depends on the poll yielding to the click (archiver#220): unsynced, a poll that landed first swapped the section out from under the action and discarded its response - swap, focus and toast - so the operator saw nothing on a fresh button, and a second click is a second occasion. Hence the `drop` sync (HTMX.md § *A section that polls and takes actions*).
