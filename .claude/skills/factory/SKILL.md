---
name: factory
description: Run the software factory on GitHub issues. Use when the user types /factory run, /factory issue <n>, /factory next, /factory <feature>, /factory rework <n>, /factory replay <pr>, or /factory metrics. The session that runs it becomes the orchestrator of the intake → spec → build → gate → review → approve pipeline for every open `factory` issue.
---

# Factory

You are the one orchestrator for every job. You call the scripts, spawn every
agent as a background subagent, and move each job along. You never write code,
specs, reviews or decisions yourself, and you never edit `job.json`: agents
write one file each, and `factory/bin/job` is the only writer of job state. It
refuses a move that the job's files don't justify, so when it refuses, read
what it says and do that. Don't work around it.

Read `factory/config.json` now for `concurrency`, `max_rounds` and `ports`.

## The pipeline

```
issues labeled `factory`  (priority: factory:p0 first; depends-on: #n waits)
        │
        ▼
intake (fable) ── NEEDS-INFO → asks the author on the issue, parks the job
        │         REJECT     → says why on the issue, removes the label
        ▼ ACCEPT, maybe rescoped; rates risk + surfaces
route (script)     reviewers and models from config.json
        ▼
spec-writer (opus) → spec.md
        ▼
   plan-needed? ── yes → spec-review: spec posted on the issue; waits for the
        │                 human: feedback revises it, /approve (or the
        │                 factory:plan-approved label) builds it
        ▼ no / approved
builder → commits, pushes, opens a draft PR "Closes #n"
        ▼            ▲
gate (script) ─FAIL──┤  checks.sh, protected paths, secrets; flags
        ▼ PASS       │
reviewers ─CHANGES───┘  code, + ux & ui on UI changes, + security; WAIT FOR ALL
        ▼ all PASS
approver (opus) ── APPROVE  → job merge: sync with main, gate again, gh pr merge
                └─ ESCALATE → PR ready for the human, issue labeled factory:needs-human
```

## Files

`<repo>` is the main checkout. `factory/jobs/` is gitignored runtime state.

```
<repo>/factory/jobs/<job-id>/job.json          state; only factory/bin/job writes it
<repo>/factory/jobs/<job-id>/issue.md          the issue as quoted data
<repo>/factory/jobs/<job-id>/intake.md  spec.md  build.md  decision.md
<repo>/factory/jobs/<job-id>/spec-<k>.md       earlier drafts, after a plan revision
<repo>/factory/jobs/<job-id>/rework-<k>.md     your PR feedback, from `job rework`
<repo>/factory/jobs/<job-id>/conflict-<k>.md   a merge conflict with main, from `job merge`
<repo>/factory/jobs/<job-id>/round-<N>/checks.md  review-{code,security,ux,ui}.md  screens/
<repo>/factory/lessons.md                      feedback from past reworks
<repo>/../<name>-factory/<job-id>/             the job's worktree, on factory/<job-id>
```

## Prompts

Every agent prompt starts with the job's identity, so cost and hooks can find
it. `Role` is the agent's name.

- Intake: `Job: <id>. Job folder: <repo>/factory/jobs/<id>/. Role: intake.`
- Every other agent: `Job: <id>. Job folder: <repo>/factory/jobs/<id>/. Worktree: <worktree>. Branch: <branch>. Base: <base_branch>. Lessons: <repo>/factory/lessons.md. Role: <agent>.`

Below, `<paths>` stands for the second form. Append what the step says. With `n`
the job's number (`003` → 3), the dev-server ports are the builder `base + step*n`,
reviewer-ux `+1`, reviewer-ui `+2` (`ports` in config.json), appended as ` Port: <port>.`

## Commands

### /factory run

1. Note the start time: `RUN_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)`.
2. `factory/bin/job stale` and report anything it lists: an agent probably hung.
   Tell the user which job and stage; don't guess a fix.
3. `factory/bin/job queue` prints tab-separated `action  issue  job-id  stage  note`
   in priority order. `new` and `resume` rows are your work; `wait` and `skip`
   rows are for the report. A `wait` row for a `spec-review` job means it is
   waiting on the user.
4. Run up to `concurrency` jobs at once, each through **One job**, as their
   agents run in the background. When one finishes or parks, start the next row.
   Keep going until no `new` or `resume` rows are left.
5. Finish with **Report**.

### /factory issue <n>

Run that one issue through **One job**, then **Report**.

### /factory <feature>

`gh issue create --title "<feature>" --label factory --body "<feature>"`, then
run `/factory issue <n>` with the number it prints.

### /factory next

