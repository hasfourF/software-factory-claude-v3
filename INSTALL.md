# Install the software factory

You are a coding agent installing this factory into the user's project. Copy
what's generic, adapt what's repo-specific, verify it, and report. Work in the
project's root. Don't clone this repository.

The source is the repository the user pointed you at,
`hasfourF/software-factory-claude-v3`. It may be private, so read its files
with the signed-in `gh` (the same account that must be able to push to the
user's project):

```bash
gh api -H "Accept: application/vnd.github.raw" repos/hasfourF/software-factory-claude-v3/contents/<path>
```

## 0. Check the project

Stop and tell the user if any of these fail:

- It's a git repo with an `origin` on GitHub, and `gh auth status` shows a user
  who can push to it and manage its labels.
- Its default branch (`gh repo view --json defaultBranchRef`) exists on
  `origin`.
- `claude --version` is 2.1.257 or later (the intake agent runs on Fable).
- `python3 --version` is 3.10 or later. The scripts use only the standard
  library.
- None of the files in step 1 already exist. If one does, show the user the
  clash and ask before overwriting.

## 1. Copy

Copy these files to the same paths in the project, unchanged:

```
.claude/skills/factory/SKILL.md
.claude/agents/intake.md
.claude/agents/spec-writer.md
.claude/agents/builder.md
.claude/agents/reviewer-code.md
.claude/agents/reviewer-security.md
.claude/agents/reviewer-ux.md
.claude/agents/reviewer-ui.md
.claude/agents/approver.md
factory/config.json
factory/checks.sh
factory/setup.sh
factory/bin/job
factory/bin/gate
factory/bin/route
factory/bin/doctor
factory/dashboard.html
```

```bash
SRC=repos/hasfourF/software-factory-claude-v3/contents
for f in <the paths above>; do
  mkdir -p "$(dirname "$f")" && gh api -H "Accept: application/vnd.github.raw" "$SRC/$f" > "$f"
done
chmod +x factory/checks.sh factory/setup.sh factory/bin/job factory/bin/gate factory/bin/route factory/bin/doctor
```

Don't copy `README.md`, `DESIGN.md`, `INSTALL.md`, `CHANGELOG.md`, `LICENSE`,
`examples/`, `docs/` or `factory/tests/`. They describe the reference, not the user's project.

## 2. Adapt

**`factory/checks.sh`.** Replace the placeholder with the project's real
checks: install dependencies if a fresh worktree needs them, then lint,
typecheck, tests and build, whichever the project has. Find them in
`AGENTS.md`, `CLAUDE.md`, `package.json` scripts, `Makefile`, `pyproject.toml`
and CI config. The script runs with a job's worktree as its working directory.
It must be non-interactive, must not rewrite files (no `--fix`, no
`--update-snapshots`), and must exit non-zero on any failure. Keep
`set -euo pipefail`.

**`factory/setup.sh`.** What a fresh worktree needs before an agent touches it:
install dependencies, copy `.env.example`. The factory runs it once, with the
new worktree as the working directory, and refuses to start a job whose setup
fails. If the project needs nothing, delete the file. Keep it non-interactive.

**`factory/config.json`.**

- `base_branch`: the default branch.
- `merge_method`: `merge`, `squash` or `rebase`, one the repo allows
  (`gh api repos/{owner}/{repo} --jq '{allow_merge_commit, allow_squash_merge, allow_rebase_merge}'`).
- `protected_paths`: keep the factory and workflow entries and add patterns for
  the existing tests, such as `tests/*` or `src/*.test.ts`. They are fnmatch
  patterns, so `*` also matches `/`. The gate fails a branch that modifies or
  deletes a matching file; new tests are fine.
- `force_security_paths`, `always_escalate_paths`, `gate.dependency_files`: add
  this project's own. A diff that touches a security path gets the security
  review whatever intake said; one that touches an escalate path, changes a
  dependency manifest or exceeds `gate.max_diff_lines` always goes to a human.
- `plan_review`: `high` makes the factory post the spec on the issue and wait
  for the user on high-risk jobs. `never`, `medium` and `always` are the other
  settings; the `factory:plan` label asks for it on one issue. Ask the user which
  they want; `high` is the default.
- `limits`: the per-job and per-run cost caps (API-equivalent USD) and the stage
  timeout. Ask the user for caps they are comfortable with.
- `notify.command`: optional, e.g. `notify-send "factory" "$FACTORY_MESSAGE"`.
- `ports`: move `base` if the project already uses ports 5100–5199.
- Leave `concurrency`, `max_rounds`, `routing`, `surface_reviewers`, `gate.retries`
  and `prices_usd_per_mtok` as they are unless the user asks.

**Agents.** The checklists are general on purpose. Tailor them to the stack
without changing their structure, file names, first-line formats or one-line
replies:

- `reviewer-security.md`: this project's hot spots (its auth, its data access
  rules, its payment and webhook code, where user input meets queries or HTML).
