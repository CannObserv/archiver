# info_item_sources.role Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `info_item_sources.role` so the primary binding is implicit (`role IS NULL`, exactly one active per InfoItem) and `role` is reserved for fragment bindings (`'cross_check'`, `'sub_aspect'`). Resolves [archiver#21](https://github.com/CannObserv/archiver/issues/21).

**Architecture:** Three coupled changes — (1) DB schema (nullable role, CHECK enum, partial-unique on `role IS NULL`), (2) app-layer cross-table validation in the bind path (shape consistency, fragment-shares-root), (3) change-bus payload reshape (`info_item_ids` → `bindings` carrying `role`). Hard break across service + SDK (pre-prod; major version bump to v3.0.0).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, pytest, openapi-python-client (SDK regen), Postgres 16.

---

## Decisions pinned

These were debated up front; the plan implements them without re-litigating.

| Decision point | Resolution |
|---|---|
| DB enforcement | Partial unique index on `(info_item_id) WHERE deactivated_at IS NULL AND role IS NULL` + CHECK constraint on allowed role values. Cross-table invariants (NULL ↔ root InfoSource; role ↔ fragment InfoSource; fragment shares primary's root) live in `bind_info_source` / atomic-create app logic. **No triggers, no generated columns.** |
| Outbox fan-out | `SourceRevisionCapturedEvent.info_item_ids: list[str]` is replaced by `bindings: list[InfoItemBinding]` where `InfoItemBinding = {info_item_id: str, role: str \| None}`. Publisher does **no** role-based filtering — consumers (Replicator, Notifier) filter on `role` if they care. Cross_check revisions flow through `info.changes` like any other; downstream owns the filter. |
| Effective-root drift | **In scope:** bind-time check that a fragment binding's underlying InfoSource has `parent_info_source_id` equal to the InfoItem's currently-active root binding's `info_source_id`. **Out of scope:** the deactivation-time policy (reject deactivating an active root binding while fragments are still active). No deactivate endpoint for `info_item_sources` exists today; document the invariant in the model docstring and CLAUDE.md, defer enforcement to the issue that adds the endpoint. |
| SDK compatibility | **Hard break, v3.0.0.** Pre-prod; no migration shim. Service `pyproject.toml` and `clients/python/pyproject.toml` both bump from 2.2.0 → 3.0.0. CHANGELOG entry tagged `[both]`. SDK callers passing `role='primary'` get a clean 422 with `code=role_removed`. |

---

## File structure

**Schema:**
- Create: `alembic/versions/<hash>_refactor_info_item_sources_role.py`
- Modify: `src/core/models/info_item_source.py`

**Routes / schemas / tools:**
- Modify: `src/api/routes/info_items.py` (atomic-create body @ line 140; `add_info_source` route @ lines 209–258)
- Modify: `src/api/schemas/info_item.py` (`InfoItemSourceCreate`, `InfoItemSourceOut`, `InfoItemCreate.initial_source_spec` docstring)
- Create: `src/core/tools/bind_info_source.py` (extract cross-table validation out of the route — three independent checks fit cleanly in a tool function; the route becomes a thin wrapper that translates typed errors to envelopes)

**Change-bus payload:**
- Modify: `src/core/changes/payloads.py` (add `InfoItemBinding`; replace `info_item_ids` with `bindings`)
- Modify: `src/api/routes/source_revisions.py` (query `(info_item_id, role)`, build `bindings`)

**SDK:**
- Modify: `clients/python/pyproject.toml` (version 2.2.0 → 3.0.0)
- Regenerate: `clients/python/src/archiver_client/generated/`
- Modify: `clients/python/src/archiver_client/client.py` (`add_info_source` signature)
- Modify: `clients/python/tests/` (any test that uses `role='primary'`)

**Docs:**
- Modify: `pyproject.toml` (service version 2.2.0 → 3.0.0)
- Modify: `CHANGELOG.md` (new v3.0.0 `[both]` entry)
- Modify: `CLAUDE.md` (Vocabulary section — InfoItemSource description + role enum table)

**Tests (mirror src/):**
- Modify: `tests/core/models/test_info_item_source.py`
- Modify: `tests/api/test_create_info_item_atomic.py`
- Modify: `tests/api/test_source_revisions.py` (outbox payload tests 18, 19, 20)
- Create: `tests/api/test_add_info_source.py` (new role/shape/root validation tests; lift the few existing role tests out of `test_info_items.py` if any live there)
- Create: `tests/core/tools/test_bind_info_source.py`

---

## Tasks

### Task 1: Branch + baseline green

**Goal:** Start clean on a feature branch with a known-green baseline.

- [ ] **Step 1: Create feature branch off main**

```bash
git checkout main
git pull
git checkout -b refactor/iis-role-21
```

- [ ] **Step 2: Verify baseline test suite passes**

```bash
uv sync
export $(cat /etc/archiver/.env .env 2>/dev/null | xargs)
uv run alembic upgrade head
uv run pytest -x
```

Expected: all pass. If anything fails on `main`, **stop** and surface — don't conflate baseline flakes with refactor regressions.

- [ ] **Step 3: Verify lint clean**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean.

---

### Task 2: Migration — drop old constraint, normalize data, add new constraint

**Files:**
- Create: `alembic/versions/<hash>_refactor_info_item_sources_role.py`

**Background:** Current head is `ed0907b43fbe`. New revision's `down_revision` must equal whatever `alembic heads` returns (may not match if other PRs landed). Use `uv run alembic revision -m "refactor info_item_sources role"` to scaffold and let Alembic fill in the parent.

- [ ] **Step 1: Scaffold the migration**

```bash
uv run alembic revision -m "refactor info_item_sources role"
```

Note the generated filename; open it.

- [ ] **Step 2: Implement `upgrade()`**

Replace the scaffolded body with:

```python
def upgrade() -> None:
    """Refactor role: primary becomes implicit (NULL); enum restricted to fragment roles."""
    # 1. Normalize data — pre-prod, so any non-conforming rows are bugs; assert
    #    via a guard query that there are none, then map 'primary' → NULL.
    op.execute(
        """
        DO $$
        DECLARE bad_count int;
        BEGIN
            SELECT count(*) INTO bad_count
              FROM information.info_item_sources
             WHERE role IS NOT NULL AND role NOT IN ('primary', 'cross_check', 'sub_aspect');
            IF bad_count > 0 THEN
                RAISE EXCEPTION
                    'info_item_sources has % rows with non-conforming role values; '
                    'clean them up before applying this migration', bad_count;
            END IF;
        END $$;
        """
    )
    op.execute(
        "UPDATE information.info_item_sources SET role = NULL WHERE role = 'primary'"
    )

    # 2. Drop the old partial-unique (keyed on role='primary')
    op.drop_index(
        "uq_info_item_sources_active_primary",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role = 'primary'"),
    )

    # 3. Make role nullable + add CHECK on allowed values
    op.alter_column(
        "info_item_sources",
        "role",
        existing_type=sa.String(length=50),
        nullable=True,
        schema="information",
    )
    op.create_check_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        "role IS NULL OR role IN ('cross_check', 'sub_aspect')",
        schema="information",
    )

    # 4. New partial-unique: at most one active root binding per InfoItem
    op.create_index(
        "uq_info_item_sources_active_root",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )


def downgrade() -> None:
    """Reverse the role refactor. Lossy: existing NULL roles become 'primary'."""
    op.drop_index(
        "uq_info_item_sources_active_root",
        table_name="info_item_sources",
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role IS NULL"),
    )
    op.drop_constraint(
        "ck_info_item_sources_role_values",
        "info_item_sources",
        type_="check",
        schema="information",
    )
    op.execute(
        "UPDATE information.info_item_sources SET role = 'primary' WHERE role IS NULL"
    )
    op.alter_column(
        "info_item_sources",
        "role",
        existing_type=sa.String(length=50),
        nullable=False,
        schema="information",
    )
    op.create_index(
        "uq_info_item_sources_active_primary",
        "info_item_sources",
        ["info_item_id"],
        unique=True,
        schema="information",
        postgresql_where=sa.text("deactivated_at IS NULL AND role = 'primary'"),
    )
```

- [ ] **Step 3: Apply and verify forward**

```bash
uv run alembic upgrade head
psql "$ARCHIVER_DATABASE_URL" -c "\d information.info_item_sources"
```

Expected: `role` column shows `nullable`; `ck_info_item_sources_role_values` and `uq_info_item_sources_active_root` are present; `uq_info_item_sources_active_primary` is gone.

- [ ] **Step 4: Verify round-trip down/up**

```bash
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: both clean. (Round-trip exercises the lossy downgrade against the pre-prod assumption that NULL roles map back to 'primary'.)

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "#21 feat(db): refactor info_item_sources.role — nullable + enum + active-root unique"
```

---

### Task 3: Update ORM model — TDD

**Files:**
- Modify: `src/core/models/info_item_source.py`
- Modify: `tests/core/models/test_info_item_source.py`

- [ ] **Step 1: Update / add failing tests**

Open `tests/core/models/test_info_item_source.py`. Replace `role="primary"` with `role=None` in the existing happy-path / unique-active-primary / deactivated-primary tests (and rename them: s/primary/root/). Add three new tests:

```python
@pytest.mark.asyncio
async def test_role_check_constraint_rejects_bogus_value(session, item, make_source):
    """CHECK constraint blocks any role outside {NULL, cross_check, sub_aspect}."""
    src = await make_source("https://example.com/x")
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id,
            info_source_id=src.info_source_id,
            role="primary",   # no longer valid
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_fragment_roles_accepted(session, item, make_source):
    """Both cross_check and sub_aspect are allowed at the schema level.

    Shape consistency (role ↔ fragment InfoSource) is enforced in the app
    layer, not the DB — see tests/core/tools/test_bind_info_source.py.
    """
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s1.info_source_id,
                role="cross_check",
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s2.info_source_id,
                role="sub_aspect",
            ),
        ]
    )
    await session.commit()  # both should persist


@pytest.mark.asyncio
async def test_one_active_root_per_item(session, item, make_source):
    """Two active NULL-role bindings on the same item violate the unique index."""
    s1 = await make_source("https://example.com/a")
    s2 = await make_source("https://example.com/b")
    session.add_all(
        [
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s1.info_source_id,
                role=None,
            ),
            InfoItemSource(
                info_item_id=item.info_item_id,
                info_source_id=s2.info_source_id,
                role=None,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run; expect failures**

```bash
uv run pytest tests/core/models/test_info_item_source.py -v
```

Expected: new tests fail (model still has `nullable=False` and no CHECK); old `test_one_active_primary_per_item` / `test_secondary_role_unconstrained` either fail or pass for the wrong reasons.

- [ ] **Step 3: Update the model**

`src/core/models/info_item_source.py`:

```python
"""InfoItem ↔ InfoSource binding (operator-declared).

Role semantics:
- ``NULL`` — the binding's InfoSource is root-shaped (URL-bearing); it is
  the InfoItem's *primary* by construction. At most one active NULL-role
  binding per InfoItem (partial-unique index).
- ``'cross_check'`` — fragment-shaped binding; selector extracts the same
  content as primary via a different selector. Used at fetch time to
  detect selector rot.
- ``'sub_aspect'`` — fragment-shaped binding; selector extracts a different
  content area of the same fetched page. Operator-watchable from Watcher.

Shape consistency (NULL ↔ root, role ↔ fragment) and fragment-shares-root
are enforced in the app layer (``src/core/tools/bind_info_source.py``),
not the DB. The DB only enforces the role enum and the active-root
uniqueness constraint.
"""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
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

# Allowed non-null role values. NULL is the implicit "primary" role.
FRAGMENT_ROLES: tuple[str, ...] = ("cross_check", "sub_aspect")
FragmentRole = Literal["cross_check", "sub_aspect"]


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
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IS NULL OR role IN ('cross_check', 'sub_aspect')",
            name="ck_info_item_sources_role_values",
        ),
        Index(
            "uq_info_item_sources_active_root",
            "info_item_id",
            unique=True,
            postgresql_where=text("deactivated_at IS NULL AND role IS NULL"),
        ),
        {"schema": "information"},
    )
