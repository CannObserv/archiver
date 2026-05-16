# Cascade Contract + Algorithm-Family Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the "InfoItem = fetch group" invariant in docs (L1) and enforce content-kind compatibility across an InfoItem's bindings at bind time (L2). Resolves [archiver#22](https://github.com/CannObserv/archiver/issues/22).

**Architecture:** Two layers — (1) **L1 docs**: add a top-level `description` to `source_spec_schema/v1.json` stating the cascade contract, plus a "Fetch group" addendum to the Vocabulary section of `CLAUDE.md`. (2) **L2 app-layer enforcement**: a new `ALGORITHM_FAMILIES` constant in `source_spec_schema/`, plus an `AlgorithmFamilyMismatchError` raised from `bind_info_source` when a fragment's algorithm family disagrees with the InfoItem's active root's. Route translates the typed error to the standard envelope. No DB-layer changes, no migration.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Pydantic v2, pytest, ruff.

---

## Decisions pinned

These were debated up front; the plan implements them without re-litigating.

| Decision point | Resolution |
|---|---|
| Family taxonomy | `{css, xpath, regex, full_page}` → `"html_text"`; `{jsonpath}` → `"json"`. Verbatim from the issue. `regex` stays in `html_text` because the dominant production use is regex-against-HTML; revisit if a JSON regex use-case appears. `full_page` stays in `html_text` because the natural whole-document JSON extraction is `jsonpath: $`. Both judgments are called out in the CHANGELOG so they're not buried. |
| Where the family map lives | New module `src/core/source_spec_schema/families.py` — keeps the algorithm taxonomy co-located with the schema it describes. `bind_info_source.py` imports it. Avoids stuffing domain knowledge into the app-layer tool. |
| Atomic-create check | `POST /info-items` only accepts a single `initial_source_spec` which becomes the (root) primary. No fragment can be created in the same call, so no family check fires there today. Add a comment at the binding site noting the check would need to fire if initial fragments are ever supported. **Do not** add the check now (YAGNI). |
| SDK scope | No API signature changes; only a new error code in the envelope. OpenAPI response model is unchanged (ErrorEnvelope is opaque). Regenerating the SDK is a no-op. Service version bump 3.0.0 → 3.1.0; SDK pinned 1:1 → 3.1.0; CHANGELOG `[both]` but body says SDK code unchanged. |
| Where the check fires in `bind_info_source` | After `ActiveRootMissingError` + `FragmentParentMismatchError`. The active root's `source_spec` is already in scope (we just looked up the root binding's source_id); one extra `db.get(InfoSource)` covers it. Fragment-only — root bindings establish the family, so they bypass the check. |
| Error path | New typed exception `AlgorithmFamilyMismatchError(expected_family, actual_algorithm)`. Route translates to `raise_envelope(422, "domain", ..., errors=[FieldError(path="/extraction/algorithm", code="algorithm_family_mismatch", ...)])`. The path string matches what the issue's test expectations demand. |

---

## File structure

**Schema + family taxonomy:**
- Modify: [src/core/source_spec_schema/v1.json](src/core/source_spec_schema/v1.json) — add top-level `description`
- Create: `src/core/source_spec_schema/families.py` — `ALGORITHM_FAMILIES` dict + `family_for(algorithm)` helper
- Create: `tests/core/source_spec_schema/test_families.py`

**App-layer enforcement:**
- Modify: [src/core/tools/bind_info_source.py](src/core/tools/bind_info_source.py) — new `AlgorithmFamilyMismatchError` + check
- Modify: [tests/core/tools/test_bind_info_source.py](tests/core/tools/test_bind_info_source.py) — new fixtures + family-mismatch tests

**Route translation:**
- Modify: [src/api/routes/info_items.py](src/api/routes/info_items.py:264-317) — one more `except` clause
- Modify: [tests/api/test_add_info_source.py](tests/api/test_add_info_source.py) — HTTP-layer family-mismatch tests

