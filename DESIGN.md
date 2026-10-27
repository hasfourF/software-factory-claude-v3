# Design

How this factory works (v3, built on ZazenCodes' v2), and why it's built this way.
The source is small enough to read in one sitting: one skill, ten agents, seven
scripts and a config file.

## The idea

A software factory turns a queue of requests into merged code with a fixed
pipeline. Scripts handle the deterministic stages, such as running the tests,
moving state and merging. Agents do the judgment in between: whether a request
is worth building, what exactly to build, the code itself, and whether it's
good. Each stage leaves a file behind, so you can see what happened and why.

## Pieces

| Piece | File | Job |
|---|---|---|
| Queue | GitHub issues labeled `factory` | What to build. Anyone can file an issue; only people with triage or write access can label it. Feeders (`factory/bin/feed`) can propose issues, but a person promotes them. |
| Orchestrator | `.claude/skills/factory/SKILL.md` | The session that runs `/factory`. Starts jobs, spawns agents, calls the scripts. Writes nothing itself. |
| Agents | `.claude/agents/*.md` | One file per role. Each reads files, writes exactly one file, and replies with one line. |
| State | `factory/jobs/<job-id>/` | `job.json` plus every agent's file. Gitignored, local to the machine running the factory. |
| Spine | `factory/bin/job`, `gate`, `route`, `policy` | Deterministic. `job` is the only writer of `job.json` and refuses illegal moves. `policy` is the agents' hook that refuses merges and pushes outside `factory/*`. |
| Tools | `factory/bin/doctor`, `metrics`, `feed` | `doctor` checks the setup, `metrics` reports how far to trust the factory, `feed` proposes issues. |
| Knowledge | `factory/recipes/`, `factory/lessons.md` | The project's playbooks for common changes, and feedback from reviews, reworks and reverts. Agents read them; people approve them. |
| Checks | `factory/checks.sh` | The repo's test, lint, typecheck and build commands. The only repo-specific script. |
| Exit | the PR | Every job ends as a PR that closes its issue. Merging it is the approval. |

## Pipeline

```
intake (fable)     → ACCEPT (scope possibly changed, recipe chosen) | NEEDS-INFO | REJECT, posted as an issue comment
route (script)     → reviewers + models from risk/surfaces via config.json
worktree           → factory/<job-id> from origin/main
spec-writer (opus) → spec.md
plan review        → optional: spec posted on the issue; feedback revises it, approval builds it
builder            → commits; first round pushes + opens draft PR "Closes #<n>"
gate (script)      → checks.sh, then acceptance commands and verify.sh; FAIL → builder gets the log, no reviewers spawned
reviewers (routed) → parallel, WAIT FOR ALL; CHANGES → builder → gate → reviewers (max rounds)
approver (opus)    → APPROVE: sync origin/main, gate, gh pr merge
                     ESCALATE: PR ready, decision as PR comment, label factory:needs-human
```

`stage` in `job.json` is one of `intake`, `needs-info`, `spec`, `spec-review`,
`build`, `gate`, `review`, `approve`, `merging`, `needs-human`, `merged`,
`rejected`, `abandoned`, and `replayed` for a calibration run.
The legal moves are in `TRANSITIONS` at the top of `factory/bin/job`.

## Decisions

**Issues are the queue; you trigger the run.** `/factory run` drains every open
`factory` issue. Nothing runs in GitHub Actions or on a schedule: the factory
runs on your machine, on your Claude plan, when you start it. An issue can't
start a Claude Code session by itself, and keeping it local means your
worktrees, dev servers and dashboard are right there.

**One orchestrator for every job.** The session running `/factory run` starts up
to `concurrency` jobs and spawns every agent as a background subagent. There
are no per-job orchestrators to coordinate. Its context stays small because
agents reply with one line and the scripts print one line; the detail lives in
files the next agent reads. Claude Code allows 20 concurrent subagents per
session by default, which covers three jobs with four reviewers each.

**Fable at the door, once.** Intake is the only Fable call per job. It decides
whether the issue is worth building, rewrites the scope when the issue is too
big or vague, and asks the author when only they can answer. Its decision goes
on the issue as a comment; the issue body stays as written. Questions go to
the author before a spec exists, so the spec writer never stalls on one.

**Risk routes the work, a script does the routing.** Intake rates risk (`low`,
`medium`, `high`) and surfaces (`ui`, `security`). `factory/bin/route` looks
them up in `config.json`:

| | builder | code review | ux | ui | security |
|---|---|---|---|---|---|
| low | Sonnet | Haiku | | | |
| medium | Sonnet | Sonnet | | | |
| high | Opus | Sonnet | | | |
| + `ui` surface | | | Sonnet | Haiku | |
| + `security` surface | | | | | Opus |

A low-risk change with no UI runs one Haiku reviewer. Routing is visible in
one file and changes without touching a prompt.

**Scripts decide whether it works.** The gate runs `checks.sh` before any
reviewer is spawned, and again after syncing with `main` before the merge.
A failing build goes straight back to the builder with the log. The gate runs
the main checkout's copy of `checks.sh`, so a branch can't edit the checks it
is judged by. It fails any branch that modifies or deletes a file under
`protected_paths`, which closes the commonest way agents game tests. The
builder also has a `SubagentStop` hook that runs the checks before it finishes,
as a nudge; the gate is still what decides.

**Agents judge what scripts can't.** Reviewers don't re-run the test suite;
they read the diff for correctness, scope, security, UX and visual fit.

**A PR per issue, merged through GitHub.** v1 merged locally, which broke when
the main checkout was dirty or busy. v2 merges with `gh pr merge`, so branch
protection, required checks and the PR history all apply, and your main
checkout is never touched. Before merging, the branch is synced with `main` and
gated again, because another job may have merged since it was tested.

**You can read the plan first.** A wrong spec is the most expensive mistake the
factory makes: it gets built, gated, reviewed and escalated before anyone
notices. So after the spec-writer, `job plan-needed` decides (the `factory:plan`
label, or `plan_review` by risk) whether the spec is posted on the issue and the
job parks in `spec-review`, like `needs-info`. Your comments revise the spec, at
most `max_spec_revisions` times, and the old draft is kept as `spec-<k>.md`.
Approval is the `factory:plan-approved` label (a label needs triage access) or a
`/approve` comment from the operator. The issue's author can ask for changes but
not approve, because the `factory` label already let their request in. The spec
keeps the things worth doing but not asked for in a separate Recommendations
section, so approving the plan does not approve every suggestion.

**The diff gets a vote that the agents can't overrule.** Intake decides the
reviewers before any code exists, and reviewers are language models. The gate
sees the diff. It adds the security review when the diff touches
`force_security_paths`, and it raises flags (`large-diff`, `new-dependency`,
`escalate-path`) that make `job advance approve→merging` refuse whatever the
approver said: it rewrites `decision.md` to ESCALATE and the job goes to you.

**A job that repeats itself is stopped.** `job` fingerprints each failed round
(the gate's log tail, or the CHANGES findings) with numbers and whitespace
removed. If a round fails the same way as the one before, another build is
unlikely to help, so the job escalates instead of spending its last rounds.
Cost caps work the same way: `job guard` runs before each spawn.

**Merge conflicts are the builder's job first.** Another job merging first is
normal when jobs run in parallel. While rounds remain, `job merge` writes
`conflict-<k>.md` and sends the branch back to `build`; only an exhausted job
reaches you with a conflict.

**State changes on GitHub end jobs.** If you merge a PR by hand, or close it,
`job queue` notices and ends the job (`merged` or `abandoned`) and removes its
worktree, whatever stage it was in.

**You approve by merging.** The approver merges what it would merge itself and
escalates the rest with a specific question. An escalated PR is ready for
review and its issue is labeled `factory:needs-human`. Merge it to approve, or
comment and run `/factory rework <n>` to send your comments to the builder.

**State is files, so runs resume.** Every fact the orchestrator needs is in
`factory/jobs/`. If the session dies or compacts, a fresh `/factory run` reads
the queue and resumes every job from its stage.

**One session at a time.** Two sessions running `/factory run` would both resume
the same jobs and put two builders on one branch. The first `job` command that
changes anything records its Claude Code session and process in
`factory/jobs/.run.json`, and `job` refuses changes from any other session while
that process is alive. A crashed or closed session lets go by itself, because its
process is gone, and the skill runs `job release` when a command finishes. Commands
run by hand from a terminal aren't sessions and are never refused.

**The agents can't merge or push to the base branch.** Every agent with a shell
has a `PreToolUse` hook, `factory/bin/policy`, that refuses `gh pr merge`, a
`gh api` call that writes, and any `git push` that doesn't name only `factory/*`
branches. The factory's own merge runs inside `job merge`, out of the hook's sight.
The hook reads command strings, so it stops mistakes, not an agent set on getting
round it: branch protection on the base branch is the backstop, and `doctor`
warns when there is none.

**Cost is measured per job.** Claude Code writes each subagent's transcript,
with model and token counts per message, to
`~/.claude/projects/<project>/<session>/subagents/`. Every factory prompt starts
with the job's folder, so `factory/bin/job` sums the transcripts that name it
and prices them with `prices_usd_per_mtok`. The figure is the API-equivalent
cost of the job's agents; on a subscription it shows relative spend, not your
bill. The orchestrator's own tokens aren't attributed to a job. The
transcript format isn't a documented interface, so a Claude Code update could
break this.

**The scripts decide what must not be automatic.** The approver is a language model,
so some limits can't be its call. The gate raises flags from the diff (`large-diff`,
`new-dependency`, `escalate-path`, `owned-path`, `unearned-area`), and `job` refuses to
merge a change with one, or one whose risk is outside `auto_merge.risks`, by rewriting
the decision to ESCALATE. CODEOWNERS is read from the base branch so a PR can't delete
the rule that covers it.

**Autonomy is earned, from numbers.** `metrics` counts, per area of the code, how
often the approver merged with no human rework and whether anything was reverted. An
area is earned at five decided jobs, 80% and no reverts, and then `auto_merge.areas`
can name it. Until it is set the approver decides as before; once it is, a change that
touches any other directory waits for a person. The sample is small by nature and the
report says so.

**The gate runs a spec's commands only if you allow them, and without a shell.** A
spec is written by an agent that read an issue, so a `## Verification` command could
be steered by whoever wrote that issue. They run only if they start with an entry of
`gate.verify_allow` (empty by default), split into arguments and never passed to a
shell, so `;`, pipes and `$(...)` are inert. Slow or app-level verification goes in
`factory/verify.sh`, which is yours and protected from the branch.

**Replay proves it on your own history, without touching GitHub.** To rebuild a merged
PR fairly the agents must not be able to find the answer. The code is exported at the
parent of the merge commit into a fresh one-commit repo, so there is no later history
to read; the shipped diff is kept in `.git/factory-replay/`, outside the job folder;
and `job` refuses any `gh` call from a replay, so nothing is commented, pushed or
merged. Equivalence is judged by running the shipped PR's own tests on what the
factory built, which checks behaviour, not resemblance.

**Recipes steer builds, so a person approves each one.** An agent drafts a recipe from
merged PRs, but into `recipes/drafts/`, which nothing reads; a person moves it up.
Intake can only name a recipe that is a real file with a plain name.

**Lessons are a prompt, so only trusted voices write them.** `lessons.md` is read by
every builder and reviewer, which makes a comment on a PR a way to instruct them. Only
the operator and the repo's owners, members and collaborators count; bots, strangers,
the factory's own comments and one-word replies don't. Each entry carries the areas it
touched so agents apply the ones that match. The curator proposes a tidy version; it
never replaces the file.

**Feeders propose; people promote.** A failing CI log or a comment in code is text
nobody wrote for an agent, and the `factory` label is what lets text reach agents that
can commit. So a feeder files `factory:proposed` and a person adds `factory`. A stable
key per item, a cooldown and two caps keep it from refiling or flooding, and it files
nothing when it can't tell what already exists. A source can be set to queue directly;
`doctor` warns when it is.

## Guardrails

- Only issues labeled `factory` run. Labels need triage or write access, so the
  label is the trust boundary.
- Issue text reaches agents as quoted data in `issue.md`, with comments only
  from the issue's author and the factory's operator. It is never part of a
  prompt. Intake, which reads it first, has no shell.
- Agents push only `factory/*` branches. Only `factory/bin/job merge` merges,
  through `gh pr merge`. The factory never deploys.
- One PR per issue; at most `max_rounds` build rounds per job before a human
  is asked.
- Spec commands run only if allowed, with no shell. Feeder issues, recipes and lessons
  reach agents only after a person has promoted or approved them, or from trusted authors.
- A replay never reaches GitHub, and the answer to it is not in the code the agents see.
- Cost caps per job and per run, and a failure that repeats goes to a person.

## What changed from v1

This table is from the original project; the names are the people its author credited
for each request. This version's changes are in [`CHANGELOG.md`](CHANGELOG.md).

| v1 | v2 | Asked for by |
|---|---|---|
| `/factory <feature>`, one job per session | `/factory run` drains the issue queue, `concurrency` jobs at once, one orchestrator | Alex; @spec2k5, @MrHossamsaraya |
| Copy-paste build prompt | One install prompt pointing at this folder | @felipeclavijo1736 |
| Every job gets all four reviewers | Fable intake rates risk and surfaces; a script routes reviewers and models | @mptrista, @Robin-ox2mz |
| Every verdict is an LLM opinion | `checks.sh` gates before review and before merge | @Robin-ox2mz |
| Local `git merge`, needs a clean main checkout | A PR per issue, merged with `gh pr merge` | v1 on-camera merge failures |
| `/factory approve` | Merge the PR on GitHub | v1 |
| The spec writer can stall on questions | Intake asks on the issue and parks the job | @acidrazor |
| Cost invisible | Cost and time per job on the dashboard and in the run summary | the most common comment |
| No license | GPLv3, commercial licensing available | @mapledev9335 |
