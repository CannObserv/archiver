# Phase 4 — Archiver v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut Archiver over from the Phase 1–3a `InfoItem ↔ InfoSpec` model to the v2 central-registry model defined in `docs/plans/2026-05-08-archiver-v2-architecture-design.md`. End state: all v2 entities creatable via SDK, change-bus events firing through Archiver's outbox, regenerated `archiver-client` v1.0, smoke test passes end-to-end.

**Architecture:** Pre-production greenfield cutover (no compat shim). Drop `info_specs`; introduce seven new tables with effective-dated joins. SourceSpec splits root vs. fragment for page-once cascade. SHA-256 fingerprints. Outbox-pattern change-bus publisher in Archiver. Authoring tools expanded for `rep_specs`, `rep_fields`, assignments. SDK regenerated to v1.0; old `info_spec` methods removed.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Alembic, Postgres (`information` schema), Pydantic, jsonschema, Redis Streams (via `redis.asyncio`), pytest + fakeredis, openapi-python-client, ULIDs, uv.

**Tracking issue:** [#7](https://github.com/CannObserv/archiver/issues/7)

**Source design:** `docs/plans/2026-05-08-archiver-v2-architecture-design.md` (Sections 2 + 3 are the authoritative reference for schema, protocols, and exit criteria).

**Worktree:** `.worktrees/phase-4-archiver-v2/` on branch `phase-4-archiver-v2`. Dev server runs on port 8021 (already started by the worktree skill).

---

## Sub-phase structure

```
4a — Schema cutover + ORM models      (10 tasks; foundation)
4b — JSON schemas + validators + authoring tools   (12 tasks; depends on 4a)
4c — Source-revision write path + change-bus publisher    (8 tasks; depends on 4a)
4d — SDK regen + smoke test           (5 tasks; depends on 4a + 4b + 4c)
```

Sub-phases 4b and 4c can run in parallel after 4a. 4d is the final integration gate.

Each task ends with a commit. Commit messages follow `#7 <type>: <description>` per CLAUDE.md.

---

## Sub-phase 4a — Schema cutover + ORM models

**Exit criteria:** all v2 tables present in the `information` schema; ORM models import cleanly; per-model unit tests pass; `uv run alembic upgrade head` round-trips against `TEST_DATABASE_URL`.

---

### Task A1: Drop `information.info_specs`

**Files:**
- Create: `alembic/versions/<hash>_drop_info_specs.py`
- Delete (Task A10 — keep imports until then): nothing yet
- Test: `tests/core/models/test_info_spec.py` — DELETE in Task A10 once nothing imports it

- [ ] **Step 1: Generate empty migration**

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run alembic revision -m "drop info_specs"
```

- [ ] **Step 2: Edit migration to drop the table**

```python
def upgrade() -> None:
    op.drop_table("info_specs", schema="information")

def downgrade() -> None:
    raise NotImplementedError("Phase 4 cutover is one-way; restore from prior migration if needed")
```

- [ ] **Step 3: Run upgrade**

```bash
uv run alembic upgrade head
```

Expected: clean upgrade, no error.

- [ ] **Step 4: Verify table is gone**

```bash
psql "$ARCHIVER_DATABASE_URL" -c "\dt information.*" | grep info_specs
```

Expected: no match.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "#7 chore: drop info_specs (v2 cutover)"
```

---

### Task A2: Add `rep_fields` JSONB column to `info_items`

**Files:**
- Modify: `src/core/models/info_item.py`
- Modify: `tests/core/models/test_info_item.py`
- Create: `alembic/versions/<hash>_add_rep_fields_to_info_items.py`

- [ ] **Step 1: Write the failing test**

In `tests/core/models/test_info_item.py`, add:

```python
def test_info_item_has_rep_fields_default_empty(db_session):
    item = InfoItem(name="t")
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    assert item.rep_fields == {}

def test_info_item_rep_fields_round_trips_nested_json(db_session):
    item = InfoItem(name="t", rep_fields={"org": {"acronym": "wslcb"}})
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    assert item.rep_fields == {"org": {"acronym": "wslcb"}}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/models/test_info_item.py -v -k rep_fields
```

Expected: FAIL with `AttributeError: 'InfoItem' object has no attribute 'rep_fields'`.

- [ ] **Step 3: Add column to model**

In `src/core/models/info_item.py`, add the import and column:

```python
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# inside class InfoItem:
    rep_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
```

- [ ] **Step 4: Generate and apply migration**

```bash
uv run alembic revision --autogenerate -m "add rep_fields to info_items"
uv run alembic upgrade head
```

Verify the generated migration adds the column with `server_default="{}"`.

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/core/models/test_info_item.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core/models/info_item.py tests/core/models/test_info_item.py alembic/versions/
git commit -m "#7 feat: add rep_fields JSONB column to info_items"
```

---

### Task A3: URL canonicalization helper

**Files:**
- Create: `src/core/url_canonicalization.py`
- Create: `tests/core/test_url_canonicalization.py`

The helper canonicalizes URLs at write time before they're stored or used as the `info_sources.url` generated-column value.

Rules (from design doc Section 2):
- Strip `#fragment`.
- Lowercase scheme + host.
- Normalize percent-encoding.
- Trim duplicate trailing slashes (single trailing `/` allowed for root paths).
- Optional per-Source override via `target.url_canonicalization.strip_query_keys` (list of query-string keys to drop, e.g., `utm_source`).

- [ ] **Step 1: Write failing tests**

In `tests/core/test_url_canonicalization.py`:

```python
import pytest

from src.core.url_canonicalization import canonicalize_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://Example.COM/path#frag", "https://example.com/path"),
        ("HTTPS://example.com/", "https://example.com/"),
        ("https://example.com/path?b=2&a=1", "https://example.com/path?b=2&a=1"),
        ("https://example.com/p%2Fath", "https://example.com/p%2Fath"),
        ("https://example.com//double//slash", "https://example.com/double/slash"),
    ],
)
def test_canonicalize_basic(raw, expected):
    assert canonicalize_url(raw) == expected


def test_strip_query_keys():
    raw = "https://example.com/p?utm_source=x&id=42&utm_medium=y"
    out = canonicalize_url(raw, strip_query_keys=["utm_source", "utm_medium"])
    assert out == "https://example.com/p?id=42"


def test_strip_query_keys_preserves_order():
    raw = "https://example.com/p?b=2&utm_x=z&a=1"
    out = canonicalize_url(raw, strip_query_keys=["utm_x"])
    assert out == "https://example.com/p?b=2&a=1"


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        canonicalize_url("not a url")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/test_url_canonicalization.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement helper**

In `src/core/url_canonicalization.py`:

```python
"""URL canonicalization for InfoSource.url storage and lookup.

Applied at write time before persisting to info_sources. Keeps the UNIQUE(url)
constraint coherent and prevents duplicate sources for cosmetically-different URLs.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def canonicalize_url(url: str, *, strip_query_keys: list[str] | None = None) -> str:
    """Return canonical form of `url`.

    - Strips #fragment.
    - Lowercases scheme + host.
    - Collapses duplicate path slashes (preserves single trailing slash).
    - Optionally drops query-string keys named in strip_query_keys.

    Raises ValueError on a URL with no scheme or host.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"URL must have scheme and host: {url!r}")

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    # collapse duplicate slashes in path (keep single trailing slash if present)
    path_segments = [seg for seg in parts.path.split("/") if seg != ""]
    canonical_path = "/" + "/".join(path_segments)
    if parts.path.endswith("/") and canonical_path != "/":
        canonical_path += "/"

    query = parts.query
    if strip_query_keys:
        keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k not in strip_query_keys]
        query = urlencode(keep)

    return urlunsplit((scheme, netloc, canonical_path, query, ""))
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/core/test_url_canonicalization.py -v
```

Expected: PASS (all parameterized cases + edge tests).

- [ ] **Step 5: Commit**

```bash
git add src/core/url_canonicalization.py tests/core/test_url_canonicalization.py
git commit -m "#7 feat: add URL canonicalization helper for info_sources"
```

---

### Task A4: Create `info_sources` model + migration + tests

**Files:**
- Create: `src/core/models/info_source.py`
- Create: `tests/core/models/test_info_source.py`
- Create: `alembic/versions/<hash>_create_info_sources.py`

Schema reference: design doc Section 2 (`information.info_sources`).

- [ ] **Step 1: Write failing tests**

```python
"""InfoSource model tests."""