**Docs:**
- Modify: [CLAUDE.md](CLAUDE.md) — Vocabulary section: "Fetch group" addendum on `InfoItem`
- Modify: [pyproject.toml](pyproject.toml) — version 3.0.0 → 3.1.0
- Modify: [clients/python/pyproject.toml](clients/python/pyproject.toml) — version 3.0.0 → 3.1.0
- Modify: [CHANGELOG.md](CHANGELOG.md) — new v3.1.0 `[both]` entry

---

## Tasks

### Task 1: Branch + baseline green

**Goal:** Start clean on a feature branch with a known-green baseline.

- [ ] **Step 1: Create feature branch off main**

```bash
git checkout main
git pull
git checkout -b feat/cascade-family-22
```

- [ ] **Step 2: Verify baseline test suite passes**

```bash
uv sync
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run alembic upgrade head
uv run pytest -x
```

Expected: all pass. If anything fails on `main`, **stop** and surface — don't conflate baseline flakes with feature regressions.

- [ ] **Step 3: Verify lint clean**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean.

---

### Task 2: Algorithm-families module — TDD

**Goal:** A small, well-tested mapping from algorithm string to content-kind family. This is the single source of truth for the L2 check.

**Files:**
- Create: `src/core/source_spec_schema/families.py`
- Create: `tests/core/source_spec_schema/test_families.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/source_spec_schema/test_families.py` (full file):

```python
"""Tests for the algorithm-family taxonomy."""

import pytest

from src.core.source_spec_schema.families import (
    ALGORITHM_FAMILIES,
    UnknownAlgorithmError,
    family_for,
)


def test_html_text_family_members():
    assert family_for("css") == "html_text"
    assert family_for("xpath") == "html_text"
    assert family_for("regex") == "html_text"
    assert family_for("full_page") == "html_text"


def test_json_family_member():
    assert family_for("jsonpath") == "json"


def test_unknown_algorithm_raises():
    with pytest.raises(UnknownAlgorithmError):
        family_for("xqilla")


def test_taxonomy_covers_every_algorithm_in_the_schema():
    """Every algorithm enumerated in v1.json must have a family.

    Guards against silent drift: adding a new algorithm to the JSON schema
    without classifying it here would make bind_info_source raise
    UnknownAlgorithmError on every fragment binding using it.
    """
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "src/core/source_spec_schema/v1.json").read_text()
    )
    schema_algorithms = set(schema["properties"]["extraction"]["properties"]["algorithm"]["enum"])
    assert schema_algorithms == set(ALGORITHM_FAMILIES.keys())
```

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/core/source_spec_schema/test_families.py -v
```

Expected: ImportError (module not yet created).

- [ ] **Step 3: Create the module**

`src/core/source_spec_schema/families.py`:

```python
"""Algorithm → content-kind family taxonomy.

Each extraction algorithm operates on a particular content kind. The Archiver
enforces that all InfoSources bound to a single InfoItem agree on the family,
because every fragment's extraction runs against the InfoItem's primary's
fetched bytes (the "InfoItem = fetch group" invariant; see
``src/core/source_spec_schema/v1.json`` description).
"""

from typing import Literal

Family = Literal["html_text", "json"]

ALGORITHM_FAMILIES: dict[str, Family] = {
    "css": "html_text",
    "xpath": "html_text",
    "regex": "html_text",
    "full_page": "html_text",
    "jsonpath": "json",
}


class UnknownAlgorithmError(Exception):
    """Algorithm string is not classified in ALGORITHM_FAMILIES.

    Should never happen for documents that pass schema validation — guarded
    by tests/core/source_spec_schema/test_families.py.
    """


def family_for(algorithm: str) -> Family:
    """Return the content-kind family for ``algorithm``.

    Raises ``UnknownAlgorithmError`` if ``algorithm`` is not in the taxonomy.
    """
    try:
        return ALGORITHM_FAMILIES[algorithm]
    except KeyError as e:
        raise UnknownAlgorithmError(algorithm) from e
```

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/core/source_spec_schema/test_families.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/source_spec_schema/families.py tests/core/source_spec_schema/test_families.py
git commit -m "#22 feat(schema): algorithm → content-kind family taxonomy"
```

