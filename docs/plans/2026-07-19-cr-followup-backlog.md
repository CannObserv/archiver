# CR-Followup Backlog Orchestration — #85, #88, #89, #91, #92

Date: 2026-07-19
Tracking issue: (opened after this doc; see repo issues)
Skill: `orchestrating-issue-backlog`

## Goal

Clear the five CR-surfaced followup issues from the #82/#86/#87 shipping
cycles — three bugs (#88 offset 500, #89 lying BUILD_ID, #91 broken
no-changelog opt-out) and two infra enhancements (#85 service version
drift, #92 archiver-client regen + drift gate) — via a parallel-safe,
two-batch agent execution plan.

## Approved approach

- Rubric: equal weights — Score = (Foundation × 2) + (Correctness × 2) + Scope, max 15.
- Deployment context: early production (live on 8020, real consumer = Watcher, low volume).
- No deferrals: all five scored in full, including #89's `/health` surfacing and #92's step 4 (attempt-or-document).
- Parallelism: hybrid — parallel workers within a batch (Agent tool `isolation: "worktree"`), human-reviewed gate between batches.
- Worktree ceiling: none — no custom provisioning script; plain `git worktree add`. Effective constraint is the shared `TEST_DATABASE_URL`: **full pytest runs are serialized** (workers run targeted tests during TDD, one full pass at self-review; the orchestrator's full-suite run on the batch branch is the authoritative gate).
- Batch→main merge strategy: **regular merge commit** (matches `Merge #90: …` precedent). Intra-batch worker→batch merges are FF/regular only (never squash/rebase — preserves the worktree-destroy ancestor check).

## Prioritization rubrics

| Dimension | 1 | 2 | 3 |
|---|---|---|---|
| Foundation Leverage | Standalone | 1–2 issues benefit | Multiple issues depend on it |
| Correctness Risk | Cosmetic/organizational | Edge-case failure, runtime risk | Data loss, races, silent failures |
| Scope Clarity | Needs design discovery | Clear direction, minor decisions | Mechanical |

Score = (Foundation × 2) + (Correctness × 2) + Scope. Blast radius drives sequencing, not score.

## Scored backlog

| # | Title (short) | F | C | S | Score | Blast |
|---|---|---|---|---|---|---|
| 92 | Regen `clients/python` + drift gate | 3 | 2 | 2 | **12** | Med-High |
| 89 | BUILD_ID lies about dirty tree | 1 | 3 | 2 | **10** | Low |
| 91 | no-changelog opt-out broken end-to-end | 2 | 2 | 2 | **10** | Med |
| 88 | List routes 500 on offset > int64 | 1 | 2 | 3 | **9** | Low |
| 85 | Service version drift 3.2.0 vs 4.2.2 | 2 | 1 | 2 | **8** | Med |

All five verified live against current files at orchestration time (no closed-in-fact issues).

## Conflict zones

| Contested file | Issues | Resolution |
|---|---|---|
| `.github/workflows/ci.yml` | #91 (changelog job), #92 (client-drift job), #85 (lockstep check) | #85's check goes in the **lint** job (keeps it out of both contested jobs). #91/#92 edit distinct jobs; merge order #91 → #92, #92 rebases before merge. |
| `CHANGELOG.md` | #88, #92, #89 (entries), #85 (heading discipline) | Top-append conflicts are trivial; Batch A merge order #88 → #89 → #85, workers rebase. #85 takes **option 1** (bump pyproject, keep headings) — option 2's full-file rewrite was rejected for blast. |
| `info.version` in #92's spec snapshot | #85 → #92 | **Hard edge**: #85 (pyproject → 4.2.2) must be on `main` before #92 generates `archiver-openapi.json`, else the contract-of-record is born stale at 3.2.0. Enforced by the A→B batch gate. |

Implementation surfaces are otherwise fully disjoint (CR-surfaced backlog: one bug per surface).

## Dependency graph

```
#88 ──────────────────────────┐
#89 ──────────────────────────┼──> independent, parallel-safe
#85 (pyproject + lint check) ─┤
        │                     │
        └─ hard ─> #92 (snapshot embeds info.version)
#91 ─ ci.yml same-file edge ─ #92 (distinct jobs; merge-order only)
```

## Batch execution plan

| Batch | Issues | Agents | Files | Gate |
|---|---|---|---|---|
| A | #88, #89, #85 | 3 parallel | Disjoint except CHANGELOG top-append | Start immediately |
| B | #91, #92 | 2 parallel | Disjoint except `ci.yml` (distinct jobs) | After A merged to `main` |

- Batch A merge order: **#88 → #89 → #85** (#85 last so its lockstep check validates the batch's final CHANGELOG/pyproject state).
- Batch B merge order: **#91 → #92** (#92 rebases before merge).
- Branches: `batch/a`, `batch/b`. Orchestrator creates and checks out the batch branch before spawning workers; reconciles and merges each worker explicitly on completion (auto-merge is not assumed).
- Human review happens on the batch branch (tests + combined diff), then regular-merge to `main`.

### Per-issue worker scope

- **#88** — add `le=2**63 - 1` to the four offset `Query` declarations
  (`domains.py:45`, `info_items.py:203`, `info_sources.py:109`,
  `rep_specs.py:61`); parametrized test asserting 422 (not 500) at
  `offset=2**63` per route; CHANGELOG `[service]` entry.
- **#89** — `git describe --always --dirty` in
  `deploy/archiver.service` ExecStartPre; surface BUILD_ID on `/health`;
  CHANGELOG `[service]` entry (health route is a contract path).
- **#85** — bump `pyproject.toml` to `4.2.2` (option 1); add a lockstep
  check (newest `## vX.Y.Z` CHANGELOG heading == pyproject version) to
  the CI **lint** job; no changelog entry required (no contract paths)
  unless the worker cuts a new heading.
- **#91** — option 1 + option 3: resolve the PR from the merge commit on
  push events (`GET /repos/{owner}/{repo}/commits/{sha}/pulls`) and
  honour `no-changelog`; fix `check_changelog_on_push.sh` messaging to
  stop advertising `--no-verify` as a viable escape.
- **#92** — regen `clients/python` generated tree via `regen.sh` against
  the post-#87 (and post-#85) spec; commit `archiver-openapi.json` as
  contract-of-record; add `archiver` entry to
  `scripts/check_client_drift.py` CLIENTS + CI client-drift job; attempt
  step 4 (migrate the six hand-written domain wrappers onto the
  generated module) if mechanical, else document the decision on the
  issue; CHANGELOG `[sdk]` entry.

## Key decisions

1. **#85 option 1 over option 2** — preserves the documented lockstep
   policy; option 2's CHANGELOG rewrite would conflict with every other
   changelog-touching worker in the batch.
2. **Lockstep check lives in the lint job** — keeps #85 out of the two
   ci.yml jobs contested by Batch B.
3. **#85 gates #92's snapshot** (hard edge) — enforced structurally by
   the batch boundary rather than by worker coordination.
4. **#91/#92 parallel, not bundled** — they differ in kind (CI policy vs
   SDK regen); same-file contact is two unrelated jobs; ordering note
   suffices.
5. **#89 Correctness scored 3** — the stamp actively denying dirty state
   during incident triage is the rubric's silent-failure class, despite
   low practical volume.
6. **Test-run serialization over per-worker test DBs** — zero setup; the
   orchestrator's batch-branch suite run is authoritative anyway.

## Deferred items

None — all five issues in scope, in full (Q3).

## Out of scope

- Deploying from a clone instead of the working tree (#89 names it as
  the deeper issue; explicitly out of scope there).
- The changelog trigger regex itself (#91 confirms it works as
  intended).
- Issues not in the requested set (#83, #77, #75, #72, #71, #69, #54,
  #51, #45, #20, #5, #4, #3, #2).
