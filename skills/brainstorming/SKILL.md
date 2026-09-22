---
name: brainstorming
description: Explores user intent, requirements, and design before any implementation. Use when the user says "brainstorm", "design this", "let's design", or proposes a new feature without a prior design discussion.
compatibility: Designed for Claude. Requires git and gh CLI. Python project using FastAPI, Pydantic, uv, ruff, pytest.
metadata:
  author: gregoryfoster
  triggers: brainstorm, design this, let's design
  overrides: obra-superpowers/brainstorming
  synced-from: "obra-superpowers v6.4.1 (5bf4e78011075bcfc0dc295f0724994cd123ee71)"
  override-reason: "Project-specific conventions: docs/plans/ path, #<n> type: desc commit convention, writing-plans is optional not mandatory; invokes using-git-worktrees for any multi-step implementation on either the bounded or the architectural path; opens a GH issue as part of handoff; FastAPI stack context. Keeps a Scope detection gate upstream has no equivalent for, and ships no visual companion."
---

# Brainstorming Ideas Into Designs — archiver

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

First check whether brainstorming applies at all (**Scope detection**). If it
does, classify how much process the request needs (**Three Paths**), then work
that path: understand the context, refine the idea, present a design, and get
approval.

## Establish Shared Understanding

The outcome of brainstorming is an understanding the user can recognize and
correct, grounded in what they want to accomplish.

1. **Discover intent.** Use the request and available context to identify the
   intended outcome, who it is for, and what success looks like. When that
   information is missing, ask one focused question about purpose or intended
   use before proposing features or an approach. Knowing which part of the
   service a request touches does not tell you why the user wants it. Gathering
   missing requirements does not ask them to authorize the task again.
2. **Write back your understanding.** Summarize the intended outcome, relevant
   constraints, and success criteria in a short note the user can assess.
   Separate what they said from assumptions. Invite correction and incorporate
   their answer before treating this as the design brief.
3. **Carry intent into the design.** Preserve the agreed understanding in the
   selected path's artifact: the design doc under `docs/plans/` for
   architectural work, or the in-chat design or probe for bounded work and
   spikes. Check proposed features and technical choices against it.

When the request already supplies the purpose and constraints — a written GH
issue carrying the decision, most often — reflect that understanding instead of
asking the same questions again. Keep the note concise; its accuracy and the
opportunity to correct it are what matter.

<HARD-GATE>
Before taking any implementation action — invoking an implementation skill,
writing code, creating any file other than the design doc, installing a
dependency — complete the selected path's prerequisites:

- **Spike** — the user approves the question and the probe.
- **Bounded** — the user approves the short in-chat design.
- **Architectural** — the user approves the written design doc, and the GH issue
  it hands off to. Conversational approval of the idea only permits writing the
  design doc. `writing-plans` stays optional here (upstream makes it a required
  second gate; archiver does not) — but when a formal plan *is* wanted, it is
  written and reviewed before implementation, not alongside it.

A reply approves the stage actually presented. Approval of an idea or of feature
scope does not approve artifacts that do not exist yet. Resume at the earliest
incomplete stage; do not turn one approval into permission to skip the rest of
the path. Read-only exploration of the repo is allowed throughout.

This applies to EVERY task this skill applies to (see **Scope detection**), on
EVERY path below — the ceremony scales with the task; the approval gate never
does. A task Scope detection exempts is one this skill never gated; it is not
one this gate released.
</HARD-GATE>

## Scope detection

Two questions in order, and they are different questions. This one is whether
to brainstorm; **Three Paths** below is how much process to spend once you are.

Brainstorming applies when (priority order):

1. **Explicit trigger** — user says "brainstorm", "design this", "let's design"
2. **New feature request** — user proposes functionality not yet discussed or designed in this conversation
3. **Ambiguous scope** — a request could be interpreted multiple ways; design discussion prevents wasted work

Brainstorming is **not** required for:

- Bug fixes with a clear, agreed-upon cause and solution
- Explicit directed tasks ("add this field", "fix this test", "implement GH #<n>") with no design ambiguity
- Continuation of previously approved design in the same conversation