import pytest
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from src.core.models import InfoSource


def _root_doc(url: str) -> dict:
    return {
        "schema_version": 1,
        "target": {"url": url},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }


def _fragment_doc() -> dict:
    return {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }


def test_root_source_creates_with_url(db_session):
    src = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)
    assert isinstance(src.info_source_id, ULID)
    assert src.url == "https://example.com/p"
    assert src.parent_info_source_id is None


def test_fragment_source_requires_parent(db_session):
    parent = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    db_session.add(parent)
    db_session.commit()

    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=parent.info_source_id,
    )
    db_session.add(frag)
    db_session.commit()
    db_session.refresh(frag)
    assert frag.url is None
    assert frag.parent_info_source_id == parent.info_source_id


def test_xor_constraint_root_with_parent_rejected(db_session):
    parent = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    db_session.add(parent)
    db_session.commit()

    bad = InfoSource(
        source_spec=_root_doc("https://example.com/q"),
        schema_version=1,
        parent_info_source_id=parent.info_source_id,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_xor_constraint_fragment_without_parent_rejected(db_session):
    bad = InfoSource(source_spec=_fragment_doc(), schema_version=1)
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_url_unique(db_session):
    a = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    b = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    db_session.add_all([a, b])
    with pytest.raises(IntegrityError):
        db_session.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/core/models/test_info_source.py -v
```

Expected: FAIL (model not defined).

- [ ] **Step 3: Implement model**

In `src/core/models/info_source.py`:

```python
"""Information Source — URL-keyed (root) or parent-keyed (fragment)."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class InfoSource(Base):
    """An InfoSource — either a root (URL-keyed) or a fragment (parent-keyed)."""

    __tablename__ = "info_sources"

    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    parent_info_source_id: Mapped[ULID | None] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_spec: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str | None] = mapped_column(
        Text,
        Computed("(source_spec->'target'->>'url')", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(parent_info_source_id IS NULL) != (url IS NULL)",
            name="ck_info_sources_root_xor_fragment",
        ),
        UniqueConstraint("url", name="uq_info_sources_url"),
        Index(
            "ix_info_sources_parent",
            "parent_info_source_id",
            postgresql_where="parent_info_source_id IS NOT NULL",
        ),
        {"schema": "information"},
    )
```

In `src/core/models/__init__.py`, add the export:

```python
from src.core.models.info_source import InfoSource
# ... include in __all__
```

- [ ] **Step 4: Generate and apply migration**

```bash
uv run alembic revision --autogenerate -m "create info_sources"
uv run alembic upgrade head
```

Inspect the generated file: confirm the `Computed` column renders as `GENERATED ALWAYS AS ...`, the CHECK constraint and UNIQUE INDEX are present, and the partial index on `parent_info_source_id` is included. Edit by hand if autogenerate misses any of these (Alembic's `Computed` support is generally good but partial indexes sometimes need manual help).

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/core/models/test_info_source.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/core/models/info_source.py src/core/models/__init__.py tests/core/models/test_info_source.py alembic/versions/
git commit -m "#7 feat: add info_sources model with root/fragment XOR + URL gen-col"
```

---

### Task A5: Create `source_revisions` model + migration + tests

**Files:**
- Create: `src/core/models/source_revision.py`
- Create: `tests/core/models/test_source_revision.py`
- Create: `alembic/versions/<hash>_create_source_revisions.py`

Schema reference: design doc Section 2.

- [ ] **Step 1: Write failing tests**

```python
"""SourceRevision model tests."""

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoSource, SourceRevision


@pytest.fixture
def root_source(db_session):
    src = InfoSource(
        source_spec={
            "schema_version": 1,
            "target": {"url": "https://example.com/p"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    db_session.add(src)
    db_session.commit()
    return src


def test_source_revision_round_trip(db_session, root_source):
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "a" * 64,
        captured_at=datetime.now(UTC),
        content_size_bytes=1234,
        content_media_type="text/html",
    )
    db_session.add(rev)
    db_session.commit()
    db_session.refresh(rev)
    assert rev.source_revision_id is not None
    assert rev.content_cache_uri is None


def test_dedup_via_unique_constraint(db_session, root_source):
    fp = "sha256:" + "b" * 64
    a = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint=fp,
        captured_at=datetime.now(UTC),
    )
    b = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint=fp,
        captured_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    db_session.add_all([a, b])
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_cache_fields_optional(db_session, root_source):
    rev = SourceRevision(
        info_source_id=root_source.info_source_id,
        content_fingerprint="sha256:" + "c" * 64,
        captured_at=datetime.now(UTC),
        content_cache_uri="file:///var/cache/archiver/01HZZ.bin",
        content_cache_expires_at=datetime.now(UTC) + timedelta(seconds=600),
    )
    db_session.add(rev)
    db_session.commit()
    db_session.refresh(rev)
    assert rev.content_cache_uri.startswith("file://")
```

- [ ] **Step 2: Run tests; verify failure**

```bash
uv run pytest tests/core/models/test_source_revision.py -v
```

- [ ] **Step 3: Implement model**

In `src/core/models/source_revision.py`:

```python
"""SourceRevision — captured snapshot of an InfoSource at a point in time."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class SourceRevision(Base):
    """A captured snapshot identified by (info_source_id, content_fingerprint)."""

    __tablename__ = "source_revisions"

    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    content_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cache_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "info_source_id",
            "content_fingerprint",
            name="uq_source_revisions_source_fingerprint",
        ),
        Index(
            "ix_source_revisions_source_captured",
            "info_source_id",
            "captured_at",
            postgresql_using="btree",
        ),
        {"schema": "information"},
    )
```

Add to `src/core/models/__init__.py`.

- [ ] **Step 4: Migration + upgrade**

```bash
uv run alembic revision --autogenerate -m "create source_revisions"
uv run alembic upgrade head
```

- [ ] **Step 5: Tests pass**

```bash
uv run pytest tests/core/models/test_source_revision.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/core/models/source_revision.py src/core/models/__init__.py tests/core/models/test_source_revision.py alembic/versions/
git commit -m "#7 feat: add source_revisions model with (source_id, fingerprint) dedup"
```

---

### Task A6: Create `info_item_sources` (operator-declared item↔source binding)

**Files:**
- Create: `src/core/models/info_item_source.py`
- Create: `tests/core/models/test_info_item_source.py`
- Create: `alembic/versions/<hash>_create_info_item_sources.py`

- [ ] **Step 1: Write failing tests**

```python
"""InfoItemSource binding tests."""

import pytest
from datetime import UTC, datetime
from sqlalchemy.exc import IntegrityError

from src.core.models import InfoItem, InfoItemSource, InfoSource


@pytest.fixture
def item(db_session):
    i = InfoItem(name="t")
    db_session.add(i)
    db_session.commit()
    return i


@pytest.fixture
def source(db_session):
    s = InfoSource(
        source_spec={
            "schema_version": 1,
            "target": {"url": "https://example.com/p"},
            "extraction": {"algorithm": "full_page"},
            "fingerprint": {},
        },
        schema_version=1,
    )
    db_session.add(s)
    db_session.commit()
    return s


def test_round_trip(db_session, item, source):
    binding = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=source.info_source_id,
        role="primary",
    )
    db_session.add(binding)
    db_session.commit()
    db_session.refresh(binding)
    assert binding.deactivated_at is None


