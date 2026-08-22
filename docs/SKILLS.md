# Agent Skills

This project follows the [agentskills.io](https://agentskills.io) spec.

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

## Skill Sources

For the trigger list of all available skills, see the **Agent Skills** table in `AGENTS.md`. Each project skill is sourced from one of:

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
| `shipping-work-python-fastapi` | Thin override - sources `/etc/archiver/.env` + `$PROJECT_ROOT/.env` via `set -a; source; set +a` before delegating to upstream pre-ship; other scripts symlinked back to vendor |
| `brainstorming` | Project conventions (docs/plans/ path, commit format); invokes using-git-worktrees after design approval; FastAPI stack context; proactive-suggestion mode |
| `using-git-worktrees` | Archiver-specific dev port (8021) and env file (`/etc/archiver/.env`); auto-starts uvicorn on 8021; systemd `archiver.service` on 8020 |

`reviewing-code` is consumed via a symlink to upstream `reviewing-code-python-fastapi` (FastAPI stack variant) - no override needed. `writing-plans` is consumed via a direct symlink to upstream (vendor now defaults to `docs/plans/`, so the historical override-reason no longer applies).

## SocratiCode (Codebase Search)

This project is indexed with SocratiCode. Always use its MCP tools to explore the codebase before reading files directly.

**Core principle: search before reading.** The index gives you a map of the codebase in milliseconds; raw file reading is expensive and context-consuming.

### Workflow

1. **Start most explorations with `codebase_search`.** Hybrid semantic + keyword (vector + BM25, RRF-fused) in a single call. Broad queries for orientation ("how is auth handled"), precise queries for symbol lookup. **Use grep instead** when you already know the exact identifier, error string, or regex pattern.
2. **Follow the graph before following imports.** Use `codebase_graph_query` to see what a file imports and what depends on it before opening it. Check dependents before modifying or deleting.
3. **Use Impact Analysis BEFORE refactoring/renaming/deleting.** Symbol-level call graph (`codebase_impact`, `codebase_flow`, `codebase_symbol`, `codebase_symbols`) goes deeper than the file graph - it knows which functions call which.
4. **Read files only after narrowing via search.** Never read a file just to find out if it's relevant.
5. **Use `codebase_graph_circular`** when debugging unexpected behavior or import-related errors.
6. **Check `codebase_status`** if search returns no results - the project may not be indexed yet.
7. **Leverage context artifacts** for non-code knowledge (DB schemas, API specs, infra configs). Run `codebase_context` early; use `codebase_context_search` for specific schemas/endpoints.

### When to use each tool

| Goal | Tool |
|------|------|
| Understand what a codebase does / where a feature lives | `codebase_search` (broad query) |
| Find a specific function, constant, or type | `codebase_search` (exact name) or grep if you know the exact string |
| Find exact error messages, log strings, or regex patterns | grep / ripgrep |
| See what a file imports or what depends on it | `codebase_graph_query` |
| Check blast radius before modifying or deleting a file | `codebase_impact` (symbol-level) or `codebase_graph_query` (file-level) |
| What breaks if I change function X? | `codebase_impact target=X` |
| What does this entry point actually do? | `codebase_flow entrypoint=X` |
| List entry points in this codebase | `codebase_flow` (no args) |
| Who calls this function and what does it call? | `codebase_symbol name=X` |
| What functions/classes exist in this file? | `codebase_symbols file=path` |
| Search for symbols by name across the project | `codebase_symbols query=X` |
| Spot architectural problems | `codebase_graph_circular`, `codebase_graph_stats` |
| Visualise module structure | `codebase_graph_visualize` |
| Verify index is up to date | `codebase_status` |
| Discover what project knowledge (schemas, specs, configs) is available | `codebase_context` |
| Find database tables, API endpoints, infra configs | `codebase_context_search` |

### Quick reference - the archiver-specific tool map

Condensed from the table above, in the form the policy file carried until the
2026-08-11 curation. `AGENTS.md` keeps only the negative rule and points here.

| Goal | Tool |
|------|------|
| Where is X defined / how does Y work / what files touch Z | `codebase_search` |
| Exact string/regex match (errors, log lines, known symbols) | `grep` / `rg` |
| Blast radius of changing/deleting a file or function | `codebase_impact` |
| What does an entry point actually do? | `codebase_flow` |
| Callers and callees of a function | `codebase_symbol` |
| List symbols in a file or search by name across the project | `codebase_symbols` |
| Imports/dependents of a file | `codebase_graph_query` |
| Spot circular deps or structural issues | `codebase_graph_circular`, `codebase_graph_stats` |
| Visualise module structure | `codebase_graph_visualize` |
| Verify index is up to date | `codebase_status` |
| DB schemas, deployment topology, runbook context | `codebase_context` / `codebase_context_search` |

Prefetch query (run via `ToolSearch` once per session if the SessionStart reminder isn't loaded):

`select:mcp__plugin_socraticode_socraticode__codebase_search,mcp__plugin_socraticode_socraticode__codebase_symbol,mcp__plugin_socraticode_socraticode__codebase_symbols,mcp__plugin_socraticode_socraticode__codebase_flow,mcp__plugin_socraticode_socraticode__codebase_impact,mcp__plugin_socraticode_socraticode__codebase_graph_query,mcp__plugin_socraticode_socraticode__codebase_graph_circular,mcp__plugin_socraticode_socraticode__codebase_graph_stats,mcp__plugin_socraticode_socraticode__codebase_graph_visualize,mcp__plugin_socraticode_socraticode__codebase_status,mcp__plugin_socraticode_socraticode__codebase_context,mcp__plugin_socraticode_socraticode__codebase_context_search`

> **Keep the connection alive during indexing.** Indexing runs in the background. Some MCP hosts disconnect idle connections. Call `codebase_status` roughly every 60 seconds after starting `codebase_index` until it completes.

### Linked Projects

Cross-project search to the sister repos is enabled via `SOCRATICODE_LINKED_PROJECTS=/home/exedev/watcher,/home/exedev/notifier` in `.claude/settings.local.json` (gitignored - per-instance config, not a project commitment). **Paths are comma-separated** (not colon-separated PATH-style - the plugin splits on `,` only; a colon-joined value is parsed as a single literal path and silently resolves to nothing). Values may be relative (resolved from the project root) or absolute; absolute is recommended since the MCP server's CWD isn't guaranteed across hosts. Pass `includeLinked: true` on `codebase_search` to fan out across all indexes; results carry a `[archiver]` / `[watcher]` / `[notifier]` label.

Watcher is archiver's primary consumer (via the `archiver-client` SDK installed as a path dependency in watcher). When changing public schemas or the API contract, search the linked watcher index for callers before merging.

Upstream reference: [giancarloerra/socraticode#agent-instructions](https://github.com/giancarloerra/socraticode#agent-instructions)

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
| `shipping-work-python-fastapi` | ship it, push GH, close GH, wrap up |
| `brainstorming` | brainstorm, design this, let's design |
| `writing-plans` | write plan, implementation plan |
| `writing-skills` | write skill, new skill, author skill |
| `systematic-debugging` | any bug, test failure, unexpected behavior |
| `verification-before-completion` | before any completion claim or commit |
| `test-driven-development` | before writing implementation code |
| `executing-plans` | execute approved plan from docs/plans/ |
| `subagent-driven-development` | dispatch agents for plan execution |
| `dispatching-parallel-agents` | 2+ independent tasks in parallel |
| `using-git-worktrees` | feature work needing isolation (dev port 8021) |
| `finishing-a-development-branch` | merge/ship a feature branch |
| `requesting-code-review` / `receiving-code-review` | CR handoff between agents |
| `managing-skills` | add skill repo, manage external skills |
| `orchestrating-issue-backlog` | backlog grooming, issue triage |
| `using-superpowers` | meta - when to invoke superpowers skills |
| `socraticode` (codebase MCP) | see **Code Exploration Policy** in `AGENTS.md` |
| `init-socraticode` | install/re-index SocratiCode; owns its two SessionStart hooks |


## SessionStart Hooks

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

- `socraticode-reminder.sh` - prints the deferred-tool prefetch query for SocratiCode MCP tools.
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
  Log: `.git/socraticode-health.log`.
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