---

### Task 3: Schema-level cascade contract (L1) — TDD

**Goal:** Add a top-level `description` to v1.json that states the cascade contract. Verifies the JSON is still loadable + the existing validator behavior is unchanged.

**Files:**
- Modify: [src/core/source_spec_schema/v1.json](src/core/source_spec_schema/v1.json)
- Create: `tests/core/source_spec_schema/test_schema_description.py`

- [ ] **Step 1: Write the failing test**

`tests/core/source_spec_schema/test_schema_description.py` (full file):

```python
"""The v1 SourceSpec schema declares the cascade contract at the top level."""

import json
from pathlib import Path

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "src/core/source_spec_schema/v1.json").read_text()
)


def test_top_level_description_states_cascade_contract():
    desc = SCHEMA.get("description", "")
    # Must explicitly call out the fetch-group invariant and the
    # "no chaining" rule. The wording can drift, but these keywords
    # are what authoring agents will grep for.
    assert "fetch group" in desc.lower()
    assert "primary" in desc.lower()
    assert "no chaining" in desc.lower() or "not chained" in desc.lower()


def test_existing_extraction_validation_still_works():
    """Top-level description must not break existing schema validation."""
    from src.core.source_spec_schema.validator import validate_source_spec

    ok, errs = validate_source_spec({
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    })
    assert ok, errs
```

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/core/source_spec_schema/test_schema_description.py -v
```

Expected: `test_top_level_description_states_cascade_contract` fails (no `description` field present yet).

- [ ] **Step 3: Add the description to v1.json**

Open `src/core/source_spec_schema/v1.json` and insert a `description` field right after `"title"` (line 5). The file should start with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://watcher.exe.xyz/schemas/source-spec/v1.json",
  "title": "Source Specification v1",
  "description": "Defines how to fetch and extract a slice of content. An InfoItem is a fetch group: exactly one URL is fetched (the primary's URL) and exactly one content-kind is produced (HTML or JSON). Every InfoSource bound to the InfoItem — primary, cross_check, sub_aspect — has its extraction.algorithm evaluated against the primary's fetched bytes. Fragment extractions are NOT chained off primary's extracted output. Consequently, all bindings on an InfoItem must use algorithms in the same content-kind family (HTML/text: css|xpath|regex|full_page; JSON: jsonpath); the Archiver rejects mixed-family bindings at bind time.",
  "type": "object",
  ...
}
```

(Keep every other field intact. Only the `description` line is new.)

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/core/source_spec_schema/test_schema_description.py -v
uv run pytest tests/core/source_spec_schema/ -v   # nothing else broke
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/source_spec_schema/v1.json tests/core/source_spec_schema/test_schema_description.py
git commit -m "#22 docs(schema): top-level description states cascade contract"
```

---

### Task 4: Extend `bind_info_source` with family check — TDD

**Goal:** Add `AlgorithmFamilyMismatchError` and the check that fires after the existing fragment-shape / fragment-shares-root validations.

**Files:**
- Modify: [src/core/tools/bind_info_source.py](src/core/tools/bind_info_source.py)
- Modify: [tests/core/tools/test_bind_info_source.py](tests/core/tools/test_bind_info_source.py)

- [ ] **Step 1: Add fixtures + failing tests**

Open `tests/core/tools/test_bind_info_source.py`. Add at the top of the file (after the existing `_root_doc` / `_fragment_doc` helpers, line ~31):

```python
def _root_json_doc(url: str) -> dict:
    """Root doc using jsonpath — establishes a JSON-family primary."""
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "jsonpath", "selector": "$"},
        "fingerprint": {},
    }


def _fragment_jsonpath_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "jsonpath", "selector": "$.items[*]"},
        "fingerprint": {},
    }
