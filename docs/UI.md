# Archiver Dashboard - UI Reference

**The dashboard's shared mechanics: URL map, proxy-header auth, error pages,
and the document-level scripts.** The HTMX swap patterns are [HTMX.md](HTMX.md).

The other parts of this reference, under the same living-doc rule:

- [HTMX.md](HTMX.md) - the HTMX patterns: the 422 and flash contracts, failure
  surfacing, async partials, action swaps, polling, shared sections.
- [SCREENS.md](SCREENS.md) - the conventions every entity detail
  screen follows: header anatomy, affordances, mutation and pagination rules.
- [PAGES.md](PAGES.md) - the per-page route inventory: what each screen renders
  and the routes behind it.
  The RepSpec screens are [REP_SPEC_PAGES.md](REP_SPEC_PAGES.md), the source screens
  [SOURCE_PAGES.md](SOURCE_PAGES.md).
- [COMPONENTS.md](COMPONENTS.md) - the Alpine.js component catalogue.
- [STYLE.md](STYLE.md) - design tokens and component classes.
- [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md), [ORG_ROW.md](ORG_ROW.md),
  [TAGS_ROW.md](TAGS_ROW.md), [REGISTER.md](REGISTER.md), [HEALTH_ROW.md](HEALTH_ROW.md),
  [BUS_TRIAGE.md](BUS_TRIAGE.md) - one screen's internals each: the InfoItem
  hub and its Organization and Tags rows, the register wizard, the home screen's health
  row, the Bus triage screen.
  The hub's action routes are [INFO_ITEM_ACTIONS.md](INFO_ITEM_ACTIONS.md).
- [NOTIFICATIONS.md](NOTIFICATIONS.md) - the Notifications page, with the model, API and
  import behind it.

> **AGENTS.md enforcement:** a Jinja2 template change, a new or changed
> dashboard route, or a new Alpine.js component must update the doc it touches
> in the same commit - usually PAGES.md or COMPONENTS.md, and this file when it
> changes a shared pattern or convention.
> An HTMX pattern's doc is [HTMX.md](HTMX.md); a document-level script's is
> this file's § Document-level scripts.

---

## URL Structure

```
/dashboard/                          Home - CTA, health strip, Recent Activity, domain overview
/dashboard/registry-audit            Registry Audit - stored documents the current schemas reject
/dashboard/bus-triage                Bus Triage - dead-lettered outbox rows and archiver's DLQs
/dashboard/domains/                  Domains list
/dashboard/domains/{name}            Domain detail - notes, status, linked sources
/dashboard/register                  Register Information Item - 4-step flow
/dashboard/info-items/               Information Items list
/dashboard/info-items/{id}           Information Item detail (hub page - 5-section scroll)
/dashboard/info-items/new            → 301 redirect to /dashboard/register
/dashboard/notifications/            Notification subscriptions, grouped by scope (+ /new, /{id}/edit)
/dashboard/info-sources/             Information Sources list
/dashboard/info-sources/{id}         Information Source detail
/dashboard/info-sources/new          Create Information Source
/dashboard/source-revisions/         Information Source Revisions list
/dashboard/source-revisions/{id}     Information Source Revision detail
/dashboard/rep-specs/                Replication Specifications list
/dashboard/rep-specs/{id}            Replication Specification detail
/dashboard/rep-specs/new             Create Replication Specification
/dashboard/settings/api-keys         API Keys management
/dashboard/settings/notifier         Notifier - the tenant's channels, read-only
```

---

## Authentication

Every dashboard request - full pages and HTMX partials alike - passes through
`get_dashboard_user` (`src/dashboard/deps.py`). It reads the `X-ExeDev-UserID`
and `X-ExeDev-Email` request headers, resolves the `AppUser` (creating it on
first sight, updating the email if changed) and returns the row; absent headers
→ 307 redirect to `/__exe.dev/login?redirect=<path>`. Tests override via
`app.dependency_overrides[get_dashboard_user]`.

Identity is `external_id`; email is descriptive, **not unique** (#177 - the
proxy doesn't guarantee it, and enforcing it locked colliding operators out
with a 500). Don't reintroduce a unique constraint or key any lookup on email.

