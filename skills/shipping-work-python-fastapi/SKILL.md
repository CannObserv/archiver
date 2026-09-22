---
name: shipping-work-python-fastapi
description: "For the archiver service (Python/FastAPI on uv + ruff + pytest): finalizes work by ensuring everything is committed, pushed to the remote, and reflected on GitHub: closes issues, posts summary comments, and presents a completion table. Use when the user says 'ship it', 'push GH', 'close GH', or 'wrap up'."
compatibility: Designed for the archiver service. Sources `/etc/archiver/.env` and `$PROJECT_ROOT/.env` before pre-ship pytest; otherwise delegates to the upstream shipping-work-python-fastapi variant.
metadata:
  author: gregoryfoster
  version: "1.4"
  triggers: ship it, push GH, close GH, wrap up
  overrides: gregoryfoster-skills/shipping-work-python-fastapi
  synced-from: "gregoryfoster-skills 1.4 (178ec64)"
  override-reason: "Sources /etc/archiver/.env and $PROJECT_ROOT/.env before delegating to upstream pre-ship; fixes broken `export $(cat … | xargs)` env-loading pattern via `set -a; . <file>; set +a`."
---

# Shipping Work - Python/FastAPI - archiver

Finalizes work: pre-ship checks, clean commit, push, GitHub issue comments, and closure. Tuned for the archiver service.

## The Iron Law

```
NO PUSH WITHOUT PASSING PRE-SHIP CHECKS - VERIFIED IN THIS SESSION
NO ISSUE CLOSURE WITHOUT FULL IMPLEMENTATION - VERIFIED AGAINST ORIGINAL REQUIREMENTS
```

## Rationalization prevention

| Thought | Reality |
|---|---|
| "Checks passed earlier in this session" | Run them again. State can change. Require fresh output. |
| "It's basically done, just needs minor cleanup" | Incomplete = not done. Finish or explicitly descope before closing. |
| "The issue will track follow-up work" | Only close if the core requirement is fully met. Open a new issue for follow-up. |
| "gh push is failing, I'll skip it" | Resolve the error. Do not mark as shipped without a successful push. |
| "User is in a hurry" | A bad ship is slower than a good one. Run the checklist. |

## Parameterized invocation

Trigger phrases may include scope inline - e.g., `wrap up #19 #20`, `ship it #14`. Apply the appended issue numbers as the explicit scope (step 1 of Scope detection); skip the conversation-context fallback.

## Scope detection

Determine which GitHub issue(s) to close (priority order):
1. **Explicit scope** - user specifies issue number(s)
2. **Conversation context** - issues referenced in recent commit messages or discussion
3. **Ask** - if ambiguous, confirm before closing anything

## Procedure

### Step 1 - Run pre-ship checks

<!-- skill:required id=skill-scripts -->
```bash
N=shipping-work-python-fastapi
{ [ ! -x .skills/doctor.sh ] || bash .skills/doctor.sh; } || exit 1
for S in doc-check.sh check-status.sh push.sh comment-issue.sh close-issue.sh pre-ship.sh; do SD=
  for d in scripts ".claude/skills/$N/scripts" "$HOME/.claude/skills/$N/scripts"; do
    [ -f "$d/$S" ] && { SD="$d"; break; }
  done
  [ -n "$SD" ] || echo "$S not found in scripts/, .claude/skills/$N/scripts/, or ~/.claude/skills/$N/scripts/" >&2
  echo "<$S>=${SD:?}/$S"
done
bash "${SD:?}/$S"
```

