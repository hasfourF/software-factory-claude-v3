# Software Factory for Claude Code (v3)

A software factory that works through your GitHub issues. Label an issue
`factory`, run `/factory run`, and agents decide whether it's worth building,
write a spec (that you can read and change first, on the issues you choose),
build it, test it with your own checks, review it, and open a
pull request that closes the issue. The approver merges what it's sure of and
hands you the rest.

> Based on [ZazenCodes' software factory](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code-v2)
> (v2, GPLv3). This version adds the skill and agents the original never
> committed, plan review, and the safety limits listed in
> [`CHANGELOG.md`](CHANGELOG.md). See [Credits](#credits).

## Install

Open Claude Code in your project and paste:

```text
Build me a software factory inside this project following the provided reference (below) closely:

https://github.com/hasfourF/software-factory-claude-v3
```

Your agent reads [`INSTALL.md`](INSTALL.md), copies the skill, agents, scripts
and dashboard, fills `factory/checks.sh` with your project's real test, lint,
typecheck and build commands, tailors the reviewers to your stack, creates the
GitHub labels, and checks that `checks.sh` passes on `main`.

You need Claude Code 2.1.257 or later, `python3` 3.10 or later, and an
authenticated [`gh`](https://cli.github.com/) that can push to the repo. When
the install finishes, `factory/bin/doctor` tells you whether it's ready.

## The loop

```
issues labeled `factory`  (yours, or proposed by a feeder and promoted by you)
        │
        ▼
intake (fable) ── NEEDS-INFO → asks the author on the issue, waits for a reply
        │         REJECT     → says why on the issue, removes the label
        ▼ ACCEPT, maybe rescoped; rates risk + surfaces; picks a recipe if one fits
route (script)    picks reviewers and models from config.json
        ▼
spec-writer (opus) → spec.md ──► plan review (optional): the spec is posted on
        │                        the issue; your comments revise it, `/approve` builds it
        ▼
builder (sonnet, opus when risky) → commits, pushes, opens a draft PR "Closes #n"
        ▼            ▲
gate (script) ─FAIL──┤  checks.sh, acceptance commands, verify.sh, protected paths,
        ▼ PASS       │  secret scan; no reviewer runs on a failing build
reviewers ─CHANGES───┘  code (haiku | sonnet), + ux & ui on UI changes, + security
        ▼ all PASS
approver (opus) ── APPROVE  → sync with main, gate again, gh pr merge
                └─ ESCALATE → PR ready for you, issue labeled factory:needs-human
```

Around the loop: feeders fill the queue, recipes and lessons steer the agents, and
`metrics` and `replay` tell you how far to trust the result.

One Claude Code session orchestrates every job, `concurrency` at a time
(default 3). Each job gets its own git worktree and branch. All state lives in
`factory/jobs/`, so if the session dies, `/factory run` picks every job back up.

## Commands

In Claude Code, from the project root:

| Command | What it does |
|---|---|
| `/factory run` | Drain the queue: every open `factory` issue, `concurrency` at a time. Also resumes jobs after a crash, then learns from PRs that merged since last time and lists what is waiting on you. With `feeders.auto_create` on, it files feeder issues first. |
| `/factory issue <n>` | Run one issue now. |
| `/factory <feature>` | File the issue (labeled `factory`) from a sentence, then run it. |
| `/factory next` | Turn the first `- [ ]` line of `factory/backlog.md` into an issue, then run it. |
| `/factory rework <n>` | Send an escalated job back to the builder with your comments on its PR. They also go into `lessons.md`. |
| `/factory feed [--create] [--source <name>]` | Show work the project already knows about (failing CI, advisories, `TODO(factory)` comments, custom sources) and what would be filed. Files nothing without `--create`. `<name>` is `ci`, `deps`, `todo` or `custom:<name>`. See [Fill the queue](#fill-the-queue). |
| `/factory replay list` | Merged PRs that make a fair test: they closed an issue and are small. Those with tests come first. |
| `/factory replay <pr> [<pr>...]` | Rebuild each PR's issue offline from the code before it and compare with what shipped. Nothing is pushed or merged. It tells you the cost first. |
| `/factory replay` | Resume replays that didn't finish. |
| `/factory replay clean <pr>` | Delete a replay's snapshot and answer key. |
| `/factory metrics [--github] [--min N] [--json]` | Auto-merge rate, cost, reverts, by risk, area, surface, recipe and origin; which areas have earned auto-merge. `--github` counts reverted PRs; `--min N` sets how many jobs an area needs (default 5). |
| `/factory recipe <pr> [<pr>...]` | Draft a recipe from merged PRs that did the same kind of change, into `factory/recipes/drafts/`. |
| `/factory learn [<job>]` | Add what trusted people said on merged factory PRs, and any reverts, to `lessons.md`. Runs by itself after each `/factory run`. |
| `/factory lessons` | Propose a tidied, grouped `lessons.md` in `lessons.proposed.md`. You replace the file yourself. |

You approve a PR by merging it on GitHub. You approve a plan with the
`factory:plan-approved` label or a `/approve` comment on the issue.

### From the terminal

These are plain scripts; run them from the project root. `python3` 3.10+ and `gh` only.

| Command | What it does |
|---|---|
| `factory/bin/doctor [--skip-checks] [--run-validation]` | Is the project ready? Checks tools, config, labels, agents, name clashes, permissions, and that `checks.sh` passes on the base branch (`--skip-checks` skips that slow part). `--run-validation` also runs the validation commands in `AGENTS.md` on a clean base branch, shows them first, and flags any that fail where `checks.sh` passes. Run it first when something looks wrong. |
| `factory/bin/metrics [--json] [--github] [--min N]` | The same report as `/factory metrics`. |
| `factory/bin/feed [--create] [--source <name>]` | The same as `/factory feed`. |
| `factory/bin/job summary [<job>...]` | Every job: stage, round, PR, cost, time. |
| `factory/bin/job queue` | What `/factory run` would do with each labeled and proposed issue. |
| `factory/bin/job stale` | Jobs stuck in one stage longer than `limits.stage_timeout_minutes`. |
| `factory/bin/job post-merge <job>` | Did CI on the base branch stay green after this job merged? |
| `factory/bin/job recipes` | The recipes in `factory/recipes/` and when each applies. |
| `factory/bin/job learn [<job>]` | The same as `/factory learn`. |
| `factory/bin/job backlog` | Turn the first unchecked `factory/backlog.md` line into a labeled issue. |
| `factory/bin/job replay-list`, `replay-clean <job>` | The same as `/factory replay list` and `replay clean`. |
| `factory/bin/job release [--force]` | Let another Claude Code session run the factory. Only one session runs it at a time, and a closed one lets go by itself; `--force` takes it from a session that is still open. |
| `python3 -m unittest discover -s factory/tests` | The test suite. |

`job` is the only writer of job state, and it refuses moves the job's files don't
justify, so don't run its other subcommands (`create`, `advance`, `merge`, `rework`,
`agents`, `sync`, `plan`, `plan-needed`, `overlap`, `guard`, `replay-create`,
`replay-finish`) or `gate` and `route` by hand. The skill calls them.

### Labels

| Label | Meaning |
|---|---|
| `factory` | Build this issue. Only people with triage or write access can add it. |
| `factory:needs-info` | The factory asked the author a question and is waiting. |
| `factory:needs-human` | The PR is ready for you: merge it, or comment and `/factory rework`. |
| `factory:plan` | Show me the plan before you build. |
| `factory:plan-review` | The plan is posted and waiting for you. |
| `factory:plan-approved` | Build the plan as written. |
| `factory:feed` | A feeder filed this issue. |
| `factory:proposed` | A feeder filed this and it waits until you add `factory`. |
| `factory:p0`, `p1`, `p2` | Priority, p0 first. |

### Settings

Everything is in `factory/config.json`. The ones you'll touch:

| Setting | Default | What it does |
|---|---|---|
| `concurrency` | `3` | Jobs at once. Start with `1`. |
| `max_rounds` | `3` | Build rounds per job before a human is asked. |
| `base_branch`, `merge_method` | `main`, `merge` | Where PRs go and how they merge (`merge`, `squash`, `rebase`). |
| `plan_review` | `high` | Post the spec and wait for you: `never`, `high`, `medium` or `always`. The `factory:plan` label asks for it on one issue. |
| `routing`, `surface_reviewers` | see file | Builder and reviewer models by risk, and the extra reviewers for `ui` and `security`. |
| `auto_merge.risks`, `auto_merge.areas` | all risks, `null` | The autonomy dial. A change outside them always waits for you. `metrics` suggests `areas`. |
| `gate.retries` | `1` | Re-runs of a failing `checks.sh`; a pass on a retry is reported as flaky. |
| `gate.verify_allow` | `[]` | Command prefixes the gate may run from a spec's `## Verification`. Empty means none run. |
| `gate.max_diff_lines` | `800` | A bigger diff always goes to a human. |
| `gate.respect_codeowners` | `true` | A path with a `CODEOWNERS` owner always goes to a human. |
| `protected_paths` | the factory and `.github/workflows/*` | Existing files a branch must not modify. Add your tests. |
| `force_security_paths`, `always_escalate_paths` | see file | A diff touching the first gets the security review; one touching the second always goes to a human. |
| `limits` | `$5` a job, `$25` a run, `90` min | Cost caps (API-equivalent) and the stage timeout. |
| `feeders` | `ci` on, `deps` and `todo` off | Sources, caps (`max_open` 5, `max_per_run` 3, `cooldown_days` 30), and `auto_create` (off). |
| `replay` | `300` lines | The size limit for `replay list`, and which files count as tests. |
| `lessons.curate_after` | `20` | Entries before `learn` suggests `/factory lessons`. |
| `post_merge` | `report` | After a merge, check CI on the base branch: `off`, `report` or `issue`. |
| `notify.command` | `null` | A shell command run with `$FACTORY_MESSAGE` when a job needs you or merges. |

## Review the plan first

Add the `factory:plan` label to an issue, or set `"plan_review": "high"` in
`factory/config.json` (the default) to do it for every high-risk job. A job that
intake rescoped always waits, because it builds less than the issue asked for.
After the spec is written the factory posts it on the issue and waits:

- **Comment** with what's missing or wrong. The spec-writer revises it (twice at
  most) and posts it again.
- **Approve** by adding the `factory:plan-approved` label, or by commenting
  `/approve` as the user running the factory. The build starts on the next
  `/factory run`.

The spec lists numbered acceptance criteria (AC1, AC2, ...), the files it expects
to change, and a separate **Recommendations** section for things worth doing that
it did not put in scope. The code reviewer later maps each AC to a test, and the
gate compares the real diff with the planned files.

## Fill the queue

`/factory feed` finds work the project already knows about and files it, so the queue
isn't only what you type. It shows what it found first and files nothing until you say.

| Source | Files an issue when | On by default |
|---|---|---|
| `ci` | the latest run of a workflow on the base branch failed (the log's tail is quoted in the issue) | yes |
| `deps` | an open Dependabot security alert is at or above `min_severity` | no |
| `todo` | a committed comment says `TODO(factory): ...` (your pattern, on the base branch only) | no |
| `custom` | your own command prints a JSON list (Sentry, Linear, anything with an API) | none |

Issues are labeled `factory:feed` and **`factory:proposed`, not `factory`**. The `factory`
label is what lets text reach an agent that can commit, and a CI log or a code comment is
text nobody wrote for an agent. So a feeder proposes and you promote: read the issue,
add `factory`. `/factory run` lists proposed issues as waiting. You can set a source's
`label` to `"factory"` if you trust it; `doctor` warns when you do.

It can't flood you: every item has a stable key (a moved TODO keeps it), a key with an
open issue or one closed in the last `cooldown_days` isn't filed again, at most
`max_per_run` are filed per run, and none while `max_open` feeder issues are open. If it
can't read what's already filed, it files nothing. `metrics` splits results by origin, so
you can see whether feeder work merges as well as work you filed.

## Teach it your project

Two things make the factory build like a member of your team instead of a stranger.

**Recipes.** A recipe is your project's playbook for a kind of change you make often:
add an endpoint, add a migration, add a feature flag. It lists the steps in order, the
files, the tests and the part that's easy to forget. Intake matches an issue to a
recipe, and then the spec-writer, the builder and the code reviewer all work from it.
`metrics` shows whether jobs that followed a recipe merged more often than the rest.

You don't write them. `/factory recipe 41 44 52` drafts one from merged PRs that did
the same kind of change (several beat one: it keeps what they share). The draft goes to
`factory/recipes/drafts/`, which is never used. Read it, fix it, and move it to
`factory/recipes/`. A recipe steers every later build of that kind, so a person
approves each one.

**Lessons.** `factory/lessons.md` is read by every builder and reviewer. It fills from
three places: your comments when you `/factory rework`, what the repo's owners, members
and collaborators said on a factory PR once it merged, and reverts (the strongest
signal there is). Each entry is tagged with the areas of the code it touched, so
agents apply the ones that match. Comments from anyone else, bots and one-word
approvals are ignored, because this file steers every agent. `/factory learn` does it
on demand and it runs after each `/factory run`. When the file grows,
`/factory lessons` proposes a deduplicated version grouped by area, in
`lessons.proposed.md`; you replace `lessons.md` with it yourself.

## One list of checks

`factory/checks.sh` decides. It is what the gate runs, and the agents are told so. A
project's `AGENTS.md` often lists its own validation commands too, and the two lists drift:
`AGENTS.md` runs strict `json.tool` over locale files that start with a `/* */` header,
`checks.sh` knows they are JSONC, and every agent that follows `AGENTS.md` reports a
failure the gate never sees. So:

- An agent that sees an `AGENTS.md` command fail while `checks.sh` passes writes
  `DISAGREES: <command>: <why>` and carries on, unless its own change plainly caused it. It
  doesn't loop or block.
- The approver escalates a job with a `DISAGREES` in it, because every job will hit it until
  a person fixes one of the two lists. `metrics` counts these as their own reason.
- `factory/bin/doctor --run-validation` finds the disagreement up front, and the installer
  runs it. The fix is usually to make `AGENTS.md` say `bash factory/checks.sh`.

## Checks beyond `checks.sh`

The gate is only as good as what it runs, so there are three ways to make it stronger:

- **Acceptance commands.** The spec can list `AC1: pytest tests/test_x.py` lines under
  `## Verification`. The gate runs them itself instead of trusting `build.md`. A spec
  comes from an agent that read an issue, so nothing runs until you list command
  prefixes in `gate.verify_allow`, and commands run without a shell (no pipes, no `;`).
- **`factory/verify.sh`.** For what is too slow for `checks.sh`: boot the app and hit
  it, end-to-end or visual-regression tests, coverage of changed lines. It runs after
  `checks.sh` passes, with `$FACTORY_PORT` set.
- **`CODEOWNERS`.** A change to a path that has an owner always waits for a human
  (the rules are read from the base branch, so a branch can't edit its way out).

## Know how far to trust it

Run it on your own history before you run it on new work, then let the numbers
set how much it merges alone.

**Calibrate with a replay.** `/factory replay list` shows merged PRs that closed an
issue and are small. `/factory replay 41 44 52` rebuilds each from the issue as it
was written, on a copy of the code *before* the PR, with no later history to peek
at. Nothing is pushed, commented on or merged. Then the PR's own tests are run
against what the factory built:

| Result | Meaning |
|---|---|
| `equivalent` | passed the gate, and the shipped PR's tests pass on its code |
| `plausible` | passed the gate and touched at least half the shipped files; no shipped tests to prove it |
| `diverges` | passed the gate, but the shipped tests fail on its code, or it touched few of the same files |
| `failed` | nothing built, or it never passed the gate |

Each replay writes `replay.md` (what it changed that the PR did not, and the
reverse). Choose PRs that touched tests; they are the only ones a rebuild can be
proven against.

**Measure real runs.** `factory/bin/metrics` reports auto-merge rate, cost and
time per merged PR, rounds, gate failures, why jobs went to a human, and reverts
(`--github`), by risk, by area (top-level directory) and by surface.

**Turn that into autonomy.** An area is *earned* after five decided jobs, at least
80% merged by the approver with no human rework, and no reverts. `metrics` prints
the config to paste:

```json
"auto_merge": { "risks": ["low", "medium", "high"], "areas": ["docs", "src"] }
```

Then a change that touches any other directory, or a risk level you leave out of
`risks`, always waits for you. It's enforced by the scripts, so the approver can't
overrule it. Until you set it, the approver decides, as before.

Small samples mislead. Treat the numbers as a prompt to read the PRs.

## Priorities and order

`factory:p0`, `factory:p1` and `factory:p2` labels set the order (p0 first). Put
`depends-on: #12` on a line of an issue to hold it until #12 has merged. Two jobs
whose specs plan to touch the same files don't build at the same time.

## What stops a runaway

- **Repeated failure**: a gate failure or set of review findings that matches the
  round before escalates to you instead of burning another round.
- **Cost caps**: `limits.max_cost_usd_per_job` and `max_cost_usd_per_run`. A job
  over its cap is escalated; a run over its cap starts nothing new.
- **Always a human**: a diff over `gate.max_diff_lines`, a changed dependency
  manifest, a touched path in `always_escalate_paths`, a path with a `CODEOWNERS`
  owner, a directory outside `auto_merge.areas`, or a risk outside `auto_merge.risks`
  can't be auto-merged, whatever the approver says.
- **Security backstop**: a diff that touches `force_security_paths` gets the
  security review even if intake didn't ask for it.
- **Flaky checks** are retried (`gate.retries`) and reported as flaky.
- **Merge conflicts** go back to the builder; they don't wait for you.
- A PR you merge or close by hand ends its job. `job stale` lists jobs stuck in
  one stage.

## What's in here

```
.claude/
  skills/factory/SKILL.md     the orchestrator: queue, concurrency, the pipeline
  agents/
    intake.md                 fable    worth building? at what scope? risk + surfaces
    spec-writer.md            opus     spec.md
    builder.md                routed   code, commits, the PR, build.md
    reviewer-code.md          routed   correctness, simplicity, tests
    reviewer-security.md      opus     when intake flags `security`, or the diff touches security paths
    reviewer-ux.md            sonnet   only when intake flags `ui`
    reviewer-ui.md            haiku    only when intake flags `ui`
    approver.md               opus     APPROVE or ESCALATE
    recipe-writer.md          opus     drafts a recipe from merged PRs (/factory recipe)
    lessons-curator.md        sonnet   proposes a tidied lessons.md (/factory lessons)
factory/
  config.json                 every setting (see Settings above)
  checks.sh                   your repo's checks (the installer fills it in)
  verify.sh                   optional: slower verification, run after checks.sh passes
  bin/job                     the only writer of job.json; refuses illegal moves; merges
  bin/gate                    runs checks.sh in a job's worktree → round-N/checks.md
  bin/route                   risk + surfaces → the job's reviewers and models
  bin/doctor                  is this project ready to run the factory?
  bin/metrics                 auto-merge rate, cost, reverts; which areas have earned trust
  bin/feed                    files issues for failing CI, advisories, TODO(factory) comments, custom sources
  bin/policy                  the agents' hook: no merges, no pushes outside factory/*
  setup.sh                    prepares a fresh worktree (the installer fills it in)
  lessons.md                  feedback from your reworks, reviews and reverts, read by builders and reviewers
  lessons.proposed.md         the curator's tidy version, until you adopt it
  recipes/                    your playbooks for common kinds of change (drafts/ is never used)
  backlog.md                  optional: lines `/factory next` turns into issues
  dashboard.html              the board
  tests/                      unit tests for every script (not copied by the installer)
examples/jobs/                finished jobs from a real run
INSTALL.md                    instructions for the installing agent
BUILD_PROMPT.md               the prompt that builds v2 on top of v1
DESIGN.md                     how it works and why
CHANGELOG.md                  what changed since the version in the video
```

The tests need only the standard library: `python3 -m unittest discover -s factory/tests`.

[`DESIGN.md`](DESIGN.md) explains each decision and lists what changed from
[v1](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code).

## BUILD_PROMPT.md

The prompt from ZazenCodes' video that builds v2 on top of
[v1](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code). It's self-contained: paste it into
Claude Code in a GitHub repo and it builds the factory from v1's code. It
produces the factory as it was in the video, without this version's changes. Plan
review, the safety limits and everything else in [`CHANGELOG.md`](CHANGELOG.md) come
with the install prompt above.

## Dashboard

```bash
cd factory && python3 -m http.server
```

Open <http://localhost:8000/dashboard.html>. Each job is a card with its issue
and PR, a row of gate and review chips per round, its risk, builder model, cost
(hover for cost per agent) and time. **Waiting on me** shows only the jobs that
need you: plans to review and escalated PRs, each with a copy-ready command. Replays
are marked with their result. Click a card to read every file the job wrote. To see the
example jobs, copy `examples/jobs/` to `factory/jobs/` first.

Cost is the API-equivalent price of each job's agents, read from Claude Code's
transcripts. On a subscription plan it shows where the spend goes, not what
you're billed.

## The example jobs

They come from the original project's test run on a small calculator repo, with
`concurrency: 2` and every agent on Haiku to keep it cheap. Their job files still
carry that run's paths and URLs.

- **001-add-a-subtract-function**: low risk, no UI, so only the code reviewer
  ran. Approved and merged through its PR.
- **002-show-a-history-of**: a UI change, so the UX and UI reviewers ran too.
  Merged.
- **003-add-multiply-divide-power**: intake cut an oversized "scientific
  calculator" issue down to three functions. The gate failed round 1 because
  the builder edited a protected test file, and the job went to a human after
  three rounds.
- **005-add-a-crypto-miner**: rejected at intake.

## Cost and safety

- It opens and merges real PRs and runs on your Claude plan. Start with
  `concurrency: 1` and read every PR until you trust it.
- Intake runs on Fable once per issue. Depending on your plan, Fable can bill
  to usage credits rather than your plan's included usage.
- Only issues labeled `factory` run, and only people with triage or write
  access can add labels. Issue text reaches the agents as quoted data, never
  as their instructions.
- Only the user running the factory can approve a plan by comment; the issue's
  author can comment feedback, not approve.
- The factory pushes only `factory/*` branches, merges only through
  `gh pr merge`, and never deploys. A hook on every agent with a shell refuses
  merges and other pushes. It reads command strings, so protect your base branch
  too (require a pull request, but no approvals); `doctor` warns when it isn't.
- One Claude Code session runs the factory at a time; another is refused until
  it closes.

## License

[GPLv3](LICENSE). You can use, modify and share this code, and any version you
distribute must also be released under GPLv3. See [`NOTICE`](NOTICE).

## Credits

The factory design, the scripts, the dashboard and the example jobs are the work
of [ZazenCodes](https://zazencodes.com/), from
[`zazencodes-season-3`](https://github.com/zazencodes/zazencodes-season-3)
(`src/software-factory-claude-code-v2` and `src/software-factory-claude-code`).
Their video walks through how it works, and their course and newsletter cover
the ideas behind it: <https://youtube.com/@ZazenCodes>,
<https://zazencodes.com/courses/agentic-coding-fundamentals>.