**The steady state is a read.** One indexed SELECT on `external_id`, no write,
committed so no transaction outlives it (below).
Only first sight or a real email change reaches the `INSERT … ON CONFLICT
(external_id) DO UPDATE`, which keeps concurrent first-logins from racing
(#177) and commits inside the dependency - `get_db_session` doesn't commit and
a read-only route won't either, so an identity that rode the route's
transaction was rolled back at session close. Don't restore the unconditional
upsert: `DO UPDATE` locks the conflicting row even when its `WHERE` skips the
write, and this dependency resolves before the route body, so the lock spanned
the whole request and an operator's parallel partials queued on their own row
(#180).

Because identity is `external_id` and nothing reconciles on email, a proxy that
ever re-issues an id yields a *second* `AppUser` row. The first row's API keys
keep authenticating - `require_api_key` matches on `key_hash` alone - but no
longer appear on the settings page, so they can't be revoked from the UI. That
is the accepted cost of not letting a header pair adopt an existing identity.

The gate is universal, so the route entries in [PAGES.md](PAGES.md) do not repeat
it: assume any dashboard route redirects 307 when unauthenticated.

### No transaction across an outbound wait (#405)

**Every route body starts with no transaction open.** `get_db_session` never
commits. So the gate's SELECT used to leave a transaction open until the
session closed, holding `ACCESS SHARE` on `app_users` through every wait in
the route. A deploy migration that needs `ACCESS EXCLUSIVE` there gives up
after `MIGRATION_LOCK_TIMEOUT` (5 s), so viewing a page could fail a deploy.
Measured on `archiver_dev`: `idle in transaction` plus the lock for the whole
of a stalled Power Map search. The gate now commits its read too.
- **Commit, never roll back.** The shared factory sets `expire_on_commit=False`,
  so `user` stays loaded for the templates. A rollback expires it, and the next
  attribute read raises `MissingGreenlet`.
- **A route that reads and then waits ends its read first** with
  `await session.commit()`. The read is read-only, so the commit writes
  nothing. The waits are Power Map, the fetch driver, the broker, Notifier,
  GCS and `asyncio.to_thread`. Today that means `PUT /info-items/{id}/org`
  (before `link_org`'s Power Map call), the Bus triage page (before the DLQ
  listings), the notification test-send (before compose and dispatch), and the
  capture image (before its GCS read).
- **No other dependency takes the session.** A dependency that read the
  database would reopen a transaction before the body runs.

`tests/dashboard/test_transaction_scope.py` pins all three rules. It has a
structural walk over every route's dependencies, and one test per wait that
records `session.in_transaction()` at the moment of the wait. A new wait gets
a test there.

**Accepted residual: the last read stays open through render and send (#522).**
The session closes only after the response is sent. Starlette renders inside
`TemplateResponse(...)`, so a route's last read holds `ACCESS SHARE` through
render, then the send.
- **Measured on `archiver_dev`** with the heaviest page, InfoItem detail at 50
  revisions: about 7 ms warm and 120 ms cold. Render is 5 ms warm and 90 ms
  cold, the send under 3 ms, and templates run no lazy loads.
- **In production**, a first detail render after a restart held 1.4 s in all
  (#405). Dev doesn't reproduce that.
- **Why it's accepted:** both figures are far below the 5 s lock timeout.
  - A `scope="function"` session dependency would cut only the send.
  - Committing before render is a rule every route would have to follow, with
    nothing to enforce it.
  - If a function-scoped session is ever used, move every site to it at once.
    FastAPI caches dependencies per scope, so a request that mixes scopes opens
    two sessions.
- **Revisit** if any page's render nears a second.

### Writes must be same-origin (#404)

**The login cookie is the dashboard's only credential, and a cross-port page
can spend it.** Same-site means scheme plus registrable domain, with no port.
`exe.xyz` is on the Public Suffix List, so every port of `co-registrar.exe.xyz`
is one site. On 8001, a form and a `no-cors` fetch from a page on `:8002` both
arrived logged in, carrying `Sec-Fetch-Site: same-site` (measured 2026-11-16).
Any page served from another port, such as the dev server, a preview or a tool,
can therefore submit to production on 8000.

**The cookie itself** (read in the operator's devtools, 2026-11-17, #517). The
proxy sets one cookie per port, `login-with-exe-443`, `-8001` and `-8002`. Each
is host-only (Domain `co-registrar.exe.xyz`, no leading dot) with Path `/`,
`HttpOnly`, `Secure` and `SameSite=Lax`. Cookies ignore the port, so all of
them ride to every port. **The app never sees one:** the proxy removes `Cookie`
and sends its own `X-ExeDev-UserID` / `X-ExeDev-Email` pair instead. A pair the
client sent is replaced, never passed through (measured through 8001, #517).
That sizes the cross-VM exposure:
- **Host-only** means another VM's hostname never receives the cookie.
- **`exe.xyz` is a public suffix,** so a page on `other-vm.exe.xyz` is
  cross-site, and `Lax` withholds the cookie from its subrequests (fetches,
  frames, images) and its cross-site `POST`s.
- **Only a top-level `GET` navigation** (a link, or a `GET` form) carries it
  cross-VM, and no dashboard `GET` writes beyond the visitor's own `AppUser` row.

The same-origin rule below is for the same-site, cross-port case.

**`require_same_origin` (`src/dashboard/deps.py`) refuses every unsafe
dashboard request that isn't same-*origin*** (scheme, host and port). Unsafe
means `POST`, `PUT`, `PATCH` or `DELETE`.
- **`Sec-Fetch-Site` decides when it's present.** Only `same-origin` passes, and
  `same-site`, `cross-site` and `none` are refused. The browser sets this header
  itself, from the URL it requested.
- **Without it, `Origin` must equal ours.** Our origin is `X-Forwarded-Proto` +
  `X-Forwarded-Host` (the proxy sends both, port included), or the request's
  own URL when they're absent. Default ports are normalized, and `null` never
  matches.
- **A request with neither header passes.** curl, scripts and `TestClient`
  send neither, and no browser that carries the cookie omits both (operator
  decision, 2026-11-16).
- **A refusal is a 403 on the dashboard's HTML error page**, logged as a WARNING
  `Dashboard write refused: not same-origin`, with `reason`, `origin` and
  `sec_fetch_site` attached.

**It's mounted once,** as a router dependency in `register_dashboard`'s loop
(`src/dashboard/main.py`). So it covers every route by construction, and it
resolves before the route's auth and session: a refused request touches no
database. `tests/dashboard/test_same_origin_guard.py` fails CI for any unsafe
route outside `/api/` that the check doesn't reach. A new router goes through
that loop.

**Not covered:**
- `GET`. No dashboard `GET` writes, except the visitor's own `AppUser` row.
- Script injected into our own origin (a synchronizer token would cover that,
  option B on #404).
- The exe.dev logout. It posts to `/__exe.dev/logout`, which the proxy
  answers without reaching the app (measured on 8001), and it's unboosted
  ([HTMX.md](HTMX.md) § Boosted navigation).

---

## HTMX Patterns

Moved to [HTMX.md](HTMX.md): boosted navigation, inline validation errors
(`hx-target-422`), flash messages, live validation, failures are surfaced, not
swallowed, the async partial and action-swaps-card patterns, a section that
polls and takes actions, blocks that share a section, and the JSON data island
pattern.

## Error pages

Rendered by the exception handlers in `src/dashboard/errors.py` on any
`/dashboard` path; [PAGES.md](PAGES.md) keeps the pointer entry.

- `_error.html` - standalone document (`<!doctype html>`, its own stylesheet
  link), returned when the request carries no `HX-Request` header: a hard load,
  a reload, a typed URL.
- `_error_body.html` - the `<main class="error-page">` block alone, returned to
  an htmx request because the swap lands inside the existing `<body>`.
  `_error.html` includes it, so the two cannot drift.

Both render from `heading`, `message`, and an optional `incident_id` only -
deliberately **not** extending `base.html`, which needs `user` from a database
session that may be the thing that failed. `_error.html` shares
`_theme_boot.html` with it instead, so the operator's colour scheme survives.
Status-specific behaviour, the `HX-Trigger: showFlash` a partial failure
carries, and the client listener that makes any of it visible:
[HTMX.md](HTMX.md) § **Failures are surfaced, not swallowed**.

Replaces `_404.html`, which covered one status and appeared only on a hard load.

## Detail Screen Conventions

Moved to **[SCREENS.md](SCREENS.md)** - header anatomy, detail
grid and authored rows, the row-level view/edit pattern, the copy /
external-open / replication-state affordances, the double-guard and flash
rules for irreversible actions, reported state from another service, HTMX
mutation and focus rules, related-collection tables, and pagination clamping.

## Document-level scripts (not Alpine)

Each is an IIFE that attaches listeners to `document` on load, surviving HTMX
body swaps because nothing it binds to is inside the swapped tree. Dropping any
of them from the `base.html` script list is silent - the behaviour simply stops
(archiver#62).

### `flash.js`

Toast/flash system. Listens for the `showFlash` `CustomEvent` - dispatched by
htmx from an `HX-Trigger` response header, or directly by other scripts - and
injects `.flash--*` toasts into the `#flash-region` overlay, announcing every
message through the two visually-hidden live regions. All three regions are
**recreated on demand** when absent: a boosted swap replaces everything inside
`<body>`, and the dashboard error page does exactly that, so without it the
first toast after such a swap was dropped in silence (archiver#178). Levels, dismissal rules,
the visible cap and its two overflow affordances: [HTMX.md](HTMX.md) § Flash
messages.

### `dark-mode.js`

Colour-scheme toggle (`[data-theme-toggle]`), persisting the choice in
`localStorage` under `co-color-scheme`. `base.html` re-reads that key in a
blocking inline script before the stylesheet paints, to prevent FOUC.

### `sidebar-drawer.js`

The phone-width sidebar drawer (archiver#400). Under 640 px `dashboard.css`
hides `.sidebar` off-canvas and shows the topbar's `[data-sidebar-toggle]`, a
`<button>` whose `aria-controls` names `#sidebar`; this script keeps the
toggle's `aria-expanded` and the drawer's `data-open` in step. Opening moves
focus to the first link. Escape closes and returns focus to the toggle; a click
outside, or focus moving anywhere but the drawer or toggle, closes it without
moving focus. That click is swallowed (capture phase), so the dismissing tap
never acts on the control under it - there is no scrim. Closed, the drawer is `visibility: hidden`, so its links are out
of the Tab order ([STYLE.md](STYLE.md) § Layout). State lives only on the toggle
and drawer, never on `<body>`, so a boosted navigation lands on the server's
closed render. Wider than 640 px the toggle is `display: none` and `data-open`
is ignored.

### `htmx-errors.js`

Makes failed htmx requests visible (archiver#178). htmx refuses to swap a
non-2xx response, so without this a failure is indistinguishable from a click
that never happened.

**Listens for:**
- `htmx:beforeSwap` - on a failed response, either swaps the server's error page
  in (boosted/full-page request: sets `detail.shouldSwap = true` and
  `detail.isError = false`) or, for a partial, leaves the swap refused and
  raises an `error` toast through `flash.js`.
- `htmx:sendError`, `htmx:timeout` - no response arrived, so
  `htmx:responseError` never fires; both toast.

**Reads:** the response's `HX-Trigger` header. A dashboard error carries
`showFlash`, which htmx raises before `beforeSwap` runs, so the listener stays
silent rather than double-reporting; a failure carrying no flash gets a
status-code toast rather than silence.

**Defers by one task before toasting.** htmx runs extension `onEvent` hooks
after DOM listeners, so at listener time the `response-targets` extension has
not yet decided whether an `hx-target-422` claims this failure. The deferred
check reads `detail.shouldSwap`: set means the error is already going somewhere
visible, and toasting would report it twice.

The server half - which paths render HTML, and why `_error.html` does not extend
`base.html` - is in [HTMX.md](HTMX.md) § Failures are surfaced, not swallowed.