```

- [ ] **Step 4: Run model tests**

```bash
uv run pytest tests/core/models/test_info_item_source.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/models/info_item_source.py tests/core/models/test_info_item_source.py
git commit -m "#21 feat(model): nullable role + CheckConstraint + active-root unique"
```

---

### Task 4: Extract `bind_info_source` core tool — TDD

**Goal:** Move all cross-table validation out of the route into a typed tool function. Three checks:

1. Shape consistency: `role IS NULL` ↔ source has a URL (root); `role IN (...)` ↔ source has `parent_info_source_id` (fragment).
2. Fragment-shares-root: fragment binding's source's `parent_info_source_id` must equal the InfoItem's currently-active NULL-role binding's `info_source_id`.
3. Existence: InfoItem and InfoSource both exist.

This mirrors `assign_rep_spec` / `bind_revision` — typed errors at the tool layer, route translates them to envelope responses.

**Files:**
- Create: `src/core/tools/bind_info_source.py`
- Create: `tests/core/tools/test_bind_info_source.py`

- [ ] **Step 1: Write failing tests**

`tests/core/tools/test_bind_info_source.py`:

```python
"""Tests for the bind_info_source core tool."""

import pytest
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    FragmentParentMismatchError,
    InfoItemNotFoundError,
    InfoSourceNotFoundError,
    RoleShapeMismatchError,
    bind_info_source,
)


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


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


