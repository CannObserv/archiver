# Archiver Dashboard - UI Reference

**The dashboard's shared mechanics: URL map, proxy-header auth, and HTMX swap
patterns.**

The other parts of this reference, under the same living-doc rule:

- [SCREENS.md](SCREENS.md) - the conventions every entity detail
  screen follows: header anatomy, affordances, mutation and pagination rules.
- [PAGES.md](PAGES.md) - the per-page route inventory: what each screen renders
  and the routes behind it.
- [COMPONENTS.md](COMPONENTS.md) - the Alpine.js component catalogue.

> **AGENTS.md enforcement:** a Jinja2 template change, a new or changed
> dashboard route, or a new Alpine.js component must update the doc it touches
> in the same commit - usually PAGES.md or COMPONENTS.md, and this file when it
> changes a shared pattern or convention.

---

## URL Structure

```
/dashboard/                          Home - CTA, health strip, Recent Activity, domain overview
/dashboard/domains/                  Domains list
/dashboard/domains/{name}            Domain detail - notes, status, linked sources
/dashboard/register                  Register Information Item - 4-step flow
/dashboard/info-items/               Information Items list
/dashboard/info-items/{id}           Information Item detail (hub page - 5-section scroll)
/dashboard/info-items/new            → 301 redirect to /dashboard/register
/dashboard/info-sources/             Information Sources list
/dashboard/info-sources/{id}         Information Source detail
/dashboard/info-sources/new          Create Information Source
/dashboard/source-revisions/         Information Source Revisions list
/dashboard/source-revisions/{id}     Information Source Revision detail
/dashboard/rep-specs/                Replication Specifications list
/dashboard/rep-specs/{id}            Replication Specification detail
/dashboard/rep-specs/new             Create Replication Specification
/dashboard/settings/api-keys         API Keys management
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

**The steady state is a read.** One indexed SELECT on `external_id`, no write.
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

---

## HTMX Patterns

### Boosted navigation

`<body hx-boost="true">` - all in-dashboard `<a>` links and form submissions use HTMX fetch automatically (no full page reload). HTMX swaps the `<body>` and updates `<title>`.

### Partial fragment swaps

Server returns a partial HTML fragment with `HX-Reswap: outerHTML` / `HX-Retarget: #target-id` headers when refreshing a sub-section (e.g., the rep-spec assignment table row).

### Inline validation errors (`hx-target-422`)

`<body hx-ext="response-targets">` enables the vendored
`htmx-ext-response-targets` extension, which lets a form send a failure response
somewhere other than its success target. A form that can 422 carries
`hx-target-422="#some-error"` and the route returns just that error `<div>`, so
the message lands beside the field instead of replacing the whole form. Both
forms in `info_items/_swap_primary.html` use it; route entries elsewhere name
only their target id.

This is the form-level counterpart to the pagination clamp (see **Pagination
params are clamped, not validated**) - query-param errors are removed by
clamping, form-field errors are rendered.

For forms that submit via HTMX and need inline validation errors without a full-page reload, use `hx-target-422` from the `htmx-ext-response-targets` extension (vendored as `vendor/htmx-ext-response-targets.min.js` v2.0.4, activated globally via `hx-ext="response-targets"` on `<body>`):

```html
<form hx-post="/dashboard/path/to/action"
      hx-target-422="#my-error">
  <div id="my-error" role="alert" aria-live="polite" aria-atomic="true"></div>
  <!-- fields -->
</form>
```

Rules:
- `hx-target-422="#my-error"` routes 422 responses into `#my-error`. Requires the `response-targets` extension; without it the attribute is silently ignored and 4xx responses are discarded.
- The server returns `422` with an HTML fragment: `<div id="my-error" role="alert" aria-live="polite" aria-atomic="true"><p class="text-danger">…</p></div>`. Including the same `id` in the response preserves the element for subsequent submissions (default swap style is `outerHTML`).
- `aria-live="polite" aria-atomic="true"` is required on the error target so screen readers announce the complete message on each update.
- On success, the server returns `204` with an `HX-Redirect` header. HTMX follows it as a full-page navigation regardless of `hx-target` settings.
- Place the error div inside the same Alpine `x-show` container as the form so it stays in DOM when the panel is toggled. Placing it inside the `<form>` element satisfies this by default; outside-form placements (e.g. after `</form>` but within the same `<details>`) are valid if the enclosing container is under the same Alpine toggle.


