---
title: Fetch headers - the carrier, the Domain/InfoSource shape, save-time checks
date: 2026-11-24
status: proposed
issue: archiver#376 (design only; the build stays parked)
---

# Fetch headers (#376) - design

**Issue:** archiver#376 · **Epic:** #503, Tier 2 · **Upstream:** cannobserv#577 (v0.51.1),
cannobserv#763 (v0.52.0), replicator#216 (done), watcher#457 (parked on this design)
· **Siblings:** #377 (timeout), #379 (render), #454 (co-core catch-up)

Read against `main` at `9d870dfe` and co-core `v0.52.0`. The brief's review is posted on
#376 (corrections 1-6, 2026-11-24). This design rests on three of them: Watcher holds no
read grant on `content.fetch-policy` (2); Archiver doesn't store or announce `render` yet
(3); co-core refuses every header but `user-agent` under `render="browser"` (4).

## Problem

Some sites block the default client, or need an `Accept` header, a cookie or an API key.
Blocking and auth usually apply to a whole site, so most of this policy is per host, and a
little is per source. Archiver records the policy, and Watcher and Replicator carry it out.
Every link in the chain except two has shipped: Replicator resolves `fetch-<role>`
references (replicator#216), and co-core has `ContentFetchCommand.credential_headers`.
The two missing links are the field that carries the policy from Archiver to Watcher, and
Archiver's choice of where that field goes. watcher#457 is parked on that choice.

## Decisions

### D1. The carrier: `info.registry`, both levels, resolved by Archiver

Archiver merges each source's Domain entries and InfoSource entries into **one resolved
pair of maps per source**. It announces that pair on every InfoItem announcement whose
active primary source is that source. `content.fetch-policy` doesn't change.

- **The precedent is #364 (design C-e).** The Domain's cadence tier is already resolved in
  Archiver and announced per item as `watch_spec`. A Domain header edit is the same kind
  of write: `update_domain` announces the host's items whose resolved headers moved, the
  way it already does for the resolved interval.
- **Watcher already reads this stream.** Its grant is `+xread ~info.registry` and nothing
  on `content.fetch-policy` (correction 2). One stream means no second tail reader, no ACL
  change, and no join of two last-write-wins states with independent orderings at
  `content.fetch` time.
- **The policy stays with the identity it describes.** The url, the specs, `render` (once
  #379 ships) and the headers all arrive in one ordered frame. A source switching to
  `render="browser"` can't be fetched with the previous frame's headers.
- **`content.fetch-policy` stays Replicator's politeness frame.** Its frame stays
  `(revoked, min_interval_seconds)`, and a header edit draws no `fetch_policy_generation`.
  DOMAINS.md's frame contract and Replicator's map are untouched.

| Option | Why not |
|---|---|
| Host level on `content.fetch-policy`, source level on `info.registry` | Needs a broker grant and a second reader for Watcher, plus a cross-stream join on every fetch. Every header edit redraws a generation Replicator orders on. Replicator receives header policy it never uses. Plain values repeat every 300 s rather than hourly. |
| Both levels unresolved on `info.registry` (a Domain map and a source map), merged by Watcher | Every item announcement repeats the host map anyway, so carrying it unresolved saves no bytes. The control-plane rule lives in two repos. Archiver's dashboard couldn't show the effective set without reimplementing Watcher's merge. |

### D2. The stored shape: one JSONB column per level

`domains.fetch_headers` and `info_sources.fetch_headers`, both `JSONB NULL` (`none_as_null`,
as `capture_policy` does). Both hold one validated document:

```json
{"schema_version": 1,
 "headers": [
   {"name": "Accept", "value": "application/json"},
   {"name": "X-Api-Key", "credential": "fetch-wa-leg-api"}
 ]}
```

- **Each entry has exactly one of `value` (plain) or `credential` (a `fetch-<role>`
  reference).** A secret's value is never stored, in any column.
- **It is a list, not a map.** A JSON object would admit `Accept` and `accept` as two keys,
  so the save would need a refusal the shape could have made impossible. The list keeps the
  operator's spelling, and the save refuses a name repeated case-insensitively.
- **`NULL` means no policy at this level**, and so does an empty `headers` list. Writes
  normalize the empty list to `NULL`.
- **This is the Domain docstring's "own column" rule, met.** It is a narrowly named column
  for headers only, never folded into `default_watch_spec` or a generic policy blob.
  #377's `fetch_timeout_seconds` gets its own column beside it; nothing here boxes that out.
- **The house style.** One pydantic model validates the document on write
  (`src/core/fetch_headers.py`, after `src/core/capture_policy.py`). Both levels and both
  surfaces (the API and the dashboard) call that same model.

A child table was considered: it would let the DB enforce case-insensitive uniqueness and
"exactly one kind". It was rejected because the save already has to run co-core's checks,
which a DB constraint can't call. And a Domain edit has to lock and announce through
`update_domain`'s row lock either way.

### D3. The merge order, per header name

Names compare case-insensitively. **The most specific level that names a header decides its
value, its kind and its spelling**, so each name lands in `fetch_headers` or
`fetch_credential_headers`, never both. Lowest to highest:

1. **The fetcher's defaults** (Replicator's `FetchContent`; "issuer wins").
2. **Watcher's pinned `user-agent: watcher/0.1.0`.** A policy `user-agent` replaces it by a
   case-insensitive match. A case-sensitive replace would send `user-agent` and `User-Agent`
   together, which `FetchContent` refuses (#283), closing every fetch of the source
   `invalid_request_options`.
3. **The Domain's entries** (by the source's `domain_name`). A host with no row, or a source
   whose `domain_name` is `NULL`, contributes nothing at this level.
4. **The InfoSource's entries.**
5. **Watcher's replayed conditional-GET validators.** Policy can never name them (D4), so
   they never collide with a policy entry.

Steps 3 and 4 run in Archiver (D1). Steps 1, 2 and 5 run downstream, as they do today.
Putting the pinned UA at step 2 is the #376 body's exception, written into the order: a
policy UA beats Watcher's (correction 5).

Worked collisions:
- Domain plain `X-Client: abc` and InfoSource credential `X-Client → fetch-x`: the
  credential is sent, and no plain value goes with it.
- Domain credential `Authorization → fetch-a` and InfoSource credential
  `Authorization → fetch-b`: `fetch-b` is sent.
- Domain credential `X-Trace → fetch-t` and InfoSource plain `X-Trace: 1`: the plain value
  is sent. That's allowed only because `X-Trace` isn't a secret-bearing name (D4).

**A UA override is a fingerprint discontinuity.** A save that changes any source's resolved
`user-agent` (setting it, changing it, or clearing it back to Watcher's pin, at either
level) does two things:
- On both surfaces it requires an explicit acknowledgement that names how many sources move:
  a confirm in the dashboard, and an acknowledgement field in the API.
- It logs a structured `WARNING` (`fetch user-agent changed`) that names the
  `info_source_id`s.

Archiver has no discontinuity record to write to (correction 6). The durable marker on the
source's revision history is shared with #379, whose render-mode change is the same kind of
event, and is filed as a follow-up rather than designed here.

### D4. Validation on save

Both levels and both surfaces run these checks. Each one fails at save, not as a fetch
failure later:

- **A credential entry is checked with
  `co_core.pure.util.aliases.validate_fetch_credential`.** The design never uses
  `FETCH_CREDENTIAL_PATTERN`. Its anchor changed in v0.52.0 (cannobserv#763), and as
  `Field(pattern=…)` it raises `SchemaError` under pydantic's default Rust engine. The
  function matches the whole string and **doesn't quote the value**, because the likeliest
  wrong value is a pasted secret. Archiver's own messages for every check below don't quote
  a value either. This is #276's `credentials_alias` check (`_alias_errors`,
  `src/core/rep_spec_schema/validator.py`), with the opposite quoting rule.
- **A plain value under a secret-bearing name is refused**, so the charter's rule (a frame
  carries a reference, never a secret) holds at the edge:
  - the exact names `authorization` and `cookie`;
  - any name containing `key`, `token`, `secret`, `auth`, `session`, `password` or
    `signature`.

  The message says to store the value as a credential instead.