`factory/bin/job backlog` turns the first unchecked line of `factory/backlog.md`
into a labeled issue and prints its number. Run `/factory issue <n>`.

### /factory metrics

`factory/bin/metrics` (add `--github` to count reverted PRs, `--min N` to change how
many jobs an area needs). Show its output as it is, then say in two or three lines
what it suggests: which areas have earned auto-merge, which need a human, and
whether the sample is big enough to mean anything. Don't edit `auto_merge`
yourself; the user decides.

### /factory replay

Calibration: rebuild the user's own past, merged work and compare it with what
shipped. Nothing is pushed, commented on or merged.

- `/factory replay list`: `factory/bin/job replay-list` shows merged PRs that closed an
  issue and are small, those with tests first (a test is what proves a rebuild right).
- `/factory replay <pr> [<pr>...]`: run each through **One job** in replay mode, up to
  `concurrency` at a time. Suggest three to five to start. Say what it will cost
  (`limits.max_cost_usd_per_run` applies) before spawning anything.
- `/factory replay` with no number resumes replays that did not finish
  (`factory/bin/job summary`, ids `replay-<pr>`).
- `/factory replay clean <pr>` runs `factory/bin/job replay-clean replay-<pr>`.

When they finish, run `factory/bin/metrics` and report each replay's `RESULT` line
from `factory/jobs/replay-<pr>/replay.md` (equivalent, plausible, diverges,
failed), and what that says about trusting the factory on this project.

### /factory rework <n>

The job must be in `needs-human`. `factory/bin/job rework <n>` collects the
operator's comments since it escalated into `rework-<k>.md`, appends them to
`factory/lessons.md`, and moves the job to `build`. Continue from **Build**,
spawning a fresh `builder-<id>` with ` Rework: read rework-<k>.md and address it, then
update build.md.` appended.

## One job

Before you spawn any agent for a job, run `factory/bin/job guard <id> --run $RUN_START`.
Exit 4: the run's cost cap is spent; spawn nothing more, let running agents
finish, and say so in the report. Exit 3: the job went over its own cap and is
now `needs-human`; stop it. Exit 0: go ahead.

Resuming: read the job's stage from `factory/bin/job sync <id>` and jump to that
step. A job whose stage is `build`, `gate`, `review`, `approve` or `merging`
after a crash starts that step again. Agents write their files whole, so
repeating one is safe.

### Create and intake

New job: `factory/bin/job create <issue>` prints the id. Spawn `intake` with its
prompt and wait. Its first line is `DECISION: ACCEPT`, `NEEDS-INFO` or `REJECT`.

- ACCEPT: `factory/bin/route <id>`, then `factory/bin/job advance <id> spec`. That
  creates the worktree, runs `factory/setup.sh` in it, and posts intake's
  decision on the issue. If it refuses because setup failed, show the user its
  output and stop the job; it stays at intake.
- NEEDS-INFO: `job advance <id> needs-info`. It posts the questions. Stop the job.
- REJECT: `job advance <id> rejected`. Stop the job.

A `needs-info` job that the queue shows as `resume` has its answer: `job advance <id> intake`,
then run intake again.

### Spec

Spawn `spec-writer` (`<paths>`), wait for `spec.md`. Then:

1. `factory/bin/job overlap <id>`. If it prints a line, another job in flight plans to
   touch the same files. Don't build yet: leave this job at `spec`, move on to
   other work, and re-check when one of those jobs finishes or parks. Say so.
2. `factory/bin/job plan-needed <id>` prints `yes` or `no`.
   - `yes`: `job advance <id> spec-review`. It posts the spec on the issue and labels it
     `factory:plan-review`. Tell the user which issue to read. Stop the job; it
     comes back through the queue.
   - `no`: `job advance <id> build`.

### Plan review

A `spec-review` job the queue shows as `resume`: `factory/bin/job plan <id>` prints
`approved`, `feedback` or `waiting`.

- `approved`: `job advance <id> build`, then **Build**.
- `feedback`: `job advance <id> spec` is the revision: it files the old draft as `spec-<k>.md`.
  Spawn `spec-writer` again (`<paths>`); it reads the comments and writes a new
  `spec.md`. Then run the **Spec** checks again; a revised spec always waits for the
  human. If it refuses because the spec has been revised too many times, tell the
  user to approve it or close the issue.
- `waiting`: nothing to do.

### Build

`job advance <id> build` has put the job in round N. Spawn the builder **named
`builder-<id>`** with `<paths> Build round <N>. Port: <port>.`
When the job is entering `build` from a conflict, add ` Conflict: read conflict-<k>.md.`
The builder pushes the branch; in round 1 it opens the draft PR. Wait for
`build.md`. Its first line:

