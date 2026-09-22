# archiver - Conventions Reference

The reasoning and worked examples behind the rules stated in `AGENTS.md`.

## Changelog trigger - what the path regex means

That is: deployed migrations, the HTTP API surface, the Pydantic
request/response models, and the SDK. Everything else - **dashboard UX
included** - needs no entry, along with internal refactors, test-only,
lint/tooling, and docs-only changes. A dashboard-only behaviour fix does
not get a changelog entry even though it is user-visible; the surface
that matters here is the contract, not the UI.

Tag each entry `[service]`, `[sdk]`, or `[both]` per the format header in
`CHANGELOG.md`. The SDK README links here; do not maintain a second
changelog there. On a PR, the `no-changelog` label opts out.

## Logging - plain-text `ExecStartPre` lines in journald

The app's own records - including uvicorn's access/error lines via `--log-config`
- are JSON. `ExecStartPre` steps in `deploy/archiver.service` (wheelhouse sync,
redis floor check) write **plain text** to journald by design: they run
outside the app process, before the Python logging config exists, so they
cannot use `build_json_formatter()`. A journald consumer that blindly `json.loads` every
`MESSAGE` must tolerate these lines (the failure-path `error: could not sync gs://…`
in particular); native field-based readers are unaffected. See archiver#124,
gregoryfoster/skills#83.

## Error envelope

**Error envelope:** Every non-2xx response uses one shape, defined by
`ErrorEnvelope` in `src/api/errors.py`:

```json
{"detail": {"kind": "lookup", "message": "...", "errors": [...], "data": {...}}}
```

Routes raise via `raise_envelope(status, kind, message, ...)` or `raise_422(...)`
(in `src/api/errors.py`), never via `HTTPException` directly. The global
exception handlers in `register_error_handlers(app)` wrap any FastAPI-raised
HTTPException (unmatched route 404, 405) or uncaught Exception (500) into the
envelope. See archiver#15.