```

Then add these fixtures alongside the existing `root_src` / `frag_of_root` fixtures (after line ~80):

```python
@pytest.fixture
async def root_src_json(session):
    """Root InfoSource whose primary algorithm is jsonpath (JSON family)."""
    src = InfoSource(source_spec=_root_json_doc("https://example.com/api"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def frag_css_of_root(session, root_src):
    """Fragment under HTML-family root, using css — same family, should bind."""
    frag = InfoSource(
        source_spec=_fragment_doc(),  # algorithm=css
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_jsonpath_of_html_root(session, root_src):
    """Fragment under HTML-family root, using jsonpath — CROSS-FAMILY, must reject."""
    frag = InfoSource(
        source_spec=_fragment_jsonpath_doc(),
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_css_of_json_root(session, root_src_json):
    """Fragment under JSON-family root, using css — CROSS-FAMILY, must reject."""
    frag = InfoSource(
        source_spec=_fragment_doc(),  # algorithm=css
        schema_version=1,
        parent_info_source_id=root_src_json.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_jsonpath_of_json_root(session, root_src_json):
    """Fragment under JSON-family root, using jsonpath — same family, should bind."""
    frag = InfoSource(
        source_spec=_fragment_jsonpath_doc(),
        schema_version=1,
        parent_info_source_id=root_src_json.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag
```

Add `AlgorithmFamilyMismatchError` to the import at the top of the file:

```python
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    AlgorithmFamilyMismatchError,
    FragmentParentMismatchError,
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    RoleShapeMismatchError,
    bind_info_source,
)
```

Then append the new tests at the bottom of the file:

```python
# --- algorithm-family compatibility (issue #22) ---


@pytest.mark.asyncio
async def test_same_family_fragment_html_html_accepted(session, item, root_src, frag_css_of_root):
    """css fragment under full_page primary — both html_text, should bind."""
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_css_of_root.info_source_id,
        role="cross_check",
    )
    assert binding.role == "cross_check"


@pytest.mark.asyncio
async def test_same_family_fragment_json_json_accepted(
    session, item, root_src_json, frag_jsonpath_of_json_root
):
    """jsonpath fragment under jsonpath primary — both json, should bind."""
    await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=root_src_json.info_source_id,
        role=None,
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_jsonpath_of_json_root.info_source_id,
        role="sub_aspect",
    )
    assert binding.role == "sub_aspect"


@pytest.mark.asyncio
async def test_cross_family_jsonpath_under_html_rejected(
    session, item, root_src, frag_jsonpath_of_html_root
):
    """jsonpath fragment under full_page (html_text) primary — must reject."""
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(AlgorithmFamilyMismatchError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_jsonpath_of_html_root.info_source_id,
            role="cross_check",
        )
    assert exc_info.value.expected_family == "html_text"
    assert exc_info.value.actual_algorithm == "jsonpath"


@pytest.mark.asyncio
async def test_cross_family_css_under_jsonpath_rejected(
    session, item, root_src_json, frag_css_of_json_root
):
    """css fragment under jsonpath primary — must reject (the other direction)."""
    await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=root_src_json.info_source_id,
        role=None,
    )
    with pytest.raises(AlgorithmFamilyMismatchError) as exc_info:
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_css_of_json_root.info_source_id,
            role="cross_check",
        )
    assert exc_info.value.expected_family == "json"
    assert exc_info.value.actual_algorithm == "css"
```

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/core/tools/test_bind_info_source.py -v
```

Expected: ImportError on `AlgorithmFamilyMismatchError`.

- [ ] **Step 3: Extend the tool**

Open `src/core/tools/bind_info_source.py`. Add the import alongside the existing ones at the top:

```python
from src.core.source_spec_schema.families import Family, family_for
```

Add the new exception class alongside the others (after `FragmentParentMismatchError`, before `bind_info_source`):

```python
class AlgorithmFamilyMismatchError(Exception):
    """Fragment's extraction algorithm belongs to a different content-kind
    family than the InfoItem's active root binding's algorithm.

    Every fragment's extraction runs against the root's fetched bytes (the
    "InfoItem = fetch group" invariant; see
    ``src/core/source_spec_schema/v1.json`` description). A jsonpath
    selector evaluated against HTML bytes silently misextracts, and
    vice-versa — hence the bind-time rejection.
    """

    def __init__(self, *, expected_family: Family, actual_algorithm: str):
        self.expected_family = expected_family
        self.actual_algorithm = actual_algorithm
        super().__init__(
            f"fragment algorithm {actual_algorithm!r} does not match the "
            f"InfoItem's primary algorithm family {expected_family!r}"
        )
```

Replace the `bind_info_source` body's fragment branch (the `if not source_is_root:` block, line ~79) with:

```python
    # 2. Fragment-shares-root: fragment's parent must equal the InfoItem's
    # currently-active NULL-role binding's info_source_id.
    if not source_is_root:
        active_root = (
            await db.execute(
                select(InfoSource)
                .join(
                    InfoItemSource,
                    InfoItemSource.info_source_id == InfoSource.info_source_id,
                )
                .where(
                    InfoItemSource.info_item_id == info_item_id,
                    InfoItemSource.role.is_(None),
                    InfoItemSource.deactivated_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active_root is None:
            raise ActiveRootMissingError(str(info_item_id))
        if active_root.info_source_id != source.parent_info_source_id:
            raise FragmentParentMismatchError(
                expected_root_id=active_root.info_source_id,
                actual_parent_id=source.parent_info_source_id,
            )

        # 3. Algorithm-family compatibility (archiver#22). The active root's
        # algorithm establishes the fetch group's content kind; this fragment
        # must agree.
        expected_family = family_for(active_root.source_spec["extraction"]["algorithm"])
        actual_algorithm = source.source_spec["extraction"]["algorithm"]
        if family_for(actual_algorithm) != expected_family:
            raise AlgorithmFamilyMismatchError(
                expected_family=expected_family,
                actual_algorithm=actual_algorithm,
            )
```

(The change replaces the `db.scalar(...)` lookup of just the id with a full `InfoSource` row fetch so we can read its `source_spec` for the algorithm. The downstream check that compares against `source.parent_info_source_id` now uses `active_root.info_source_id`.)

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/core/tools/test_bind_info_source.py -v
```

Expected: all PASS (existing tests + four new family tests).

- [ ] **Step 5: Commit**

```bash
git add src/core/tools/bind_info_source.py tests/core/tools/test_bind_info_source.py
git commit -m "#22 feat(tools): reject cross-family algorithm bindings in bind_info_source"
```

---

### Task 5: Route translation for the family-mismatch error — TDD

**Goal:** Translate `AlgorithmFamilyMismatchError` to a `422 domain` envelope with `code="algorithm_family_mismatch"` and a `/extraction/algorithm` path, matching the issue's test plan.

**Files:**
- Modify: [src/api/routes/info_items.py](src/api/routes/info_items.py)
- Modify: [tests/api/test_add_info_source.py](tests/api/test_add_info_source.py)

- [ ] **Step 1: Add failing HTTP-layer tests**

Open `tests/api/test_add_info_source.py`. Add this helper after `_fragment_doc` (line ~34):

```python
def _root_json_doc(url: str) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "jsonpath", "selector": "$"},
        "fingerprint": {},
    }


