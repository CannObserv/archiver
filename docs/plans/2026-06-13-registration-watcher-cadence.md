---
title: Registration flow — Watcher cadence config at Step 3 (#50)
date: 2026-06-13
status: draft
---

# Registration flow — Watcher cadence config at Step 3 (#50)

## Problem

The registration flow (Step 3 — Metadata) collects name, description, owner, then
provisions a WatchedItem post-commit via `provision_on_create`
([register.py:395](../../src/dashboard/routes/register.py#L395)). Every item lands
on Watcher's **default** fetch cadence — the operator has no say at registration
time. #50 asks for Watcher configuration affordances at Step 3 (cadence + active/
paused on create). Since #50 was filed, both its dependencies shipped: #49 (UX
redesign) is closed and the Watcher integration was wired by the 2026-06-09
control-plane design. The remaining gap is narrow — config is not threaded through
the provisioning call — but it is asymmetric: Watcher's JSON API supports cadence
on create, but **not** `is_active` on create.

## Approach

Ship **cadence-only** at registration. Watcher's create/patch bodies accept
`default_schedule_config` (shape `{interval_seconds: int}`, per `_format_cadence`
at [info_items.py:933](../../src/dashboard/routes/info_items.py#L933)); the only
work is plumbing — thread an optional `schedule_config` from a new advanced Step 3
field, through `provision_on_create`, into `WatcherClient.provision_watched_item`.
Keep it on the existing **post-commit, best-effort** path so a Watcher failure
still never fails registration. Defer "paused on create": Watcher's
`watched_item_create` body has no `is_active` field, so it needs a Watcher-side API
change — split that into a separate issue. Default cadence = daily; default state =
active (unchanged behavior).

## Tradeoffs / alternatives

- **Include active/paused on create now** — rejected: not supported by Watcher's
  create body; would require a Watcher API change (add `is_active`) or a fragile
  post-create toggle against an HTML form endpoint. Out of scope; split out.
- **Make provisioning part of the atomic registration transaction** — rejected:
  breaks the "Watcher failure never fails registration" invariant the current
  post-commit design guarantees. Cadence rides the same best-effort call.
- **Add content_type / tags fields too** — rejected for now: content-type is
  derived from the fetch; tags are an authoring concern better placed on the
  detail page. Keeps Step 3 lean.
- **Domain-level cadence default instead of per-item** — rejected: Watcher owns
  domain rate-limiting; `default_schedule_config` is per-WatchedItem. Per-item is
  the right altitude for the registration affordance.

## Steps

1. Extend `WatcherClient.provision_watched_item` (and `patch_watched_item` for
   parity) to accept an optional `schedule_config: dict | None` and forward it as
   `default_schedule_config` only when set
   ([client.py:75](../../clients/watcher-python/src/watcher_client/client.py#L75)).
   Add SDK tests asserting the body carries / omits the field. Bump
   watcher_client version.
2. Thread `schedule_config: dict | None = None` through `provision_on_create`
   ([watcher_provisioning.py:27](../../src/core/watcher_provisioning.py#L27)) into
   the wrapper call. Update `tests/core/test_watcher_provisioning.py`.
3. Add a collapsed **"Watcher settings (advanced)"** block to Step 3 in
   `register/index.html` — a cadence `<select>` (hourly / 6h / daily / weekly)
   defaulting to daily; Alpine `x-model="cadenceSeconds"`; submit as a form field.
4. In the register submit handler, parse the cadence field, build
   `{"interval_seconds": N}` (or `None` if unset/default-sentinel), and pass it to
   `provision_on_create`. Tests for: field present → schedule forwarded; absent →
   no `default_schedule_config` in the Watcher call.
5. Surface the chosen cadence in the Step 4 review summary (read-only, with an
   Edit link back to Step 3, consistent with existing review rows).
6. Update `docs/UI.md` (registration flow — new advanced field) and append a
   CHANGELOG `[both]` entry (new SDK arg + registration cadence affordance).
7. File the deferred split-out: Watcher issue to add `is_active` to the
   `watched_item_create` body, then a follow-up Archiver issue to expose
   paused-on-create at Step 3. Link both from #50.

## Open questions / risks

- **Cadence vocabulary** — confirm the dropdown buckets (hourly / 6h / daily /
  weekly) match operationally meaningful intervals; confirm Watcher honors
  arbitrary `interval_seconds` vs. a fixed enum. Verify against Watcher's
  schedule-config schema before finalizing the options.
- **Default cadence** — daily assumed. If Watcher's own default differs and we
  want to preserve it, send `None` (omit) rather than forcing daily, so Watcher's
  default wins. Decide: explicit daily vs. defer-to-Watcher.
- **`patch_watched_item` cadence** — step 1 adds it for parity but no caller sets
  it yet (no "change cadence" affordance on the detail page). Acceptable as latent
  capability; flag if reviewers prefer to omit until needed.
