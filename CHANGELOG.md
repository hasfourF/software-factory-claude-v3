# Changelog

## Unreleased

Changes since ZazenCodes' v2, the version in their video.

### Fixed

- **The skill and agents are in the repo.** `.claude/skills/factory/SKILL.md` and
  the eight agents in `.claude/agents/` were never committed, because the root
  `.gitignore` ignores `.claude` and only v1 had an exception. The install
  prompt pointed at files that did not exist. The exception is added for v2.
- A secret scan pattern that missed names like `SECRET_KEY` (found by running the
  gate against a throwaway repo).
- The dashboard stopped updating as soon as a job existed. `job create` leaves a hidden
  `.claim-NNN` folder in `factory/jobs/`, the dashboard tried to load a `job.json` from it,
  got a 404, and that one failure rejected the whole load. It now ignores hidden folders and
  skips a job folder whose `job.json` isn't written yet (it exists a few seconds before),
  and a malformed `job.json` is shown as a banner instead of blanking the board.
- Two approved jobs could merge at once, each gated against a `main` without the other's
  change. `job merge` now holds a lock (`factory/jobs/.merge.lock`) from syncing with main
  to the merge, and passes `gh pr merge --match-head-commit` the commit the merge gate
  passed, so a push after the gate makes GitHub refuse the merge. A branch that moved
  after the gate can no longer be approved or merged on reviews of the older commit: the
  job goes to a human.
- A rescoped job built a smaller feature than its issue asked for, and its PR closed
  the issue, so the rest disappeared. A rescope now always waits for plan review, and
  on merge intake's `## Deferred` list is filed as a `factory:proposed` issue.
- When `checks.sh` broke on the base branch, every job failed the gate and builders
  spent rounds fixing code they hadn't touched. The gate now reruns a failing
  `checks.sh` on the commit the branch started from; if it fails there too, the job
  goes to a human and `job guard` stops the run.
- A rescoped PR merged by hand on GitHub skipped the follow-up issue for its deferred
  work: `reconcile` marked the job merged without filing it. Both paths file it now.
- The gate ran the checks on the worktree, not the commit, so an uncommitted edit could
  make a commit pass that would fail as pushed. It now fails on uncommitted changes
  before the checks or tracked files they change, and `job` refuses to approve or merge
  a worktree with uncommitted changes since the gate.
- `depends-on: #n` counted any closed issue as done, including one closed as not
  planned, and found only the last 200 closed issues. It now asks for #n itself and
  needs its factory job merged or the issue closed as completed.
- `checks.sh` had no time limit, so a hung test in the merge gate held the merge lock
  for good. `gate.checks_timeout` (30 minutes) kills it and everything it started.
- Two sessions running `/factory run` would both resume the same jobs and put two
  builders on one branch. `job` now records the session that runs the factory in
  `factory/jobs/.run.json` and refuses changes from any other session while that
  process lives. `job release` hands it over; a closed session lets go by itself.

### Added

- `factory/bin/policy`, a `PreToolUse` hook on every agent with a shell. Agents share
  your `gh` login, so only their prompts kept them from merging or pushing to the base
  branch; the hook refuses `gh pr merge`, `gh api` writes and pushes outside `factory/*`.
  `doctor` fails an agent with a shell but no hook, and warns when the base branch has
  no protection.
- **Plan review.** The spec can be posted on the issue and wait for you. Comment
  to revise it, `/approve` or the `factory:plan-approved` label to build. Asked
  for with the `factory:plan` label or `plan_review` in config.json. New stage
  `spec-review`.
- **Specs with numbered acceptance criteria, a `Files to touch` section and a
  `Recommendations` section.** The code reviewer maps each criterion to a test.
- `factory/bin/doctor`: checks the tools, config, labels, agents and that
  `checks.sh` passes on the base branch.
- The installer and `doctor` account for a project that already uses Claude Code:
  skill and agent name clashes (project and `~/.claude`), permission rules that
  would stall or block unattended agents (with a minimal allowlist to propose),
  `PreToolUse` hooks, an unrelated `factory/` folder, and `AGENTS.md` shadowing
  `CLAUDE.md`.
- `factory/setup.sh`: runs once in every new worktree.
- Gate: retries flaky checks, scans added lines for secrets, flags large diffs,
  changed dependency manifests, escalate-paths, security-paths and files the
  spec did not list.
- Flags that cannot be overridden: `large-diff`, `new-dependency` and
  `escalate-path` always escalate to a human.
- The security review is added when the diff touches `force_security_paths`.
- A failure that repeats the previous round's escalates immediately.
- Cost caps per job and per run (`limits`), and cost per agent role.
- Merge conflicts with the base branch go back to the builder (`conflict-<k>.md`)
  while rounds remain.
- PRs merged or closed by hand end their job; new stage `abandoned`.
- `job stale`, `job post-merge` (is CI on the base branch still green), `job guard`.
- `factory:p0` to `p2` priorities, `depends-on: #n`, and no two jobs building
  the same files at once.
