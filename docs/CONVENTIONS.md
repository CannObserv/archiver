# archiver — Conventions Reference

The reasoning and worked examples behind the rules stated in `AGENTS.md`.

## Changelog trigger — what the path regex means

That is: deployed migrations, the HTTP API surface, the Pydantic
request/response models, and the SDK. Everything else — **dashboard UX
included** — needs no entry, along with internal refactors, test-only,
lint/tooling, and docs-only changes. A dashboard-only behaviour fix does
not get a changelog entry even though it is user-visible; the surface
that matters here is the contract, not the UI.

Tag each entry `[service]`, `[sdk]`, or `[both]` per the format header in
`CHANGELOG.md`. The SDK README links here; do not maintain a second
changelog there. On a PR, the `no-changelog` label opts out.

## Logging — plain-text `ExecStartPre` lines in journald

The app's own records — including uvicorn's access/error lines via `--log-config`
— are JSON. `ExecStartPre` steps in `deploy/archiver.service` (wheelhouse sync,
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
raise_envelope(409, "conflict", "duplicate URL",
               data={"existing_info_source_id": str(existing.id)},
               source_exc=e)

# Domain error with field-level code
raise_envelope(422, "domain", "info_item_id is not a valid ULID",
               errors=[FieldError(path="/info_item_id",
                                  message="not a valid ULID",
                                  code="invalid_ulid")],
               source_exc=e)
```

`kind` is one of: `body` (Pydantic body validation), `schema` (envelope/JSON-schema
validators), `domain` (typed core-tool errors, malformed ULIDs, target unreachable),
`lookup` (404), `conflict` (409), `auth` (401/403), `unimplemented` (501/405),
`server` (5xx).  Always pass `source_exc=e` from inside `except X as e:` blocks.

## Dashboard living docs — which doc a change requires

**Dashboard living docs:** each doc is scoped to what it actually documents —
update the one(s) the change touches, in the same commit. Failure to update an
applicable doc is a CR blocker.

- `docs/PAGES.md` — required for any change to a Jinja2 template in
  `src/dashboard/templates/`, or a new/changed dashboard route. It is the
  per-page inventory: what the screen renders, what the route returns.
- `docs/COMPONENTS.md` — required for any change to a JS module under
  `src/dashboard/static/` that adds or alters an Alpine component.
- `docs/UI.md` — required when the change alters a *shared* mechanic rather
  than one screen: the URL map, the auth gate, an HTMX swap pattern, or a
  detail-screen convention. A change that merely follows an existing
  convention updates PAGES.md alone.
- `docs/STYLE.md` — required when the change introduces or alters *styling*:
  `src/dashboard/static/dashboard.css`, or a template that adds a new visual
  pattern rather than reusing existing classes.

A template change that composes only existing CSS classes needs PAGES.md alone.

## Import placement — scope and exemptions

- No inline module imports; all at file top — `src/`, `tests/`, `scripts/`, and
  `alembic/` alike. Ruff `PLC0415` enforces this in CI (archiver#97); `if
  TYPE_CHECKING:` guards are module-level and pass. The vendored SDKs under
  `clients/` resolve their own `[tool.ruff]` config and are exempt — their
  generated code imports lazily to dodge circular imports.