- `reviewer-ui.md`: where the design tokens, theme and shared components live.
  Also tell `reviewer-ux.md` and `reviewer-ui.md` how to start the app, if
  `AGENTS.md` doesn't already.
- `reviewer-ux.md`: the kinds of users the app has.
- `approver.md`: what a human must always see in this project, added to the
  ESCALATE list.
- `intake.md`: one line under **Decide** saying what the project is for, so
  intake can tell what belongs.

**`AGENTS.md`** (or `CLAUDE.md`, whichever the project uses; create `AGENTS.md`
if neither exists). Every agent reads it. Make sure it says:

- how to set up a fresh checkout (install dependencies, env files to copy);
- how to start the dev server on a given port, if the project has one;
- the validation commands, matching `factory/checks.sh`.

Then add a short section:

```markdown
## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python3 -m http.server`, then
open http://localhost:8000/dashboard.html.
```

**`.gitignore`.** Add `/factory/jobs/`, the runtime state, and nothing else of the
factory: everything else you copied must be committed, because every job
branches from `origin/<base_branch>`. If an existing rule ignores `.claude` (or
`.claude/agents`, or `factory/`), add exceptions such as `!.claude/skills/factory/`
and `!.claude/agents/` so the skill and agents can be committed. Check with
`git check-ignore -v .claude/agents/intake.md`, which must print nothing.

**Labels.** Create them on GitHub:

```bash
gh label create factory --color 5319E7 --description "Build this with the software factory"
gh label create factory:needs-info --color FBCA04 --description "The factory asked the author a question"
gh label create factory:needs-human --color D93F0B --description "The factory needs a human decision on the PR"
gh label create factory:plan --color 0E8A16 --description "Show me the plan before the factory builds this"
gh label create factory:plan-review --color FBCA04 --description "The factory posted its plan and is waiting for you"
gh label create factory:plan-approved --color 0E8A16 --description "Build the plan as written"
gh label create factory:p0 --color B60205 --description "Build first"
gh label create factory:p1 --color D93F0B --description "Build soon"
gh label create factory:p2 --color FBCA04 --description "Build when there is time"
```

## 3. Verify

1. `factory/bin/doctor` exits 0. It checks the tools and `gh` sign-in, the
   config, the base branch and merge method, the labels, `.gitignore`, the skill
   and agents (including frontmatter keys: Claude Code ignores unknown keys
   without a warning, so a typo silently changes behaviour), and that
   `factory/checks.sh` and `factory/setup.sh` pass on a clean checkout of the base
   branch. If checks.sh fails there, the factory can never pass a job: fix the
   script (not the project) or tell the user what's broken. Fix every FAIL line;
   explain any `warn` to the user.
2. `factory/bin/job queue` runs without an error.

## 4. Hand over

Commit the install on a branch with a one-line message and show the user the
diff. Ask before pushing: the factory branches every job from
`origin/<base_branch>`, so the install must be merged there before the first
run.

Then tell the user, in a few lines:

- Label one or two small issues `factory`, then run `/factory run` in Claude
  Code from the project root.
- Every job ends as a PR. The approver merges what it approves; the rest wait
  labeled `factory:needs-human`. Approve one by merging it on GitHub, or
  comment on it and run `/factory rework <issue>`.
- Intake runs on Fable, once per issue. Depending on their plan, Fable can
  bill to usage credits rather than the plan's included usage.
- To start carefully, set `concurrency` to 1 in `factory/config.json` and read
  every PR until they trust it.
- Add the `factory:plan` label to an issue to read the factory's plan before it
  builds. It posts the spec on the issue; they comment to revise it, then add
  `factory:plan-approved` (or comment `/approve`) to build.
- `factory/bin/doctor` is the first thing to run when something looks wrong.

## Moving from v1

v1 ([zazencodes' original](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code)) keeps a `factory/backlog.md`, merges
locally and has `/factory approve`. To move a project over, install v2 as above
(its `.claude/` files replace v1's, so show the user the diff), then:

- Delete v1's `factory/jobs/`, or finish and merge those jobs first: v2 reads a
  different `job.json` and will not resume them.
- Turn backlog lines into issues with `factory/bin/job backlog` (one per run), or
  paste them into GitHub by hand and delete `backlog.md`.
- `/factory approve <job>` is gone; the user merges the PR on GitHub.