@pytest.fixture
async def root_src(session):
    src = InfoSource(source_spec=_root_doc("https://example.com/p"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def other_root(session):
    src = InfoSource(source_spec=_root_doc("https://example.com/q"), schema_version=1)
    session.add(src)
    await session.flush()
    return src


@pytest.fixture
async def frag_of_root(session, root_src):
    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=root_src.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


@pytest.fixture
async def frag_of_other(session, other_root):
    frag = InfoSource(
        source_spec=_fragment_doc(),
        schema_version=1,
        parent_info_source_id=other_root.info_source_id,
    )
    session.add(frag)
    await session.flush()
    return frag


# --- happy paths ---


@pytest.mark.asyncio
async def test_bind_root_with_null_role(session, item, root_src):
    binding = await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    assert binding.role is None
    assert binding.deactivated_at is None


@pytest.mark.asyncio
async def test_bind_fragment_with_cross_check(session, item, root_src, frag_of_root):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    binding = await bind_info_source(
        session,
        info_item_id=item.info_item_id,
        info_source_id=frag_of_root.info_source_id,
        role="cross_check",
    )
    assert binding.role == "cross_check"


# --- shape consistency ---


@pytest.mark.asyncio
async def test_root_with_role_rejected(session, item, root_src):
    with pytest.raises(RoleShapeMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=root_src.info_source_id,
            role="sub_aspect",
        )


@pytest.mark.asyncio
async def test_fragment_with_null_role_rejected(session, item, root_src, frag_of_root):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(RoleShapeMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_root.info_source_id,
            role=None,
        )


# --- fragment-shares-root ---


@pytest.mark.asyncio
async def test_fragment_under_different_root_rejected(
    session, item, root_src, frag_of_other
):
    await bind_info_source(
        session, info_item_id=item.info_item_id, info_source_id=root_src.info_source_id, role=None
    )
    with pytest.raises(FragmentParentMismatchError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_other.info_source_id,
            role="sub_aspect",
        )


@pytest.mark.asyncio
async def test_fragment_without_active_root_rejected(session, item, frag_of_root):
    with pytest.raises(ActiveRootMissingError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=frag_of_root.info_source_id,
            role="cross_check",
        )


# --- existence ---


@pytest.mark.asyncio
async def test_unknown_info_item(session, root_src):
    with pytest.raises(InfoItemNotFoundError):
        await bind_info_source(
            session,
            info_item_id=ULID(),
            info_source_id=root_src.info_source_id,
            role=None,
        )


@pytest.mark.asyncio
async def test_unknown_info_source(session, item):
    with pytest.raises(InfoSourceNotFoundError):
        await bind_info_source(
            session,
            info_item_id=item.info_item_id,
            info_source_id=ULID(),
            role=None,
        )
```

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/core/tools/test_bind_info_source.py -v
```

Expected: ImportError (module not yet created).

- [ ] **Step 3: Implement the tool**

`src/core/tools/bind_info_source.py`:

```python
"""Bind an InfoSource to an InfoItem with cross-table shape/root validation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.core.models import InfoItem, InfoItemSource, InfoSource


class InfoItemNotFoundError(Exception):
    """The given info_item_id does not reference an InfoItem."""


class InfoSourceNotFoundError(Exception):
    """The given info_source_id does not reference an InfoSource."""


class RoleShapeMismatchError(Exception):
    """role/shape combination is invalid.

    NULL role requires a root-shaped InfoSource (URL non-null).
    Fragment role requires a fragment-shaped InfoSource (parent non-null).
    """

    def __init__(self, *, role: str | None, source_is_root: bool):
        self.role = role
        self.source_is_root = source_is_root
        super().__init__(
            f"role={role!r} is not valid for "
            f"{'root' if source_is_root else 'fragment'}-shaped InfoSource"
        )


class ActiveRootMissingError(Exception):
    """Tried to bind a fragment-role InfoSource before any active root binding exists."""


class FragmentParentMismatchError(Exception):
    """Fragment's parent_info_source_id does not match the InfoItem's active root binding."""

    def __init__(self, *, expected_root_id: ULID, actual_parent_id: ULID):
        self.expected_root_id = expected_root_id
        self.actual_parent_id = actual_parent_id
        super().__init__(
            f"fragment's parent {actual_parent_id} != active root binding's source "
            f"{expected_root_id}"
        )


async def bind_info_source(
    db: AsyncSession,
    *,
    info_item_id: ULID,
    info_source_id: ULID,
    role: str | None,
) -> InfoItemSource:
    """Persist a new ``info_item_sources`` row after validating shape + root invariants.

    Caller commits.
    """
    item = await db.get(InfoItem, info_item_id)
    if item is None:
        raise InfoItemNotFoundError(str(info_item_id))

    source = await db.get(InfoSource, info_source_id)
    if source is None:
        raise InfoSourceNotFoundError(str(info_source_id))

    source_is_root = source.parent_info_source_id is None

    # 1. Shape consistency
    if role is None and not source_is_root:
        raise RoleShapeMismatchError(role=role, source_is_root=False)
    if role is not None and source_is_root:
        raise RoleShapeMismatchError(role=role, source_is_root=True)

    # 2. Fragment-shares-root: fragment's parent must equal the InfoItem's
    # currently-active NULL-role binding's info_source_id.
    if not source_is_root:
        active_root_id = await db.scalar(
            select(InfoItemSource.info_source_id).where(
                InfoItemSource.info_item_id == info_item_id,
                InfoItemSource.role.is_(None),
                InfoItemSource.deactivated_at.is_(None),
            )
        )
        if active_root_id is None:
            raise ActiveRootMissingError(str(info_item_id))
        if active_root_id != source.parent_info_source_id:
            raise FragmentParentMismatchError(
                expected_root_id=active_root_id,
                actual_parent_id=source.parent_info_source_id,
            )

    binding = InfoItemSource(
        info_item_id=info_item_id,
        info_source_id=info_source_id,
        role=role,
    )
    db.add(binding)
    await db.flush()
    return binding
```

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/core/tools/test_bind_info_source.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/tools/bind_info_source.py tests/core/tools/test_bind_info_source.py
git commit -m "#21 feat(tools): bind_info_source with shape + active-root validation"
```

---

### Task 5: Update request/response schemas — TDD

**Files:**
- Modify: `src/api/schemas/info_item.py`

- [ ] **Step 1: Update the schemas**

Replace `InfoItemSourceCreate` and `InfoItemSourceOut`:

```python
from typing import Literal


class InfoItemSourceCreate(BaseModel):
    """Request body for POST /info-items/{id}/info-sources."""

    info_source_id: str = Field(min_length=1, description="ULID of an existing InfoSource.")
    role: Literal["cross_check", "sub_aspect"] | None = Field(
        default=None,
        description=(
            "Binding role. ``null`` (default) for root-shaped InfoSources (the "
            "InfoItem's primary). ``'cross_check'`` or ``'sub_aspect'`` for "
            "fragment-shaped InfoSources sharing the primary's root."
        ),
    )


class InfoItemSourceOut(BaseModel):
    """Light projection of an info_item_sources row."""

    info_source_id: str
    role: str | None
    created_at: datetime
```

Update `InfoItemCreate.initial_source_spec` docstring:

```python
    initial_source_spec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional SourceSpec document to atomically create alongside the new "
            "InfoItem as the primary (NULL-role) binding. Validated before any row "
            "is written; on validation failure neither InfoItem nor InfoSource is "
            "persisted."
        ),
    )
