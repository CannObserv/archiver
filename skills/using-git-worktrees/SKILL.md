---
name: using-git-worktrees
description: A workflow for parallel branch checkouts via `git worktree`. Standardizes creation, lifecycle, and cleanup so multiple branches can be worked on simultaneously without colliding. Use when the user says "create worktree", "new worktree", "destroy worktree", "merge worktree", or "wt".
compatibility: Designed for the archiver service. Requires git, uv, and `lsof` for port cleanup in Phase 5. Worktree provisioning is the vendor's; Phase 3 is archiver-specific (dev server on a per-worktree port, env sourcing, `.venv` opt-out).
metadata:
  author: gregoryfoster
  version: "1.0"
  triggers: create worktree, new worktree, destroy worktree, merge worktree, wt
  overrides: gregoryfoster-skills/using-git-worktrees
  synced-from: "gregoryfoster-skills 1.0 (d3f91c8)"
  override-reason: "Archiver-specific Phase 3 — `.skills/worktree_venv` is `none` here because the main checkout is archiver.service's WorkingDirectory; the dev server runs on a per-worktree ARCHIVER_DEV_PORT via scripts/dev_server.sh (never hand-rolled uvicorn, see the 2026-07-18 production-write incident); env files load via `set -a; . <file>; set +a`, not the broken `export $(cat … | xargs)` pattern. Phase 5 names when --force is actually required here: once the SessionStart doctor has checked out submodule content inside the worktree, not merely because the repo has submodules."
---

# Using Git Worktrees

A workflow for parallel branch checkouts via `git worktree`. Standardizes creation, lifecycle, and cleanup so multiple branches can be worked on without colliding.

**Activation triggers:** "create worktree", "new worktree", "destroy worktree", "merge worktree", "wt".

## The Iron Law

```
NO WORKTREE DESTROY WITHOUT VERIFIED MERGE OR EXPLICIT DESCOPE
NO BRANCH CHECKED OUT IN TWO WORKTREES SIMULTANEOUSLY
```

If the branch hasn't been merged (or the user hasn't explicitly waived the merge), you cannot destroy the worktree.
If the target branch is already checked out in another worktree (visible in `git worktree list`), you cannot create another worktree for it — git refuses, and so do we.

## Rationalization prevention

| Thought | Reality |
|---|---|
| "I'll merge later, just destroy it" | Destroy = work loss if commits aren't on a tracked branch. Merge or document descope first. |
| "Same branch in two worktrees is fine, I'll be careful" | Git refuses for a reason — divergent commits race. Use a different branch or a separate clone. |
| "The dev server is still running, but I want to destroy now" | Free the port first. A live process pinning files in the worktree blocks cleanup and leaks state. |
| "Every branch needs a worktree" | Short patches don't. Phase 1 exists to filter; skip it and you pay the overhead for nothing. |
| "The project has no wrapper, I'll just `cd ~/wherever`" | Resolution order is explicit: env var → `.skills/worktree_root` → default. Ad-hoc paths defeat reproducibility. |
| "I'll link the main `.venv` like every other project" | Not here. This checkout is a running service's `WorkingDirectory=` — see **Venv linking** below. |

## Parameterized invocation

Trigger phrases may include the target branch inline — e.g., `create worktree feature/foo`, `wt feature/foo`, `destroy worktree feature/foo`. Apply the appended branch as the explicit target; skip the "ask for branch name" fallback.

## Script path resolution

The skill's `scripts/` directory is not at the project root — it ships inside the skill. Resolve it once, then substitute the printed path wherever `<SKILL_SCRIPTS>` appears below ([#63](https://github.com/gregoryfoster/skills/issues/63)):

<!-- skill:required id=skill-scripts -->
```bash
N=using-git-worktrees S=resolve-worktree-root.sh SD=
for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
  [ -f "$d/$S" ] && { SD="$d"; break; }
done
echo "SKILL_SCRIPTS=${SD:?not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/}"
```

In this repo it resolves to `.claude/skills/using-git-worktrees/scripts`, which symlinks into `skills-vendor/gregoryfoster-skills/`. The loop's first candidate — a bare `scripts/` — is **archiver's own** `scripts/` directory (`dev_server.sh`, `sync_wheelhouse.py`); it holds none of the five worktree scripts, so the loop passes over it correctly. `<SKILL_SCRIPTS>` is a **placeholder** for the literal path printed here, not an inherited shell variable — each Bash invocation runs in a fresh shell.

## Worktree root resolution

Every operation resolves the worktree directory in this order (first match wins):

