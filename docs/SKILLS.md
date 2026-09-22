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
| `shipping-work-python-fastapi` | Thin override - sources `/etc/archiver/.env` + `$PROJECT_ROOT/.env` via `set -a; source; set +a` before delegating to upstream pre-ship; other scripts symlinked back to vendor. Step 1.5 documents archiver's `.skills/doc-sensitive-paths` and `.skills/doc-sections` (below) |
| `brainstorming` | Project conventions (docs/plans/ path, commit format); invokes using-git-worktrees after design approval; FastAPI stack context; proactive-suggestion mode |
| `using-git-worktrees` | Archiver-specific Phase 3 only; scripts and `references/` symlinked back to vendor. Own `ARCHIVER_DEV_PORT` per worktree recorded in `.port` (8001 is *main's*, 8000 systemd's) via `scripts/dev_server.sh`, never hand-rolled uvicorn; `.skills/worktree_venv` is `none` (this checkout is `archiver.service`'s `WorkingDirectory`) |

`reviewing-code` is consumed via a symlink to upstream `reviewing-code-python-fastapi` (FastAPI stack variant) - no override needed. `writing-plans` is consumed via a direct symlink to upstream (vendor now defaults to `docs/plans/`, so the historical override-reason no longer applies).

### Sensitive paths and advice (`doc-check.sh`)

`.skills/doc-sensitive-paths` is archiver's list for the `shipping-work-python-fastapi`
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

Prefetch query: the SessionStart reminder hook prints it, and
`.claude/hooks/socraticode-reminder.sh` is the one copy of it in this repo. To
run it by hand, take the string that hook emits:

```bash
bash .claude/hooks/socraticode-reminder.sh
```

It is not transcribed here on purpose. The hook is a symlink into
`skills-vendor/`, so upstream can change which tools the query selects; a second
copy in this doc would go stale silently, and the doc copy is the one an operator
reads (archiver#184 CR).

> **Keep the connection alive during indexing.** Indexing runs in the background. Some MCP hosts disconnect idle connections. Call `codebase_status` roughly every 60 seconds after starting `codebase_index` until it completes.

### The shared index on `co-index` (archiver#226)

This repo does **not** host its index. Qdrant and Ollama run on a fifth cohort VM,
`co-index` (`index` on the tailnet); nothing is embedded locally and there is no
Docker image to keep. Two committed files are the whole client contract, and
`tests/deploy/test_socraticode_config.py` pins both:

- **`.socraticode.json`** - `projectId: archiver` names the collections
  (`codebase_archiver`, `archiver_symgraph_file`, …) so every checkout and every
  worktree addresses the same ones. Without it the id is `sha256(abs_path)[:12]`,
  which is why this repo's collections were `…7a9d625938ee` before adoption.
- **`.claude/settings.json`** `env` - the six non-secret client variables
  (`QDRANT_MODE`/`QDRANT_URL`, `OLLAMA_MODE`/`OLLAMA_URL`, `EMBEDDING_MODEL`,
  `EMBEDDING_DIMENSIONS`). Committed on purpose: self-documenting, and they
  travel with the checkout.

`QDRANT_API_KEY` is the one per-host value and lives in
`.claude/settings.local.json`, git-ignored by `.gitignore:11`. Install it with
notifier's `scripts/install_qdrant_key.sh`, never by hand - the key travels on
**stdin**, since an argument is visible in `ps` and lands in shell history.
Expect `installed 64 chars`; any other length is a truncated transfer, which
401s exactly like a wrong key. Qdrant holds a single global `service.api_key`,
so a leak anywhere is a rotation everywhere with no overlap window
(CannObserv/notifier#57).

Four traps, each of which reports itself as green:

| Trap | Symptom |
|---|---|
| `QDRANT_HOST` instead of `QDRANT_URL` | fallback builds https against port **16333**; reads as a network fault |
| short MagicDNS name | `index` is not in the certificate SAN - TLS is mandatory because the key is refused over plain http |
| `QDRANT_COLLECTION_PREFIX` | prepended to the *global* `socraticode_metadata` too; one VM setting it splits the cohort namespace |
| `SOCRATICODE_BRANCH_AWARE=true` | a fresh six-collection set per branch, re-indexed from empty |

The `env` block applies **only in a trusted folder**. Untrusted, `QDRANT_MODE`
reverts to `managed` - and what happens next depends on whether this host still
has Docker. **It does not**: the managed stack was removed at adoption and
`docker.socket`, `docker.service` and `containerd` are all disabled, so the
revert now fails loudly, which is the only reason that revert is survivable.
Confirm with `codebase_health` that it names the external endpoints and not a
container.

**Do not reinstate a local managed store while this repo is adopted.** During
adoption, with the containers still up, the running managed-mode server
re-indexed under the newly-declared `projectId` and produced a *second*
`codebase_archiver` - 3204 points locally against 4162 on co-index, and
`context_archiver` 204 against 541. Two collections, one name, different stores.
A folder-trust revert then answers from the stale local one: well-formed reply,
real file paths, ~23% of the index missing, no warning at either layer. A green
`codebase_search` is not evidence of *which store* answered. Reported to the
repos that have not adopted yet (CannObserv/replicator#92,
CannObserv/watcher#300); the ordering that avoids it is to stop the managed
server **before** adding `.socraticode.json`.

Note also that an already-running MCP server never picks up a changed `env`
block - the server that indexes must be started after it exists, which means a
fresh session or an out-of-band launch.

Indexing is the memory-hungry step, and this VM shares 3.9 GB with the
production service on port 8000. Run long index jobs capped; broker took a
production VM down by launching one uncapped (CannObserv/broker#17, #27). The
full index of this repo cost 50 min wall under:

```bash
systemd-run --user --scope -p MemoryHigh=1200M -p MemoryMax=1536M -p CPUQuota=100% \
  choom -n 500 -- node \
  skills-vendor/gregoryfoster-skills/skills/init-socraticode/scripts/mcp-driver.mjs index
```

`choom -n 500` matters: it makes the index job a *more* attractive OOM target
than the production service, which sits at adj 0. Memory never dropped below
1.4 GB free and the bus was unaffected. That driver also carries `validate-store`
and `validate-manifest`, which check the config with no server and no network -
run them before an index rather than after a failure.

### Cross-repo search

`linkedProjects` lists the four sibling repos as `../<name>`. Each resolves to a
**link stub** on this VM - a directory holding one `.socraticode.json`, not a
clone:

```
/home/exedev/<sibling>/.socraticode.json   →  { "projectId": "<sibling>" }
```

`includeLinked` uses the path for exactly two things: reading that `projectId` to
build a collection name, and `basename` for the result label. No path reaches
the search itself - content comes wholly from Qdrant. A stub is therefore
sufficient, and *safer* than a clone: a real checkout carries the sibling's own
config, so if that repo changes its `projectId` the stale clone silently
resolves to the old collection.

Pass `includeLinked: true` on `codebase_search` to fan out; results carry a
`[archiver]` / `[watcher]` / … label. Watcher is archiver's primary consumer (via
the `archiver-client` SDK, a path dependency there), so search it for callers
before changing a public schema or the API contract.

**Two silent-skip modes, neither visible in a tool result.** `loadLinkedProjects`
filters on `fs.existsSync` with no warning, so a missing stub is dropped -
notifier searched one repo instead of four for weeks this way. And
`searchMultipleCollections` catches per-collection failures and logs them to the
server's stderr, so a collection that is missing, unindexed, or written in a
*newer* `indexFormatVersion` than the client returns zero rows and reports
nothing (CannObserv/broker#17). A green result is not evidence every sibling
answered. The daily health hook reports the first half as
`linkedProjects — N of M resolved`; the second half stays unchecked.

This replaces the pre-#226 mechanism, `SOCRATICODE_LINKED_PROJECTS` set to
absolute paths in `.claude/settings.local.json` - a per-host value that only
worked while all four services shared one box.

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
| `using-git-worktrees` | feature work needing isolation (own dev port, not 8001) |
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
  Since `d04cebf` it also reports the trap-1 half of cross-repo search -
  `linkedProjects — N of M resolved (missing: …)`, read the way
  `loadLinkedProjects()` reads it - and, past the manifest gate, says so out loud
  on a host with no `node` instead of skipping in silence
  ([gregoryfoster/skills#281](https://github.com/gregoryfoster/skills/issues/281):
  9 days, 5 sessions, 0 session lines). It cannot tell whether a link that *does*
  resolve was ever indexed. Log: `.git/socraticode-health.log`.
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