```

- [ ] **Step 2: Spot-check OpenAPI dump**

```bash
uv run python scripts/dump_openapi.py | python -m json.tool | grep -A 8 '"InfoItemSourceCreate"'
```

Expected: `role` shows as `nullable: true` (or `anyOf` with `null`) and enum `["cross_check","sub_aspect"]`.

- [ ] **Step 3: Commit**

```bash
git add src/api/schemas/info_item.py
git commit -m "#21 refactor(schemas): InfoItemSourceCreate.role optional + Literal enum"
```

---

### Task 6: Rewrite `add_info_source` route + atomic-create role=None — TDD

**Files:**
- Modify: `src/api/routes/info_items.py` (line 140; lines 209–258)
- Create: `tests/api/test_add_info_source.py`
- Modify: `tests/api/test_create_info_item_atomic.py`

- [ ] **Step 1: Write failing route tests**

`tests/api/test_add_info_source.py` (full file):

```python
"""HTTP-layer tests for POST /info-items/{id}/info-sources.

Covers role validation, shape consistency, fragment-shares-root, and existence.
Mirrors the cases in tests/core/tools/test_bind_info_source.py at the HTTP level
to confirm error translation.
"""

import pytest

from src.core.models import InfoItem, InfoItemSource, InfoSource

HEADERS = {"X-API-Key": "test-secret-key"}


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


