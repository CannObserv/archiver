# Archiver Dashboard — UI Reference

**The dashboard's shared mechanics: URL map, proxy-header auth, HTMX swap
patterns, and the conventions every detail screen follows.**

The other two parts of this reference, under the same living-doc rule:

- [PAGES.md](PAGES.md) — the per-page route inventory: what each screen renders
  and the routes behind it.
- [COMPONENTS.md](COMPONENTS.md) — the Alpine.js component catalogue.

> **AGENTS.md enforcement:** a Jinja2 template change, a new or changed
> dashboard route, or a new Alpine.js component must update the doc it touches
> in the same commit — usually PAGES.md or COMPONENTS.md, and this file when it
> changes a shared pattern or convention.

---

## URL Structure

```
/dashboard/                          Home — CTA, health strip, Recent Activity, domain overview
/dashboard/domains/                  Domains list
/dashboard/domains/{name}            Domain detail — notes, status, linked sources
/dashboard/register                  Register Information Item — 4-step flow
/dashboard/info-items/               Information Items list
/dashboard/info-items/{id}           Information Item detail (hub page — 5-section scroll)
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

Every dashboard request — full pages and HTMX partials alike — passes through
`get_dashboard_user` (`src/dashboard/deps.py`). It reads the `X-ExeDev-UserID`
and `X-ExeDev-Email` request headers, upserts `AppUser` (creates if new, updates
the email if changed) and returns the row; absent headers → 307 redirect to
`/__exe.dev/login?redirect=<path>`. Tests override via
`app.dependency_overrides[get_dashboard_user]`.

The gate is universal, so the route entries in [PAGES.md](PAGES.md) do not repeat
it: assume any dashboard route redirects 307 when unauthenticated.

---

## HTMX Patterns

### Boosted navigation

`<body hx-boost="true">` — all in-dashboard `<a>` links and form submissions use HTMX fetch automatically (no full page reload). HTMX swaps the `<body>` and updates `<title>`.

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
params are clamped, not validated**) — query-param errors are removed by
clamping, form-field errors are rendered.

### Flash messages

Server returns `HX-Trigger: {"showFlash": {"level": "success", "body": "Saved."}}` alongside a mutating response **whose outcome the swap does not already make obvious**. A swap that visibly replaces what the operator just acted on — the assignment-table deactivate, say — carries no toast; a swap whose result is a badge inside a re-rendered region does, and an *irreversible* action carries one on every outcome (see **Irreversible actions guard themselves twice**). The rule is "the operator must be able to tell what happened", not "every mutation toasts". `flash.js` (loaded in `base.html`) injects `.flash--*` divs into `#flash-region` — a `position: fixed` viewport overlay (a direct `<body>` child, outside `<main>`, so HTMX content swaps can't wipe live toasts) anchored top-right on desktop and full-width top on narrow viewports, so toasts stay visible at any scroll position (archiver#65). **Note:** `flash.js` must be in the `base.html` script list — if it is dropped, every `showFlash` is silently ignored site-wide (CannObserv/archiver#62).