def _fragment_jsonpath_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "jsonpath", "selector": "$.items[*]"},
        "fingerprint": {},
    }
```

Update `_make_source` to accept an optional `doc` override:

```python
async def _make_source(session, *, url=None, parent_id=None, doc=None):
    if doc is not None:
        src = InfoSource(
            source_spec=doc,
            schema_version=1,
            parent_info_source_id=parent_id,
        )
    elif url is not None:
        src = InfoSource(source_spec=_root_doc(url), schema_version=1)
    else:
        src = InfoSource(
            source_spec=_fragment_doc(),
            schema_version=1,
            parent_info_source_id=parent_id,
        )
    session.add(src)
    await session.flush()
    return src
```

Append the new HTTP-level tests at the bottom of the file:

```python
@pytest.mark.asyncio
async def test_cross_family_jsonpath_under_html_returns_422_domain(client, session, item):
    """jsonpath fragment under full_page (html_text) primary → 422 domain."""
    root = await _make_source(session, url="https://example.com/a")  # full_page
    frag = await _make_source(
        session, parent_id=root.info_source_id, doc=_fragment_jsonpath_doc()
    )
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "cross_check"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    err = detail["errors"][0]
    assert err["code"] == "algorithm_family_mismatch"
    assert err["path"] == "/extraction/algorithm"
    # Structured data lets clients render a useful message
    assert detail["data"]["expected_family"] == "html_text"
    assert detail["data"]["actual_algorithm"] == "jsonpath"