**What that exemption is and is not.** These are cases where the design
conversation has already happened somewhere else — a written issue carrying the
decision, an agreed diagnosis, an approved design earlier in the thread — or
where there is no design question to have. It is **not** licence to skip
approval for work the user did not ask for. Scope creep discovered inside a
directed task is a new request: say so and classify it.

## Three Paths

Once brainstorming applies: before your first question, classify the request and
say the classification out loud — "this looks bounded, so I'll present a short
design here rather than write a design doc" — so the user can override it.

- **Spike** — a feasibility question ("can we...", "is it possible...", "quick
  and dirty is fine") whose output is an answer, not code you keep. Present the
  question and what you'll try in 2-3 sentences, get a nod, then find out as
  cheaply as correctness allows. No design doc, no GH issue. Report findings as
  a recommendation; anything you built stays labeled throwaway.
- **Bounded** — a well-scoped change to code that already exists in this repo: a
  new flag, a small endpoint, a one-file fix. Understanding the kind of app is
  not enough — bounded means the flow you are changing is already here to read.
  If there is no existing flow to change, the task is not bounded. Ask the
  clarifying questions that matter, present a short design IN CHAT (a few
  sentences to a few short paragraphs), and STOP. Implementation starts only
  after the user says yes to that design — a bounded task's approval is as hard
  a gate as an architectural one. No design doc, no plan document; a worktree
  only if the work is genuinely multi-step (see **Worktrees**).
- **Architectural** — new subsystems, changes that restructure how components
  fit together, or anything altering a contract another service depends on (a
  bus payload, a route, an SDK surface). Follow the full process: questions,
  approaches, sectioned design, written design doc, GH issue, worktree.

When in doubt between two paths, take the heavier one. The ratchet is one-way:
hidden complexity discovered mid-task upgrades the path — stop, say so, and step
up. Nothing downgrades mid-task.

## Anti-Pattern: "Too Simple To Need Approval"

Every path ends with the user approving the required design before
implementation. A config change or a one-function utility is bounded and may
need only two sentences in chat; a new subsystem is architectural and gets the
written design doc and the GH issue whatever its line count. Scale the
**artifact** to the selected path and complete that path's approvals — what
never scales down is the approval itself. "Simple" tasks are where unexamined
assumptions cause the most wasted work.

## Red Flags

| Thought | Reality |
|---------|---------|
| "This is too simple to need a design" | Follow the selected path: a bounded change gets a short chat design, an architectural one gets the written design doc and the GH issue. Neither gets no design. |
| "I'll call it bounded and skip the design doc" | Reaching for a label to skip work IS the doubt — take the heavier path. |
| "It's bounded and the design is obvious — I'll start while they read it" | The gate is the approval, not the design's length. Present, then stop until you hear yes. |
| "I understand this kind of app, so it's bounded" | Bounded measures the repo, not your familiarity. A flow that does not exist yet is architectural. |
| "The spike works, so I'll keep the code" | A spike's output is an answer. Keeping the code is a new request — classify it. |
| "It grew, but I'm almost done — no need to re-classify" | Hidden complexity upgrades the path mid-task. Stop and say so. |
| "They approved the spike, so the follow-up change is approved too" | Each task gets its own classification and its own approval. |
| "It's a directed task, so Scope detection exempts the extra bit I noticed" | The exemption covers what was asked. Anything else is a new request. |

## Checklist

Classify first, announce the path, then create a task for each item on your path
and complete them in order.

**Spike:**

1. **Explore project context** — enough to frame the probe
2. **Present question + probe plan** — 2-3 sentences
3. **Get approval** — a nod is enough
4. **Investigate** — as cheaply as correctness allows
5. **Report findings** — a recommendation; label anything built as throwaway

**Bounded:**

1. **Explore project context** — read AGENTS.md, check recent commits, review relevant files
2. **Ask clarifying questions** — one at a time, the ones that matter
3. **Present short design in chat** — approach, files touched, testing
4. **Get approval** — STOP and wait for an explicit yes; presenting the design and starting in the same breath is skipping the gate
5. **Set up a worktree** — only if the work is multi-step; see **Worktrees**
6. **Implement** — proceed with the normal development workflow (TDD applies); no design doc, no plan document

**Architectural:**

1. **Explore project context** — read AGENTS.md, check recent commits, review relevant files
2. **Ask clarifying questions** — one at a time; understand purpose, constraints, success criteria
3. **Propose 2–3 approaches** — with trade-offs and a recommendation
4. **Present design** — in sections scaled to complexity; get approval after each section
5. **Write design doc** — save to `docs/plans/YYYY-MM-DD-<topic>-design.md` and commit
6. **Open a GH issue** — and report the number
7. **Set up a worktree** — see **Worktrees**
8. **Hand off** — move to implementation, or invoke `writing-plans` if a formal plan is needed

**Terminal states are path-bound.** Architectural: hand off to implementation, or
to `writing-plans` if a formal plan is wanted — never to `frontend-design`,
`mcp-builder`, or any other implementation skill without asking. Bounded: after
approval, implementation proceeds directly through the normal development
workflow; no plan document. Spike: the terminal state is a reported
recommendation.

## Process

The subsections below serve the bounded and architectural paths (a spike stops
at "present the probe, get a nod"). **Proposing approaches** onward is
architectural-path depth — for bounded work, context plus a few questions plus a
short in-chat design is the whole process.

### Exploring the idea

- Read AGENTS.md and relevant source files before asking questions
- Ask **one question at a time** — multiple questions overwhelm and get partial answers
- Prefer multiple-choice questions when options are bounded
- Focus on: purpose, constraints, success criteria, what failure looks like

### Proposing approaches

- Always propose 2–3 alternatives with explicit trade-offs
- Lead with your recommended option and explain why
- Apply YAGNI ruthlessly — remove scope creep from all options
- For API changes: flag breaking vs. non-breaking per AGENTS.md versioning strategy

### Presenting the design

- Scale each section to its complexity: a few sentences if simple, up to ~250 words if nuanced
- Ask after each major section whether it looks right before continuing
- Cover relevant dimensions: architecture, data model, error handling, testing strategy, API contract
- Be ready to revise — go back if something doesn't land

## After the Design (architectural path)

**Write the design doc:**

- Path: `docs/plans/YYYY-MM-DD-<topic>-design.md`
- Include: goal, approved approach, key decisions and their rationale, out-of-scope items

**Open GitHub issue:**

```bash
gh issue create \
  --title "<topic — concise imperative phrase>" \
  --body "$(cat <<'EOF'
## Summary
<1–3 sentence summary of what was designed>

## Design doc
`docs/plans/YYYY-MM-DD-<topic>-design.md`

## Scope
<bullet list of the key decisions / in-scope items from the design>
EOF
)"
```

Report the issue number to the user (e.g. "Opened #42").

**Commit the design doc:**

```
#<n> docs: add design doc for <topic>
```

**Hand off:**

- For small changes: proceed directly to implementation
- For multi-step work: invoke `writing-plans` to create a task-by-task plan (optional — not required)
- Do NOT invoke any other skill without asking

## Worktrees

Path-independent: bounded and architectural work both reach this, because
"multi-step" is a property of the work, not of the path it was classified on.
The guard below is the only filter — do not add a second one per path.

- Invoke `using-git-worktrees` to create an isolated workspace on a feature branch
- Use `.worktrees/` as the local directory (verify it is gitignored first)
- Skip for single-commit or directed fixes where isolation adds no value

## Proactive suggestion

When a user makes a feature request without explicit design context, suggest
brainstorming before diving in:

> "Before I start, this looks like a good candidate for a quick design discussion to make sure we're aligned on approach. Want me to run brainstorming, or do you have a specific implementation in mind?"

This is a suggestion, not a HARD-GATE — if the user confirms they have a clear
intent, proceed.