- `factory/lessons.md`: your rework feedback, read by later builders and
  reviewers.
- `factory/backlog.md` and `/factory next`, which turns a backlog line into an issue.
- Optional notifications (`notify.command`).
- UX and UI reviewers save the screenshots they judge, next to their review.
- Dashboard: a "Waiting on me" filter, copy-ready commands, plan-review cards,
  and cost per agent.
- Job numbers are claimed with an atomic `mkdir`, so concurrent creators cannot
  share one.
- Unit tests for `job` and `gate` (`factory/tests/`).

- **Metrics.** `factory/bin/metrics`: auto-merge rate, cost and time per merged
  PR, rounds, gate failures, why jobs escalated and reverts, by risk, area and
  surface; it names the areas that have earned auto-merge and prints the config.
- **Earned autonomy.** `auto_merge.risks` and `auto_merge.areas` in config.json.
  A change outside them is never merged without a human, enforced in `job` and
  `gate` (new `unearned-area` flag), not left to the approver.
- **Replay.** `/factory replay <pr>` rebuilds a merged PR's issue offline from a
  one-commit snapshot of the code before it (no later history), then runs the
  shipped PR's own tests against the result. Nothing is pushed, commented on or
  merged, and `job` refuses any GitHub call from a replay. `replay-list`,
  `replay-create`, `replay-finish`, `replay-clean`. New stage `replayed`.
- The gate writes `round-N/changed-files.txt`.
- **Acceptance commands.** A spec's `## Verification` lines (`AC1: <command>`) are run
  by the gate, without a shell, and only if the command starts with an entry of
  `gate.verify_allow` (empty by default). A failing command fails the gate.
- **`factory/verify.sh`.** Optional slow verification (app smoke tests, visual
  regression, coverage), run after `checks.sh` passes with `$FACTORY_JOB` and
  `$FACTORY_PORT`.
- **CODEOWNERS.** A path with an owner raises `owned-path`, which always goes to a
  human; rules come from the base branch.

- **Recipes.** `factory/recipes/<name>.md` is the project's playbook for a kind of change.
  Intake picks at most one (`RECIPE:` in intake.md, validated against the files), and
  the spec-writer, builder and code reviewer follow it. `/factory recipe <pr>...` drafts
  one from merged PRs into `factory/recipes/drafts/`, which is never used until a human
  moves it. `metrics` reports results by recipe.
- **Learning loop.** `job learn` (and `/factory learn`, run after every `/factory run`)
  adds comments by the repo's owners, members, collaborators and the operator on merged
  factory PRs, and reverts, to `lessons.md`. Bots, strangers, the factory's own comments
  and one-word replies are left out; repeats are skipped; each entry carries the areas
  it touched. `/factory lessons` proposes a deduplicated, grouped version in
  `lessons.proposed.md` for a human to adopt.

- **Feeders.** `factory/bin/feed` (`/factory feed`) files issues for a failing CI run on
  the base branch, open Dependabot advisories, `TODO(factory)` comments on the base
  branch, and custom commands. A dry run unless `--create`. Issues get `factory:feed` and
  `factory:proposed` and wait for a human to add `factory`; a source can be set to queue
  directly, which `doctor` warns about. Stable keys, a cooldown, `max_per_run` and
  `max_open` stop duplicates and floods, and it files nothing if it can't tell what is
  already filed. Proposed issues show as waiting in `job queue`; jobs record their
  `origin` and `metrics` reports by it.

- **Docs that can't drift.** `factory/tests/test_docs.py` fails when the README, the
  skill, `INSTALL.md`, `DESIGN.md`, the scripts and `config.json` disagree about
  commands, flags, subcommands, labels, settings and their defaults, agents, scripts,
  stages or links. The README now has a full command reference.

- **One list of checks.** `checks.sh` now decides, in the builder, code reviewer and
  approver prompts. A command in `AGENTS.md` that fails where `checks.sh` passes is
  reported as `DISAGREES:` instead of blocking or looping, the approver escalates it so a
  person fixes the two lists, and `metrics` counts it as its own reason. The installer
  stops leaving two lists, and `factory/bin/doctor --run-validation` runs the commands
  `AGENTS.md` lists on a clean base branch and flags any that fail where `checks.sh`
  passes. Found in a Shopify theme whose `AGENTS.md` ran strict `json.tool` over JSONC
  locale files.

### Changed

- `protected_paths` also covers `factory/bin/*`, `factory/setup.sh` and
  `.github/workflows/*`.
- `job` resolves its working directory when it runs, not when it loads.
- Agent prompts begin `Job: <id>. Job folder: ... Role: <agent>.` so the cost
  can be split by role.

### Not changed

- The model prices in `config.json` and `DESIGN.md` are as they were.

### Upgrading an installed factory

Re-run the install prompt in the project; it shows you the diff. Create the new
labels (see `INSTALL.md`). Old `config.json` files keep working: every new
setting has a default. Jobs in `factory/jobs/` carry on, and fields they lack
(`depends_on`, `priority`, `spec_revisions`) are read as empty.
