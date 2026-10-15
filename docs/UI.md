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
- [COMPONENTS.md](COMPONENTS.md) - the Alpine.js component catalogue.
- [STYLE.md](STYLE.md) - design tokens and component classes.
- [INFO_ITEM_DETAIL.md](INFO_ITEM_DETAIL.md), [ORG_ROW.md](ORG_ROW.md),
  [REGISTER.md](REGISTER.md), [HEALTH_ROW.md](HEALTH_ROW.md) - one screen's
  internals each: the InfoItem hub and its Organization row, the register
  wizard, the home screen's health row.

> **AGENTS.md enforcement:** a Jinja2 template change, a new or changed
> dashboard route, or a new Alpine.js component must update the doc it touches
> in the same commit - usually PAGES.md or COMPONENTS.md, and this file when it
> changes a shared pattern or convention.

---

## URL Structure

```
/dashboard/                          Home - CTA, health strip, Recent Activity, domain overview
/dashboard/registry-audit            Registry Audit - stored documents the current schemas reject
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