Dismissal is severity-based: `success`/`info` auto-dismiss after 6 s; `error`/`warning` persist until the operator clicks `.flash__close` (failures must not vanish unseen). The visible overlay caps at 4 slots, with two overflow affordances (archiver#73):

- **Transient overflow.** A `success`/`info` that arrives while 4 persistent toasts fill the cap is *not* dropped — it shows as a single overflow lane below them (momentarily 5 visible) for the full 6 s, then auto-dismisses. Only the newest transient occupies the lane (last-write-wins); older surplus transients are evicted oldest-first.
- **Persistent overflow.** A 5th `error`/`warning` no longer evicts the oldest (which silently lost failures before #73). Instead the 4th slot becomes a `+N more` counter button: the newest 3 stay visible and older ones collapse behind it. Activating the counter (click/Enter) expands the overlay to show all and removes the counter — there is no re-collapse affordance; once engaged the operator dismisses each. The counter counts hidden *persistent* toasts only, and because it occupies a slot the smallest N is 2 (first seen at the 5th persistent toast). A fresh pile (after all toasts clear) starts collapsed again.

Accessibility: announcement is decoupled from the visible overlay (archiver#73). Two visually-hidden live regions declared in `base.html` — `#flash-announcer-assertive` (`aria-live="assertive"`, errors) and `#flash-announcer-polite` (`aria-live="polite"`, all other levels) — receive *every* message, so assistive tech hears it even when the visible cap suppresses or collapses the toast. Visible toasts therefore carry no live role. The `+N more` counter is a real `<button>` (`aria-expanded`, `aria-controls="flash-region"`, `aria-label="Show N more notifications"`); expanding moves focus to the first revealed toast's dismiss button. The `flash-in` animation is suppressed under `prefers-reduced-motion` via the global reduced-motion block in `dashboard.css`.

Levels: `"success"` | `"warning"` | `"error"` | `"info"`.

### Live validation

SourceSpec and RepSpec editors use HTMX to POST to `/api/v1/tools/validate-source-spec` (or `-rep-spec`) on blur and render inline error feedback.

---

## Detail Screen Conventions

Canonical patterns for entity **detail** pages. The Source Revision detail
(`source_revisions/detail.html` + `_detail_card.html`) is the reference
implementation (archiver#78); other detail screens should converge on these.
The screens themselves are inventoried in [PAGES.md](PAGES.md).

**Header.** An `.entity-card` whose `.entity-card__header` contains, in order:
1. An `.eyebrow` kicker naming the entity kind, singular (e.g. "Information
   Source Revision"). Non-interactive; detail screens carry no breadcrumb `<nav>`.
2. An `<h1 class="entity-card__title" id="…-heading" tabindex="-1">` whose
   content is the entity's identity — for ULID-keyed entities, the copyable
   ULID (see `copyable`). The `id`+`tabindex="-1"` make it a focus target for
   post-swap focus moves (see HTMX mutations).

**Detail grid.** `.detail-grid` with `.detail-grid__item` → `.detail-grid__label`
+ `.detail-grid__value` children (never bare `<dl><dt><dd>` — those misalign
against the CSS grid). Long single-line values (fingerprints, URLs) go on a
full-width row via `.detail-grid__item--full` so they extend horizontally
instead of cramping into one ~200px track. Timestamps are UTC-suffixed
(`%Y-%m-%d %H:%M UTC`) everywhere, including table cells.

**Copy affordance.** `copyable(value)` from `_macros.html` — a monospace value
plus a `.btn--secondary
.btn--sm` "Copy" button ("Copy"→"Copied ✓" for 1.5 s). The value is bound via
`|tojson` to an Alpine data prop and copied through it — never spliced into the
handler's JS source — so arbitrary DB strings cannot break out of the JS
context.

**External-open affordance.** `open_button(url, label="Open")` from
`_macros.html` — a link styled as a `.btn--secondary .btn--sm` button ("Open
↗"), `target=_blank rel=noopener noreferrer`, modeled on the Copy button so
opening a URL reads as a distinct action separated from the displayed value.
Used for every external URL (source URLs, RepSpec `public_url`, http(s)
`content_cache_uri`). Section-header deeplinks styled as headings are
intentionally exempt — the carve-out currently has no instance, its one example
having been the InfoItem "Watcher ↗" `<h2>` that retired with archiver#142.

**Replication state affordance.** `replication_state(command)` from
`_macros.html` — the latest `replication_commands` row for one assignment,
rendered as a state badge (`complete`→success, `requested`→info, `failed`→danger,
`abandoned`→warning, `skipped`→muted) plus the `reason` token, the `command_id`,
and the close/issue timestamp. Used by both assignment tables — the InfoItem hub
and the RepSpec detail — because "which items does this spec replicate?" and
"has this item replicated?" are the same question from two sides.

Two rules it encodes, both from archiver#171:

- **A refusal is a state, not an absence.** Issuance persists a `skipped` row for
  every assignment it declines to publish for, and this macro renders it. A
  refusal that lives only in a log line shows as "not replicated yet" forever —
  indistinguishable from one still in flight, and permanent.
- **No occasion at all is its own state**, rendered "Never replicated" rather
  than an em-dash. The same rule the reported-state panels below hold to.

`reason` is shown **verbatim** — a producer-owned token for a failure, an
Archiver-local one for a skip, from deliberately disjoint vocabularies. It is the
string an operator will grep the logs and CannObserv/replicator for, so
prettifying it costs more than it reads.

**Irreversible actions guard themselves twice.** An action whose effect cannot
be undone — today only "Replicate now", which asks Replicator to write into a
permanent store, one of which (archive.org) cannot be deleted at all — carries
both `hx-confirm` and `hx-disabled-elt="this"`. The second is not redundant:
htmx does not deduplicate concurrent requests from an element, so without it a
double-click issues two occasions. They render the same destination (the
issuer contract's R2 determinism), so the bytes are safe, but the second
snapshot is not free and `public_url` follows whichever lands second.

**Every** outcome flashes — issued at `success` naming the rendered destination,
a recorded skip at `warning` naming its reason, an unrecordable refusal at
`error`. Refusals are **200s**, never 4xx: htmx discards a non-2xx body, so the
same rule as inline validation errors above applies for the same reason, and a
422 would reach the operator as nothing at all. Announcing only the failures was
the first cut, and it is backwards — the irreversible outcome is the one that
needs confirming. The translation lives in `src/dashboard/replication_actions.py`
so both screens offering the action answer the same way.

**Reported state from another service.** Where a panel renders state some other
service reports over the bus rather than state Archiver owns — the InfoItem
watched-item panel is the reference (archiver#151, inventoried in
[PAGES.md](PAGES.md)) — three rules hold, and they generalise to every such
panel the cluster grows:

1. **"Not reported yet" is its own state**, never folded into the nearest
   negative. A consumer that has heard nothing and a subject that is genuinely
   idle are different facts, and collapsing them makes a booting consumer
   indistinguishable from a broken subject.
2. **Open vocabularies fail toward not-OK.** Where the contract types a field as
   a bare `str` so it can grow, exactly one value means healthy and every other
   value — known or never seen — renders verbatim on the non-healthy styling.
   Test `== "ok"`, never `!= "error"`; the tempting guess (unknown ⇒ fine) is
   the one that fails silently.
3. **Desired and applied are shown together** when they can diverge, with the
   divergence and its age surfaced rather than reconciled away. A panel that
   renders only what was asked for reports a state nothing is actually in.

**HTMX mutations.** A mutating action on a detail page re-renders the affected
region in place rather than full-page reloading: extract the region to a
partial with a stable `id`, post via `hx-post`/`hx-patch` with
`hx-target="#…" hx-swap="outerHTML"` (+ `hx-confirm` for destructive ones), and
return the re-rendered partial with `HX-Trigger: {"showFlash": {...}}` for a
success toast (see **Flash messages**). Keep a `method`/`action` fallback on the
form so it still works as a plain POST→303 without JS (progressive
enhancement). Emit a focus-move `<script>` in the swap response only (gated on a
`swapped` flag) so keyboard focus lands on the region heading rather than
`<body>`.

*Editor cards.* A card whose body is an inline editor — InfoSource **Source
Specification**, RepSpec **Document** — follows one shape. Extract the card to a
partial with stable root and heading `id`s and `hx-post` with
`hx-target="#…-card" hx-swap="outerHTML"`. Success returns the re-rendered card
with `HX-Trigger: showFlash` and moves focus to the heading. **A rejection
returns status 200, not 422**, so htmx still performs the swap: the card comes
back with its inline `*_error` (`role="alert"`) visible, focus on the heading,
and the operator's submitted text echoed into the textarea so the edit is not
discarded. The route branches on the `HX-Request` header, not on the target:
non-HTMX requests fall back to a 303 on success and a full-page 422 re-render —
text still preserved — on failure, so the editor works without JS.

Gate the focus-move script on `swapped` (see **HTMX mutations**) and pass
`swapped=False` on that non-HTMX path. The card partial and the section's other
partial both gate on the same flag, so a full-page 422 rendered with
`swapped=True` emits both scripts and the second one steals focus away from the
error the operator needs to read.

*Allowed variant — full-page POST→303.* HTMX partial-swap applies to mutations
whose visible effect is **contained within a single card or section**. When a
mutation changes page-level state across **disjoint regions**, a plain
POST→303 is the correct implementation, not a shortfall to be migrated later.
Domain archive/restore is the reference case (#82): it moves the header Status
badge, the inline Restore button beside it, *and* the presence of the
`.danger-zone` block — three separate DOM regions, which HTMX would need
`hx-swap-oob` or a body-spanning partial to cover. Contrast SourceRevision
clear-cache, which swaps the one contiguous `#revision-card` partial. The 303
also preserves correct back-button semantics for a state transition.

**Related-collection tables.** `.data-table` under an `<h2 class="section-heading">`
carrying the row count (e.g. "Revision History (12)"). When the table is **paginated**,
the count must come from a route-level `COUNT` over the full result set, never
a template `|length` — that would report only the current page. Domain detail
(`source_total`) is the reference; InfoSource detail's "Other Sources at This
URL" uses the capped `limit+1` "50+" probe instead, appropriate where the
section is truncated rather than paged. Keep `has_more` on its own `limit+1`
probe even when a `COUNT` is already being run — the probe is self-consistent
by construction (one statement, one snapshot), whereas deriving `has_more` from
the `COUNT` compares two statements under READ COMMITTED and lets a concurrent
delete render a Next link into an empty page. The apparent redundancy is
deliberate: the two values answer different questions. A section heading with a
count needs **two** empty
states: "nothing here at all" and "nothing on *this page*" (overshot offset);
collapsing them makes the heading contradict the body. Cache state uses the
`.status-pill--cached/expired/missing` pills, not `.badge` variants. A
succession/currency status column uses `.badge--primary`/`.badge--muted`.

**Pagination params are clamped, not validated.** Every paginated dashboard
route takes `page: Pagination = Depends(pagination)`
(`src/dashboard/pagination.py`) rather than bare `limit`/`offset` ints. `limit`
clamps to `[1, 200]`, `offset` to `[0, 2**63 - 1]`, so out-of-range values render
a sensible page instead of erroring (#84). The upper offset bound is a storage
limit rather than a product judgement: the query binds offset to
`OFFSET $2::BIGINT` and asyncpg rejects anything wider with `DataError: value out
of int64 range`, which surfaced as a 500 until it was capped — and capping costs
nothing else, since any offset that large already yields an empty page.

This is a **deliberate divergence from the API layer**, which uses
`Query(ge=…, le=…)` and returns 422. The API is a contract surface where a bad
`limit` is a client bug worth surfacing loudly; the dashboard is a human surface
reached by hand-edited URLs and stale bookmarks. It also has no HTML rendering
path for validation errors — `RequestValidationError` falls through to the
app-wide handler in `src/api/errors.py`, which always returns JSON, and HTMX does
not swap non-2xx responses, so a 422 on a partial silently does nothing. Clamping
removes the error path rather than styling it.

**The params are declared `str`, not `int`, and parsed in the dependency** (#86).
Under `int` annotations FastAPI coerces *before* the dependency runs, so
`?limit=abc` answers a browser with a raw JSON envelope. Parsing inside
`clamp_pagination` closes that: unparseable input falls back to the default
(`int()`'s tolerance of surrounding whitespace is kept, so `?limit=%2025%20`
still means 25), and each param is handled independently so one bad value doesn't
discard the other. Since `limit` and `offset` are the only non-`str` request
params on any dashboard route — every form field is `str`, path params are `str`
ULIDs — no `RequestValidationError` is reachable from a dashboard URL. Form-field
validation is a separate mechanism; see **Inline validation errors**.

That completeness claim is enforced, not just asserted:
`test_pagination.py::test_no_dashboard_route_declares_a_coercible_param` walks
every `/dashboard` route's flattened dependant and fails if any query, path, or
body param is annotated as anything but `str` (`str | None` is fine —
optionality is absence, not coercion). **A new dashboard route must take its
params as `str`**; declaring `page: int` or `after: date` reopens the raw-JSON
422, because coercion happens during dependency solving before any dashboard
code runs.

The dependency is `async` so FastAPI resolves it inline rather than paying a
`run_in_threadpool` hop for two comparisons; the parse and arithmetic live in a
sync `clamp_pagination()` helper so they stay unit-testable without reaching
through `Query` defaults. Each param's `description` documents the
clamp-don't-reject behaviour for readers of the code. New paginated routes must
use the dependency; do not reintroduce bare `limit: int = 50`.

None of this reaches OpenAPI: dashboard routers are included with
`include_in_schema=False` (#87), because `clients/python/scripts/regen.sh`
generates the public SDK from `app.openapi()`, so any dashboard path in the
schema is one routine regen away from shipping as `archiver_client` API surface
— HTML responses under proxy-header auth, useless as client methods.
`test_openapi_exclusion.py` pins the exclusion, and **a ninth dashboard router
must be added to the loop in `register_dashboard`** rather than via its own
`app.include_router(...)` call, so it cannot forget the flag.

If a dashboard route ever needs a typed param that *cannot* be clamped into
something sensible — a date filter, say — this approach runs out, and the HTML
error-page work sketched in #86 (a `_422.html` plus a dashboard-owned
`RequestValidationError` handler registered from `register_dashboard`) becomes
the answer.
