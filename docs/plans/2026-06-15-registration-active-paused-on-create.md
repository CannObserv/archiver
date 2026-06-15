---
title: Expose active/paused on WatchedItem create + pause/resume on detail (archiver#60)
date: 2026-06-15
status: draft
---

# Expose active/paused on create (archiver#60)

## Problem

Issue #50 shipped the registration cadence affordance **cadence-only** because Watcher's
create API had no `is_active` field — every WatchedItem was provisioned active. The companion
requirement, "watch active immediately vs. register paused" (plus a pause/resume control on the
InfoItem detail page), was deferred to #60 pending a Watcher change. That change shipped:
**watcher#188** (`2d60e61`, watcher `main`) added `is_active` to `WatchedItemCreate` (default
`True`) and `WatchedItemPatch` (`bool | None`, explicit `null` rejected → 422), decoupled from
archive/restore. Watcher also guards: `check-now` on a paused item → 409, and `PATCH is_active`
on an *archived* item → 409. Archiver can now thread active/paused through provisioning and the
dashboard. Without this, operators must register an item, let it fetch, then pause it in Watcher's
own UI — there is no "register paused" and no in-dashboard pause.

## Approach

Mirror the existing `schedule_config` (cadence) wiring end-to-end, using the **omit-when-None**
body convention as the safety guarantee against Watcher's explicit-null 422.

1. **SDK adapter** (`clients/watcher-python/src/watcher_client/client.py`): add
   `is_active: bool | None = None` to `provision_watched_item` and `patch_watched_item`; include
   `"is_active"` in the request body **only when not None**. `None` means "don't touch" → never
   sends `null`. Regen the generated layer for parity (housekeeping; the hand-written adapter is
   what's called).
2. **Provisioning helper** (`src/core/watcher_provisioning.py`): add `is_active: bool | None = None`
   to `provision_on_create`, forward to the adapter.
3. **Registration Step 3** (`register.py` + `register/index.html`): a "Watch active immediately"
   checkbox (default checked) inside the existing advanced Watcher `<details>` block, next to the
   cadence select. Parse to `is_active`, thread into `provision_on_create`, preserve across
   validation re-renders, and reflect in the Alpine review-step summary.
4. **Detail-page pause/resume** (`info_items.py` dashboard route + `_watcher_section.html` /
   `_watcher_status.html`): a POST handler mirroring `check_now` that calls
   `patch_watched_item(is_active=...)` and emits `HX-Trigger: watcherUpdated`; a Pause/Resume
   button keyed on `watched_item.is_active`; a "Paused" badge. Honor Watcher's guards — when paused,
   suppress the check-now 409 (disable/relabel the button); hide the toggle for archived items.

TDD throughout (red → green). Update CHANGELOG `[both]`, `docs/UI.md`, and `docs/STYLE.md`
(template change is a CR blocker without doc updates).

## Tradeoffs / alternatives

- **Core-only first PR (defer detail-page pause/resume to a follow-up)** — rejected: the patch
  path is live and the detail-page piece is one handler + one button; splitting adds a second
  review cycle for little isolation benefit. (User chose full scope.)
- **Pass `is_active=True` explicitly on every create instead of omit-when-None** — rejected:
  Watcher's create default is already `True`, so omitting when the operator leaves the box checked
  keeps the body minimal and matches the `schedule_config` precedent. We only send `is_active`
  when provisioning *paused* (`False`).
- **Separate `/pause` and `/resume` endpoints** — rejected in favor of one toggle handler that
  reads current state; fewer routes, symmetric with the single button. (Revisit only if audit
  semantics demand distinct actions — watcher#189 tracks dedicated pause/resume events.)
- **Block on SDK regen** — rejected: regen needs Watcher live on `:8000` and the generated
  create/patch models aren't on the call path. Do it for parity but don't gate the feature on it.

## Steps

1. **SDK adapter + tests.** Add `is_active` (omit-when-None) to `provision_watched_item` and
   `patch_watched_item`; assert body includes `is_active` only when an explicit bool is passed and
   is absent for `None`. Run `bash clients/watcher-python/scripts/regen.sh` if Watcher is reachable;
   otherwise note regen as a follow-up. Verify: SDK test suite green.
2. **`provision_on_create` threading + test.** Add `is_active` param, forward it; test asserts it
   reaches the adapter call. Verify: `pytest tests/.../watcher_provisioning` green.
3. **Registration checkbox.** Add the form field + parse in `register.py`, the checkbox in the
   advanced block, value preservation on re-render, and the Alpine summary line. Test: posting with
   the box unchecked provisions paused (`is_active=False`); checked/default provisions active.
   Verify: register route tests green.
4. **Detail-page pause/resume handler + UI.** Add the toggle POST route (mirrors `check_now`,
   `HX-Trigger: watcherUpdated`), the Pause/Resume button + Paused badge, and check-now suppression
   when paused / toggle-hidden when archived. Tests cover toggle both directions, the paused
   check-now path, and the archived 409 path. Verify: dashboard detail tests green.
5. **Docs + changelog.** CHANGELOG `[both]` entry; `docs/UI.md` (new affordances) and `docs/STYLE.md`
   (if any new styles). Verify: full `pytest` + `ruff check`/`ruff format --check` green; changelog
   guard satisfied.

## Open questions / risks

- **Paused check-now UX.** Plan: when `is_active` is false, disable/relabel "Check now" rather than
  let it 409. Confirm that's the desired behavior vs. surfacing a "resume first" message.
- **Archived-state exposure.** Toggle should be hidden for archived items (PATCH `is_active` → 409).
  Need to confirm the dashboard ever renders archived WatchedItems; if not, this is defensive only.
- **SDK regen reachability.** Regen requires Watcher on `localhost:8000`. If unavailable during
  implementation, the generated create/patch models stay stale (adapter still works) — track as a
  follow-up chore rather than blocking the PR.
- **Audit events.** watcher#189 (dedicated `WATCHED_ITEM_PAUSED/RESUMED` events) is deferred;
  generic `WATCHED_ITEM_UPDATED` covers pause/resume for now. No Archiver action required.