- **Names co-core or the transport already give a meaning are refused in either kind:**
  - `if-none-match` and `if-modified-since` (Watcher's validators);
  - the names Replicator refuses as `invalid_request_options` (replicator
    `docs/contracts/content-fetch-issuer-reference.md`): the hop-by-hop `connection`,
    `keep-alive`, `te`, `trailer`, `transfer-encoding` and `upgrade`; the derived `host`
    and `content-length`; and any `proxy-*` name.
- **`user-agent` is a plain entry only.** co-core refuses it as a credential.
- **Grammar:** a name is an RFC 9110 token. A value has no CR, LF or NUL (co-core's C4
  guard).
- **Bounds.** Replicator refuses more than 32 headers, or more than 8,192 bytes of them,
  across both maps with the resolved credential values counted. Watcher adds up to three
  headers of its own (the UA and two validators), so a source's resolved policy is capped
  at 29 entries. That cap is checked at both levels' saves, against the resolved set. The
  byte total can't be checked: Archiver never sees a credential's value. Archiver checks
  the names and plain values against 8,192 bytes, and an overrun caused by a resolved
  value surfaces as `invalid_request_options`. The build re-reads both numbers from
  Replicator's contract and doesn't fork them.
- **A name may appear only once per level, compared case-insensitively.**

What a save can't check: whether Replicator has a binding for the reference, or whether that
binding names this host. Those failures close the fetch `credential_unknown` or
`credential_refused`, which Watcher reports as `health_reason` on `info.watch-status`, and
the item's health row shows it.

**References may ride a retained stream; values never do** (the charter, and the 2026-11-22
relay on #376). A `fetch-<role>` name in every hourly full set leaks nothing: only
Replicator's host can resolve it.

**Plain values are public-equivalent.** They ride `info.registry`, are retained, and are
repeated in every hourly full set, once per item. Every reader of that stream can see them,
which today means Watcher and the broker's admin role. Anything an operator wouldn't print
in a public doc belongs in a credential. The name refusal above is a heuristic net, not a
detector: a secret pasted under an innocuous name gets through (Known limits).

### D5. `render="browser"`

co-core refuses every header except `user-agent` under `browser`, plain ones and credentials
alike (correction 4). A rendered page sends its headers to every host it contacts. Archiver
doesn't store `render` yet (correction 3), so this rule is written against #379 and stays
dormant until #379 is built.

- **Resolution.** For a source that renders, the resolved plain map keeps only `user-agent`,
  and the credential map is empty. A Domain's other headers don't apply to that host's
  browser sources. A Domain UA does apply (it becomes the browser's UA), and it is a
  discontinuity like any other UA change.
- **An InfoSource save is refused** if a rendering source carries a credential entry or a
  plain entry other than `user-agent`. **#379's render save is refused** if it switches a
  source to `browser` while the source carries such entries. Each refusal names the other
  field.
- **A Domain save is never refused because the host has rendering sources.** Refusing it
  would block policy for every HTTP source on the host. The dashboard lists which of the
  host's sources the entries skip.
- The Emit-side refusal (the upstream ask) catches drift. Archiver's resolver never emits
  that combination.

### D6. Generations and announcement

- **`info.registry`:** a header edit is an ordinary announcement, and each item's generation
  is bumped atomically as it is today.
  - A Domain edit becomes an *announcing* write in `update_domain`. It locks the host's
    items, then takes the row `FOR UPDATE`, and announces only the items whose resolved maps
    moved. Adding `fetch_headers` to the columns an announcement reads does that.
  - An InfoSource edit fans out to every item the source actively backs, the spec-update
    path.
  - The hourly snapshot reads and resolves; it never bumps.
- **`content.fetch-policy`:** unchanged (D1). A header edit doesn't move
  `fetch_policy_generation`.

### D7. Bus versioning

The two fields are optional, `None` by default, and absent on a tombstone, so they're
additive and `schema_version` stays 1. That follows CLAUDE.md's rule and co-core's #272 and
#577 precedents. Both classes are `extra="ignore"`, so an older Watcher ignores the fields
and fetches with no policy, silently. For the same reason as co-core's MUSTs on `render` and
`credential_headers`, **Archiver doesn't populate them until Watcher announces support**.

## Sequence

1. This design merges (docs only; no deploy, no CHANGELOG entry).
2. **With the operator's consent**, the ask (Draft A) goes to cannobserv. co-core releases the
   fields.
3. **With the operator's consent**, the note (Draft B) goes to watcher#457. Watcher bumps,
   builds the merge, and announces support.
4. Archiver's build stays parked until a source needs headers **and** step 2 has shipped. It
   rides #454's catch-up to at least the carrier release (which is above v0.52.0, so
   `validate_fetch_credential` comes with it), and includes:
   - the migration;
   - `src/core/fetch_headers.py`;
   - the resolver, plus the `update_domain` and InfoSource fan-out;
   - the API (contract-visible: CHANGELOG and SDK regeneration) and the dashboard (the
     living docs);
   - populating the fields, gated on step 3's announcement.
5. The operator provisions the `fetch-<role>` bindings on Replicator's host. That's outside
   Archiver.

The build also changes these living docs, and none of them changes now:
- `docs/DOMAINS.md`: "Left open" and "The two policy fields";
- `docs/BUS.md`: `info.registry`;
- `docs/SCHEMA.md`: `info_sources`;
- `docs/API.md`;
- `docs/PAGES.md`;
- the `Domain` docstring.

## Draft A: the upstream ask on cannobserv (not posted; needs the operator's consent)

> **Title:** Add the fetch-header carrier to `RegistryAnnouncementState` (CannObserv/archiver#376)
>
> CannObserv/archiver#376's design chooses `info.registry` to carry fetch-header policy to
> Watcher, at both levels. Archiver resolves Domain < InfoSource per source and announces
> the result on each item. `FetchPolicyState` doesn't change. This is the field
> CannObserv/watcher#457's re-park trigger waits on. Design:
> archiver `docs/plans/2026-11-24-376-fetch-headers-design.md`.
>
> **Ask:** two optional fields on `RegistryAnnouncementState`, shaped like
> `ContentFetchCommand`'s pair so the consumer copies them across:
> - `fetch_headers: dict[str, str] | None`: header name to a plain, non-secret value.
> - `fetch_credential_headers: dict[str, str] | None`: header name to a `fetch-<role>`
>   reference, never a value (#577).
>
> **Semantics:**
> - Both fields are already resolved per header name, and the two maps are disjoint
>   case-insensitively.
> - `None`, absent and `{}` all mean "no policy": the consumer's behaviour today.
> - They're descriptive payload, so they're not required on a live announcement and are
>   absent on a tombstone (#324's rule).
> - They're additive, so `schema_version` stays 1.
>
> **The canonical class decodes any map, with no validator.** It's a no-DLQ config stream,
> and `watch_spec`'s rule applies: one malformed field must not quarantine the whole
> announcement and leave the key stale.
>
> **`RegistryAnnouncementEmit` refuses**, mirroring `ContentFetchCommandEmit`:
> - any credential under `render="browser"`, and any plain name but `user-agent` under it;
> - a reference that fails `validate_fetch_credential`;
> - one name twice within a map, or a name in both maps (case-insensitive);
> - `if-none-match` or `if-modified-since` in either map;
> - `user-agent` as a credential.
>
> **MUST, in the docstring:** the producer doesn't populate either field until the consumer
> announces support. An older consumer ignores them and fetches with no policy, and nothing
> fails. That's `render`'s MUST.
>
> **Archiver adopts** this field through archiver#454's catch-up, at the release that carries
> it.

## Draft B: the unpark note on watcher#457 (not posted; needs the operator's consent)

> **The carrier is chosen: `info.registry`** (CannObserv/archiver#376, design
> `docs/plans/2026-11-24-376-fetch-headers-design.md`). Your re-park trigger is met when the
> co-core release from cannobserv#<ask> ships `RegistryAnnouncementState.fetch_headers` and
> `.fetch_credential_headers`. Until then, nothing changes.
>
> **What changes from the merge you planned:** Archiver resolves Domain < InfoSource and
> announces one disjoint pair per source, so you merge one announced level, not two:
> 1. fetcher defaults < your pinned UA < the announced maps < your validators;
> 2. an announced `user-agent` replaces your pin, matched case-insensitively (an operator
>    types `User-Agent`; both spellings together are refused by `FetchContent`, #283). That's
>    the #376 body's exception, and
>    Archiver treats the change as a fingerprint discontinuity on its side;
> 3. copy `fetch_credential_headers` to `credential_headers` unchanged. Policy never names a
>    validator, and a name is never in both maps.
>
> **`render="browser"`:** Archiver announces only `user-agent` there, and no credentials.
> Archiver doesn't announce `render` until CannObserv/archiver#379 ships, so every source
> reads as `http` until then.
>
> **If `ContentFetchCommandEmit` refuses a merged set anyway**, the safe default is not to
> fetch without the credential (C3's reasoning) and to report it as `health_reason`. That's
> your call.
>
> **Archiver populates the fields only after you announce support** (D7).

## Known limits

- **The secret-name net is a heuristic.** A secret pasted as a plain value under an innocuous
  name is stored and published. The dashboard copy says so.
- **Save can't see Replicator's bindings.** A reference with no binding, or a binding that
  doesn't name this host, surfaces as `credential_unknown` or `credential_refused` on the
  item's health row, not at save.
- **A source can't remove a Domain header.** It can only override the header's value or
  kind. A per-source "omit" entry is a follow-up, if a source ever needs one.
- **The UA discontinuity is acknowledged and logged, not recorded durably** on the
  revision history. That's a follow-up, shared with #379.

- **Plain headers follow httpx on a redirect:** every header except `Authorization` goes to
  the next host, so a Domain-scoped plain header can reach another host. That's harmless
  only because plain values are public-equivalent (D4). Credentials are scoped per hop by
  Replicator (C2).

## Open questions

None block the design. The build decides three things:
- how populating the fields is gated on Watcher's support (D7). The build normally lands
  after that support is announced, which needs no gate. If it lands first, a unit-only flag
  is the `ARCHIVER_FETCH_POLICY_PRODUCER` precedent;
- whether the API's UA acknowledgement is a request field or a separate confirm route;
- whether the effective-headers view is on the source page, the Domain page, or both.