@pytest.fixture
async def item(session):
    obj = InfoItem(name="t")
    session.add(obj)
    await session.flush()
    return obj


async def _make_source(session, *, url=None, parent_id=None):
    if url is not None:
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


@pytest.mark.asyncio
async def test_bind_root_with_omitted_role_201(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] is None


@pytest.mark.asyncio
async def test_bind_fragment_with_cross_check_201(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
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
    assert resp.json()["role"] == "cross_check"


@pytest.mark.asyncio
async def test_legacy_primary_role_rejected_422(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id), "role": "primary"},
    )
    # Pydantic Literal rejects this before reaching the route handler
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "body"


@pytest.mark.asyncio
async def test_root_with_role_returns_422_domain(client, session, item):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id), "role": "sub_aspect"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "role_shape_mismatch"


@pytest.mark.asyncio
async def test_fragment_with_null_role_returns_422_domain(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id)},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "role_shape_mismatch"


@pytest.mark.asyncio
async def test_fragment_without_active_root_returns_422_domain(client, session, item):
    root = await _make_source(session, url="https://example.com/a")
    frag = await _make_source(session, parent_id=root.info_source_id)
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag.info_source_id), "role": "cross_check"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "active_root_missing"


@pytest.mark.asyncio
async def test_fragment_under_different_root_returns_422_domain(client, session, item):
    root_a = await _make_source(session, url="https://example.com/a")
    root_b = await _make_source(session, url="https://example.com/b")
    frag_of_b = await _make_source(session, parent_id=root_b.info_source_id)
    session.add(
        InfoItemSource(
            info_item_id=item.info_item_id, info_source_id=root_a.info_source_id, role=None
        )
    )
    await session.commit()

    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(frag_of_b.info_source_id), "role": "sub_aspect"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["kind"] == "domain"
    assert detail["errors"][0]["code"] == "fragment_parent_mismatch"


