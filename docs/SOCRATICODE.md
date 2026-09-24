# SocratiCode

Semantic code search for this repo, and the shared store behind it.
`AGENTS.md` "Code Exploration Policy" carries the rule; skills and the
SessionStart hooks that run here: [SKILLS.md](SKILLS.md).

This project is indexed with SocratiCode. Always use its MCP tools to explore the codebase before reading files directly.

**Core principle: search before reading.** The index gives you a map of the codebase in milliseconds; raw file reading is expensive and context-consuming.

## Workflow

1. **Start most explorations with `codebase_search`.** Hybrid semantic + keyword (vector + BM25, RRF-fused) in a single call. Broad queries for orientation ("how is auth handled"), precise queries for symbol lookup. **Use grep instead** when you already know the exact identifier, error string, or regex pattern.
2. **Follow the graph before following imports.** Use `codebase_graph_query` to see what a file imports and what depends on it before opening it. Check dependents before modifying or deleting.
3. **Use Impact Analysis BEFORE refactoring/renaming/deleting.** Symbol-level call graph (`codebase_impact`, `codebase_flow`, `codebase_symbol`, `codebase_symbols`) goes deeper than the file graph - it knows which functions call which.
4. **Read files only after narrowing via search.** Never read a file just to find out if it's relevant.
5. **Use `codebase_graph_circular`** when debugging unexpected behavior or import-related errors.
6. **Check `codebase_status`** if search returns no results - the project may not be indexed yet.
7. **Leverage context artifacts** for non-code knowledge (DB schemas, API specs, infra configs). Run `codebase_context` early; use `codebase_context_search` for specific schemas/endpoints.

## When to use each tool

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

## Quick reference - the archiver-specific tool map

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

## The shared index on `co-index`

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

## Cross-repo search

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
`[archiver]` / `[watcher]` / … label. Search the siblings for callers before
changing a public schema or the API contract. Watcher no longer depends on the
`archiver-client` SDK (CannObserv/watcher#254); it reads the bus.

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