@pytest.mark.asyncio
async def test_cross_family_css_under_jsonpath_returns_422_domain(client, session, item):
    """css fragment under jsonpath primary → 422 domain (other direction)."""
    root = await _make_source(
        session, doc=_root_json_doc("https://example.com/api"), url=None
    )
    # _make_source above takes either url or doc; doc-only path here:
    # adjust if your call shape differs.
    frag = await _make_source(session, parent_id=root.info_source_id)  # css default
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "sub_aspect"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    err = detail["errors"][0]
    assert err["code"] == "algorithm_family_mismatch"
    assert err["path"] == "/extraction/algorithm"
    assert detail["data"]["expected_family"] == "json"
    assert detail["data"]["actual_algorithm"] == "css"


@pytest.mark.asyncio
async def test_same_family_fragment_still_binds_201(client, session, item):
    """xpath fragment under full_page primary — both html_text → 201."""
    root = await _make_source(session, url="https://example.com/a")  # full_page
    xpath_doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "xpath", "selector": "//div[@id='agenda']"},
        "fingerprint": {},
    }
    frag = await _make_source(session, parent_id=root.info_source_id, doc=xpath_doc)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "cross_check"},
    )
    assert resp.status_code == 201
```

(The second test's call to `_make_source(... url=None, doc=...)` works because `doc` takes priority in the helper; if you prefer cleanness, refactor the helper to remove the `url=None` argument when `doc` is provided.)

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/api/test_add_info_source.py -v
```

Expected: the three new tests fail — first two get a 201 (no rejection yet), or fail with a key error on `data["expected_family"]` because the route doesn't translate the new error.

- [ ] **Step 3: Wire the route translation**

In `src/api/routes/info_items.py`:

1. Extend the `bind_info_source` import (around line 47–58):

```python
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    AlgorithmFamilyMismatchError,
    FragmentParentMismatchError,
    RoleShapeMismatchError,
    bind_info_source,
)
```

2. In `add_info_source` (around line 264–317), append one more `except` clause after `FragmentParentMismatchError`:

```python
    except AlgorithmFamilyMismatchError as e:
        raise_envelope(
            422,
            "domain",
            "fragment algorithm does not match the InfoItem's primary algorithm family",
            errors=[
                FieldError(
                    path="/extraction/algorithm",
                    message=(
                        f"algorithm {e.actual_algorithm!r} is in a different "
                        f"content-kind family than the primary ({e.expected_family!r})"
                    ),
                    code="algorithm_family_mismatch",
                )
            ],
            data={
                "expected_family": e.expected_family,
                "actual_algorithm": e.actual_algorithm,
            },
            source_exc=e,
        )
```

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/api/test_add_info_source.py -v
```

Expected: all PASS (including the existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/info_items.py tests/api/test_add_info_source.py
git commit -m "#22 refactor(api): translate AlgorithmFamilyMismatchError to 422 domain envelope"
```

---

### Task 6: Atomic-create comment (no code change)

**Goal:** Anchor a one-line note at the atomic-create binding site so a future contributor adding "initial fragment specs" support knows to add the family check.