1. **`WORKTREE_ROOT` env var** (highest priority) — explicit override for one-off invocations
2. **`.skills/worktree_root` file** — single-line file under the repo root; project's persistent default
3. **`<repo-root>/.worktrees/`** — fallback when neither of the above is set

Archiver sets neither, so worktrees land in `/home/exedev/archiver/.worktrees/<branch-slug>`. Invoke `bash "<SKILL_SCRIPTS>/resolve-worktree-root.sh"` to print the resolved root. The final worktree path is always `<resolved-root>/<branch-slug>`, where `<branch-slug>` is the branch name with `/` replaced by `-` (e.g., `feature/foo` → `feature-foo`).

**Verify the resolved root is ignored before creating anything.** None of the five scripts does this — `worktree-create.sh` will happily create a worktree inside a tracked directory — so it stays a step here:

```bash
ROOT=$(bash "<SKILL_SCRIPTS>/resolve-worktree-root.sh")
case "$ROOT" in
  "$(git rev-parse --show-toplevel)"/*)
    git check-ignore -q "$ROOT" || echo "NOT IGNORED: add $ROOT to .gitignore and commit" ;;
  *) echo "outside the repo — nothing to ignore" ;;
esac
```

`.gitignore` already carries `.worktrees/`, so the default root passes. The check is not therefore redundant: it is the only guard on the two paths that *override* that default, `WORKTREE_ROOT` and `.skills/worktree_root`, and an unignored root commits an entire second checkout into the repo. The `case` matters — `git check-ignore` exits non-zero for *any* unmatched path, so a root outside the repo (where no rule is needed or possible) would otherwise report a false `NOT IGNORED` and teach you to skip the one check with no upstream substitute.

## Venv linking — `.skills/worktree_venv` is `none` here

A worktree inherits no virtualenv, so `worktree-create.sh` normally symlinks the main checkout's `.venv` into it. **Archiver turns that off**, and the file recording it is **committed** — deliberately against the vendor's default advice ("commit it only if it holds for every clone"), because the asymmetry runs one way here: uncommitted, a fresh clone *on this host* silently reinstates the corruption below, while the cost anywhere else is a clone running `uv sync` instead of linking.

```bash
cat .skills/worktree_venv    # none
```

This is the upstream-documented case where linking is wrong: the main checkout is a running service's `WorkingDirectory=`, so the symlink would hand every worktree one shared *mutable* environment while isolating it in every other respect. Both symptoms are live here:

- `deploy/archiver.service` — `WorkingDirectory=/home/exedev/archiver`, `ExecStart=uv run uvicorn …`. `uv run` reinstalls the project, restamping the `importlib.metadata.version(...)` that `src/api/main.py` reads to *main's* version.
- `deploy/archiver-bus-health.service`, fired by `archiver-bus-health.timer` — `uv run python -m src.core.bus_health` from that same directory, on a schedule. It restamps the shared environment *while a worktree suite is running*, so the failure appears in a full run and vanishes in isolation.

The hazard runs both ways: a worktree's own `uv sync` mutates what the live workers import from — the live site, on this host. With `none`, `worktree-create.sh` creates no `.venv` and says so on stderr; provision one in Phase 3.

## Procedure

### Phase 1 — Decide whether a worktree is appropriate

A worktree is appropriate when at least one applies:
- Branch is long-lived (days+, not minutes)
- You need to work on a different branch without disturbing the current branch's environment
- The branch requires an isolated dev server, env config, or DB state
- A reviewer needs a clean main checkout to compare against

A worktree is **not** appropriate for:
- Short patches that will be committed and merged in one sitting (`git switch` is faster)
- Branches the user will switch back to immediately

If none apply, stop. Don't create a worktree just because the trigger phrase fired.

### Phase 2 — Create the worktree

```bash
bash "<SKILL_SCRIPTS>/worktree-create.sh" <branch>          # existing branch
bash "<SKILL_SCRIPTS>/worktree-create.sh" --new <branch>    # create the branch too
```

Flags are position-independent: `--new <branch>` and `<branch> --new` are equivalent. `--help` works anywhere and never provisions. A stray second word is an error, not a silent drop.

The script:
- Resolves the worktree root
- Refuses if `<branch>` is already checked out elsewhere (per the Iron Law)
- Runs `git worktree add <root>/<slug> <branch>` (or `add -b <branch> <root>/<slug>` with `--new`)
- Prints the absolute worktree path on stdout
- Exits 0 on success, 1 on Iron Law violation (double checkout), 2 on tooling failure

It will **not** link a `.venv` here — `.skills/worktree_venv` is `none`. That is expected; Phase 3 provisions one.