**Except on `/dashboard`.** Those paths answer a browser, and JSON is unreadable
to one - htmx will not even swap it. `register_dashboard(app)` therefore
installs wrappers (`src/dashboard/errors.py`) that render HTML for a dashboard
path and delegate every other path back to the handlers above; the envelope is
unchanged for `/api/v1` and the SDK. Registration order is load-bearing, and the
whole mechanism is described in [UI.md](UI.md) § Failures are surfaced, not
swallowed (archiver#178).

Examples:

```python
from src.api.errors import FieldError, raise_422, raise_envelope

# Plain lookup
raise_envelope(404, "lookup", "InfoItem not found")

# Schema-validator translation (preserve cause for ruff B904)
try:
    spec = await create_rep_spec(session, ...)
except InvalidRepSpecError as e:
    raise_422("invalid rep_spec", errors=e.errors, source_exc=e)

# Conflict with structured payload
raise_envelope(
    409,
    "conflict",
    "duplicate URL",
    data={"existing_info_source_id": str(existing.id)},
    source_exc=e,
)

# Domain error with field-level code
raise_envelope(
    422,
    "domain",
    "info_item_id is not a valid ULID",
    errors=[FieldError(path="/info_item_id", message="not a valid ULID", code="invalid_ulid")],
    source_exc=e,
)
```

`kind` is one of: `body` (Pydantic body validation), `schema` (envelope/JSON-schema
validators), `domain` (typed core-tool errors, malformed ULIDs, target unreachable),
`lookup` (404), `conflict` (409), `auth` (401/403), `unimplemented` (501/405),
`server` (5xx).  Always pass `source_exc=e` from inside `except X as e:` blocks.

## Dashboard living docs - which doc a change requires

**Dashboard living docs:** each doc is scoped to what it actually documents -
update the one(s) the change touches, in the same commit. Failure to update an
applicable doc is a CR blocker.

- `docs/PAGES.md` - required for any change to a Jinja2 template in
  `src/dashboard/templates/`, or a new/changed dashboard route. It is the
  per-page inventory: what the screen renders, what the route returns.
- `docs/COMPONENTS.md` - required for any change to a JS module under
  `src/dashboard/static/`. Alpine components are catalogued there; a module
  that is not an Alpine component is documented where its behaviour lives
  instead, and a change to it updates that doc - `flash.js` in `docs/UI.md`
  ("Flash messages") and `docs/STYLE.md`, `dark-mode.js` in `docs/STYLE.md`.
- `docs/INFO_ITEM_DETAIL.md` - required when the change alters the InfoItem hub
  screen itself: its five sections, a partial's swap target, or one of the
  action-route contracts that moved there in archiver#176. PAGES.md keeps the
  inventory line for those routes, so a behaviour change updates both.
- `docs/HEALTH_ROW.md` and `docs/REGISTER.md` - required when the change alters
  the health row (a badge added or removed, its states, or the lag-probe bound),
  or the register wizard's summary bar or Step 3 controls. PAGES.md keeps only
  the inventory line for those routes: update it too when a route, or a form
  field it lists, is added, removed or renamed.
- `docs/UI.md` - required when the change alters a *shared* mechanic rather
  than one screen: the URL map, the auth gate, or an HTMX swap pattern.
  `docs/SCREENS.md` for a detail-screen convention. A change that merely follows an existing
  convention updates PAGES.md alone.
- `docs/STYLE.md` - required when the change introduces or alters *styling*:
  `src/dashboard/static/dashboard.css`, or a template that adds a new visual
  pattern rather than reusing existing classes.

A template change that composes only existing CSS classes needs PAGES.md alone.

## Re-syncing a `skills/` override

An override is *supposed* to differ from its vendor, so nothing is auto-merged
and no diff can police it. `.skills/doctor.sh` prints the procedure on every
run; the half it cannot enforce is the last step. Reapply the local deltas the
`override-reason:` names onto the **newer upstream text**, never the reverse,
then bump `version:` **and** `synced-from:` together - a `synced-from:` left
behind re-reports the drift just paid down. Diff the pre-merge copy afterwards
and account for every removed line: a presence check cannot see a local delta
the merge dropped.

All three overrides were re-synced in archiver#243 - `brainstorming` to
obra-superpowers v6.4.1, `shipping-work-python-fastapi` to 1.5,
`using-git-worktrees` to 1.1. The required-fragment half is gated by
`tests/scripts/test_skill_required_fragments.py`
([docs/SKILLS.md](SKILLS.md)); the rest is advisory and stays a hand merge.

## Script resolution in the cadence workflow

`.github/workflows/context-cadence.yml` is curating-context's installed cadence
job and runs four of that skill's scripts. It used to resolve one anchor -
`measure-context.sh` - and export the *directory* it was found in, which every
later step then joined a script name onto: a project `scripts/` holding that one
file sent the rest somewhere that lacked them (gregoryfoster/skills#301, carried
here by archiver#243). It now exports one path per script, under a name derived
from the script, so the list is the only thing to edit.

`tests/scripts/test_context_cadence.py` **extracts the step and runs it** under
`bash -e` against fixture projects - the ordinary case, the lone-project-copy
case, and a script found nowhere. Not an assertion over the YAML: a step can
export exactly the right variable names and resolve them wrongly, and only
running it tells the two apart.

The workflow's header lists the deltas archiver holds over the installer's
render, this one included. Re-rendering it is archiver#249.

## Import placement - scope and exemptions

- No inline module imports; all at file top - `src/`, `tests/`, `scripts/`, and
  `alembic/` alike. Ruff `PLC0415` enforces this in CI (archiver#97); `if
  TYPE_CHECKING:` guards are module-level and pass. The vendored SDKs under
  `clients/` resolve their own `[tool.ruff]` config and are exempt - their
  generated code imports lazily to dodge circular imports.

## Ruff's scope - what it reads, and what it must not

Since ruff 0.16 (archiver#242) `ruff format` also formats the `python` fences
inside `*.md`. Markdown is kept in scope - a sample in a live doc is worth
formatting - with two trees held out in the root `[tool.ruff] exclude`:

- `docs/plans/` - dated snapshots of what was proposed at the time, not
  maintained source. Reformatting their samples rewrites a record.

  **A date is not what decides this.** `CHANGELOG.md` entries are dated too and
  stay in scope: their samples are migration guidance someone runs today, so
  formatting them is maintenance. A plan's samples describe what was intended
  at the time, and editing them makes the record disagree with what shipped.
  Ask which of the two a document is before adding it here.
- `skills/` - overrides quoting vendor skill text, where keeping the two
  byte-comparable is what makes a re-sync merge (archiver#243) reviewable. It
  is also where a file-level symlink into `skills-vendor/` lives, and the main
  CI workflow checks out no submodules: ruff reading a link that dangles there
  is `io: No such file or directory` and a red build, no formatting opinion
  involved. `tests/scripts/test_ruff_config.py` re-derives that set of symlinks
  from `.gitmodules` rather than naming the one path, so the next vendored
  reference file cannot repeat it.

**A nested `[tool.ruff]` table governs everything beneath it.** The root
`exclude` never reached `clients/python/src/archiver_client/generated/`,
because `clients/python/pyproject.toml` carries its own table - which, having
no `select`, tracked ruff's *default* rule set and picked up 91 findings the
day those defaults widened. That config now selects its rules explicitly and
excludes the generated tree under `[tool.ruff.lint]` only: `ruff format` must
still reach it, because `clients/python/scripts/regen.sh` and the
`client-drift` gate both format it and diff the result against the committed
tree. A `lint.exclude` pattern filters per file rather than pruning the walk,
so the trailing `/**` is load-bearing.

The `rev:` in `.pre-commit-config.yaml` and the `ruff` pin in `pyproject.toml`
move together; a skew means the commit-time hook and CI disagree about what is
an error. The same test fails when they drift apart.