**Files:**
- Modify: [src/api/routes/info_items.py:148-156](src/api/routes/info_items.py#L148-L156)

- [ ] **Step 1: Add the comment**

In `src/api/routes/info_items.py` around line 148, before `if info_source is not None:`, add:

```python
    # Atomic-create only supports a single initial_source_spec (becomes the
    # NULL-role / root binding). If initial fragment specs are added later,
    # they must run through bind_info_source for the family-compatibility
    # check (archiver#22).
```

- [ ] **Step 2: Lint + commit**

```bash
uv run ruff check src/api/routes/info_items.py
git add src/api/routes/info_items.py
git commit -m "#22 docs(api): note family check required if initial fragments are added"
```

(Skip if Step 1 left no actual diff because the comment already exists.)

---

### Task 7: CLAUDE.md vocabulary — Fetch group invariant (L1)

**Goal:** Make the invariant easy to discover when reading `CLAUDE.md`.

**Files:**
- Modify: [CLAUDE.md](CLAUDE.md)

- [ ] **Step 1: Add the invariant to the InfoItem entry**

Find the line in CLAUDE.md's Vocabulary section starting with `- **`InfoItem`** (`info_items`)` and replace it with:

```markdown
- **`InfoItem`** (`info_items`) — semantic anchor; carries domain meaning + `rep_fields` JSONB bag.
  **Fetch group invariant:** exactly one URL is fetched (the primary's URL) and exactly one
  content-kind is produced (HTML/text or JSON). Every InfoSource bound to this InfoItem —
  primary, cross_check, sub_aspect — has its `extraction.algorithm` run against the primary's
  fetched bytes (no chaining off primary's extracted output). The Archiver enforces this at
  bind time by rejecting cross-family algorithm bindings (`{css,xpath,regex,full_page}` ≠
  `{jsonpath}`); see `src/core/source_spec_schema/families.py` and
  `src/core/tools/bind_info_source.py::AlgorithmFamilyMismatchError`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "#22 docs: fetch group invariant on InfoItem in CLAUDE.md Vocabulary"
```

---

### Task 8: Full test sweep + lint

**Goal:** Catch any regressions in adjacent tests + fix formatting drift.

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean. If `ruff format --check` fails, run `uv run ruff format .` and commit the diff.

- [ ] **Step 3: (If needed) commit any format fixes**

```bash
git add -p
git commit -m "#22 chore: ruff format"
```

---

### Task 9: Version bump + CHANGELOG

**Files:**
- Modify: [pyproject.toml](pyproject.toml)
- Modify: [clients/python/pyproject.toml](clients/python/pyproject.toml)
- Modify: [CHANGELOG.md](CHANGELOG.md)

- [ ] **Step 1: Bump versions**

`pyproject.toml` — change `version = "3.0.0"` to `version = "3.1.0"`.

`clients/python/pyproject.toml` — change `version = "3.0.0"` to `version = "3.1.0"`.

- [ ] **Step 2: Prepend CHANGELOG entry**

Insert directly below the format header, above `## v3.0.0`:

```markdown
## v3.1.0 (2026-05-16)

[both] **Behaviour change** — cross-family extraction algorithm bindings
are now rejected at bind time (archiver#22). The Archiver codifies the
"InfoItem = fetch group" invariant: every InfoSource bound to an InfoItem
(primary, cross_check, sub_aspect) has its `extraction.algorithm`
evaluated against the primary's fetched bytes — no chaining off primary's
extracted output. Mixed content-kind families silently misextract and are
now rejected.

**Content-kind families:**
- `html_text` — `css`, `xpath`, `regex`, `full_page`
- `json` — `jsonpath`

`regex` lives in `html_text` because the dominant production use is
regex-against-HTML; `full_page` lives in `html_text` because the natural
whole-document JSON extraction is `jsonpath: $`. Both are revisitable if
new use-cases emerge.

**Wire-format:** A cross-family bind attempt now returns `422 domain`
with `errors[0].code = "algorithm_family_mismatch"`,
`errors[0].path = "/extraction/algorithm"`, and structured
`data = {"expected_family": "...", "actual_algorithm": "..."}` so clients
can render a useful message without parsing the human-readable string.

**Docs (L1):**
- `src/core/source_spec_schema/v1.json` declares the cascade contract at
  the top level in its `description`.
- `CLAUDE.md` Vocabulary section anchors the fetch group invariant on
  `InfoItem` and points at the enforcement modules.

**SDK:** No code changes. OpenAPI response model is unchanged (errors
flow through the existing `ErrorEnvelope`). Version is bumped 1:1 with
the service per the pinning policy; no regen required.

See archiver#22 and watcher's InfoItem-first design
(`CannObserv/watcher/docs/plans/2026-05-15-watched-item-infoitem-first-design.md`)
for the downstream consumer (selector-rot detection).
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml clients/python/pyproject.toml CHANGELOG.md
git commit -m "#22 docs: bump to 3.1.0; CHANGELOG entry"
```

---

### Task 10: End-to-end smoke + push + PR

**Goal:** Confirm the dev server boots, the v2 authoring loop still works, and the new validator path returns the expected envelope shape.

- [ ] **Step 1: Restart any running dev server**

```bash
pkill -f "uvicorn.*8021" || true
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8021 --reload &
sleep 2
curl -fsS http://localhost:8021/health
```

Expected: `{"status":"ok"}` (or equivalent).

- [ ] **Step 2: Run the Phase 4 smoke**

```bash
bash scripts/smoke_phase4.sh
```

Expected: all steps pass. Step 9 (Redis stream check) is skipped unless `ARCHIVER_REDIS_URL` is set — that's fine.

- [ ] **Step 3: Manually exercise the new rejection path**

```bash
# (Requires ARCHIVER_API_KEY in env; the smoke script left a primary
# InfoItem behind. Replace IDs with values from that run.)
curl -fsS -X POST http://localhost:8021/api/v1/info-items/<ITEM>/info-sources \
  -H "X-API-Key: $ARCHIVER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"info_source_id": "<JSON_FRAG_UNDER_HTML_ROOT>", "role": "cross_check"}' \
  | python -m json.tool
```

Expected: `{"detail": {"kind": "domain", "errors": [{"code": "algorithm_family_mismatch", ...}], "data": {"expected_family": "html_text", "actual_algorithm": "jsonpath"}, ...}}`.

(Skip this step if setting up the fixture data via curl is too fiddly; the HTTP-layer tests in Task 5 already cover this path.)

- [ ] **Step 4: Final full sweep**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: all green.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin feat/cascade-family-22
gh pr create --title "#22 feat: codify cascade contract + enforce algorithm-family compatibility" --body "$(cat <<'EOF'
## Summary

- Closes #22.
- **L1 docs**: top-level `description` in `source_spec_schema/v1.json` states the "InfoItem = fetch group" invariant; `CLAUDE.md` Vocabulary anchors it on `InfoItem` with a pointer to the enforcement.
- **L2 enforcement**: new `src/core/source_spec_schema/families.py` classifies algorithms (`html_text` vs `json`); `bind_info_source` raises `AlgorithmFamilyMismatchError` when a fragment's family disagrees with the InfoItem's active root; route translates to a `422 domain` envelope with `code=algorithm_family_mismatch`.
- No DB or migration changes; pure app-layer + docs.
- Service + SDK bumped 3.0.0 → 3.1.0 (SDK code unchanged; pinned 1:1).

## Test plan

- [ ] `uv run pytest` is green locally.
- [ ] `bash scripts/smoke_phase4.sh` passes against `:8021`.
- [ ] Manually verified the new rejection envelope shape against the dev server.
- [ ] Watcher selector-rot work can now rely on cross-family rejection (see CannObserv/watcher's InfoItem-first design).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Out of scope (defer to follow-up issues)

These were considered and explicitly deferred. Don't bundle into this PR.

1. **L3 — explicit `content_kind` column on `info_sources`.** Per the issue's "Not in scope" section. Derivable from algorithm; YAGNI today. Revisit if algorithm taxonomy grows past the simple two-family split.
2. **Deactivation-time policy for active root bindings with active fragments.** Inherited deferral from archiver#21 (no deactivate endpoint for `info_item_sources` exists today). File when the deactivate endpoint is added.
3. **Family check at atomic-create time.** Only relevant if `POST /info-items` ever accepts `initial_fragment_specs` plus an `initial_source_spec`. Comment in the route notes this; no code today.
4. **Watcher's selector-rot detection.** Unblocked by this PR but lives in the watcher repo and ships under its own version cadence.