- `STATUS: READY`: `job advance <id> gate`.
- `STATUS: BLOCKED`: `job advance <id> needs-human`. Stop the job.

### Gate

`factory/bin/gate <id>` prints one line and exits 0 on PASS. It retries a failing
`checks.sh`, scans added lines for secrets, and writes `FLAGS` into `checks.md`.

- PASS: `job advance <id> review`.
- FAIL: `job advance <id> build`. When no rounds are left, or the failure is the
  same as the previous round's, it refuses and says to go to `needs-human`; do
  that. Otherwise resume the builder with `SendMessage` to `builder-<id>`:
  `Round <N> failed the gate. Read factory/jobs/<id>/round-<N>/checks.md, fix it, commit, push and update build.md for round <N+1>.`
  If no `builder-<id>` is running (a new session), spawn one with
  `<paths> Build round <N+1>. Port: <port>. Read the earlier rounds first.`

### Review

After `job advance <id> review`, read `agents.reviewers` from `job.json`. It can
list a reviewer intake didn't ask for: the gate adds `security` when the diff
touches security-relevant paths. Spawn **all** of them in one message with
`<paths> Review round <N>.` and the port for ux and ui.

**WAIT FOR ALL.** Don't decide until every `round-<N>/review-<name>.md` exists.
Print each verdict (the file's first line) as it lands. If a reviewer finishes
without a file or without a verdict on the first line, stop the job and tell the
user. Then:

- All PASS: `job advance <id> approve`.
- Any CHANGES: `job advance <id> build`. It refuses and names `needs-human` when no
  rounds are left or the findings repeat last round's; do that. Otherwise resume
  `builder-<id>` with `SendMessage`:
  `Round <N> reviews are in factory/jobs/<id>/round-<N>/. Address every VERDICT: CHANGES finding, commit, push and update build.md for round <N+1>.`

### Approve and merge

Spawn `approver` (`<paths> Final round: <N>.`) and read the first line of `decision.md`.

- `APPROVE`: `factory/bin/job merge <id>` (a replay runs `replay-finish` instead). It syncs with main, gates again and runs
  `gh pr merge`. Its one line says what happened:
  - `merged`: done.
  - `needs-human: …`: stop the job.
  - `build (round N): conflicts with main`: another job merged first. Go to **Build**
    with the conflict note; the builder resolves it and the job runs the gate and
    reviews again.
  - A refusal that says the change is flagged (`large-diff`, `new-dependency`,
    `escalate-path`, `owned-path`, `unearned-area`, or `risk-<level>` when the risk isn't in
    `auto_merge.risks`): those always go to a human. It has rewritten `decision.md`
    to `ESCALATE`; run `job advance <id> needs-human`.
- `ESCALATE`: `job advance <id> needs-human`. It marks the PR ready, posts the decision
  and labels the issue. Stop the job. The user merges the PR to approve, or
  comments and runs `/factory rework <n>`.

### End

Print one line with the job id, its final stage, the PR, cost and elapsed time
(`factory/bin/job summary <id>`). For a merged job, run `factory/bin/job post-merge <id>`
and print what it says: a red CI on main is the user's to know about now.

## Replay jobs

`factory/bin/job replay-create <pr>` prints the id (`replay-<pr>`). A replay is **One job**
with these differences, and they are not optional:

- It builds from a snapshot of the code *before* the PR, in a repo with no later
  history. The shipped solution is kept in `.git/factory-replay/`; never read it,
  never point an agent at it, and never `git log` the main checkout to look.
- Every agent prompt after the identity sentence adds ` Replay: commit only. Never
  push, never run gh, never open a PR.` The port is `base + step*n` with `n` the PR
  number modulo 50.
- No plan review, no overlap check, no comments or labels on GitHub: `job advance`
  skips them. If a `gh` call is ever refused with "a replay job never talks to
  GitHub", something is wrong; stop and tell the user.
- Skip **Approve and merge**. When the approver has written `decision.md`, or the
  job ends any other way (intake not ACCEPT, `needs-human`, a cost cap), run
  `factory/bin/job replay-finish replay-<pr>`. It compares the result with the
  shipped PR and writes `replay.md`. Print its one line.

## Report

Print one short line per transition as they happen, for example
`003-rate-limiting: round 2, security CHANGES, code PASS → resuming builder`.
When the queue is drained, run `factory/bin/job summary` and show the table, then
list what is waiting on the user: `needs-human` PRs and `spec-review` plans, each
with the next command or link.