def test_one_active_primary_per_item(db_session, item, db_other_source_factory):
    s1 = db_other_source_factory("https://example.com/a")
    s2 = db_other_source_factory("https://example.com/b")
    db_session.add_all([
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=s1.info_source_id, role="primary"),
        InfoItemSource(info_item_id=item.info_item_id, info_source_id=s2.info_source_id, role="primary"),
    ])
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deactivated_primary_allows_new_primary(db_session, item, db_other_source_factory):
    s1 = db_other_source_factory("https://example.com/a")
    s2 = db_other_source_factory("https://example.com/b")
    old = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s1.info_source_id,
        role="primary",
        deactivated_at=datetime.now(UTC),
    )
    db_session.add(old)
    db_session.commit()
    new = InfoItemSource(
        info_item_id=item.info_item_id,
        info_source_id=s2.info_source_id,
        role="primary",
    )
    db_session.add(new)
    db_session.commit()  # should not raise
```

The `db_other_source_factory` fixture: add to `tests/core/models/conftest.py` (or wherever fixtures live):

```python
@pytest.fixture
def db_other_source_factory(db_session):
    def _make(url):
        src = InfoSource(
            source_spec={
                "schema_version": 1,
                "target": {"url": url},
                "extraction": {"algorithm": "full_page"},
                "fingerprint": {},
            },
            schema_version=1,
        )
        db_session.add(src)
        db_session.flush()
        return src
    return _make
```

- [ ] **Step 2: Run tests, verify fail**

- [ ] **Step 3: Implement model**

In `src/core/models/info_item_source.py`:

```python
"""InfoItem ↔ InfoSource binding (operator-declared)."""

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class InfoItemSource(Base):
    """Operator-declared binding between an InfoItem and an InfoSource."""

    __tablename__ = "info_item_sources"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    info_source_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_sources.info_source_id"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_info_item_sources_active_primary",
            "info_item_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL AND role = 'primary'"),
        ),
        {"schema": "information"},
    )
```

- [ ] **Step 4: Migration + upgrade**

- [ ] **Step 5: Tests pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "#7 feat: add info_item_sources binding (operator-declared)"
```

---

### Task A7: Create `info_item_source_revisions` (append-only revision history)

**Files:**
- Create: `src/core/models/info_item_source_revision.py`
- Create: `tests/core/models/test_info_item_source_revision.py`
- Create: `alembic/versions/<hash>_create_info_item_source_revisions.py`

- [ ] **Step 1: Write tests** — round-trip; PRIMARY KEY (info_item_id, source_revision_id) prevents duplicate binding.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement model:**

```python
"""InfoItem ↔ SourceRevision binding (append-only)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType


class InfoItemSourceRevision(Base):
    """Append-only history of which revisions an item has bound to."""

    __tablename__ = "info_item_source_revisions"

    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_revision_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.source_revisions.source_revision_id"),
        primary_key=True,
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_iisr_item_bound_desc",
            "info_item_id",
            "bound_at",
            postgresql_using="btree",
        ),
        {"schema": "information"},
    )
```

- [ ] **Step 4: Migration + upgrade.**
- [ ] **Step 5: Tests pass.**
- [ ] **Step 6: Commit.**

```bash
git commit -m "#7 feat: add info_item_source_revisions append-only history"
```

---

### Task A8: Create `rep_specs` model + migration + tests

**Files:**
- Create: `src/core/models/rep_spec.py`
- Create: `tests/core/models/test_rep_spec.py`
- Create: `alembic/versions/<hash>_create_rep_specs.py`

- [ ] **Step 1: Write tests** — round-trip, provider+name allowed duplicates (no unique constraint there), JSONB document storage.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement model:**

```python
"""Replication specification — provider config + path template + required fields."""

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class RepSpec(Base):
    """A replication specification for a particular provider."""

    __tablename__ = "rep_specs"

    rep_spec_id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_rep_specs_provider", "provider"),
        {"schema": "information"},
    )
```

- [ ] **Step 4: Migration + upgrade.**
- [ ] **Step 5: Tests pass.**
- [ ] **Step 6: Commit.**

```bash
git commit -m "#7 feat: add rep_specs registry model"
```

---

### Task A9: Create `info_item_rep_specs` (effective-dated assignments) + tests

**Files:**
- Create: `src/core/models/info_item_rep_spec.py`
- Create: `tests/core/models/test_info_item_rep_spec.py`
- Create: `alembic/versions/<hash>_create_info_item_rep_specs.py`

- [ ] **Step 1: Write tests:**
  - Round-trip with `activated_at`, `deactivated_at` NULL = active.
  - `public_url` writeback updates the active row.
  - Two active rows per (item, rep_spec) allowed (independent assignments — see design doc).
  - Active-row index applies (`deactivated_at IS NULL`).

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement model:**

```python
"""InfoItem ↔ RepSpec assignment (effective-dated)."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from src.core.models.base import Base, ULIDType, generate_ulid


class InfoItemRepSpec(Base):
    """A replication assignment with effective dating + public_url writeback."""

    __tablename__ = "info_item_rep_specs"

    id: Mapped[ULID] = mapped_column(
        ULIDType(), primary_key=True, default=generate_ulid
    )
    info_item_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.info_items.info_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    rep_spec_id: Mapped[ULID] = mapped_column(
        ULIDType(),
        ForeignKey("information.rep_specs.rep_spec_id"),
        nullable=False,
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_iirs_item_active",
            "info_item_id",
            postgresql_where=text("deactivated_at IS NULL"),
        ),
        Index("ix_iirs_rep_spec", "rep_spec_id"),
        {"schema": "information"},
    )
```

- [ ] **Step 4: Migration + upgrade.**
- [ ] **Step 5: Tests pass.**
- [ ] **Step 6: Commit.**

```bash
git commit -m "#7 feat: add info_item_rep_specs effective-dated assignments"
```

---

### Task A10: Drop legacy `InfoSpec` model + delete its tests

**Files:**
- Delete: `src/core/models/info_spec.py`
- Delete: `tests/core/models/test_info_spec.py` (if exists)
- Modify: `src/core/models/__init__.py` (remove import + `__all__` entry)
- Search and fix: any imports of `InfoSpec` outside of these files

- [ ] **Step 1: Find all imports**

```bash
grep -rn "from src.core.models.info_spec" src/ tests/ scripts/ alembic/ 2>/dev/null
grep -rn "import InfoSpec" src/ tests/ scripts/ alembic/ 2>/dev/null
grep -rn "InfoSpec" src/ tests/ scripts/ alembic/ 2>/dev/null | grep -v "info_specs.py"
```

These imports will break things in 4b (validators, tools) and 4d (SDK). The plan as a whole replaces them. For now in 4a: delete only the model file + `__init__.py` entry; expect remaining imports to go red. Sub-phase 4b will retire each remaining import as it reshapes the corresponding tool/route.

- [ ] **Step 2: Delete model file**

```bash
rm src/core/models/info_spec.py
rm -f tests/core/models/test_info_spec.py
```

- [ ] **Step 3: Update `__init__.py`**

Remove `InfoSpec` import and `__all__` entry. Add the six new models in their place:

```python
"""Archiver service ORM models."""

from src.core.models.base import Base, TimestampMixin, ULIDType, generate_ulid
from src.core.models.info_item import InfoItem
from src.core.models.info_item_rep_spec import InfoItemRepSpec
from src.core.models.info_item_source import InfoItemSource
from src.core.models.info_item_source_revision import InfoItemSourceRevision
from src.core.models.info_source import InfoSource
from src.core.models.rep_spec import RepSpec
from src.core.models.source_revision import SourceRevision

__all__ = [
    "Base",
    "InfoItem",
    "InfoItemRepSpec",
    "InfoItemSource",
    "InfoItemSourceRevision",
    "InfoSource",
    "RepSpec",
    "SourceRevision",
    "TimestampMixin",
    "ULIDType",
    "generate_ulid",
]
```

