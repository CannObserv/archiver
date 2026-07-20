# ADR — RepSpec document editing: tiered mutability

**Date:** 2026-07-20
**Issue:** CannObserv/archiver#83 (tier 3 split to #95)
**Status:** Accepted

## Context

The RepSpec detail screen (#80) renders `document` read-only. There is no
update path — `src/api/routes/rep_specs.py` exposes POST/GET only, and its
module docstring states immutability as a deliberate decision:

> POST/GET only — RepSpecs are immutable once written. To change provider
> config, author a new RepSpec and reassign affected InfoItems.

That decision is not incidental. `InfoItemRepSpec` is effective-dated
(`activated_at` / `deactivated_at` / `public_url`), so an assignment row
asserts *"item X replicated under spec R from T1 to T2, producing the artifact
at `public_url`."* `rep_specs` carries no `updated_at` and no document history.
An in-place PATCH would therefore make that assertion unverifiable: you could
no longer explain which `path_template` produced an artifact that already
exists in a provider bucket.

But full immutability is too strict in one specific, common case: a RepSpec
that has been authored and *not yet assigned to anything*. Fixing a typo in
`path_template` on a spec no consumer has ever seen currently requires
authoring a replacement, and that is the friction #83 was opened about.

## Decision

Adopt a **tiered mutability contract** rather than a general-purpose PATCH.

| Tier | Condition | Mutable |
|---|---|---|
| 1 | always | `name` |
| 2 | **draft** — zero assignment rows, active *or* deactivated | `document` (whole-document replace) |
| 3 | any assignment row exists | nothing — clone + migrate (#95) |

`provider` is frozen in all tiers, including draft. It is both a column and a
document key that must agree; freezing it removes a consistency invariant
rather than adding a check. A draft with the wrong provider should be
re-authored.

`name` is a label with no replication semantics, so it is mutable regardless of
assignment state.

### Draft gate

Draft-ness is `NOT EXISTS (SELECT 1 FROM information.info_item_rep_specs WHERE
rep_spec_id = :id)` — **all** rows, not just `deactivated_at IS NULL`. A
deactivated assignment still means a replication run happened under that
document. `_load_active_assignments` in `src/dashboard/routes/rep_specs.py`
filters to active rows and is the wrong helper to reuse for this gate.

### Replace, not merge

`document` updates are whole-document replacement, matching
`PATCH /info-sources/{id}/source-specs`. JSON merge-patch semantics interact
badly with the envelope's `additionalProperties: false` — a merge cannot
express field *removal*, so `object_options` keys would become unremovable.

### Validation

`src/core/tools/update_rep_spec.py` mirrors `update_info_source_specs.py`:
typed exceptions from the core tool, translated at the route into the standard
envelope. Reuses `validate_rep_spec` unchanged — the same envelope +
per-provider sub-schema path as create.

## Consequences

**Audit.** A nullable `updated_at` column is added to `rep_specs`. Nullable
rather than defaulted so that "never edited" stays distinguishable from
"edited at creation time"; backfilling existing rows with `created_at` would
assert an edit that never happened.

**No bus event.** A tier-2 edit is unobservable by construction: zero
assignments means no consumer can have acted on the document. Per the bus
versioning convention, adding a `rep_spec_changed` event later is additive and
does not bump any `schema_version`, so deferring costs nothing. Revisit with
#95.

**`required_fields` coupling evaporates.** The concern in #83 — that changing
`required_fields` silently breaks assigned items' `rep_fields` bags — cannot
arise under tier 2, because a draft has no assigned items. It moves wholly to
#95, where it becomes a pre-flight dry-run.

**Tier 3 is deferred, not rejected.** `docs/plans/2026-06-25-replicator-mvp-design.md`
lists "RepSpec resolution / reads from archiver" as explicitly out of scope for
the MVP loop, so nothing consumes `document` today. Designing clone + migrate
now would be designing against a hypothetical consumer. #95 carries the
trigger condition: pull it forward once RepSpecs are being assigned in anger.

**One-way door risk: low.** Tier 2 is a strict relaxation of the current
contract. If it proves wrong, re-freezing drafts breaks no stored data — only
an endpoint that will have been used on specs nothing consumed.

## Alternatives considered

**General PATCH with a warning + confirmation on assigned specs.** Rejected:
warnings do not restore the audit trail. The artifact at `public_url` is
already written under the old `path_template`, and no dialog changes that.

**Document version history table.** Rejected as premature. It solves tier 3
properly but is meaningfully more schema and UI than #83 warrants, and #95 may
land on copy-on-write (clone) instead, which gets the same lineage from rows
that already exist.

**Provider mutable while draft.** Rejected for contract simplicity — see above.
