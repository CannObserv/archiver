# Agent Skills

This project follows the [agentskills.io](https://agentskills.io) spec.

Skills live in `skills/` (agentskills.io) and `.claude/skills/` (Claude Code); overrides in `skills/` shadow the `skills-vendor/` submodules. Layout, triggers and the SessionStart hook rules: the sections below.

## Directory Layout

Two directories serve different discovery systems:

| Directory | Discovery system | Contents |
|---|---|---|
| `skills/` | agentskills.io | Committed overrides + symlinks → `skills-vendor/` |
| `.claude/skills/` | Claude Code | Symlinks → `../../skills/<name>` |

Local overrides in `skills/` automatically shadow vendor skills in both systems. When adding a skill, always create both the `skills/<name>` entry and `.claude/skills/<name>` symlink.

## External Skill Repos (Git Submodules)

| Repo | Submodule path |
|---|---|
| [`gregoryfoster/skills`](https://github.com/gregoryfoster/skills) | `skills-vendor/gregoryfoster-skills/` |
| [`obra/superpowers`](https://github.com/obra/superpowers) | `skills-vendor/obra-superpowers/` |

Init after cloning: `git submodule update --init --recursive`

Submodule freshness auto-enforced by `SessionStart` hook in `.claude/settings.json`. Force-refresh: `git submodule update --remote --merge -- skills-vendor/`

That entry carries `timeout: 120` (archiver#232): one run updates every vendored repo *and* pushes what it commits, and a kill between those two strands the bump on this machine. Restore it with `install-refresh.sh`, never by hand.

To add a new external skill repo: follow the `managing-skills` skill.

### Doctor

`.skills/doctor.sh` diagnoses and self-heals dangling `skills/` symlinks (the
uninitialized-submodule state). It is **committed** so it exists before any
session runs - fresh worktrees, shallow CI clones, first checkouts (archiver#126).
It is a real file copy, not a symlink: a symlinked doctor would itself be
unreachable in exactly the failure mode it repairs. It re-syncs itself from
`skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/doctor.sh` on
every run, and the `SessionStart` hook commits the refreshed copy on `main`.

```bash
bash .skills/doctor.sh --version    # diagnostic version stamp
bash .skills/doctor.sh --verbose    # resolution details even when healthy
bash .skills/doctor.sh --check-only # report only; makes no changes
```

**Required fragments are gated by the suite** (archiver#241). A vendor fences a
block `<!-- skill:required id=… -->` when dropping it reintroduces a fixed
failure; an override is *supposed* to differ, so no diff and no `version:` stamp
sees one go missing. `tests/scripts/test_skill_required_fragments.py` fails on an
override that omits one, or on a stale `omits-required:`. It **delegates** to
`.skills/doctor.sh --check-only` rather than reimplementing the rule (a second
implementation is a second standard); `--check-only` keeps the self-sync above
from dirtying the tree mid-suite. Skips when `skills-vendor/` is absent, as in
CI. Where a fragment cannot apply, declare
`omits-required: "<id>: why"` rather than pasting back a block that cannot run.
Drift in the *rest* of an override is a hand merge; archiver#243 re-synced all
three. How: [docs/CONVENTIONS.md](CONVENTIONS.md).

## Skill Sources

The trigger list of all available skills is **Skill Trigger Inventory** below. Each project skill is sourced from one of:

| Source | Path | Notes |
|---|---|---|
| Local override | `skills/<name>/` | Committed in this repo; supersedes any vendor copy of the same name |
| `gregoryfoster/skills` | `skills-vendor/gregoryfoster-skills/` | Cross-project skills authored for Cannabis Observer |
| `obra/superpowers` | `skills-vendor/obra-superpowers/` | Upstream community skills |

Description-driven skills (`systematic-debugging`, `verification-before-completion`, `test-driven-development`) activate from their description field rather than an explicit trigger phrase - they fire on any bug/test failure, before any completion claim, and before writing implementation code respectively.

## Local Overrides

A committed directory in `skills/` completely supersedes the vendor version (no inheritance). Must be fully self-contained.

| Skill | Override reason |
|---|---|
| `brainstorming` | Project conventions (docs/plans/ path, commit format); invokes using-git-worktrees after design approval; FastAPI stack context; proactive-suggestion mode |

`shipping-work` and `using-git-worktrees` are whole-directory symlinks since archiver#457: what their overrides carried is now `scripts/pre-ship.sh` and `.skills/` knobs (**Ship gate**, below) and **Worktrees**. `reviewing-code` is consumed via a symlink to upstream `reviewing-code-python-fastapi` (FastAPI stack variant) - no override needed. `writing-plans` is consumed via a direct symlink to upstream (vendor now defaults to `docs/plans/`, so the historical override-reason no longer applies).

### Ship gate (`shipping-work`)

The skill resolves each script on its own, so the repo-root `scripts/pre-ship.sh`
replaces only the gate (gregoryfoster/skills#301). It is upstream's wrapper recipe
with two departures (archiver#457). It never reads `/etc/archiver/.env`, which is
root's alone (#339) and would hand a sudo'd test run production's URL. From the repo
`.env`, falling back to the primary checkout's, it exports only `TEST_DATABASE_URL`,
not the PATs beside it (#452). `tests/scripts/test_pre_ship.py` pins both. The knobs,
pinned by `tests/scripts/test_ship_knobs.py`:

| Knob | Value | Why |
|---|---|---|
| `.skills/import-targets` | `src.api.main` | `[project] name` is `archiver`, which names no package; without the knob the import check is skipped |
| `.skills/merge_mode` | `pr` | Work lands through a PR merged on GitHub; the next "ship it" after the merge is the post-merge pass, which runs Step 8 |
| `.skills/deploy_command` | `setsid -w scripts/deploy.sh` | Step 8 offers the deploy once, with the pushed SHA, and runs it only on a yes. An issue about what production runs gets `Refs #N` in the PR and closes after the deploy exits 0 |

No `.skills/test-workers`. pytest-xdist isn't installed, so the gate runs serially.
Before adding it, run the suite shuffled under `-n auto --dist loadfile`: about 23 test
files share one database or Redis, so the right value may be `off`.

### Sensitive paths and advice (`doc-check.sh`)

`.skills/doc-sensitive-paths` is archiver's list for the `shipping-work`
Step 1.5 doc spot-check. Committing it **replaces** the skill's built-in defaults
wholesale (one path per line, `#`-comments ignored) rather than extending them, which
is the supported alternative to forking `doc-check.sh` (gregoryfoster/skills#252,
archiver#190). Entries match whole path *segments* at any depth, so `pyproject.toml`
covers `clients/python/pyproject.toml`; the old start-anchored matcher did not, and a
list that matched nothing printed the same green as a doc-neutral branch.

Archiver's list drops three upstream defaults that match nothing here - `schema.sql`,
`src/models/`, `.env.example` - and every verdict that consulted the list names it, so
a `built-in defaults` line means the file went missing (a bare `No changes vs <ref>.`
never reached the list at all). `tests/scripts/test_doc_sensitive_paths.py` fails on
any entry that stops matching a tracked file, on any changelog-trigger path the list
stops covering (regex read from `scripts/check_changelog_lib.sh`, the gate itself), and
on any entry carrying a glob metacharacter, which bash `case` would expand.

`.skills/doc-sections` is the other half: the advice a hit prints, one doc section per
line, which likewise replaces the skill's two defaults (AGENTS.md's route table, a
README quick start) - archiver#228, upstream gregoryfoster/skills#261. Edit it beside
the list. A repo that tailors only one half gets a hit ending in `Note: this project
tailors …` (gregoryfoster/skills#284). Upstream never checks advice, since it is prose;
`tests/scripts/test_doc_sections.py` fails on any path it names that stops being
tracked, on any `doc "Heading"` pair whose heading is gone, and on a line naming no doc.
Whether a line routes a given list entry stays unchecked: pasting paths in would
satisfy such a test and make the advice worse.

## Worktrees

`using-git-worktrees` is the vendored skill, unmodified (#457). What archiver adds
lives here. Worktrees land in `.worktrees/<branch-slug>`: archiver sets neither
`WORKTREE_ROOT` nor `.skills/worktree_root`, and `.gitignore` covers the default.
Nothing upstream checks that an overridden root is ignored, so an override must
pass `git check-ignore -q <root>` first. That guard is
[gregoryfoster/skills#567](https://github.com/gregoryfoster/skills/issues/567).

**No linked `.venv`: `.skills/worktree_venv` is `none`, committed.** The main
checkout's `.venv` holds two path-bound editable installs: `archiver` and
`archiver-client` (`clients/python/src`). A worktree linked to it imports main's
SDK, and its first `uv run` re-points both installs at the worktree. From then on
every checkout imports that branch, and once the worktree is destroyed `import
archiver_client` fails everywhere until the next `uv sync`. The vendored Phase 3
tells a harness-made worktree (the Agent tool's `isolation: "worktree"`) to
symlink main's `.venv` by hand. **Not here:** provision instead.

**Phase 3, in order:**

1. `uv sync`, after populating the gitignored `./.wheelhouse` by the recipe in
   CLAUDE.md § Environment & Tooling.
2. Copy `.env` from the primary checkout. `scripts/dev_server.sh` reads it from the
   worktree, not just the tests. `scripts/pre-ship.sh` falls back to the primary's
   own copy, but the dev server doesn't.
3. If the branch serves, pick its own port (any free one in 3000-9999, never 8000,
   which is systemd's, or 8001, the main checkout's) and record it in `.port` so
   Phase 5 frees it:
   `echo 8002 > .port; ARCHIVER_DEV_PORT=8002 bash scripts/dev_server.sh &`.
   Never hand-roll uvicorn: on 2026-07-18 a worktree server that did inherited
   production's URL and wrote to the live registry
   ([ENVIRONMENT.md](ENVIRONMENT.md)).

**Phase 4 is a PR** (`.skills/merge_mode` is `pr`): no local merge.

**Phase 5: `--force` only on git's refusal** (`working trees containing submodules
cannot be moved or removed`). Git refuses once the SessionStart doctor has checked
out submodule content in the worktree, which happens in any worktree a session ran
in. `--force` also discards uncommitted changes, and the merged-branch gate never
checks for them, so confirm `git -C <worktree> status --porcelain` is empty first.

## SocratiCode (Codebase Search)

Workflow, tool map, the shared index on `co-index`, and cross-repo search:
[SOCRATICODE.md](SOCRATICODE.md).

## Authoring New Skills

Follow the `writing-skills` TDD cycle:
1. **RED** - run pressure scenarios without the skill; document where the agent fails
2. **GREEN** - write a minimal SKILL.md addressing those failures
3. **REFACTOR** - find new rationalizations, close loopholes, re-test

New project-specific skills go in `skills/<name>/` with a `.claude/skills/<name>` symlink to `../../skills/<name>`. Cross-project skills belong in `gregoryfoster/skills`.

## Skill Trigger Inventory

Which skill fires on which phrase. Invoke by name via the Skill tool.

| Skill | Triggers / when to invoke |
|---|---|
| `reviewing-code-python-fastapi` | CR, code review |
| `reviewing-architecture` | AR, architecture review |
| `enforcing-architecture` | add a fitness function, enforce this contract, lock this rule (delegated to by `reviewing-architecture` on a `fitness` directive) |
| `shipping-work` | ship it, push GH, close GH, wrap up |
| `brainstorming` | brainstorm, design this, let's design |
| `writing-plans` | write plan, implementation plan |
| `writing-skills` | write skill, new skill, author skill |
| `systematic-debugging` | any bug, test failure, unexpected behavior |
| `verification-before-completion` | before any completion claim or commit |
| `test-driven-development` | before writing implementation code |
| `executing-plans` | execute approved plan from docs/plans/ |
| `subagent-driven-development` | dispatch agents for plan execution |
| `dispatching-parallel-agents` | 2+ independent tasks in parallel |
| `using-git-worktrees` | feature work needing isolation (**Worktrees** above) |
| `finishing-a-development-branch` | merge/ship a feature branch |
| `requesting-code-review` / `receiving-code-review` | CR handoff between agents |
| `managing-skills` | add skill repo, manage external skills |
| `orchestrating-issue-backlog` | backlog grooming, issue triage |
| `coordinating-epics` | coordinate the epic, burn down, check-in, I finished #N, next issue. Serial, operator-paced; the coordinator writes no code (epic #357) |
| `using-mayfly-chat` | mayfly, open a channel, join the channel, chat with `<repo>`, agent chat. Never commit a channel URL; nothing here guards it, so run the skill's leak check first |
| `using-superpowers` | meta - when to invoke superpowers skills |
| `socraticode` (codebase MCP) | see **Code Exploration Policy** in `AGENTS.md` |
| `init-socraticode` | install/re-index SocratiCode; owns its two SessionStart hooks |


## SessionStart Hooks

Wired in `.claude/settings.json`; each script is a symlink into `skills-vendor/`.
Never re-copy one, never symlink the committed `.skills/doctor.sh`, and never
un-wire a hook to hold a submodule - pin it in `.skills/skills-pin`.
`tests/scripts/test_claude_hooks_registered.py` fails when a script and
`settings.json` disagree, and when the refresh or health hook loses its 120s
`timeout`. Each hook and its logs: below.

> **The 2026-08-06 suspension is over (archiver#163).** The hook's
> `.claude/settings.json` entry was removed under archiver#131, which asked this
> repo to hold `skills-vendor/gregoryfoster-skills` at `curating-context` v1.2
> (`3fc7b71`) as the control arm of the cohort experiment. That experiment
> retired the wave A/B split on 2026-08-17
> ([gregoryfoster/skills#168](https://github.com/gregoryfoster/skills/issues/168),
> jointly with [#118](https://github.com/gregoryfoster/skills/issues/118)):
> `wave:`/`pair:` are now rollout *staging*, never an assignment in force, and a
> run's arm is the `skill_version` on its own telemetry row. With no version to
> hold, the hold had nothing left to protect and the entry was restored on
> 2026-08-19.
>
> Should a future hold be needed, do **not** un-wire the hook again - that also
> stops the `obra-superpowers` refresh and the `.skills/doctor.sh` self-heal, and
> it fails silently, which is exactly how twelve days passed unnoticed. Use the
> per-submodule pin instead
> ([gregoryfoster/skills#100](https://github.com/gregoryfoster/skills/issues/100),
> landed 2026-08-11): a committed `.skills/skills-pin` line,
> `skills-vendor/gregoryfoster-skills <commit-ish>`, which the hook consults and
> logs. Note `submodule.<name>.update = none` is *not* an alternative: the hook
> passes `--merge`, which git documents as overriding that setting (verified
> empirically; a pathspec alone does not override it either).

`.claude/settings.json` wires three `SessionStart` hooks (see `.claude/hooks/`).
Both halves are load-bearing: a script sitting in `.claude/hooks/` that
`settings.json` does not name never runs, and looks identical to one that
works. `tests/scripts/test_claude_hooks_registered.py` asserts the two halves
agree, so that state fails a test instead of going unnoticed (archiver#163).

- `socraticode-reminder.sh` - prints the deferred-tool prefetch query for
  SocratiCode MCP tools. **Symlink** into
  `skills-vendor/gregoryfoster-skills/skills/init-socraticode/scripts/`
  (archiver#184). It was a hand-typed copy from 2026-05-07 until then: before
  [gregoryfoster/skills#186](https://github.com/gregoryfoster/skills/issues/186)
  the hook had no vendored source at all, so every consumer's copy was whatever
  the installing agent typed that day. The query it prints has to stay identical
  to the skill's own template, and it carries no per-project state - which is
  precisely the argument for linking rather than copying. Same installer, same
  two artifacts; its dedupe markers (`socraticode-prefetch` canonical,
  `socraticode-reminder` legacy) are distinct from the health hook's so one
  hook's strip cannot evict the other's entry from the array they share.
- `socraticode-health.sh` - **symlink** into
  `skills-vendor/gregoryfoster-skills/skills/init-socraticode/scripts/`
  (archiver#184). Once-per-day infra check: graph edge yield, `codebase_health`,
  a failed last operation, and - the reason it was wired here - whether every
  artifact declared in `.socraticodecontextartifacts.json` is actually indexed.
  Adding an artifact to that manifest does not index it, and nothing else
  notices: `codebase_context_search` answers from indexed artifacts only, with
  no error and no warning for the missing one, while `codebase_status` stays
  green. Installed by `init-socraticode` via `managing-skills`'
  `scripts/install-hook.sh`, never by hand. It **reports; it never repairs** - a
  SessionStart hook that kicked off a two-hour re-index would be worse than the
  drift it found. Silent when clean, which is why a copy is unacceptable here:
  a frozen copy that has stopped detecting anything looks exactly like a healthy
  install ([gregoryfoster/skills#179](https://github.com/gregoryfoster/skills/issues/179)).
  Since `d04cebf` it also reports the trap-1 half of
  [cross-repo search](SOCRATICODE.md#cross-repo-search) -
  `linkedProjects — N of M resolved (missing: …)`, read the way
  `loadLinkedProjects()` reads it - and, past the manifest gate, says so out loud
  on a host with no `node` instead of skipping in silence
  ([gregoryfoster/skills#281](https://github.com/gregoryfoster/skills/issues/281):
  9 days, 5 sessions, 0 session lines). It cannot tell whether a link that *does*
  resolve was ever indexed. Log: `.git/socraticode-health.log`. It caps its own
  check in a user-systemd scope ([gregoryfoster/skills#330](https://github.com/gregoryfoster/skills/issues/330)),
  and through the pinned pre-install installs nothing ([SOCRATICODE.md](SOCRATICODE.md#repo-specific-notes)).
- `skills-submodule-update.sh` - **symlink** into
  `skills-vendor/gregoryfoster-skills/skills/managing-skills/scripts/` (archiver#126),
  so upstream fixes arrive with the normal submodule refresh. Never re-copy it -
  a copy freezes at the version it was taken from, which is how this repo ran a
  hook predating the doctor for months. Once-per-day refresh scoped to
  `skills-vendor/`. Lock file: `.git/skills-update.lock` (holds the UTC
  `YYYYMMDD` stamp). Log: `.git/skills-update.log` (auto-rotates at 64 KiB →
  last 200 lines). **Auto-commits only on `main`**, staging exactly
  `skills-vendor/` and `.skills/doctor.sh` - never `.skills/` wholesale, which
  would absorb operator config. The commit message names what changed
  (`chore: update skills submodules`, `chore: refresh .skills/doctor.sh`, or
  both). On a feature branch it stops at the branch gate - before the fetch and
  before stamping the lock - so only the `.skills/doctor.sh` self-heal above it
  runs there. Network failures are logged and don't block session start.
  Descended from watcher's hook
  (CannObserv/watcher#153 → CannObserv/archiver#8).

**`.skills/doctor.sh` is committed** (archiver#126). It is a real file copy, not
a symlink - deliberately, since a symlink would dangle in exactly the
uninitialized-submodule state the doctor exists to repair. Committing it is what
makes it present in a fresh `git worktree add`, a shallow CI clone, and a new
contributor's first checkout, where the Phase 1 preflight
`{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; }` would otherwise
silently short-circuit. The doctor re-syncs itself from the vendored source on
every run; the hook commits the refreshed copy. Check it with
`bash .skills/doctor.sh --version`.
