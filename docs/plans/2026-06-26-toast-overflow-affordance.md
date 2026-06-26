---
title: Toast overflow affordance — hybrid (transient flash + persistent "+N more") with announcer
date: 2026-06-26
status: draft
---

# Toast overflow affordance (archiver#73)

## Problem

The toast overlay (archiver#65) caps visible toasts at 4 and evicts transient
(`success`/`info`) toasts before persistent (`error`/`warning`) ones. Two
dead-spots fall out of that policy:

1. **Transient (the filed issue, #73):** when 4 persistent toasts fill the cap
   and a `success`/`info` arrives, the newcomer is appended then *synchronously
   evicted* in the same `showFlash` call — the operator gets no visual feedback
   that their action did anything, and because the node is added-and-removed in
   one synchronous turn it is almost certainly never announced to assistive tech
   either.
2. **Persistent (latent, surfaced while designing):** persistent toasts are
   FIFO-capped at 4 too (`pickCapVictim` → `firstElementChild`). The 5th error
   silently evicts the 1st — directly violating #65's "failures must not vanish
   unseen" guarantee. Currently untested-as-a-bug and unaddressed.

Both holes share a root cause: announcement and visual capacity are coupled, and
overflow is resolved by destroying toasts rather than deferring them.

## Approach

Hybrid, split by toast lifetime, on top of an accessibility keystone:

- **Announcer (keystone).** Add two visually-hidden live regions — one
  `aria-live="assertive"` (errors), one `aria-live="polite"` (everything else).
  Every `showFlash` writes the toast text into the matching announcer regardless
  of whether the toast is shown, flashed, or collapsed. Move live semantics off
  the visible region: `#flash-region` loses `aria-live`, and visible toasts lose
  their `role="alert"`/`role="status"` (so nothing double-announces). Visible
  toasts become purely visual; the announcer carries all SR output.
- **Transient overflow.** A transient that can't fit because persistent toasts
  fill the cap is shown anyway as a single overflow lane below the persistent
  block — full `AUTO_DISMISS_MS` (6s), last-write-wins (at most one transient
  lane; a newer transient replaces the prior). Never silently dropped.
- **Persistent overflow.** More than 4 persistent toasts collapse the excess
  into a `+N more` counter button occupying the 4th slot (3 toasts + counter).
  Click/Enter expands to show all (region grows, scrolls if needed); there is no
  re-collapse — once engaged the operator dismisses each. The counter counts
  hidden *persistent* toasts only (honest "+N unresolved" semantics) and replaces
  today's silent oldest-error eviction.

## Tradeoffs / alternatives

- **Pure "+N more / expand" single model (user's first alt)** — rejected as the
  sole mechanism because collapsing the just-triggered `success` behind a counter
  forces a click to confirm a routine save, and risks errors going unannounced
  unless paired with the announcer anyway. Kept its strength (backlog model) for
  the persistent path where the semantics are honest.
- **Shorten transient overflow to ~3s** — rejected per user decision; show the
  full 6s like any other transient. Simpler (one constant) and consistent.
- **Overflow-flash only, no persistent counter** — rejected: leaves the latent
  5th-error silent-eviction hole (#65 violation) open.
- **aria-only fix (announce but don't show)** — rejected: sighted operators still
  get no visual feedback; fails sighted/AT parity.

## Steps

TDD throughout (Red → Green → Refactor); JS tests are vitest + happy-dom in
`tests/js/flash.test.js`, run via `npm test` (CI-gated).

1. **Announcer — red.** Add tests: each level writes its body into the correct
   announcer region (error → assertive, others → polite); `#flash-region` no
   longer carries `aria-live`; visible toasts carry no `role` attribute. Update
   the existing "ARIA role by severity" tests to assert on the announcer instead.
2. **Announcer — green.** Implement the two hidden live regions (created/ensured
   by `flash.js`, or markup in `base.html` + styled `.sr-only`), write text on
   each `showFlash`, prune announced nodes after a short delay. Strip role/live
   from visible toasts and `#flash-region`.
3. **Transient overflow — red.** Replace the "drops a new transient when the cap
   is full of persistent" test: assert the transient is shown (full 6s, then
   auto-dismisses) and that a second transient replaces the first in the lane
   (last-write-wins). Keep the all-transient FIFO-at-4 test green.
4. **Transient overflow — green.** Rework eviction so the newcomer is never the
   victim: transients evict older transients first; if only persistent remain,
   keep the newcomer as a single +1 overflow lane with a normal 6s timer.
5. **Persistent "+N more" — red.** Add tests: 5th persistent → 3 toasts + counter
   button (no error removed); counter text = `+N more` with correct N; button has
   `aria-expanded="false"`, `aria-controls`, accessible label; activating it shows
   all persistent toasts and removes the counter; no re-collapse control; dismiss
   resets state. Replace the "caps all-persistent at 4, evicting the oldest" test.
6. **Persistent "+N more" — green.** Implement the counter slot, expand state
   (module-level flag), focus move to the first revealed toast on expand, and
   counter recompute on each arrival/dismiss while collapsed.
7. **CSS.** Add `.flash__more` counter pill, expanded region `max-height` +
   `overflow:auto`, `.sr-only` announcer styling, narrow-viewport behavior, and
   confirm `prefers-reduced-motion` still suppresses `flash-in`.
8. **Docs (same commit as code).** Rewrite the "Flash messages" section of
   `docs/UI.md` (drop "the incoming transient is dropped"; document announcer,
   transient lane, "+N more"/expand/no-rehide, focus + ARIA). Update `docs/STYLE.md`
   for `.flash__more`/`.sr-only` and the expanded region. Add a `CHANGELOG.md`
   `[service]` entry (dashboard behavior change).
9. **Verify.** `npm test`, `uv run ruff check .`; manual smoke against dev server
   (port 8021): trigger 4 errors + a success (lane flashes), 5 errors (counter +
   expand), keyboard-only expand (focus lands), and an AT pass (VoiceOver/NVDA)
   confirming errors announce while collapsed.

## Open questions / risks

- **Collapse order for persistent overflow:** show newest-3 + "+N older", or
  oldest-3 + "+N newer"? Default proposed: **newest-3 visible** (active errors in
  view, counter for the backlog). Confirm.
- **Announcer ownership:** create the live regions in `flash.js` on first use, or
  add static markup to `base.html`? Leaning `base.html` (declarative, no
  first-event race). Confirm.
- **Region height when expanded** on short viewports: scroll within the overlay
  vs. let it run; plan uses `max-height: calc(100vh - …)` + `overflow:auto`.
- **Pre-existing-behavior change:** step 5 stops silently evicting the oldest
  error — intended, and arguably the more important fix, but it is a visible
  behavior change beyond the filed scope of #73. Calling it out explicitly.
- No backend/Python surface touched; no migration; risk confined to the dashboard
  static + templates + docs.
