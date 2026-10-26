Build a software factory in this repo by extending my v1 factory:
https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code

Read v1 first: its README, the /factory skill, the seven agents and the
dashboard. Copy it in as the starting point and keep what works: agents get
context from files and write only their own file, verdicts are the first line,
WAIT FOR ALL, a named builder resumed with SendMessage, a worktree and ports per
job. Then make the changes below. This repo is on GitHub, so issues and PRs are
available through `gh`. Keep it small enough to understand in a few minutes.

## What changes

1. GitHub issues are the queue. Only open issues labeled `factory` are built.
   No backlog.md, no GitHub Actions: everything runs locally when I start it.
2. One master orchestrator. The session that runs /factory starts up to
   `concurrency` jobs (default 3) and spawns every agent of every job as a
   background subagent. Agents reply with one line; the detail goes in their
   file, so the orchestrator's context stays small. State lives in files, so a
   new /factory run resumes every job after a crash.
3. A Fable intake agent at the door, the only Fable call per job. It decides
   ACCEPT (possibly rescoped), NEEDS-INFO or REJECT, rates risk
   (low/medium/high) and surfaces (ui, security), and the decision is posted
   as an issue comment. It never edits the issue. NEEDS-INFO parks the job
   until the author replies; that's where questions get answered, so the spec
   writer never stalls.
4. Routing by risk. A script maps intake's risk and surfaces to the reviewers
   and models through a table in config.json. Only the code reviewer always
   runs; ux and ui run for `ui`, security for `security`.
5. Deterministic checks. `factory/checks.sh` holds the repo's real test, lint,
   typecheck and build commands. A gate script runs it before any reviewer is
   spawned; a failing build goes back to the builder with the log.
6. A PR per issue. The builder pushes `factory/<job-id>` and opens a draft PR
   "Closes #<n>" in its first round. APPROVE merges with `gh pr merge` after
   syncing with main and gating again. ESCALATE marks the PR ready, posts the
   decision on it and labels the issue `factory:needs-human`. I approve by
   merging the PR, so /factory approve goes away.
7. Cost and time per job, on the dashboard and in the run summary.

## The pipeline (edit this to change the factory)

    intake (fable)     → ACCEPT (scope possibly changed) | NEEDS-INFO | REJECT, posted as an issue comment
    route (script)     → reviewers + models from risk/surfaces via config.json
    worktree           → factory/<job-id> from origin/main
    spec-writer (opus) → spec.md
    builder            → commits; first round pushes + opens draft PR "Closes #<n>"
    gate (script)      → checks.sh; FAIL → builder gets the log, no reviewers spawned
    reviewers (routed) → parallel, WAIT FOR ALL; CHANGES → builder → gate → reviewers (max rounds)
    approver (opus)    → APPROVE: sync origin/main, gate, gh pr merge
                         ESCALATE: PR ready, decision as PR comment, label factory:needs-human

| Role | Model |
|---|---|
| Orchestrator | the session's model |
| Intake | fable |
| Spec writer, approver | opus |
| Builder | sonnet; opus when risk is high |
| Code review | haiku when risk is low, else sonnet |
| UX review / UI review | sonnet / haiku, ui surface only |
| Security review | opus, security surface only |

## The deterministic spine

- `factory/checks.sh`: the repo's checks, exit 0 or not. The only
  repo-specific script.
- `factory/bin/gate <job-id>`: runs the main checkout's `checks.sh` inside the
  job's worktree, fails if the branch modified or deleted a protected test
  file, and writes `round-N/checks.md` (first line `GATE: PASS` or `GATE: FAIL`).
- `factory/bin/route <job-id>`: intake's risk and surfaces → the agent set.
- `factory/bin/job`: the only writer of job.json. It refuses illegal
  transitions (review without a passing gate, merge without APPROVE) and does
  each transition's GitHub side effects: comments, labels, the worktree, the
  merge.
- A SubagentStop hook on the builder runs `checks.sh` as an early nudge. The
  gate still decides.

## job.json

    { "id": "004-dark-mode-toggle", "issue": 12, "pr": 31,
      "branch": "factory/004-dark-mode-toggle",
      "worktree": "/abs/path/my-app-factory/004-dark-mode-toggle",
      "stage": "review", "round": 1,
      "intake": { "decision": "ACCEPT", "rescoped": true, "risk": "low", "surfaces": ["ui"] },
      "agents": { "builder": "sonnet", "reviewers": { "code": "haiku", "ux": "sonnet", "ui": "haiku" } },
      "gate": "PASS",
      "reviews": { "code": "pending", "ux": "PASS", "ui": "pending" },
      "cost_usd": 1.84, "started": "2026-11-02T14:03:00Z" }

`stage` is one of intake, needs-info, spec, build, gate, review, approve,
merging, needs-human, merged, rejected. Per-job cost: sum the token usage in
the Claude Code subagent transcripts whose prompt names the job's folder.

## Commands

    /factory run          drain the queue: every open `factory` issue, `concurrency` at a time; also resumes
    /factory issue <n>    one issue now
    /factory <feature>    create the issue (labeled), then run it
    /factory rework <n>   needs-human job → builder, with the PR's review comments

## Guardrails

- The `factory` label is the trust boundary: only people with triage or write
  access can add it.
- The issue body reaches agents as quoted data in `issue.md`, never as the
  prompt.
- Push only `factory/*` branches, merge only via `gh pr merge`, never deploy.
- A maximum number of rounds per job, one PR per issue.

## Dashboard

Extend v1's: columns for the new stages, needs-human before merged, issue and
PR links on each card, a gate chip before the review chips in every round,
only the routed reviewers, and cost and time per job.

Create the labels `factory`, `factory:needs-info` and `factory:needs-human`,
fill `checks.sh` for this repo, and confirm it passes on main.