The first line is a preflight: when `.skills/doctor.sh` is present, it heals any dangling vendor symlinks (or reports an actionable error); when absent, the group is a no-op. `|| exit 1` skips `pre-ship.sh` if the doctor reports unrecoverable state so the original "No such file or directory" noise doesn't drown out the doctor's message. The loop then resolves the script against the skill directory rather than the cwd - a bare `scripts/` path resolves relative to the project root, where the script does not exist ([#63](https://github.com/gregoryfoster/skills/issues/63)). A project-local `scripts/` copy still wins if one exists; when no candidate resolves the block stops, naming the script and the searched paths. Resolution runs *after* the doctor so a freshly healed symlink chain is visible to it.

**Each script is resolved on its own** ([#301](https://github.com/gregoryfoster/skills/issues/301)). Probing one anchor and reusing its directory for the other five breaks on a partial `scripts/` override - and archiver has exactly that shape: `skills/shipping-work-python-fastapi/scripts/` holds a local `pre-ship.sh` wrapper beside five symlinks into `skills-vendor/`, so a future change that moves one script without the others would resolve the rest to the wrong directory.

Step 1 prints one `<script>=<path>` line per script. In every later step `<doc-check.sh>`, `<push.sh>` and the rest are **placeholders** for the literal paths printed here - substitute the value printed for that script. Each Bash invocation runs in a fresh shell, so the shell variables themselves are not inherited.

```
NO CONTINUATION IF CHECKS FAIL
```

The archiver wrapper (`skills/shipping-work-python-fastapi/scripts/pre-ship.sh`, the one
non-symlinked script here) sources `/etc/archiver/.env` (system secrets) and
`$PROJECT_ROOT/.env` (repo-local overrides) before delegating to the upstream variant's
pre-ship.sh. The upstream script handles lint (`ruff check`), the per-SHA stamp
(auto-derived as `archiver-tests-clean-<sha>`), and pytest with `-m "not integration"`
(skips `tests/integration/` flows; CI runs them separately).

If checks fail: stop, report the failure, fix before proceeding. Do not push failing code under any circumstances.

### Step 1.5 - Documentation spot-check

```bash
bash "<doc-check.sh>"
```

`doc-check.sh` lists files changed on this branch vs the upstream default branch
and flags any that match the project's sensitive-path list, then prints the doc
sections to spot-check. Entries match path *segments*, so `pyproject.toml`
covers `clients/python/pyproject.toml` as well as the root one. When sensitive
paths change, the matching doc sections may need updates too.

**Archiver tailors both halves under `.skills/`** (one entry per line, blank
lines and `#`-comments ignored). Each file replaces its upstream defaults
wholesale rather than extending them:

- `.skills/doc-sensitive-paths` - what the gate watches (archiver#190). The
  defaults' `schema.sql`, `src/models/` and `.env.example` match nothing in
  this tree.
- `.skills/doc-sections` - the advice a hit prints: which of archiver's docs to
  spot-check (archiver#228). The defaults name AGENTS.md's route table and a
  README quick start, a layout this repo does not keep.

Edit the two together: the list says what the gate watches, the sections say
what to do about a hit. Every verdict names the list it consulted and every hit
names its advice; either one reading `built-in defaults` means that file went
missing (a bare `No changes vs <ref>.` never reached the list at all). A hit
ending in `Note: this project tailors ...` says the same thing, naming the half
that is still the default. `tests/scripts/test_doc_sensitive_paths.py` fails on
any list entry that no longer matches a tracked file, and
`tests/scripts/test_doc_sections.py` on any advice line naming a path or heading
that is gone; edit the file and let the tests confirm the result.

If the script exits 1: review the listed files, decide whether each requires a
doc update, and either commit the docs now or note them as deliberate skips. If
the script exits 2: an infra/tooling problem prevented the doc check from
running - investigate the underlying error rather than proceeding. One exit-2
case is worth naming: when no entry in the list matches any tracked file, it says
so instead of passing, because a list that cannot hit anything would otherwise
print the same clean green as a genuinely doc-neutral branch. Fix the list; do
not wave the step through. The same goes for either file above, or `.skills/`
itself, when the script cannot use it: a tailoring never silently reverts to the
built-in defaults, so an exit 2 there means the override is unusable, not absent.

### Step 2 - Ensure a clean working tree

```bash
bash "<check-status.sh>"
```

If the script exits 2, `git status` itself failed: the tree state is **unknown**,
which is not the same as clean. Investigate git's error rather than proceeding
([#257](https://github.com/gregoryfoster/skills/issues/257)).

If uncommitted changes exist, commit them using **archiver's bracket-less convention**
(note: the upstream variant inlines `[type]` brackets as a default - archiver does not):

```
#<number> <type>: <description>       # with GH issue
<type>: <description>                 # without GH issue
```

Common `<type>` values: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`. Multi-issue:
`#19, #20 <type>: <description>`. Scope parens are tolerated (`#24 feat(events): ...`)
but bare types are preferred.

### Step 2.5 - Worktree-aware merge (if applicable)

If this checkout is a worktree (test: `git rev-parse --show-toplevel` differs from the main checkout, listed first in `git worktree list`):

1. Commit current changes inside the worktree (Step 2 above)
2. Invoke `using-git-worktrees` Phase 4 to merge the branch back into the main checkout before continuing
3. The remaining steps (push, GH comments, close) run from the main checkout

If this is a single (non-worktree) checkout, skip this step.

### Step 3 - Ensure on main

If Step 2.5 applied, the merge already happened - you're on `main` in the main checkout; continue.
If Step 2.5 did not apply (single checkout) and you're on a feature branch, merge to `main` first.

### Step 4 - Push

```bash
bash "<push.sh>"
```

Confirm push succeeded before proceeding.

### Step 5 - Comment on GitHub issues

For each issue in scope:

```bash
bash "<comment-issue.sh>" <number> "<summary>"
```

Comment must include:
- What was implemented (2-4 bullets)
- Key commit SHAs or commit range
- Any follow-up items or known limitations

### Step 6 - Close GitHub issues

<HARD-GATE>
Before closing any issue, verify the original requirements against what was implemented:
1. Re-read the issue body
2. Confirm each stated requirement is addressed in commits
3. If any requirement is missing: do NOT close - ask the user whether to descope or continue
</HARD-GATE>

```bash
bash "<close-issue.sh>" <number>
```

### Step 7 - Report

Present a summary table:

| Issue | Title | Status | Comment |
|---|---|---|---|
| #19 | ... | ✅ Closed | Summary posted |

### Step 8 - Next-steps notification

After the summary table, review commits and changes shipped to identify any post-deploy work the user may need to perform. Common categories for archiver:

| Category | Trigger | Example action |
|---|---|---|
| DB migration | New file under `alembic/versions/` | `uv run alembic upgrade head && sudo systemctl restart archiver` |
| Service restart | Code change touched a non-reload path | `sudo systemctl restart archiver` (port 8000) |
| Integration tests | New `@pytest.mark.integration` tests | `uv run pytest -m integration` on a real env (or wait for CI) |
| Env var / secret | New config key | Add to `/etc/archiver/.env` and `sudo systemctl restart archiver` |
| Dev-server cleanup | Worktree shutdown | `fuser -k 8001/tcp` for the dev port |
| Changelog | feat/fix changes on `main` | Ensure `CHANGELOG.md` carries the entry; CI's changelog job enforces |

Present only the items that apply. Be specific - name the file, command, or path. Then **offer to execute** any item within your capabilities. Ask once - don't nag.

If nothing applies, omit this step entirely.

## Notes

- If `gh` CLI hits errors (e.g., Projects API changes), use `--json` flag workarounds as needed
- AGENTS.md is authoritative for commit conventions - read it before committing if unsure
- The archiver wrapper sources `/etc/archiver/.env` and `$PROJECT_ROOT/.env` with `set -a; . <file>; set +a` (NOT the broken `export $(cat | xargs)` pattern that fails on whitespace/quotes/`=`)
- The upstream `pre-ship.sh` auto-derives its per-SHA stamp prefix from `$(basename "$(git rev-parse --show-toplevel)")` → `archiver-tests-clean-<sha>` - no hardcoded literal in the wrapper
