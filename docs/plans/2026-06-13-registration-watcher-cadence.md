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
`default_schedule_config`; the only work is plumbing — thread an optional
`schedule_config` from a new advanced Step 3 field, through `provision_on_create`,
into `WatcherClient.provision_watched_item`. Keep it on the existing **post-commit,
best-effort** path so a Watcher failure still never fails registration. Defer
"paused on create": Watcher's `watched_item_create` body has no `is_active` field,
so it needs a Watcher-side API change — split that into a separate issue. Default
cadence = daily; default state = active (unchanged behavior).

**Schedule-config shape (verified against Watcher source 2026-06-13).** Watcher's
`default_schedule_config` is `{"interval": "<N><unit>"}` where unit ∈ `{s,m,h,d}`
(`parse_interval` in `watcher/src/core/scheduler.py`; system default `{"interval":
"1d"}`). It is **not** `{"interval_seconds": int}`. Archiver's `_format_cadence`
([info_items.py:933](../../src/dashboard/routes/info_items.py#L933)) reads the wrong
key (`interval_seconds`), so cadence has never rendered for provisioned items —
pre-existing bug, fixed as part of this plan. Registration dropdown maps to:
hourly → `"1h"`, 6h → `"6h"`, daily → `"1d"` (default), weekly → `"7d"`.

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
- **Send cadence as `interval_seconds`** — rejected: Watcher's `parse_interval`
  only accepts duration strings (`30s`/`15m`/`6h`/`1d`); seconds-as-int would be
  stored but never honored by the scheduler.

## Steps

1. Fix `_format_cadence` ([info_items.py:933](../../src/dashboard/routes/info_items.py#L933))
   to read `default_schedule_config["interval"]` (duration string) instead of
   `interval_seconds`, and render it directly (e.g. `1d` → "~1 day"). Add a unit
   test with a `{"interval": "6h"}` config. (Pre-existing display bug — surfaces
   cadence for all provisioned items, not just newly-registered ones.)
2. Extend `WatcherClient.provision_watched_item` (and `patch_watched_item` for
   parity — confirmed in scope) to accept an optional `schedule_config: dict | None`
   and forward it as `default_schedule_config` only when set
   ([client.py:75](../../clients/watcher-python/src/watcher_client/client.py#L75)).
   Add SDK tests asserting the body carries / omits the field. Bump
   watcher_client version.
3. Thread `schedule_config: dict | None = None` through `provision_on_create`
   ([watcher_provisioning.py:27](../../src/core/watcher_provisioning.py#L27)) into
   the wrapper call. Update `tests/core/test_watcher_provisioning.py`.
4. Add a collapsed **"Watcher settings (advanced)"** block to Step 3 in
   `register/index.html` — a cadence `<select>` with values `1h` / `6h` / `1d` /
   `7d` (labels Hourly / Every 6h / Daily / Weekly), defaulting to `1d`; Alpine
   `x-model="cadence"`; submit as a form field.
5. In the register submit handler, build `{"interval": <selected>}` (always send —
   daily is explicit per decision) and pass it to `provision_on_create`. Tests:
   selected non-default → that interval forwarded; default → `{"interval": "1d"}`
   forwarded.
6. Surface the chosen cadence in the Step 4 review summary (read-only, with an
   Edit link back to Step 3, consistent with existing review rows).
7. Update `docs/UI.md` (registration flow — new advanced field). **No CHANGELOG
   entry** (deviation from original plan): the change touches `src/dashboard/`,
   `src/core/`, and `clients/watcher-python/` — none of the gated contract-visible
   paths (`alembic/versions/`, `src/api/routes/`, `src/api/schemas/`,
   `clients/python/`), and the changelog policy excludes dashboard-UX/docs changes.
   The watcher_client SDK (separate version, bumped to 1.2.0) is not covered by
   this changelog.
8. File the deferred split-out: Watcher issue to add `is_active` to the
   `watched_item_create` body, then a follow-up Archiver issue to expose
   paused-on-create at Step 3. Link both from #50.

## Open questions / risks

_All resolved 2026-06-13:_

- **Cadence vocabulary** — ✅ agreed. Buckets `1h` / `6h` / `1d` / `7d`, verified
  against Watcher's `parse_interval` (accepts `s`/`m`/`h`/`d` duration strings).
- **Default cadence** — ✅ daily (`{"interval": "1d"}`), sent explicitly (matches
  Watcher's own system default, so behavior is unchanged if omitted; explicit is
  clearer in the provision call).
- **`patch_watched_item` cadence** — ✅ include (latent capability; no detail-page
  "change cadence" affordance yet — possible follow-up, out of scope here).

_New (from Watcher source verification):_

- **`_format_cadence` reads the wrong key today** — fixed in step 1. The fix
  changes display for *all* watched items, not just newly-registered ones; worth a
  CHANGELOG `[service]` note. Consider whether to file as a standalone bug or carry
  it under #50 (carrying it here, since it's the same surface).