### Flash messages

Server returns `HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}` alongside a mutating response **whose outcome the swap does not already make obvious**. A swap that visibly replaces what the operator just acted on - the assignment-table deactivate, say - carries no toast; a swap whose result is a badge inside a re-rendered region does, and an *irreversible* action carries one on every outcome (see **Irreversible actions guard themselves twice**). The rule is "the operator must be able to tell what happened", not "every mutation toasts". `flash.js` (loaded in `base.html`) injects `.flash--*` divs into `#flash-region` - a `position: fixed` viewport overlay (a direct `<body>` child, outside `<main>`, so HTMX content swaps can't wipe live toasts) anchored top-right on desktop and full-width top on narrow viewports, so toasts stay visible at any scroll position (archiver#65). `flash.js` recreates `#flash-region` and both announcers if they are missing, so a swap that replaces the whole of `<body>` (the error page below) cannot silence the next toast. **Note:** `flash.js` must be in the `base.html` script list - if it is dropped, every `showFlash` is silently ignored site-wide (CannObserv/archiver#62).

Dismissal is severity-based: `success`/`info` auto-dismiss after 6 s; `error`/`warning` persist until the operator clicks `.flash__close` (failures must not vanish unseen). The visible overlay caps at 4 slots, with two overflow affordances (archiver#73):

- **Transient overflow.** A `success`/`info` that arrives while 4 persistent toasts fill the cap is *not* dropped - it shows as a single overflow lane below them (momentarily 5 visible) for the full 6 s, then auto-dismisses. Only the newest transient occupies the lane (last-write-wins); older surplus transients are evicted oldest-first.
- **Persistent overflow.** A 5th `error`/`warning` no longer evicts the oldest (which silently lost failures before #73). Instead the 4th slot becomes a `+N more` counter button: the newest 3 stay visible and older ones collapse behind it. Activating the counter (click/Enter) expands the overlay to show all and removes the counter - there is no re-collapse affordance; once engaged the operator dismisses each. The counter counts hidden *persistent* toasts only, and because it occupies a slot the smallest N is 2 (first seen at the 5th persistent toast). A fresh pile (after all toasts clear) starts collapsed again.

Accessibility: announcement is decoupled from the visible overlay (archiver#73). Two visually-hidden live regions declared in `base.html` - `#flash-announcer-assertive` (`aria-live="assertive"`, errors) and `#flash-announcer-polite` (`aria-live="polite"`, all other levels) - receive *every* message, so assistive tech hears it even when the visible cap suppresses or collapses the toast. Visible toasts therefore carry no live role. The `+N more` counter is a real `<button>` (`aria-expanded`, `aria-controls="flash-region"`, `aria-label="Show N more notifications"`); expanding moves focus to the first revealed toast's dismiss button. The `flash-in` animation is suppressed under `prefers-reduced-motion` via the global reduced-motion block in `dashboard.css`.

Levels: `"success"` | `"warning"` | `"error"` | `"info"`.

### Live validation

SourceSpec and RepSpec editors use HTMX to POST to `/api/v1/tools/validate-source-spec` (or `-rep-spec`) on blur and render inline error feedback.

### Failures are surfaced, not swallowed

**htmx does not swap a non-2xx response** (archiver#178). With `hx-boost` on `<body>` that
covers nearly every interaction, so before #178 a failed request did *nothing at
all*: no error, no change, no clue the click was even received. Two halves fix
it, and neither works alone.

**Server - `src/dashboard/errors.py`.** Three exception classes are wrapped so a
`/dashboard` path gets HTML where the API keeps its JSON envelope: `Exception`
(the crash), `StarletteHTTPException` (FastAPI's own 404 on a mistyped URL, its
405, and any `raise_envelope` a dashboard route makes), and
`RequestValidationError` (a `Form(...)` field that never arrived - the one arm
the pagination clamp below cannot close). Each wrapper *delegates* the
non-dashboard case back to the API handler: there is one handler slot per
exception class app-wide, so adding rather than wrapping would have answered the
SDK with HTML. `register_dashboard(app)` must
therefore run **after** `register_error_handlers(app)`.

The response shape follows the `HX-Request` header - `_error.html` (standalone
document) for a hard load, `_error_body.html` (the block alone) for an htmx
request, which lands inside an existing `<body>`. Neither extends `base.html`:
that template needs `user`, and the session that would supply it may be what
failed; both include `_theme_boot.html`, so the operator's colour scheme
survives the failure. A 5xx page carries an **incident id**, printed once and
logged beside the traceback (`journalctl -u archiver | grep <id>`); the
exception text itself never reaches the page.

A *partial* failure also carries `HX-Trigger: showFlash` - the same flash
mechanism as any other outcome, because htmx raises those events **before** it
decides whether to swap, so they survive a response it discards
(`tests/js/htmx-error-trigger.test.js` drives the real library to prove it). A
hard load has no htmx to read the header, and a boosted request swaps the page
in, so neither carries one. Reusing the flash also makes a class of bug
unrepresentable: `json.dumps` escapes non-ASCII, where the hand-written header
this replaced was latin-1 and reached operators as `Something went wrong ?
incident a1b2c3d4`.

**Client - `static/htmx-errors.js`,** loaded from `base.html`. On
`htmx:beforeSwap` for a failed response:

- **boosted (full-page) request** → `shouldSwap = true`, `isError = false`, so
  the server's error page is shown. This is also what finally makes a 404
  visible: `DashboardNotFound` has rendered a page since long before #178, and
  every in-dashboard link to a stale ID discarded it.
- **partial request** → the swap is left refused (a fragment must not replace
  the screen) and the server's `showFlash` has already toasted. The listener
  speaks only when the response carries no flash - a failure from outside
  `/dashboard`, or one that never reached the handler - since a refused swap
  that says nothing is the whole of this issue. That fallback is deferred by one
  task: htmx runs extension `onEvent` hooks *after* DOM listeners, so a form
  carrying `hx-target-422` has not been retargeted yet - by the timeout,
  `detail.shouldSwap` says whether response-targets claimed it, and a claimed
  failure is not toasted twice.

`htmx:sendError` and `htmx:timeout` toast as well: with no response at all
`htmx:responseError` never fires, and "the service is restarting" is the most
common way an operator meets this silence.

**What this does not change: a refusal is still a 200 with a flash.** Visible is
not the same as well-placed - a whole-screen error page in answer to a bad label
is worse than a toast over the form the operator is still looking at. Routes
that *decline* keep returning their partial at 200 with `HX-Trigger: showFlash`
(see **Flash messages** and `src/dashboard/replication_actions.py`). The error
page is for failures with no partial to return to.

---

### HTMX async partial pattern

For non-blocking page sections that call a slow or potentially unavailable service, load them after the page renders:

```html
<div id="target-id"
     hx-get="/dashboard/path/to/partial"
     hx-trigger="load"
     hx-swap="outerHTML"
     aria-live="polite" aria-atomic="false">
  <p class="text-muted text-sm">Loading…</p>
</div>
```

Rules:
- `hx-trigger="load"` fires the request immediately after the page renders (no user interaction needed).
- `hx-swap="outerHTML"` replaces the entire placeholder div. The server-rendered partial **must** include the same `id` as the placeholder so subsequent re-renders can re-target it.
- `aria-live="polite" aria-atomic="false"` is required on async content sections (see Accessibility section). For error announcement targets, use `aria-atomic="true"` instead - see the inline form error pattern below.
- The placeholder content degrades gracefully if JS is disabled or the request fails.
- Use this pattern for sections that depend on a sibling service (Watcher, Replicator) so that service outages do not block the dashboard page load.

**Event-driven refresh variant.** When a panel should auto-refresh in response to actions elsewhere on the page, add `hx-trigger="<event-name> from:body"` alongside `hx-trigger="load"` using HTMX's comma-separated multi-trigger syntax:

```html
<div id="watcher-section"
     hx-get="/dashboard/path/to/section"
     hx-trigger="load, watcherUpdated from:body"
     hx-swap="outerHTML"
     aria-live="polite" aria-atomic="false">
  <p class="text-muted text-sm">Loading…</p>
</div>
```

The server-side action endpoint (e.g. `POST /toggle-watch-active`) sends `HX-Trigger: {"watcherUpdated":{}}` in the response header. HTMX dispatches `watcherUpdated` on the triggering element; it bubbles to `body`, which causes the section to re-fetch. Use this to keep multiple independent sections in sync without coupling their endpoints.

### HTMX action-swaps-card pattern

For a mutating action on a detail page (submit a form, click a button) that should update just the affected card without a full-page reload, swap the card in place and toast the result. Used by clear-cache (`source_revisions/_detail_card.html`) and the Source Specs editor (`info_sources/_source_specs_card.html`).

```html
<form hx-post="/dashboard/path/to/action"
      hx-target="#the-card" hx-swap="outerHTML"
      method="POST" action="/dashboard/path/to/action">
  <!-- fields + submit -->
</form>
```

Rules:
- Extract the card into its own partial whose root carries the target `id` (e.g. `#the-card`). The route renders that same partial for HTMX requests so the swap re-targets cleanly on subsequent actions.
- **Progressive enhancement:** keep `method`/`action` (and, for buttons, a real submit) alongside the `hx-*` attributes so the action still works as a plain POST→303 when JS is disabled. Branch server-side on the `HX-Request` header: HTMX → partial; non-HTMX → 303 redirect (success) / full-page re-render (error).
- On success the route sends `HX-Trigger: {"showFlash": {...}}` for a toast, and moves focus to the card heading (`tabindex="-1"`, focused by an inline `<script>` gated on a `swapped` flag) so keyboard users are not dropped to `<body>` after the swap (archiver#78).
- **Validation errors** return the partial with the inline error at status **200** (not 422) so HTMX performs the swap - otherwise a 4xx is discarded unless the `response-targets` extension is wired (see the inline form error pattern above, which is the alternative when you want the error routed to a separate `#error` div rather than re-swapping the whole card). Give the inline error `<p>` `role="alert"` so screen readers announce it after the swap (focus lands on `<body>` otherwise), move focus to the card heading on the error swap too, and echo the operator's submitted input back into the field so a rejected edit isn't discarded.

### JSON data island pattern

When an Alpine component needs server-rendered data at initialisation, place the data in a `<script type="application/json">` child element rather than embedding JSON inside the `x-data` attribute. Jinja2's `tojson` filter does **not** escape `"`, so JSON in a double-quoted attribute is silently truncated by the HTML parser; single-quoted attributes work but are fragile to copy. The data island avoids both problems:

```html
<div x-data="myComponent()">
  <script type="application/json">{{ my_data | tojson }}</script>
  ...
</div>
```

In `init()`, read it with:
```javascript
var el = this.$el.querySelector('script[type="application/json"]');
var data = el ? JSON.parse(el.textContent || "[]") : [];
```

Notes: `tojson` escapes `<` → `<`, so `</script>` inside JSON values cannot close the tag early. Browsers do not execute `<script type="application/json">`. Alpine and HTMX ignore it. Apply this pattern to any Alpine component that needs a non-trivial server-rendered data structure at startup.

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
§ **Failures are surfaced, not swallowed** above.

Replaces `_404.html`, which covered one status and appeared only on a hard load.

## Detail Screen Conventions

Moved to **[SCREENS.md](SCREENS.md)** - header anatomy, detail
grid and authored rows, the row-level view/edit pattern, the copy /
external-open / replication-state affordances, the double-guard and flash
rules for irreversible actions, reported state from another service, HTMX
mutation and focus rules, related-collection tables, and pagination clamping.
