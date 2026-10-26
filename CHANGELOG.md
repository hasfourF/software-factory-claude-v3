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

### Added

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