@pytest.mark.asyncio
async def test_unknown_info_source_returns_404(client, item):
    resp = await client.post(
        f"/api/v1/info-items/{item.info_item_id}/info-sources",
        headers=HEADERS,
        json={"info_source_id": "01JZZZZZZZZZZZZZZZZZZZZZZZ"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_info_item_returns_404(client, session):
    src = await _make_source(session, url="https://example.com/a")
    await session.commit()
    resp = await client.post(
        "/api/v1/info-items/01JZZZZZZZZZZZZZZZZZZZZZZZ/info-sources",
        headers=HEADERS,
        json={"info_source_id": str(src.info_source_id)},
    )
    assert resp.status_code == 404
```

Also update `tests/api/test_create_info_item_atomic.py`: any assertion `src_out["role"] == "primary"` becomes `src_out["role"] is None`, and any DB-level assertion `binding.role == "primary"` becomes `binding.role is None`.

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/api/test_add_info_source.py tests/api/test_create_info_item_atomic.py -v
```

Expected: failures (route still uses old body shape and writes `role='primary'`).

- [ ] **Step 3: Rewrite the route handler**

In `src/api/routes/info_items.py`, replace the `add_info_source` handler (lines ~209–258) with:

```python
from src.core.tools.bind_info_source import (
    ActiveRootMissingError,
    FragmentParentMismatchError,
    InfoItemNotFoundError as BindIIS_InfoItemNotFoundError,
    InfoSourceNotFoundError as BindIIS_InfoSourceNotFoundError,
    RoleShapeMismatchError,
    bind_info_source,
)


@router.post(
    "/{info_item_id}/info-sources",
    response_model=InfoItemSourceOut,
    status_code=201,
)
async def add_info_source(
    info_item_id: ULIDStr,
    body: InfoItemSourceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> InfoItemSourceOut:
    """Bind an existing InfoSource to an InfoItem.

    ``body.role`` is ``null`` for a root-shaped InfoSource (the InfoItem's
    primary; at most one active per InfoItem) or one of
    ``'cross_check'`` / ``'sub_aspect'`` for a fragment-shaped InfoSource
    whose parent equals the InfoItem's active root binding's source.
    """
    try:
        item_ulid = ULID.from_str(info_item_id)
    except ValueError as e:
        raise_envelope(
            422, "domain", "info_item_id is not a valid ULID",
            errors=[FieldError(path="/info_item_id", message="not a valid ULID",
                               code="invalid_ulid")],
            source_exc=e,
        )

    try:
        source_ulid = ULID.from_str(body.info_source_id)
    except ValueError as e:
        raise_envelope(
            422, "domain", "info_source_id is not a valid ULID",
            errors=[FieldError(path="/info_source_id", message="not a valid ULID",
                               code="invalid_ulid")],
            source_exc=e,
        )

    try:
        binding = await bind_info_source(
            session,
            info_item_id=item_ulid,
            info_source_id=source_ulid,
            role=body.role,
        )
    except BindIIS_InfoItemNotFoundError as e:
        raise_envelope(404, "lookup", "InfoItem not found", source_exc=e)
    except BindIIS_InfoSourceNotFoundError as e:
        raise_envelope(404, "lookup", "InfoSource not found", source_exc=e)
    except RoleShapeMismatchError as e:
        raise_envelope(
            422, "domain",
            f"role {e.role!r} is not valid for "
            f"{'root' if e.source_is_root else 'fragment'}-shaped InfoSource",
            errors=[FieldError(path="/role", message="role/shape mismatch",
                               code="role_shape_mismatch")],
            source_exc=e,
        )
    except ActiveRootMissingError as e:
        raise_envelope(
            422, "domain",
            "cannot bind a fragment-role InfoSource before an active root binding exists",
            errors=[FieldError(path="/info_source_id",
                               message="InfoItem has no active root binding",
                               code="active_root_missing")],
            source_exc=e,
        )
    except FragmentParentMismatchError as e:
        raise_envelope(
            422, "domain",
            "fragment's parent does not match the InfoItem's active root binding",
            errors=[FieldError(path="/info_source_id",
                               message="fragment parent != active root source",
                               code="fragment_parent_mismatch")],
            data={
                "expected_root_info_source_id": str(e.expected_root_id),
                "actual_parent_info_source_id": str(e.actual_parent_id),
            },
            source_exc=e,
        )

    await session.commit()
    return info_item_source_to_out(binding)
```

Also at line 140, the atomic-create binding: change `role="primary"` to `role=None`.

- [ ] **Step 4: Run; verify PASS**

```bash
uv run pytest tests/api/test_add_info_source.py tests/api/test_create_info_item_atomic.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/info_items.py tests/api/test_add_info_source.py tests/api/test_create_info_item_atomic.py
git commit -m "#21 refactor(api): add_info_source uses bind_info_source tool; atomic create writes NULL role"
```

---

### Task 7: Update outbox event payload — TDD

**Files:**
- Modify: `src/core/changes/payloads.py`
- Modify: `src/api/routes/source_revisions.py`
- Modify: `tests/api/test_source_revisions.py` (tests 18, 19, 20 — outbox payload shape)

- [ ] **Step 1: Update outbox tests for new payload shape**

In `tests/api/test_source_revisions.py`, the existing tests 18–20 assert on `row.payload["info_item_ids"]`. Rewrite them against the new `bindings` shape. Example for test 18:

```python
@pytest.mark.asyncio
async def test_outbox_payload_includes_active_bindings(client, session, info_source):
    item1 = await _make_info_item(session)
    item2 = await _make_info_item(session)
    session.add_all([
        InfoItemSource(info_item_id=item1.info_item_id,
                       info_source_id=info_source.info_source_id, role=None),
        InfoItemSource(info_item_id=item2.info_item_id,
                       info_source_id=info_source.info_source_id, role=None),
    ])
    await session.flush()

    resp = await client.post(
        "/api/v1/source-revisions",
        headers=HEADERS,
        json={"info_source_id": str(info_source.info_source_id),
              "content_fingerprint": FP_VALID,
              "captured_at": "2026-05-08T12:00:00.000000Z"},
    )
    assert resp.status_code == 201

    row = (await session.execute(select(ChangesOutboxRow))).scalar_one()
    bindings = row.payload["bindings"]
    ids = {b["info_item_id"] for b in bindings}
    roles = {b["role"] for b in bindings}
    assert {str(item1.info_item_id), str(item2.info_item_id)} == ids
    assert roles == {None}
```

Add one new test asserting that fragment bindings surface their role:

```python
@pytest.mark.asyncio
async def test_outbox_payload_carries_fragment_role(client, session):
    """Cross_check / sub_aspect roles are included in bindings; consumers filter."""
    # Setup: root + fragment InfoSource, item bound to fragment as sub_aspect
    # (... build via fixtures / helpers ...)
    # Assert: row.payload["bindings"][0]["role"] == "sub_aspect"
```

(Concrete fixture wiring follows the patterns in `test_add_info_source.py`.)

- [ ] **Step 2: Run; verify FAIL**

```bash
uv run pytest tests/api/test_source_revisions.py -k outbox -v
```

Expected: failures (payload still has `info_item_ids`).

- [ ] **Step 3: Update the payload model**

`src/core/changes/payloads.py`:

```python
"""Typed Pydantic models for change-bus event payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InfoItemBinding(BaseModel):
    """One active InfoItem↔InfoSource binding at the moment a revision was captured."""

    model_config = ConfigDict(extra="forbid")

    info_item_id: str
    role: str | None  # None = primary (root); 'cross_check' or 'sub_aspect' = fragment


class SourceRevisionCapturedEvent(BaseModel):
    """Event emitted when a new SourceRevision is recorded for an InfoSource.

    Producer: Archiver (POST /source-revisions on insert; not on idempotent no-op).
    Subscribers: Replicator, Notifier, etc. — consumers filter on
    ``bindings[*].role`` per their semantics (e.g. Replicator typically
    cares only about ``role IS NULL``; selector-rot tooling cares about
    ``role == 'cross_check'``).
    """

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["source_revision_captured"] = "source_revision_captured"
    occurred_at: datetime
    info_source_id: str
    source_revision_id: str
    content_fingerprint: str
    bindings: list[InfoItemBinding]
```

- [ ] **Step 4: Update the route**

In `src/api/routes/source_revisions.py`, lines ~135–151:

```python
    if inserted:
        # Query active (info_item_id, role) pairs bound to this source
        bindings_result = await session.execute(
            select(InfoItemSource.info_item_id, InfoItemSource.role).where(
                InfoItemSource.info_source_id == row.info_source_id,
                InfoItemSource.deactivated_at.is_(None),
            )
        )
        bindings = [
            InfoItemBinding(info_item_id=str(iid), role=r)
            for iid, r in bindings_result.all()
        ]
        event = SourceRevisionCapturedEvent(
            occurred_at=datetime.now(UTC),
            info_source_id=str(row.info_source_id),
            source_revision_id=str(row.source_revision_id),
            content_fingerprint=row.content_fingerprint,
            bindings=bindings,
        )
        session.add(ChangesOutboxRow(topic="info.changes", payload=event.model_dump(mode="json")))
```

Add the new import: `from src.core.changes.payloads import InfoItemBinding, SourceRevisionCapturedEvent`.

- [ ] **Step 5: Run; verify PASS**

```bash
uv run pytest tests/api/test_source_revisions.py -k outbox -v
uv run pytest tests/api/test_source_revisions.py -v  # full file, catch regressions
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/core/changes/payloads.py src/api/routes/source_revisions.py tests/api/test_source_revisions.py
git commit -m "#21 feat(events): SourceRevisionCapturedEvent.bindings replaces info_item_ids"
```

---

### Task 8: Full test sweep + lint

**Goal:** Catch any other call sites that hardcoded `role='primary'`.

- [ ] **Step 1: Find stragglers**

```bash
rg "role\s*=\s*['\"]primary['\"]" --type py
rg "info_item_ids" --type py
```

Expected: each remaining hit is in a test fixture or a Watcher/Notifier reference doc; fix the fixtures, leave the doc references alone (those describe pre-refactor history).

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest
```

Expected: PASS.

- [ ] **Step 3: Lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean. If `ruff format --check` fails, run `uv run ruff format .` and commit the diff as part of the next task.

- [ ] **Step 4: Commit any fixture cleanup**

```bash
git add -p   # stage only the test fixture changes
git commit -m "#21 test: drop legacy role='primary' from fixtures"
```

(Skip if no stragglers.)

---

### Task 9: Regenerate SDK + update hand-written wrappers

**Files:**
- Modify: `clients/python/pyproject.toml`
- Regenerate: `clients/python/src/archiver_client/generated/`
- Modify: `clients/python/src/archiver_client/client.py`
- Modify: `clients/python/tests/`

- [ ] **Step 1: Bump SDK version**

`clients/python/pyproject.toml` — change `version = "2.2.0"` to `version = "3.0.0"`.

- [ ] **Step 2: Regenerate from current OpenAPI**

```bash
bash clients/python/scripts/regen.sh
```

Expected: `clients/python/src/archiver_client/generated/` rewritten. Inspect the diff on `models/info_item_source_create.py` and `models/info_item_source_out.py` — `role` should now be optional and the create model should use the enum.

- [ ] **Step 3: Update the hand-written wrapper**

In `clients/python/src/archiver_client/client.py`, change the `add_info_source` signature:

```python
    async def add_info_source(
        self,
        info_item_id: str,
        info_source_id: str,
        role: Literal["cross_check", "sub_aspect"] | None = None,
    ) -> InfoItemSourceOut:
        """Bind an InfoSource to an InfoItem.

        ``role`` is ``None`` (default) for a root-shaped InfoSource — the
        InfoItem's primary, exactly one active per InfoItem. Pass
        ``'cross_check'`` or ``'sub_aspect'`` for a fragment-shaped
        InfoSource that shares the primary's root.
        """
        body = InfoItemSourceCreate(
            info_source_id=info_source_id,
            role=role if role is not None else UNSET,
        )
        response = await _add_info_source.asyncio_detailed(
            client=self._gen_client, info_item_id=info_item_id, body=body
        )
        return _unwrap(response)
```

(Confirm exact `UNSET` import path from the existing module top.)

- [ ] **Step 4: Update SDK tests**

```bash
rg "role\s*=\s*['\"]primary['\"]" clients/python/tests/
```

For each hit, drop the kwarg or change to `role=None` / a fragment role as appropriate to the test's intent.

- [ ] **Step 5: Run SDK tests**

```bash
cd clients/python
uv run pytest
cd ../..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add clients/python/
git commit -m "#21 feat(sdk): regenerate for nullable role; bump to 3.0.0"
```

---

### Task 10: Bump service version + CHANGELOG + CLAUDE.md

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Bump service version**

`pyproject.toml` — change `version = "2.2.0"` to `version = "3.0.0"`.

- [ ] **Step 2: Prepend CHANGELOG entry**

Insert below the format header, above `## v2.2.0`:

```markdown
## v3.0.0 (2026-05-15)

[both] **Breaking** — `info_item_sources.role` semantics are refactored
(archiver#21). The primary binding is now implicit: the unique active
root-shaped (URL-bearing) binding on an InfoItem is its primary by
construction, with `role IS NULL`. `role` is reserved for fragment-shaped
bindings and takes one of `'cross_check'` (same content, different
selector — used for selector-rot detection) or `'sub_aspect'` (different
content area on the same fetched page — operator-watchable).

The `'primary'` and `'secondary'` role strings are removed. Callers that
sent `role='primary'` get a 422 with `kind=body` (Pydantic Literal
rejection); callers that omitted `role` previously got a 422 (it was
required) and now succeed (defaults to `null`).

**Schema enforcement:**
- DB: `CHECK (role IS NULL OR role IN ('cross_check', 'sub_aspect'))`
  and unique active root binding per InfoItem
  (`uq_info_item_sources_active_root`).
- App: `bind_info_source` validates shape consistency (NULL ↔ root,
  fragment role ↔ fragment source) and that fragment bindings share
  the InfoItem's active root.

**Change-bus payload reshaped.** `SourceRevisionCapturedEvent.info_item_ids:
list[str]` is replaced by `bindings: list[InfoItemBinding]` where each
binding carries `{info_item_id, role}`. Consumers filter on `role` per
their semantics (Replicator typically wants `role IS NULL` only).

**SDK changes:**
- `add_info_source(info_item_id, info_source_id, role=None)` — `role` is
  now optional. Type is `Literal['cross_check', 'sub_aspect'] | None`.
- Regenerated models: `InfoItemSourceCreate.role` and
  `InfoItemSourceOut.role` are nullable; create-side enforces the enum.

**Migration:** Single Alembic revision normalizes existing
`role='primary'` rows to NULL, swaps the partial-unique index, and adds
the CHECK constraint. Pre-prod (no live data), so no compatibility shim.

See archiver#21 and CannObserv/watcher#157 (Watch reshape that this
unblocks).
```

- [ ] **Step 3: Update CLAUDE.md vocabulary**

Find the `**InfoItemSource**` line under the Vocabulary section. Replace with:

```markdown
- **`InfoItemSource`** (`info_item_sources`) — operator-declared
  item↔source binding. The primary binding is implicit: at most one
  active row per InfoItem has `role IS NULL`, and its underlying
  InfoSource is root-shaped. Fragment bindings carry
  `role IN ('cross_check', 'sub_aspect')` and their underlying
  InfoSource's `parent_info_source_id` must equal the primary's
  `info_source_id`.
```

In the same Vocabulary section, add a role table immediately after the
InfoItemSource line:

```markdown
| Role | Meaning | Shape constraint |
|---|---|---|
| `NULL` (primary) | Canonical content selector for the InfoItem. One active per InfoItem. | Root-shaped (URL non-null). |
| `cross_check` | Same content as primary via a different selector. Watcher uses for selector-rot detection. | Fragment-shaped; parent equals active root binding's source. |
| `sub_aspect` | Different content area of the same fetched page. Operator-watchable from Watcher. | Fragment-shaped; parent equals active root binding's source. |
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md CLAUDE.md
git commit -m "#21 docs: bump to 3.0.0; CHANGELOG + CLAUDE.md vocabulary"
```

---

### Task 11: End-to-end smoke + final verification

**Goal:** Confirm the dev server boots, the v2 authoring loop still works end-to-end, and the OpenAPI dump matches the SDK.

- [ ] **Step 1: Restart any running dev server**

If `uvicorn ... --port 8021 --reload` is running, it should pick up the changes; otherwise restart:

> **Historical.** The `uvicorn` invocation below predates `scripts/dev_server.sh` and pointed at the **production** database (2026-07-18 incident). Do not copy it; use `bash scripts/dev_server.sh`.

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

- [ ] **Step 3: Spot-check OpenAPI ↔ SDK alignment**

```bash
uv run python scripts/dump_openapi.py | python -m json.tool | grep -A 12 'InfoItemSourceCreate'
grep -A 8 "class InfoItemSourceCreate" clients/python/src/archiver_client/generated/models/info_item_source_create.py
```

Expected: both reflect the optional enum.

- [ ] **Step 4: Full lint + test sweep one more time**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: all green.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin refactor/iis-role-21
gh pr create --title "#21 refactor: info_item_sources.role — primary becomes implicit; role applies only to fragment bindings" --body "$(cat <<'EOF'
## Summary

- Closes #21.
- DB: `info_item_sources.role` becomes nullable with `CHECK (role IS NULL OR role IN ('cross_check','sub_aspect'))`; partial unique index now keys on `role IS NULL` (one active root binding per InfoItem).
- App: new `src/core/tools/bind_info_source.py` enforces shape consistency and fragment-shares-root.
- Events: `SourceRevisionCapturedEvent.info_item_ids` → `bindings` (list of `{info_item_id, role}`).
- SDK: hard break to v3.0.0; `add_info_source(role=None)`. Service version bumped 1:1.

## Test plan

- [ ] `uv run pytest` is green locally.
- [ ] `uv run alembic downgrade -1 && uv run alembic upgrade head` is round-trip clean against the dev DB.
- [ ] `bash scripts/smoke_phase4.sh` passes against `:8021`.
- [ ] Watcher reshape draft (CannObserv/watcher#157) compiles against this branch's SDK.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Out of scope (defer to follow-up issues)

These were considered and explicitly deferred. Don't bundle into this PR.

1. **Deactivate endpoint for `info_item_sources` bindings + drift policy.** No `DELETE /info-items/{id}/info-sources/{src_id}` exists today; the policy "reject deactivating an active root binding while fragment bindings are active" is documented in the model docstring but unenforced because there's no endpoint to enforce it on. File a follow-up issue when the deactivate path is added.
2. **Additional role values** (`mirror`, `archive`, etc.). The CHECK constraint is forward-extensible; do it in the issue that motivates the new value.
3. **Explicit `content_kind` column on `info_sources`.** Tracked separately per archiver#21's "Out of scope" note.
4. **Watcher's Watch reshape (CannObserv/watcher#157).** Unblocked by this PR but lives in the watcher repo and ships under its own version cadence.