### Phase 3 — Work inside the worktree

`cd` into the worktree path printed by Phase 2. Upstream leaves three responsibilities to the project; archiver's answers follow, and they are not optional.

**Interpreter environment.** Provision a real venv — do not link main's:

```bash
uv sync    # resolves co-core from ./.wheelhouse; populate it first if resolution fails
```

A worktree provisioned by something *other* than `worktree-create.sh` — notably the Claude Code Agent tool's `isolation: "worktree"`, which calls `git worktree add` directly — also arrives without a `.venv`. The upstream remedy there is to symlink main's; **in this repo, run `uv sync` instead**, for the reason in **Venv linking** above.

The wheelhouse is gitignored and does not come with the worktree:

```bash
set -a; . /etc/archiver/.env; set +a   # GOOGLE_APPLICATION_CREDENTIALS
uv run --no-project --with 'google-cloud-storage>=2,<4' python scripts/sync_wheelhouse.py
```

**Env separation.** `/etc/archiver/.env` is machine-global and reaches the worktree already. `.env` is gitignored, so a fresh worktree has none — and without it `TEST_DATABASE_URL` is unset:

```bash
MAIN=$(git rev-parse --path-format=absolute --git-common-dir | sed 's|/\.git$||')
[ -f "$MAIN/.env" ] && cp "$MAIN/.env" .env
```

Source env files **only** as `set -a; . <file>; set +a`. `export $(cat … | xargs)` silently corrupts any value containing whitespace, quotes, or a second `=` — which the database URLs do.

**Port allocation.** 8000 belongs to `systemd` (`archiver.service`) and `scripts/dev_server.sh` refuses it outright. 8001 is the **main checkout's** dev-server port (CLAUDE.md, Infrastructure). So a worktree takes its own port and records it, which is what lets Phase 5 free it and what lets two worktrees serve at once:

```bash
PORT=8002                       # any free port in 3000-9999; the exe.dev proxy forwards them all
echo "$PORT" > .port            # worktree-destroy.sh reads this
ARCHIVER_DEV_PORT=$PORT bash scripts/dev_server.sh &
sleep 2 && ss -tlnp | grep "$PORT"
```

Reachable at `https://co-registrar.exe.xyz:<PORT>/`.

**Never hand-roll the `uvicorn` invocation.** The recipe this replaced sourced `/etc/archiver/.env` and ran uvicorn directly, so the worktree dev server inherited `ARCHIVER_DATABASE_URL` pointing at **production**. On 2026-07-18 that wrote a `verify79.example.com` Domain, two InfoSources, and an AppUser into the live registry. `dev_server.sh` resolves a non-production database, refuses to start when the name lacks a `_test`/`_dev` suffix, migrates it, then serves. Without `.env` it exits with a clear message rather than falling back to production — copy `.env` in first.

### Phase 3.5 — Verify worktree health

Before doing substantial work:

- `git rev-parse --show-toplevel` prints the **worktree** path (not the main checkout)
- `git status` is clean (or shows only the expected branch state)
- The dev server (if any) listens on the port recorded in `.port`
- The baseline suite passes:

  ```bash
  set -a; [ -f /etc/archiver/.env ] && . /etc/archiver/.env; [ -f .env ] && . .env; set +a
  uv run pytest --no-cov
  ```

If any check fails, fix before proceeding. Work in the wrong checkout silently lands on the wrong branch. A failing baseline is your human partner's call to proceed past — report it, don't absorb it, or every later failure is ambiguous.

### Phase 4 — Merge back to the main checkout

When the branch is ready:

1. Commit and push from inside the worktree
2. `cd` to the main checkout — its path is the first row of `bash "<SKILL_SCRIPTS>/worktree-list.sh"` (or `git worktree list | head -n1 | awk '{print $1}'`)
3. `git switch main`
4. **Open a PR and merge it** — archiver integrates through PRs, not direct pushes to `main`; the `shipping-work-python-fastapi` override is authoritative on the sequence
5. Confirm the merge succeeded before Phase 5

If the branch is **descoped** (will not be merged), document why before Phase 5: a one-line note in the related issue or PR. The descope reason is required input to `worktree-destroy.sh --descoped <reason>`.

### Phase 5 — Destroy the worktree

```bash
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch>
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --descoped "<reason>"
bash "<SKILL_SCRIPTS>/worktree-destroy.sh" <branch> --dry-run   # preview the decision, change nothing
```

**When `--force` is needed here.** Git refuses to remove a worktree whose **submodule content is checked out**:

```
fatal: working trees containing submodules cannot be moved or removed
```