- [ ] **Step 4: Run model tests in isolation**

```bash
uv run pytest tests/core/models/ -v
```

Expected: all pass. (Other test directories may still fail at import — those will be fixed in 4b.)

- [ ] **Step 5: Commit**

```bash
git add src/core/models/ tests/core/models/
git commit -m "#7 refactor: remove legacy InfoSpec model"
```

---

**Sub-phase 4a complete.** Verify:

```bash
uv run alembic upgrade head           # full upgrade chain succeeds
uv run pytest tests/core/models/ -v   # all model tests green
```

---

## Sub-phase 4b — JSON schemas + validators + authoring tools

**Exit criteria:** All v2 schema documents validate sample payloads; all `/tools/*` endpoints serve their v2 contracts; no `info_spec` references remain in routes; `uv run pytest tests/api/ tests/core/info_spec_schema/ tests/core/tools/ -v` green (with `info_spec_schema` directory renamed to `source_spec_schema`).

---

### Task B1: Author `source_spec_schema/v1.json` (root + fragment variants)

**Files:**
- Create: `src/core/source_spec_schema/__init__.py`
- Create: `src/core/source_spec_schema/v1.json`
- Create: `tests/core/source_spec_schema/__init__.py`
- Create: `tests/core/source_spec_schema/test_v1_schema.py`
- Delete (later in Task B11): `src/core/info_spec_schema/`

