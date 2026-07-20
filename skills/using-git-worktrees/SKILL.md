---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification
metadata:
  author: gregoryfoster
  version: "1.0"
  overrides: gregoryfoster-skills/using-git-worktrees
  override-reason: "Archiver-specific operations — dev server auto-starts on port 8021 (8020 belongs to systemd archiver.service), and worktree setup sources /etc/archiver/.env + .env via `set -a; . <file>; set +a` (not the broken `export $(cat | xargs)` pattern)."
---

# Using Git Worktrees

## Overview

Git worktrees create isolated workspaces sharing the same repository, allowing work on multiple branches simultaneously without switching.

**Core principle:** Systematic directory selection + safety verification = reliable isolation.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Directory Selection Process

Follow this priority order:

### 1. Check Existing Directories

```bash
# Check in priority order
ls -d .worktrees 2>/dev/null     # Preferred (hidden)
ls -d worktrees 2>/dev/null      # Alternative
```

**If found:** Use that directory. If both exist, `.worktrees` wins.

### 2. Check CLAUDE.md

```bash
grep -i "worktree.*director" CLAUDE.md 2>/dev/null
```

**If preference specified:** Use it without asking.

### 3. Ask User

If no directory exists and no CLAUDE.md preference:

```
No worktree directory found. Where should I create worktrees?

1. .worktrees/ (project-local, hidden)
2. ~/.config/superpowers/worktrees/<project-name>/ (global location)

Which would you prefer?
```

## Safety Verification

### For Project-Local Directories (.worktrees or worktrees)

**MUST verify directory is ignored before creating worktree:**

```bash
# Check if directory is ignored (respects local, global, and system gitignore)
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

**If NOT ignored:**

1. Add appropriate line to .gitignore
2. Commit the change
3. Proceed with worktree creation

**Why critical:** Prevents accidentally committing worktree contents to repository.

### For Global Directory (~/.config/superpowers/worktrees)

No .gitignore verification needed - outside project entirely.

## Creation Steps

### 1. Detect Project Name

```bash
project=$(basename "$(git rev-parse --show-toplevel)")
```

### 2. Create Worktree

```bash
# Determine full path
case $LOCATION in
  .worktrees|worktrees)
    path="$LOCATION/$BRANCH_NAME"
    ;;
  ~/.config/superpowers/worktrees/*)
    path="~/.config/superpowers/worktrees/$project/$BRANCH_NAME"
    ;;
esac

# Create worktree with new branch
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

### 3. Run Project Setup

**archiver-specific setup:**

```bash
# Install Python dependencies
uv sync

# Copy .env from main worktree (TEST_DATABASE_URL, GH_TOKEN)
# Production ARCHIVER_DATABASE_URL is in /etc/archiver/.env and shared automatically
MAIN_WORKTREE=$(git rev-parse --path-format=absolute --git-common-dir | sed 's|/.git$||')
if [ -f "$MAIN_WORKTREE/.env" ]; then
  cp "$MAIN_WORKTREE/.env" .env
fi
```

### 4. Verify Clean Baseline

Run tests to ensure worktree starts clean:

```bash
# Source env files via `set -a; . <file>; set +a` (handles whitespace,
# quotes, and `=` correctly — unlike the broken `export $(cat | xargs)`
# pattern). Existence guards keep this safe when one file is absent.
[ -f /etc/archiver/.env ] && { set -a; . /etc/archiver/.env; set +a; }
[ -f .env ] && { set -a; . .env; set +a; }
uv run pytest --no-cov
```

**If tests fail:** Report failures, ask whether to proceed or investigate.

**If tests pass:** Report ready.

### 5. Start Dev Server

**Port 8021 belongs to worktrees.** Never serve main on 8021. When no worktree is
active, 8021 should not be running.

```bash
# Kill any existing process on 8021 (stale worktree, accidental main, etc.)
lsof -ti :8021 | xargs -r kill -9 2>/dev/null

# Start the dev server from the worktree via the launch script. It sources the
# env files, resolves a NON-PRODUCTION database, refuses to start if that
# database name lacks a _test/_dev suffix, migrates it, then serves on 8021.
bash scripts/dev_server.sh &

# Verify port is bound
sleep 2
ss -tlnp | grep 8021
```

**Never hand-roll the `uvicorn` invocation here.** The recipe this replaced
sourced `/etc/archiver/.env` and ran uvicorn directly, so the worktree dev
server inherited `ARCHIVER_DATABASE_URL` pointing at **production** — and this
step runs automatically, with no user prompt, on every worktree. On 2026-07-18
that wrote a `verify79.example.com` Domain, two InfoSources, and an AppUser
into the live registry.

A fresh worktree has no `.env` (it is gitignored), so `TEST_DATABASE_URL` is
unset there and the script exits with a clear message rather than falling back
to production. Copy or symlink `.env` into the worktree before starting.

Accessible at `https://watcher.exe.xyz:8021/` via the exe.dev proxy.

This step runs automatically — no user prompt. The result is included in the
report (next step). If the server fails to bind, report the error and ask the user.

### 6. Report Location

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Dev server running on port 8021 (https://watcher.exe.xyz:8021/)
Ready to implement <feature-name>
```

## Quick Reference

| Situation | Action |
|-----------|--------|
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Both exist | Use `.worktrees/` |
| Neither exists | Check CLAUDE.md, then ask user |
| Directory not ignored | Add to .gitignore + commit |
| Tests fail during baseline | Report failures + ask |
| Dev server on 8021 from wrong worktree | Automatically killed and restarted |

## Common Mistakes

### Skipping ignore verification

- **Problem:** Worktree contents get tracked, pollute git status
- **Fix:** Always use `git check-ignore` before creating project-local worktree

### Assuming directory location

- **Problem:** Creates inconsistency, violates project conventions
- **Fix:** Follow priority: existing > CLAUDE.md > ask

### Proceeding with failing tests

- **Problem:** Can't distinguish new bugs from pre-existing issues
- **Fix:** Report failures, get explicit permission to proceed

### Missing .env in worktree

- **Problem:** Tests fail with `RuntimeError: TEST_DATABASE_URL not set`
- **Fix:** Copy `.env` from main worktree during setup (Step 3)

### Starting dev server on port 8020

- **Problem:** Conflicts with the systemd service running the live site (`archiver.service`)
- **Fix:** Always use `--port 8021` in worktrees (and in dev generally)

### Running dev server from main

- **Problem:** Port 8021 belongs to worktrees; serving main breaks operational separation
- **Fix:** Only start 8021 from a worktree directory. Stop 8021 when worktree is torn down.

## Integration

**Called by:**
- **brainstorming** (Phase 4) - REQUIRED when design is approved and implementation follows
- **subagent-driven-development** - REQUIRED before executing any tasks
- **executing-plans** - REQUIRED before executing any tasks
- Any skill needing isolated workspace

**Pairs with:**
- **finishing-a-development-branch** - REQUIRED for cleanup after work complete