Carrying submodules is not itself the trigger — `git worktree add` leaves them empty, and an untouched worktree of this repo removes cleanly with no flag. What populates them is the SessionStart doctor: it runs `git submodule update --init --recursive` to heal the dangling vendor symlinks a new worktree always has. So **any worktree an agent has actually worked in will need `--force`, and one created and destroyed without a session in it will not.**

Add the flag when you see that message, not before. `--force` also **discards uncommitted changes**, and the Iron Law gate verifies the branch is *merged*, not that the tree is *clean* — so it is the one failure mode nothing else here catches. Confirm `git -C <worktree> status --porcelain` is empty first.

Flags are position-independent here too. Other flags: `--base <ref>` verifies the merge against a non-default integration branch (e.g. `batch/<x>`) instead of `main`; `--unlock` only when the destroy reports a held lock — a lock means the owner is still running **or** died without releasing, so check which first, and note `--force` is not the remedy. The reasoning behind each: [references/destroy-flags.md](references/destroy-flags.md).

The script:
- **Finds the worktree by branch**, via `git worktree list --porcelain`, so any layout works regardless of how the directory leaf is named. Harness-provisioned worktrees (`.claude/worktrees/agent-<id>`) are reached this way too.
- Verifies the branch is an ancestor of the base ref (the actual "merged" check, not just "pushed"), preferring `origin/main` over local `main` so an unpublished local merge doesn't fool the gate. Refuses if the branch is not merged AND `--descoped <reason>` was not supplied.
- Refuses to destroy the worktree it is being run from. `cd` to the main checkout first.
- If `<worktree>/.port` exists, kills any process bound to that port via `lsof -ti tcp:<port>`.
- Runs `git worktree remove` and then `git worktree prune`
- Exits 0 on success, 1 on Iron Law violation (unmerged work without `--descoped`), 2 on tooling failure

The branch ref itself is **not** deleted — that's a separate decision. Use `git branch -d <branch>` afterward if you also want to drop the local ref.

### Auditing for zombie processes

Operators sometimes bypass `worktree-destroy.sh` (raw `git worktree remove`, manual `rm -rf`), leaving behind processes spawned from inside the now-gone worktree — here, a `dev_server.sh` still holding its port. Run the audit from the repo root:

```bash
bash "<SKILL_SCRIPTS>/audit-worktree-zombies.sh"         # prints zombies, exits 1 if any
bash "<SKILL_SCRIPTS>/audit-worktree-zombies.sh" --quiet # silent; exit code only — wire into pre-flight
```

Detection-only — it does not kill anything. The operator decides whether to kill the listed PIDs. It will not report the systemd service on 8000; that is `archiver.service`, not a zombie.

## Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Linking main's `.venv` into the worktree | A timer's `uv run` restamps the shared environment mid-suite; failures appear only in full runs | `uv sync` in the worktree — `.skills/worktree_venv` is `none` for this reason |
| Starting the dev server on 8000 | Collides with the live site's systemd unit | `dev_server.sh` refuses 8000; pass `ARCHIVER_DEV_PORT` |
| Serving a worktree on 8001 | Collides with the main checkout's dev server | Pick a distinct port and record it in `.port` |
| No `.env` in the worktree | `RuntimeError: TEST_DATABASE_URL not set` | Copy it from the main checkout (Phase 3) |
| Passing `--force` to destroy by habit | It discards uncommitted changes, which the Iron Law gate does not check | Run unforced first; add `--force` only on the submodule refusal, with a clean tree |
| Destroying before the PR merges | Work loss; the Iron Law gate exists for this | Merge, or pass `--descoped "<reason>"` |

## Notes

- `git worktree list` is authoritative — never maintain a separate registry
- A branch may be deleted while a worktree on it exists; reattach with `git worktree repair` if you need to recover
- The vendor's "project-local wrapper scripts" guidance does not apply: archiver ships no worktree wrapper, and `scripts/dev_server.sh` is a dev-server launcher, not a worktree tool

## Integration

**Called by** — each of these invokes this skill rather than rolling its own isolation:

- `brainstorming` (Phase 4) — REQUIRED once a design is approved and implementation follows
- `executing-plans`, `subagent-driven-development` — REQUIRED before executing any tasks
- `shipping-work-python-fastapi` — invokes **Phase 4** to merge the branch back before it ships

**Pairs with** `finishing-a-development-branch` for the post-merge cleanup decision.

## Detail Docs

- [references/destroy-flags.md](references/destroy-flags.md) — when each `worktree-destroy.sh` flag is the right instrument, and what each does not cover