The schema discriminates root from fragment via the presence of `target` (root has it; fragment doesn't).

- [ ] **Step 1: Write failing schema-shape tests**

```python
"""SourceSpec v1 schema tests."""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "src/core/source_spec_schema/v1.json"


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema):
    return jsonschema.Draft202012Validator(schema)


def test_root_full_page_valid(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_root_css_with_selector_valid(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "css", "selector": "#main"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_root_missing_url_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_root_css_missing_selector_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "css"},
        "fingerprint": {},
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)


def test_fragment_no_target_valid(validator):
    doc = {
        "schema_version": 1,
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_root_with_css_selector_valid(validator):
    """A root source can use a CSS selector for its extraction — not a fragment-only thing.

    Root vs. fragment is distinguished by presence of `target.url`, not by the
    `extraction.algorithm` choice.
    """
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "css", "selector": "#agenda"},
        "fingerprint": {},
    }
    validator.validate(doc)


def test_extra_top_level_property_rejected(validator):
    doc = {
        "schema_version": 1,
        "target": {"url": "https://example.com/p"},
        "extraction": {"algorithm": "full_page"},
        "fingerprint": {},
        "junk": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(doc)
```

- [ ] **Step 2: Run tests; verify fail (file missing).**

- [ ] **Step 3: Author schema**

`src/core/source_spec_schema/v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://watcher.exe.xyz/schemas/source-spec/v1.json",
  "title": "Source Specification v1",
  "type": "object",
  "required": ["schema_version", "extraction", "fingerprint"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"const": 1},
    "target": {
      "type": "object",
      "required": ["url"],
      "additionalProperties": false,
      "properties": {
        "url": {"type": "string", "format": "uri"},
        "fragment": {"type": "string"},
        "fetch": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "render": {"type": "boolean"},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300}
          }
        },
        "url_canonicalization": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "strip_query_keys": {
              "type": "array",
              "items": {"type": "string"}
            }
          }
        }
      }
    },
    "extraction": {
      "type": "object",
      "required": ["algorithm"],
      "additionalProperties": false,
      "properties": {
        "algorithm": {"enum": ["css", "xpath", "jsonpath", "regex", "full_page"]},
        "selector": {"type": "string"}
      },
      "allOf": [
        {
          "if": {"properties": {"algorithm": {"const": "full_page"}}},
          "then": {"not": {"required": ["selector"]}},
          "else": {"required": ["selector"]}
        }
      ]
    },
    "fingerprint": {
      "type": "object",
      "additionalProperties": false,
      "properties": {}
    }
  }
}
```

The schema does NOT enforce the root/fragment XOR at the JSON-Schema level (that's a database-level invariant). It validates the *shape* of any SourceSpec document; the application layer enforces "root sources must have `target.url`" via Pydantic at write time.

In `src/core/source_spec_schema/__init__.py`:

```python
"""SourceSpec JSON schema package — versioned, file-backed."""
```

- [ ] **Step 4: Tests pass.**

- [ ] **Step 5: Commit**

```bash
git add src/core/source_spec_schema/ tests/core/source_spec_schema/
git commit -m "#7 feat: add source_spec_schema/v1.json (root + fragment variants)"
```

---

### Task B2: SourceSpec validator (Python wrapper)

**Files:**
- Create: `src/core/source_spec_schema/validator.py`
- Modify: `tests/core/source_spec_schema/test_validator.py` (new)

The validator returns a structured result, `(ok: bool, errors: list[ValidationErrorDict])`, mirroring today's `info_spec_schema/validator.py`.

- [ ] **Step 1: Write tests** — copy patterns from existing `tests/core/info_spec_schema/test_validator.py`, swap to source_spec terminology. Add a test for *application-layer* root-vs-fragment dispatch:

```python
def test_validate_source_spec_returns_structured_errors(...): ...
def test_validate_root_requires_target_url(...): ...
def test_validate_fragment_no_target_ok(...): ...
```

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement validator** — model on `src/core/info_spec_schema/validator.py` if it exists, otherwise use `jsonschema.Draft202012Validator` and produce `[{"path": "/target/url", "message": "..."}, ...]`-shaped errors.

A minimal sketch:

```python
"""SourceSpec validation against the v1 JSON Schema."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "v1.json"


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def validate_source_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    errors: list[ValidationError] = []
    for err in _validator().iter_errors(doc):
        errors.append({
            "path": "/" + "/".join(str(p) for p in err.absolute_path),
            "message": err.message,
        })
    return (len(errors) == 0, errors)


def validate_root_source_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    """Root sources additionally require target.url to be present."""
    ok, errs = validate_source_spec(doc)
    if not doc.get("target", {}).get("url"):
        errs.append({"path": "/target/url", "message": "root source requires target.url"})
        ok = False
    return ok, errs
```

- [ ] **Step 4: Tests pass.**

- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add SourceSpec validator with root-variant check"
```

---

### Task B3: Author `rep_spec_schema/v1.json` envelope + 3 provider sub-schemas

**Files:**
- Create: `src/core/rep_spec_schema/__init__.py`
- Create: `src/core/rep_spec_schema/v1.json`  (envelope)
- Create: `src/core/rep_spec_schema/providers/gcs/v1.json`
- Create: `src/core/rep_spec_schema/providers/gdrive/v1.json`
- Create: `src/core/rep_spec_schema/providers/ia/v1.json`
- Create: `tests/core/rep_spec_schema/test_v1_schema.py`

Envelope shape (top-level):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://watcher.exe.xyz/schemas/rep-spec/v1.json",
  "title": "Replication Specification v1 (envelope)",
  "type": "object",
  "required": ["provider", "credentials_alias", "path_template", "required_fields"],
  "additionalProperties": false,
  "properties": {
    "provider": {"enum": ["gcs", "gdrive", "ia"]},
    "credentials_alias": {"type": "string", "minLength": 1},
    "path_template": {"type": "string", "minLength": 1},
    "required_fields": {
      "type": "array",
      "items": {"type": "string", "pattern": "^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$"},
      "uniqueItems": true
    },
    "object_options": {"type": "object"}
  }
}
```

Each provider sub-schema constrains `object_options` for that provider. Example for GCS (`providers/gcs/v1.json`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://watcher.exe.xyz/schemas/rep-spec/providers/gcs/v1.json",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "storage_class": {"enum": ["STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"]},
    "cache_control": {"type": "string"},
    "content_disposition": {"type": "string"}
  }
}
```

`gdrive`: `{folder_id, mime_type_override}`. `ia` (Internet Archive): `{collection, mediatype, license}`. Keep minimal — extend later as the providers are implemented in Phase 6.

- [ ] **Step 1: Write tests** — envelope validates sample, rejects unknown provider, each provider sub-schema validates its sample `object_options`.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Author schemas (per snippets above).**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add rep_spec_schema/v1.json envelope + gcs/gdrive/ia provider schemas"
```

---

### Task B4: RepSpec validator (envelope + provider dispatch)

**Files:**
- Create: `src/core/rep_spec_schema/validator.py`
- Create: `tests/core/rep_spec_schema/test_validator.py`

- [ ] **Step 1: Write tests** — happy-path per provider; unknown provider rejected; envelope-required-field missing rejected; provider sub-schema mismatch rejected (e.g., GCS `storage_class: BANANA`).

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement validator**

```python
"""RepSpec validation: envelope + per-provider object_options sub-schema."""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

ENVELOPE_PATH = Path(__file__).resolve().parent / "v1.json"
PROVIDERS_DIR = Path(__file__).resolve().parent / "providers"


class ValidationError(TypedDict):
    path: str
    message: str


@lru_cache
def _envelope() -> Draft202012Validator:
    return Draft202012Validator(json.loads(ENVELOPE_PATH.read_text()))


@lru_cache
def _provider_validator(provider: str) -> Draft202012Validator | None:
    candidate = PROVIDERS_DIR / provider / "v1.json"
    if not candidate.is_file():
        return None
    return Draft202012Validator(json.loads(candidate.read_text()))


def validate_rep_spec(doc: dict) -> tuple[bool, list[ValidationError]]:
    errors: list[ValidationError] = []
    for err in _envelope().iter_errors(doc):
        errors.append({
            "path": "/" + "/".join(str(p) for p in err.absolute_path),
            "message": err.message,
        })

    provider = doc.get("provider")
    if provider:
        sub = _provider_validator(provider)
        if sub is None:
            errors.append({
                "path": "/provider",
                "message": f"unknown provider: {provider!r}",
            })
        else:
            for err in sub.iter_errors(doc.get("object_options", {})):
                errors.append({
                    "path": "/object_options/" + "/".join(str(p) for p in err.absolute_path),
                    "message": err.message,
                })

    return (len(errors) == 0, errors)
```

- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add RepSpec validator with provider dispatch"
```

---

### Task B5: Author `rep_fields_schema/v1.json` + validator

**Files:**
- Create: `src/core/rep_fields_schema/__init__.py`
- Create: `src/core/rep_fields_schema/v1.json`
- Create: `src/core/rep_fields_schema/validator.py`
- Create: `tests/core/rep_fields_schema/test_validator.py`

The schema enforces the `<namespace>.<key>` two-level naming; the validator additionally checks an item's bag against a RepSpec's `required_fields` list.

`v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://watcher.exe.xyz/schemas/rep-fields/v1.json",
  "title": "Replication Fields v1",
  "type": "object",
  "patternProperties": {
    "^[a-z][a-z0-9_]*$": {
      "type": "object",
      "patternProperties": {
        "^[a-z][a-z0-9_]*$": {"type": ["string", "number", "boolean", "null"]}
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

Validator API:

```python
def validate_rep_fields(bag: dict) -> tuple[bool, list[ValidationError]]:
    """Schema-validate the bag's namespacing convention."""

def validate_rep_fields_against_spec(
    bag: dict, required_fields: list[str]
) -> tuple[bool, list[ValidationError]]:
    """Check that all `<ns>.<key>` paths in required_fields resolve to non-null in bag."""
```

- [ ] **Step 1: Write tests** — happy path, three-level namespace rejected, missing required field reported, present-but-null required field reported.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add rep_fields_schema/v1.json + validator (with required-fields check)"
```

---

### Task B6: `resolve_rep_fields` tool (slug normalization)

**Files:**
- Create: `src/core/tools/resolve_rep_fields.py`
- Create: `tests/core/tools/test_resolve_rep_fields.py`

Input: a bag of raw values (e.g., `{"org": {"acronym": "WSLCB", "title": "Washington State LCB"}}`). Output: the same bag enriched with `_slug` companions for known string fields, plus the `acronym_or_title` / `acronym_or_title_slug` derivations modeled on `cannobserv.storage` (per design doc Section 2 example bag).

Slug rules: lowercase, replace whitespace and any non-`[a-z0-9_]` with `_`, collapse repeated `_`, strip leading/trailing `_`.

- [ ] **Step 1: Write tests** — round-trip on the design-doc example; idempotent (passing a bag with `_slug` already present returns same bag); leaves unknown namespaces untouched.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.** Sketch:

```python
"""resolve_rep_fields — domain bag normalization for InfoItem.rep_fields."""

import re

_SLUG_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    s = _SLUG_NON_WORD.sub("_", value.lower()).strip("_")
    return re.sub(r"_+", "_", s)


def resolve_rep_fields(bag: dict) -> dict:
    out: dict = {}
    for ns, fields in bag.items():
        ns_out = dict(fields) if isinstance(fields, dict) else fields
        if isinstance(fields, dict):
            for key, val in list(fields.items()):
                if isinstance(val, str) and not key.endswith("_slug"):
                    slug_key = f"{key}_slug"
                    ns_out.setdefault(slug_key, slugify(val))
            # acronym-or-title derivation (org-style namespaces)
            if "acronym" in fields and "title" in fields:
                aot = fields.get("acronym") or fields.get("title")
                if aot:
                    ns_out.setdefault("acronym_or_title", aot)
                    ns_out.setdefault("acronym_or_title_slug", slugify(aot))
        out[ns] = ns_out
    return out
```

- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add resolve_rep_fields tool (slug + acronym_or_title derivations)"
```

---

### Task B7: Reshape `preview_extraction` to take a SourceSpec

**Files:**
- Modify: `src/core/tools/preview_extraction.py`
- Modify: `tests/core/tools/test_preview_extraction.py`

- [ ] **Step 1: Update tests to pass a `source_spec` (root variant)** instead of `info_spec`. The internal logic is unchanged — only the input wrapper changes.

- [ ] **Step 2: Run; verify fail.** Likely just renames; trivial diff.

- [ ] **Step 3: Update `preview_extraction.py`:**
  - Replace `info_spec` parameter name with `source_spec`.
  - Update validator call site to use `validate_root_source_spec` (preview only meaningful for roots).
  - Update return shape: `{"valid": bool, "errors": [...], "fetched": {...}, "extracted": "...", "fingerprint": "sha256:..."}`. Compute fingerprint as `sha256:<hex>` per design doc Section 2.

- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 refactor: preview_extraction accepts SourceSpec, emits sha256:<hex> fingerprint"
```

---

### Task B8: `assign_rep_spec` tool + `bind_revision` tool

**Files:**
- Create: `src/core/tools/assign_rep_spec.py`
- Create: `src/core/tools/bind_revision.py`
- Create: `tests/core/tools/test_assign_rep_spec.py`
- Create: `tests/core/tools/test_bind_revision.py`

Both are simple CRUD wrappers; the value is in writing them with proper validation + transactional safety.

`assign_rep_spec(db, info_item_id, rep_spec_id, *, activated_at=None) -> InfoItemRepSpec`:
- Verify `rep_spec_id` exists.
- Verify `info_item_id` exists.
- Validate `info_items.rep_fields` against `rep_specs.document.required_fields` (call B5 validator); if bag missing required keys, raise `RepFieldsIncompleteError` with the missing list.
- Insert `info_item_rep_specs` row with `activated_at = activated_at or now()`.

`bind_revision(db, info_item_id, source_revision_id, *, bound_at=None) -> InfoItemSourceRevision`:
- Verify both exist.
- Insert `info_item_source_revisions` row. Idempotent on the composite primary key (return existing row if duplicate).

- [ ] **Step 1: Write tests** — happy paths, missing required fields rejected, idempotency on `bind_revision`.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add assign_rep_spec + bind_revision tools"
```

---

### Task B9: Reshape `POST /info-items` (atomic create)

**Files:**
- Modify: `src/api/routes/info_items.py`
- Modify: `src/api/schemas/info_item.py`
- Modify: `tests/api/test_info_items.py`

The atomic create endpoint accepts:

```json
{
  "name": "...",
  "description": "...",
  "owner": "...",
  "rep_fields": { ... },
  "initial_source_spec": { ... },           // optional; creates an InfoSource + info_item_sources(role='primary')
  "initial_rep_spec_assignments": [          // optional; one per assignment
    { "rep_spec_id": "01HZZ...", "activated_at": "..." }
  ]
}
```

Returns:

```json
{
  "info_item_id": "...",
  "name": "...",
  "rep_fields": {...},
  "info_item_sources": [{...}],
  "info_item_rep_specs": [{...}]
}
```

All-or-nothing: any validation failure rolls the whole transaction back.

- [ ] **Step 1: Write tests** — minimal create (name only); create with initial_source_spec; create with both; validation failures roll back.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Update Pydantic request/response models.**
- [ ] **Step 4: Update route.** Use a single `db.begin()` block.
- [ ] **Step 5: Tests pass.**
- [ ] **Step 6: Commit**

```bash
git commit -m "#7 refactor: atomic POST /info-items accepts initial_source_spec + rep_spec_assignments"
```

---

### Task B10: Wire HTTP endpoints for the new tools

**Files:**
- Modify: `src/api/routes/tools.py`
- Modify: `tests/api/test_tools.py`
- Modify: `src/api/schemas/tools.py`

Endpoints (all under `/api/v1/tools/`):

| Endpoint | Method | Wraps |
|---|---|---|
| `/validate-source-spec` | POST | B2 validator |
| `/validate-rep-spec` | POST | B4 validator |
| `/validate-rep-fields` | POST | B5 validator (with optional `required_fields` parameter) |
| `/resolve-rep-fields` | POST | B6 tool |
| `/preview-extraction` | POST | B7 (already a route — update Pydantic schema only) |
| `/fetch-and-render` | POST | unchanged |
| `/propose-selectors` | POST | unchanged |
| `/find-info-items` | GET | unchanged |

Plus mutating routes (NOT under `/tools/`):

| Endpoint | Method | Wraps |
|---|---|---|
| `/info-items/{id}/info-sources` | POST | declare a source binding (writes info_item_sources) |
| `/info-items/{id}/rep-spec-assignments` | POST | B8 `assign_rep_spec` |
| `/info-items/{id}/source-revisions` | POST | B8 `bind_revision` |
| `/info-items/{id}/rep-spec-assignments/{assignment_id}` | DELETE | sets `deactivated_at = now()`; returns 204 |

- [ ] **Step 1: Write tests** for each endpoint (happy + auth + 404 + validation-failure cases).
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement routes.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: wire v2 authoring + assignment endpoints"
```

---

### Task B11: Delete legacy `info_specs` route + `info_spec_schema/` package

**Files:**
- Delete: `src/api/routes/info_specs.py`
- Delete: `src/api/schemas/info_spec.py`
- Delete: `src/core/info_spec_schema/`
- Modify: `src/api/main.py` (drop the `info_specs` router include)
- Modify: `tests/api/test_info_specs.py` (delete) and any cross-references

- [ ] **Step 1: Find references**

```bash
grep -rn "info_spec" src/ tests/ scripts/ 2>/dev/null
```

Each remaining reference is either:
- An import of the `info_spec_schema` package — remove or repoint to `source_spec_schema`.
- A leftover route registration — remove from `main.py`.
- A test file for legacy endpoints — delete the whole file.

- [ ] **Step 2: Delete legacy code:**

```bash
rm -rf src/core/info_spec_schema/
rm src/api/routes/info_specs.py
rm src/api/schemas/info_spec.py
rm tests/api/test_info_specs.py
rm tests/core/info_spec_schema/test_validator.py 2>/dev/null
rm -rf tests/core/info_spec_schema/ 2>/dev/null
```

Edit `src/api/main.py` to drop:

```python
# REMOVE:
# from src.api.routes import info_specs
# app.include_router(info_specs.router)
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```

Expected: all green. (No info_spec-related references should remain.)

- [ ] **Step 4: Commit**

```bash
git commit -m "#7 refactor: remove legacy info_specs route + info_spec_schema package"
```

---

### Task B12: Smoke run against the dev server (manual check)

The dev server is already running on 8021. After the route reshapes, sanity-check from the command line.

- [ ] **Step 1: Hit `/openapi.json` and confirm shape**

```bash
curl -fsS http://127.0.0.1:8021/openapi.json | python -c "
import json, sys
spec = json.load(sys.stdin)
paths = list(spec['paths'].keys())
expected = [
    '/api/v1/tools/validate-source-spec',
    '/api/v1/tools/validate-rep-spec',
    '/api/v1/tools/validate-rep-fields',
    '/api/v1/tools/resolve-rep-fields',
    '/api/v1/tools/preview-extraction',
    '/api/v1/tools/fetch-and-render',
    '/api/v1/tools/propose-selectors',
    '/api/v1/tools/find-info-items',
    '/api/v1/info-items',
    '/api/v1/info-items/{info_item_id}/info-sources',
    '/api/v1/info-items/{info_item_id}/rep-spec-assignments',
    '/api/v1/info-items/{info_item_id}/source-revisions',
]
missing = [p for p in expected if p not in paths]
unexpected_info_specs = [p for p in paths if 'info-spec' in p and 'source' not in p]
assert not missing, f'missing routes: {missing}'
assert not unexpected_info_specs, f'legacy info_spec routes still present: {unexpected_info_specs}'
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 2: No commit** (manual verification only).

---

**Sub-phase 4b complete.** Verify:

```bash
uv run pytest -v       # all green
uv run ruff check .    # no lint errors
```

---

## Sub-phase 4c — Source-revision write path + change-bus publisher

**Exit criteria:** `POST /source-revisions` is idempotent on `(source_id, fingerprint)`; outbox writes happen in the same transaction as the SourceRevision insert; background publisher drains outbox to Redis Stream `info.changes` (verified with fakeredis); `PATCH /info-item-rep-specs/{id}` accepts public_url writeback; `PATCH /source-revisions/{id}` clears the cache fields.

---

### Task C1: `POST /source-revisions` (idempotent)

**Files:**
- Create: `src/api/routes/source_revisions.py`
- Create: `src/api/schemas/source_revision.py`
- Modify: `src/api/main.py`
- Create: `tests/api/test_source_revisions.py`

Request body:

```json
{
  "info_source_id": "01HZZ...",
  "content_fingerprint": "sha256:...",
  "captured_at": "2026-05-08T...",
  "content_size_bytes": 1234,
  "content_media_type": "text/html",
  "content_cache_uri": "file:///var/cache/archiver/...",
  "content_cache_expires_at": "2026-05-08T..."
}
```

Behavior:
- Validate `info_source_id` exists and `content_fingerprint` matches `^sha256:[0-9a-f]{64}$`.
- Insert via `INSERT ... ON CONFLICT (info_source_id, content_fingerprint) DO NOTHING RETURNING *`. If no row returned, SELECT the existing one. Either way, response is 200 (or 201 on insert) with the canonical row.
- (Outbox row write happens in Task C5 — for now, just persist the revision.)

- [ ] **Step 1: Write tests** — happy path; fingerprint format rejected; unknown source_id rejected; idempotency: two POSTs with same `(source_id, fingerprint)` return the same revision id.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement route.** Use SQLAlchemy's `insert().on_conflict_do_nothing(index_elements=[...]).returning(...)` for the upsert. On conflict, `RETURNING` yields no row — follow with a `SELECT` by `(info_source_id, content_fingerprint)` to fetch the existing row. The two-step pattern reads more clearly than Postgres's `xmax = 0` trick referenced in Task C5; either is acceptable.
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: POST /source-revisions (idempotent on source_id + fingerprint)"
```

---

### Task C2: `PATCH /source-revisions/{id}` (cache clear)

Allows Watcher's sweeper and Replicator's read-failure path to nullify `content_cache_uri` + `content_cache_expires_at`.

**Files:**
- Modify: `src/api/routes/source_revisions.py`
- Modify: `src/api/schemas/source_revision.py`
- Modify: `tests/api/test_source_revisions.py`

Body shape — both fields nullable; supplying `null` clears, omitting leaves untouched (use `Field(default=Unset)`/`exclude_unset` semantics).

- [ ] **Step 1: Write tests** — clear both fields; clear one and leave the other; 404 on unknown id.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: PATCH /source-revisions/{id} for cache field clearing"
```

---

### Task C3: `PATCH /info-item-rep-specs/{assignment_id}` (public_url writeback)

**Files:**
- Modify: `src/api/routes/info_items.py` (the assignment endpoints already added in Task B10)
- Modify: `tests/api/test_info_items.py`

Body shape: `{"public_url": "https://..."}` — sets/updates the field on an active assignment row.

- [ ] **Step 1: Write tests** — set on active row succeeds; setting on a deactivated row succeeds (history preserved); 404 on unknown id.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: PATCH /info-item-rep-specs/{id} for public_url writeback"
```

---

### Task C4: Outbox table + model + migration

**Files:**
- Create: `src/core/models/changes_outbox.py`
- Create: `tests/core/models/test_changes_outbox.py`
- Create: `alembic/versions/<hash>_create_changes_outbox.py`

```python
class ChangesOutboxRow(Base):
    """Pending change-bus events; drained by the publisher background task."""

    __tablename__ = "changes_outbox"

    id: Mapped[ULID] = mapped_column(ULIDType(), primary_key=True, default=generate_ulid)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)         # 'info.changes'
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bus_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_changes_outbox_unpublished_created",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
        {"schema": "information"},
    )
```

- [ ] **Step 1: Write tests** — round-trip; index allows efficient "next 100 unpublished".
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement model + migration.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: add changes_outbox table for the bus publisher"
```

---

### Task C5: Transactional outbox write on `POST /source-revisions`

**Files:**
- Modify: `src/api/routes/source_revisions.py`
- Modify: `tests/api/test_source_revisions.py`

Behavior:
- On successful *insert* of a new SourceRevision (not on idempotent-no-op), in the *same transaction*, look up `info_item_ids` (active `info_item_sources` rows joining through to this source's id) and write a `changes_outbox` row with payload:

```json
{
  "event_type": "source_revision_captured",
  "occurred_at": "2026-05-08T...",
  "info_source_id": "01HZZ...",
  "source_revision_id": "01HZZ...",
  "content_fingerprint": "sha256:...",
  "info_item_ids": ["01HZZ...", "01HZZ..."]
}
```

On idempotent no-op (revision already exists), do NOT write an outbox row.

- [ ] **Step 1: Write tests** — new revision → outbox row exists with expected payload; duplicate POST → no new outbox row; payload shape exactly matches.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.** Use `INSERT ... ON CONFLICT ... RETURNING xmax = 0 AS inserted` (Postgres trick) to detect new vs existing row.
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: write changes_outbox row on new SourceRevision insert (transactional)"
```

---

### Task C6: Outbox publisher background task → Redis Stream

**Files:**
- Create: `src/core/changes/publisher.py`
- Create: `tests/core/changes/test_publisher.py`
- Modify: `pyproject.toml` (add `redis[hiredis]>=5` and `fakeredis>=2`)

Behavior:
- Loop: pull up to N (default 100) unpublished outbox rows ordered by `created_at`. For each, `XADD topic * key=<source_revision_id> payload=<json>` to Redis. Set `published_at = now()` and `bus_message_id = <returned id>`. Increment `publish_attempts` on retry-eligible failures.
- Loop frequency: 250ms when there's work, 1s when idle. Exposed as a small `async def run()` used by a startup hook in `src/api/main.py`.

- [ ] **Step 1: Write tests using fakeredis** — model on the watcher Phase 2b plan tests we located earlier (`tests/core/changes/test_publisher.py` precedent in the watcher repo). Cover:
  - publishes available rows in `created_at` order
  - marks rows as published with the returned bus message id
  - leaves rows un-marked on Redis exception, increments `publish_attempts`, records `last_error`
  - skips rows with `published_at IS NOT NULL`

- [ ] **Step 2: Verify fail.**

- [ ] **Step 3: Implement publisher.** Connect via `redis.asyncio` using `ARCHIVER_REDIS_URL` env var (default `redis://localhost:6379/0`).

- [ ] **Step 4: Wire into FastAPI startup using the `lifespan` context manager** (FastAPI's `on_event` hooks are deprecated). In `src/api/main.py`:

```python
import asyncio
from contextlib import asynccontextmanager

from src.core.changes import publisher


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(publisher.run(...))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(lifespan=lifespan, ...)
```

- [ ] **Step 5: Tests pass.**
- [ ] **Step 6: Commit**

```bash
git commit -m "#7 feat: outbox publisher draining changes_outbox to info.changes Redis Stream"
```

---

### Task C7: End-to-end integration test (Archiver only)

**Files:**
- Create: `tests/integration/test_source_revision_to_bus.py`

Use fakeredis + the live FastAPI test client. Steps:
1. Create an InfoItem with an InfoSource bound to it.
2. POST a SourceRevision via `/source-revisions`.
3. Wait for the publisher loop tick (or invoke `await publisher.drain_once()`).
4. Verify the Redis stream has exactly one entry with the expected payload.

- [ ] **Step 1: Write the test.**
- [ ] **Step 2: Run; verify pass (or fix until passing).**
- [ ] **Step 3: Commit**

```bash
git commit -m "#7 test: end-to-end SourceRevision → outbox → Redis Stream integration"
```

---

### Task C8: Define `info.changes` event payload schema (typed)

**Files:**
- Create: `src/core/changes/payloads.py`
- Create: `tests/core/changes/test_payloads.py`

Pydantic model `SourceRevisionCapturedEvent` with the fields from Task C5. Used by Watcher (later) and any test code that needs to parse what the publisher emits.

- [ ] **Step 1: Write tests** — round-trip through `model_dump`/`model_validate`; rejects extra fields; `event_type` literal is exactly `"source_revision_captured"`.
- [ ] **Step 2: Implement.**
- [ ] **Step 3: Refactor publisher to emit `payload.model_dump_json()` instead of an ad-hoc dict.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: typed Pydantic payload model for source_revision_captured events"
```

---

**Sub-phase 4c complete.** Verify:

```bash
uv run pytest tests/core/changes/ tests/integration/ tests/api/test_source_revisions.py -v
```

---

## Sub-phase 4d — SDK regen + smoke test

**Exit criteria:** `archiver-client` v1.0 published locally with no `info_spec` methods; `scripts/smoke_phase4.sh` passes end-to-end against the dev server.

---

### Task D1: Bump SDK version + clean regen

**Files:**
- Modify: `clients/python/pyproject.toml` (bump `version` to `1.0.0`)
- Verify: `clients/python/src/archiver_client/generated/` after regen contains no `info_spec` references.

- [ ] **Step 1: Bump version**

Edit `clients/python/pyproject.toml`:

```toml
version = "1.0.0"
```

- [ ] **Step 2: Run regen**

```bash
bash clients/python/scripts/regen.sh
```

- [ ] **Step 3: Verify no legacy methods remain**

```bash
grep -rn "info_spec" clients/python/src/archiver_client/generated/ 2>/dev/null && echo "LEGACY METHODS FOUND" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 4: Commit**

```bash
git add clients/python/
git commit -m "#7 chore: regenerate archiver-client SDK to v1.0 (no info_spec methods)"
```

---

### Task D2: Hand-written SDK wrappers for v2 endpoints

**Files:**
- Modify: `clients/python/src/archiver_client/__init__.py` and any wrapper modules

Today's `ArchiverClient` exposes ergonomic helpers (`get_primary_info_spec`, `validate_info_spec`, `find_info_item`, `fetch_and_render`, `preview_extraction`, `propose_selectors`, `create_info_item`). Update to v2:

| Old method | v2 method |
|---|---|
| `get_primary_info_spec(item_id)` | `resolve_root_sources_with_children(item_id)` |
| `validate_info_spec(doc)` | `validate_source_spec(doc)` |
| `find_info_item(query)` | unchanged |
| `fetch_and_render(url)` | unchanged |
| `preview_extraction(url, info_spec)` | `preview_extraction(source_spec)` |
| `propose_selectors(url, description, top_k)` | unchanged |
| `create_info_item(name, ..., initial_info_spec)` | `create_info_item(name, ..., initial_source_spec=None, initial_rep_spec_assignments=None)` |
| (new) | `list_sources(*, parent_info_source_id=None)` |
| (new) | `get_source(info_source_id)` |
| (new) | `validate_rep_spec(doc)` |
| (new) | `validate_rep_fields(bag, required_fields=None)` |
| (new) | `resolve_rep_fields(bag)` |
| (new) | `post_source_revision(...)` |
| (new) | `patch_source_revision_cache(id, *, content_cache_uri=None, content_cache_expires_at=None)` |
| (new) | `assign_rep_spec(item_id, rep_spec_id, *, activated_at=None)` |
| (new) | `deactivate_rep_spec_assignment(assignment_id)` |
| (new) | `set_public_url(assignment_id, public_url)` |
| (new) | `bind_revision(item_id, source_revision_id, *, bound_at=None)` |

- [ ] **Step 1: Write tests** in `clients/python/tests/` exercising each wrapper against a `respx`/`httpx` mock or against the live test server.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement wrappers.**
- [ ] **Step 4: Tests pass.**
- [ ] **Step 5: Commit**

```bash
git commit -m "#7 feat: archiver-client v2 hand-written wrappers"
```

---

### Task D3: Write `scripts/smoke_phase4.sh`

**Files:**
- Create: `scripts/smoke_phase4.sh`
- Delete: `scripts/smoke_phase3a.sh` (superseded)

The smoke script exercises the full v2 authoring loop end-to-end against the dev server (port 8021) with a real Postgres + fakeredis-or-real-redis substitute (use real Redis if available; the script defaults to checking for `ARCHIVER_REDIS_URL` and falls back to fakeredis-only assertion mode).

Steps the script performs (each via `curl` + JSON output piped to `jq` for assertions):

1. Health check.
2. Validate a sample SourceSpec.
3. Validate a sample RepSpec (gcs).
4. Validate a sample rep_fields bag.
5. Resolve rep_fields (raw → with slugs).
6. Atomically create an InfoItem with `initial_source_spec` (root) and `rep_fields`.
7. Add a fragment InfoSource as child of the root.
8. POST a SourceRevision for the root source.
9. Assert idempotency: POST the same revision again, expect same `source_revision_id`.
10. POST a different SourceRevision for the fragment source.
11. Verify the bus has 2 events (consume from `info.changes` with `XREAD`).
12. Create a RepSpec for `gcs`.
13. `assign_rep_spec` and verify the assignment.
14. PATCH `public_url` and verify the assignment row.
15. `bind_revision` to pin the item to the root revision.
16. PATCH the source revision to clear cache fields; verify NULL.
17. Final summary: print all created IDs.

Model the script on `scripts/smoke_phase3a.sh` (already in the repo) for shell conventions. Set `set -euo pipefail`. Each step prints `[N/17] <description>` then runs.

- [ ] **Step 1: Write the script.**
- [ ] **Step 2: Run it manually**

```bash
bash scripts/smoke_phase4.sh
```

Expected: each step prints OK. Total time < 10s (no real fetches).

- [ ] **Step 3: Delete the legacy smoke**

```bash
git rm scripts/smoke_phase3a.sh
```

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_phase4.sh
git commit -m "#7 test: end-to-end smoke for Phase 4 v2 authoring loop"
```

---

### Task D4: Final verification

- [ ] **Step 1: Full test suite**

```bash
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run pytest -v
```

Expected: all green.

- [ ] **Step 2: Lint**

```bash
uv run ruff check .
```

Expected: no errors.

- [ ] **Step 3: Smoke**

```bash
bash scripts/smoke_phase4.sh
```

Expected: all 17 steps OK.

- [ ] **Step 4: Verify SDK has no legacy methods**

```bash
grep -rn "info_spec" clients/python/src/archiver_client/ 2>/dev/null && echo "LEAK" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 5: Confirm worktree branch state**

```bash
git log --oneline main..HEAD | wc -l
```

Expected: ~30 commits (one per task).

---

### Task D5: Hand-off

After D4 passes, the branch is ready to merge. Use the `finishing-a-development-branch` skill to integrate. Proposed workflow:

1. Merge `phase-4-archiver-v2` into `main`.
2. Run `sudo systemctl restart archiver` (production deploy on port 8020).
3. Verify production smoke (`bash scripts/smoke_phase4.sh` against `https://watcher.exe.xyz:8020/`).
4. Close GitHub issue #7.
5. Tear down the worktree (kill 8021, `git worktree remove`).

Sub-phases 5 (Watcher refactor) and 6 (Replicator stand-up) can begin once Phase 4 is on `main` and `archiver-client` v1.0 is the pinned dependency in those repos.

---

## Phase 4 exit criteria (consolidated)

- [ ] `uv run alembic upgrade head` against a fresh database produces all v2 tables; no `info_specs` table exists.
- [ ] `uv run pytest -v` is fully green across `tests/api/`, `tests/core/`, `tests/integration/`.
- [ ] `bash scripts/smoke_phase4.sh` returns 0.
- [ ] `archiver-client` v1.0 has no `info_spec` symbols.
- [ ] `info.changes` Redis Stream receives one event per new SourceRevision insert.
- [ ] `https://watcher.exe.xyz:8021/openapi.json` lists every v2 endpoint and no legacy `/info-specs/*` paths.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Alembic autogenerate misses the `Computed` URL column or partial indexes | Each migration is hand-inspected before `upgrade`. Plan tasks call this out. |
| `INSERT ... ON CONFLICT ... DO NOTHING RETURNING` semantics differ across PG versions | Verified on Postgres 14+ (which the live VM runs). Test asserts behavior. |
| Redis dependency for tests | Use `fakeredis` for unit tests; integration test gates on `ARCHIVER_REDIS_URL` being set, otherwise skips. |
| SDK regeneration produces large diff that's hard to review | Bump version to v1.0 makes the breaking-change boundary explicit. PR description should call out "regen-only" files. |
| Watcher and Replicator mirror the SourceSpec/source_revisions models | Out of scope for Phase 4. Documented in design doc Section 1; Phase 5/6 plans will pin to v1.0. |

---

## Open questions (track during implementation)

- **`info_item_sources` PK semantics.** PRIMARY KEY is `(info_item_id, info_source_id)`, matching the design spec. With effective-dated `deactivated_at`, this PK forbids ever re-binding the same `(item, source)` pair after deactivation. Probably fine for v1 (operators redeclare a fresh source if needed), but worth flagging if the constraint bites in practice — could be relaxed to add a synthetic `id ULID PK` later.

---

## Out of scope (deferred to later phases)

- Watcher refactor (Phase 5).
- Replicator stand-up (Phase 6).
- WordPress cache integration (Phase 7).
- Authoring CLI (Phase 8).
- Bulk PATCH endpoint for cache clearing (`/source-revisions:bulk-clear-cache`).
- Cross-service health endpoint for `credentials_alias` validation.
