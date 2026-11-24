# archiver — Browser tests

**The `browser` tier: headless Chromium against the app on a loopback port, for
what happy-dom cannot see (archiver#546).** Layout at a given width, the keyboard
path, focus, real taps, boosted navigation. On #400 two defects passed every
vitest test and failed only in Chromium: `focus()` refused while a `visibility`
transition still read `hidden`, and a real tap's `mousedown` moving focus (and
closing the drawer) before its `click`. `tests/js/` stays the fast inner loop;
this tier is the few checks only a browser can make.

## Run it

```bash
bash scripts/install_browser.sh              # once per host; a rerun downloads nothing
uv run --group browser pytest tests/browser -m browser
```

Without the `browser` group the run fails on `tests/browser/conftest.py`'s
import, never a skip. `-m browser` alone works too but collects the whole suite
first; `pytest tests/browser/test_server.py` runs one file. `uv run` syncs inexactly, so later plain `uv run`s keep the group; a bare
`uv sync` removes it.

## How it is gated

- **Collected only when `-m` selects `browser`, or a command-line path names
  something under `tests/browser/`** (`pytest_ignore_collect` in
  `tests/conftest.py`; pytest never consults it for a named file). Not by `addopts`: a command-line `-m` replaces that
  expression, so CI's `-m "not integration"` would bring the tier back
  (power-map #304). A run that never asked never imports Playwright.
- **Pre-ship never runs it,** like `integration`. Run it by hand when a change
  touches dashboard JS, CSS or layout.
- **CI runs it on every PR and push to `main`,** in the `browser` job, beside
  `test`, with `timeout-minutes: 15`. `scripts/deploy.sh`'s gate fails on any
  job that did not pass, so the tier gates deploys without a `CI_JOBS` entry.
- **The group:** `playwright` is in its own `browser` dependency group, never
  `dev` (every job and pre-ship would sync a 53 MB wheel) and never a default
  group (`deploy.sh` syncs `--no-dev`, which drops `dev` alone).

## Where the browser lives

| | |
|---|---|
| Pin | `playwright>=1.65.2,<1.66` in `pyproject.toml`; the lock holds 1.65.2 |
| Build | `chromium-headless-shell` v1255 (Chrome for Testing 159.0.8154.6) + `ffmpeg` v1013 |
| Path | `~/.cache/ms-playwright/` (or `PLAYWRIGHT_BROWSERS_PATH`): one per host, every worktree shares it |
| Size | 287 MB on disk |

Each Playwright minor pins a new build, hence the cap. **A bump:** raise the
cap, `uv lock -P playwright`, run `install_browser.sh`, update this table. That
deploys (`pyproject.toml` and `uv.lock` are drift runtime files), though the
release venv never holds Playwright. Dependabot covers Actions only, so nothing
bumps it unasked.

**Stale builds remove themselves.** Playwright records each venv that installs
(`~/.cache/ms-playwright/.links/`) and, on every install, deletes the builds no
live venv still links to. A bump retires the old build at the next
`install_browser.sh` run, once no worktree venv on the old version remains;
`--no-remove` keeps them. That sweep retired the hand-placed `chromium-1234`
builds (656 MB, from a deleted scratch venv) on 2026-11-24. The host disk GC has
no tier for this cache and needs none.

## The harness (`tests/browser/`)

- **`live_server`** (session): `uvicorn src.api.main:app` in a subprocess on a
  kernel-assigned 127.0.0.1 port, never 8000 or 8001
  (`tests/browser/server.py`). It inherits the `ARCHIVER_DATABASE_URL` pin and
  the outbound-env scrub of `tests/conftest.py`, refuses a database not named
  `*_test`, and drops `GH_TOKEN*`. Its `cwd` is the tree under test, so a `git
  archive` of an old commit serves its own `src/`.
- **Teardown:** terminate, then kill; it depends on `test_engine`, so it is
  down before the schema drops. `PR_SET_PDEATHSIG` kills the server when pytest
  dies without teardown (SIGKILL). `test_server.py` tests both paths, the port,
  and that the server's database connections are gone.
- **`browser`** (session): one headless Chromium. **`open_page(path, width=,
  has_touch=, reduced_motion=, color_scheme=)`**: a fresh context with the
  dashboard's `X-ExeDev-*` identity and a 5 s default timeout.
- **Seeds:** a test commits its own rows and deletes them (see
  `test_register_overflow.py`); the server sees no savepoint. The `AppUser` an
  authed GET upserts is deleted at session end.

## Writing a test

Keep the tier small: a server start is about 4 s and a check under 1 s. Each
test is red first on the tree before its fix. Prove it on a `git archive` of
that commit with the tier overlaid: copy `tests/conftest.py` and
`tests/browser/` into the archive, then run this checkout's
`.venv/bin/python -m pytest tests/browser -m browser` from inside it. The seed
suite's evidence (#546):

| Tree | Red |
|---|---|
| `a7dfc25f` (before #400) | the 5 phone-width drawer tests: no drawer |
| `50a3d5b2` (before #400 CR 1) | the 2 dismissing-tap tests: the tap requested `/info-items/new` |
| `main` with `visibility` back in `.sidebar[data-open]`'s transition | the 2 tests that open by key or toggle: `focus()` refused |
| `7cac5ee0` (before #484) | register step 2: page overflow 119 px at 1280, 631 at 768 |
| `main` | none |

## What stays manual

The proxy path (#400's host step 9). A harness on this VM cannot drive
`https://co-registrar.exe.xyz/`: the VM resolves its own hostname to eth0 via
`/etc/hosts`, 8000 and the dev server bind `127.0.0.1`, and the proxy's login
cookie is host-only and stripped before the app. A real-device or off-VM check
stays an operator step; this tier covers everything behind the proxy.
