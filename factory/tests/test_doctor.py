import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import commit, git, load_script, make_repo

doctor = load_script("doctor")


class Project(unittest.TestCase):
    """A throwaway project and home directory, so the checks never read the real ~/.claude."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo, self.home = Path(tmp.name, "repo"), Path(tmp.name, "home")
        self.repo.mkdir()
        self.home.mkdir()
        self.lines = []
        for patcher in (mock.patch.object(doctor, "REPO", self.repo), mock.patch.object(Path, "home", return_value=self.home),
                        mock.patch.object(doctor, "report", lambda level, what, detail="": self.lines.append((level, what, detail)))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def put(self, root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def settings(self, **perms):
        self.put(self.repo, ".claude/settings.json", json.dumps({"permissions": perms}))

    def levels(self, what):
        return [level for level, w, _ in self.lines if what in w]


class Collisions(Project):
    def test_clean(self):
        doctor.check_collisions()
        self.assertEqual(["ok"], self.levels("clash"))

    def test_the_factorys_own_files_are_not_clashes(self):
        for a in doctor.AGENTS:
            self.put(self.repo, f".claude/agents/{a}.md", f"---\nname: {a}\n---\nx\n")
        self.put(self.repo, ".claude/skills/factory/SKILL.md", "---\nname: factory\n---\nx\n")
        doctor.check_collisions()
        self.assertEqual(["ok"], self.levels("clash"))

    def test_another_project_agent_with_a_factory_name_fails(self):
        self.put(self.repo, ".claude/agents/my-builder.md", "---\nname: builder\ndescription: mine\n---\nx\n")
        doctor.check_collisions()
        self.assertEqual(["FAIL"], self.levels("clash"))
        self.assertIn("my-builder.md", self.lines[0][2])

    def test_a_skill_called_factory_elsewhere_fails(self):
        self.put(self.repo, ".claude/skills/deploy/SKILL.md", "---\nname: factory\n---\nx\n")
        doctor.check_collisions()
        self.assertEqual(["FAIL"], self.levels("clash"))

    def test_a_user_level_clash_warns(self):
        self.put(self.home, ".claude/agents/approver.md", "---\nname: approver\n---\nx\n")
        doctor.check_collisions()
        self.assertEqual(["warn"], self.levels("clash"))

    def test_unrelated_names_are_fine(self):
        self.put(self.repo, ".claude/agents/db-expert.md", "---\nname: db-expert\n---\nx\n")
        self.put(self.home, ".claude/skills/other/SKILL.md", "---\nname: other\n---\nx\n")
        doctor.check_collisions()
        self.assertEqual(["ok"], self.levels("clash"))


class Rules(unittest.TestCase):
    def test_prefix_rules(self):
        covers = doctor.rule_covers
        self.assertTrue(covers("Bash(git *)", "git push origin x"))
        self.assertTrue(covers("Bash(git:*)", "git push origin x"))
        self.assertTrue(covers("Bash(factory/bin/*)", "factory/bin/job queue"))
        self.assertTrue(covers("Bash", "anything"))
        self.assertFalse(covers("Bash(git status*)", "git push origin x"))
        self.assertFalse(covers("Read(*)", "git push"))
        self.assertFalse(covers("Bash()", "git push"))


class Permissions(Project):
    def test_nothing_allowed_warns(self):
        doctor.check_permissions()
        self.assertEqual(["warn"], self.levels("permissions"))

    def test_the_minimal_allowlist_is_enough(self):
        self.settings(allow=["Bash(factory/bin/*)", "Bash(bash factory/checks.sh*)", "Bash(git push -u origin factory/*)",
                             "Bash(git commit *)", "Bash(gh pr create *)"])
        doctor.check_permissions()
        self.assertEqual(["ok"], self.levels("permissions"))

    def test_a_deny_rule_that_blocks_pushes_fails(self):
        self.settings(allow=["Bash(git *)", "Bash(factory/bin/*)", "Bash(gh *)", "Bash(bash *)"], deny=["Bash(git push *)"])
        doctor.check_permissions()
        self.assertIn("FAIL", self.levels("permissions"))

    def test_bypass_mode_needs_no_rules(self):
        self.settings(defaultMode="bypassPermissions")
        doctor.check_permissions()
        self.assertEqual(["ok"], self.levels("permissions"))

    def test_user_level_rules_count(self):
        self.put(self.home, ".claude/settings.json", json.dumps({"permissions": {"allow": ["Bash"]}}))
        doctor.check_permissions()
        self.assertEqual(["ok"], self.levels("permissions"))

    def test_pretooluse_hooks_are_flagged(self):
        self.put(self.repo, ".claude/settings.json", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash"}]}}))
        doctor.check_permissions()
        self.assertEqual(["warn"], self.levels("PreToolUse"))


class Config(Project):
    def config(self, **gate):
        base = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        base["gate"].update(gate)
        self.put(self.repo, "factory/config.json", json.dumps(base))

    def check(self):
        with mock.patch.object(doctor, "FACTORY", self.repo / "factory"):
            return doctor.check_config()

    def test_the_shipped_config_is_clean(self):
        self.config()
        self.assertIsNotNone(self.check())
        self.assertEqual([], [l for l in self.lines if l[0] != "ok"])

    def test_a_shell_or_bare_interpreter_on_the_verify_allowlist_warns(self):
        self.config(verify_allow=["pytest", "bash", "python3", "python3 -m pytest", "npm run test:e2e"])
        self.check()
        warned = [d for level, w, d in self.lines if level == "warn" and w == "gate.verify_allow"]
        self.assertEqual(2, len(warned))
        self.assertTrue(any(d.startswith("`bash`") for d in warned) and any(d.startswith("`python3`") for d in warned))

    def feeders(self, **feeders):
        cfg = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        cfg["feeders"].update(feeders)
        self.put(self.repo, "factory/config.json", json.dumps(cfg))
        self.check()
        return [(l, w) for l, w, _ in self.lines if w.startswith("feeders")]

    def test_the_shipped_feeders_are_fine(self):
        self.assertEqual([], self.feeders())

    def test_a_feeder_that_labels_factory_warns_and_says_so_when_unattended(self):
        self.assertEqual([("warn", "feeders")], self.feeders(todo={"enabled": True, "label": "factory"}))
        self.assertNotIn("nobody looks", self.lines[-1][2])
        self.lines.clear()
        self.feeders(ci={"enabled": True, "label": "factory"}, auto_create=True)
        self.assertIn("nobody looks", self.lines[-1][2])

    def test_a_disabled_feeder_cannot_warn(self):
        self.assertEqual([], self.feeders(deps={"enabled": False, "label": "factory"}))

    def test_bad_feeder_settings_fail(self):
        got = self.feeders(ci={"enabled": True, "label": "everyone"}, max_open=-1,
                           custom=[{"name": "Sentry!", "command": "x"}, {"name": "ok", "command": ""}])
        self.assertEqual({"feeders.custom", "feeders.ci.label", "feeders.max_open"}, {w for l, w in got if l == "FAIL"})

    def test_a_todo_pattern_that_matches_everything_or_does_not_compile_fails(self):
        self.assertEqual([("FAIL", "feeders.todo.pattern")], self.feeders(todo={"enabled": True, "pattern": ".*"}))
        self.lines.clear()
        self.assertEqual([("FAIL", "feeders.todo.pattern")], self.feeders(todo={"enabled": True, "pattern": "(unclosed"}))

    def test_bad_auto_merge_settings_fail(self):
        cfg = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
        cfg["auto_merge"] = {"risks": ["low", "extreme"], "areas": "src"}
        self.put(self.repo, "factory/config.json", json.dumps(cfg))
        self.check()
        self.assertEqual(["FAIL", "FAIL"], [l for l, w, _ in self.lines if w.startswith("auto_merge")])


class Recipes(Project):
    def test_none_is_fine(self):
        doctor.check_recipes()
        self.assertEqual([], self.lines)

    def test_a_recipe_needs_a_when_line_and_drafts_are_flagged(self):
        self.put(self.repo, "factory/recipes/add-endpoint.md", "WHEN: adding a REST endpoint\n")
        self.put(self.repo, "factory/recipes/vague.md", "## Steps\n1. do it\n")
        self.put(self.repo, "factory/recipes/drafts/add-flag.md", "WHEN: x\n")
        doctor.check_recipes()
        self.assertEqual([("warn", "recipes"), ("warn", "recipe drafts")], [(l, w) for l, w, _ in self.lines])
        self.assertIn("vague.md", self.lines[0][2])
        self.assertNotIn("add-endpoint.md", self.lines[0][2])

    def test_good_recipes_are_ok(self):
        self.put(self.repo, "factory/recipes/add-endpoint.md", "WHEN: adding a REST endpoint\n")
        doctor.check_recipes()
        self.assertEqual(["ok"], [l for l, _, _ in self.lines])


AGENTS_MD = """# Project

## Architecture
```bash
echo "this is not a validation command"; exit 9
```

## Validation commands
Run before every commit:

```bash
# Validate JSON files
python3 -m json.tool config/settings_schema.json > /dev/null
for f in locales/*.json; do
  python3 -m json.tool "$f" > /dev/null
done
```

```console
$ npm run deploy
```

## Lint
```sh
$ python3 -c "import sys"
```
"""
LOCALE = '/*\n * Shopify locale file: comments are allowed here\n */\n{"hello": "Hello"}\n'
CHECKS_SH = """#!/usr/bin/env bash
set -e
python3 - <<'PY'
import glob, json, re
for f in glob.glob("locales/*.json"):
    json.loads(re.sub(r"/\\*.*?\\*/", "", open(f).read(), flags=re.S))
json.load(open("config/settings_schema.json"))
PY
"""


class Validation(Project):
    def test_only_shell_blocks_under_validation_headings_are_found(self):
        blocks = doctor.validation_blocks(AGENTS_MD)
        self.assertEqual(["Validation commands", "Lint"], [h for h, _ in blocks])      # not Architecture, not the console block
        self.assertIn('for f in locales/*.json; do', blocks[0][1])                      # a loop stays one block
        self.assertIn("done", blocks[0][1])
        self.assertEqual('python3 -c "import sys"', blocks[1][1])                       # a "$ " prompt is dropped

    def test_comment_only_and_non_shell_blocks_are_skipped(self):
        text = "## Tests\n```bash\n# nothing to run\n```\n```python\nprint(1)\n```\n```json\n{}\n```\n"
        self.assertEqual([], doctor.validation_blocks(text))

    def test_a_heading_inside_a_block_does_not_change_the_heading(self):
        text = "## Validation\n```bash\n# Build everything\nmake test\n```\n"
        self.assertEqual([("Validation", "# Build everything\nmake test")], doctor.validation_blocks(text))

    def project(self, agents_md):
        """A project whose base branch has the factory committed, as an install requires."""
        tmp, repo = make_repo({"AGENTS.md": agents_md, "locales/en.json": LOCALE, "config/settings_schema.json": "{}\n",
                               "factory/checks.sh": CHECKS_SH})
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(doctor, "REPO", repo), mock.patch.object(doctor, "FACTORY", repo / "factory")):
            p.start()
            self.addCleanup(p.stop)
        return repo

    def run_validation(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            doctor.check_validation({"base_branch": "main"})
        return out.getvalue()

    def test_a_command_that_fails_where_checks_sh_passes_is_reported_as_a_disagreement(self):
        """The real case: AGENTS.md runs strict json.tool over locale files that start with a comment."""
        self.project(AGENTS_MD)
        shown = self.run_validation()
        self.assertIn("for f in locales/*.json", shown)                    # the commands are shown before they run
        failed = [(l, w, d) for l, w, d in self.lines if l == "FAIL"]
        self.assertEqual(1, len(failed))
        self.assertIn("[Validation commands]", failed[0][1])
        self.assertIn("checks.sh passes on the same code", failed[0][2])
        self.assertIn("bash factory/checks.sh", failed[0][2])
        self.assertEqual(("ok", "AGENTS.md [Lint]"), [(l, w) for l, w, _ in self.lines if "Lint" in w][0])

    def test_pointing_agents_md_at_checks_sh_clears_it(self):
        self.project("## Validation\n```bash\nbash factory/checks.sh\n```\n")
        self.run_validation()
        self.assertEqual(["ok"], [l for l, _, _ in self.lines])

    def test_a_failure_checks_sh_shares_is_a_plain_failure(self):
        repo = self.project("## Validation\n```bash\nexit 3\n```\n")
        (repo / "factory" / "checks.sh").write_text("exit 1\n")
        self.run_validation()
        self.assertEqual(1, len(self.lines))
        self.assertIn("as checks.sh does", self.lines[0][2])

    def test_it_runs_on_the_base_branch_not_the_working_tree(self):
        repo = self.project("## Validation\n```bash\ntest -f marker.txt\n```\n")
        (repo / "marker.txt").write_text("only in the working tree")          # uncommitted, so absent from origin/main
        self.run_validation()
        self.assertEqual("FAIL", self.lines[0][0])

    def test_nothing_to_run(self):
        self.project("# Project\nNo commands here.\n")
        self.run_validation()
        self.assertEqual([("ok", "validation commands")], [(l, w) for l, w, _ in self.lines])

    def test_no_agents_file(self):
        repo = self.project("x")
        (repo / "AGENTS.md").unlink()
        self.run_validation()
        self.assertEqual("warn", self.lines[0][0])


class Layout(Project):
    def test_foreign_files_in_factory_warn(self):
        self.put(self.repo, "factory/bin/job", "x")
        self.put(self.repo, "factory/widgets.py", "x")
        doctor.check_layout()
        self.assertIn("widgets.py", self.lines[0][2])

    def test_our_files_are_fine(self):
        for n in ("bin/job", "checks.sh", "config.json", "lessons.md"):
            self.put(self.repo, f"factory/{n}", "x")
        doctor.check_layout()
        self.assertEqual([], self.lines)

    def test_a_long_unreferenced_claude_md_beside_a_stub_agents_md_warns(self):
        self.put(self.repo, "AGENTS.md", "# Notes\n")
        self.put(self.repo, "CLAUDE.md", "\n".join(f"rule {i}" for i in range(30)))
        doctor.check_layout()
        self.assertEqual(["warn"], self.levels("AGENTS.md"))

    def test_agents_md_that_points_at_claude_md_is_fine(self):
        self.put(self.repo, "AGENTS.md", "See CLAUDE.md\n")
        self.put(self.repo, "CLAUDE.md", "\n".join(f"rule {i}" for i in range(30)))
        doctor.check_layout()
        self.assertEqual([], self.lines)



class PolicyHook(Project):
    HOOK = "hooks:\n  PreToolUse:\n    - matcher: Bash\n      hooks:\n        - type: command\n          command: factory/bin/policy\n"

    def agents(self, builder_front):
        for a in doctor.AGENTS:
            front = builder_front if a == "builder" else f"name: {a}\nmodel: opus\ntools: Read, Write\n"
            self.put(self.repo, f".claude/agents/{a}.md", f"---\n{front}---\nx\n")
        self.put(self.repo, ".claude/skills/factory/SKILL.md", "x")

    def test_an_agent_with_a_shell_needs_the_hook(self):
        self.agents("name: builder\nmodel: sonnet\ntools: Read, Bash\n")
        with mock.patch.object(doctor, "sh", lambda *a, **k: mock.Mock(returncode=0, stdout="x")):
            doctor.check_agents()
        self.assertEqual(["FAIL"], self.levels("builder.md"))

    def test_with_the_hook_it_is_fine(self):
        self.agents("name: builder\nmodel: sonnet\ntools: Read, Bash\n" + self.HOOK)
        with mock.patch.object(doctor, "sh", lambda *a, **k: mock.Mock(returncode=0, stdout="x")):
            doctor.check_agents()
        self.assertEqual([], self.levels("builder.md"))
        self.assertEqual(["ok"], self.levels("skill and agents"))


class Protection(Project):
    def check(self, classic, rules):
        answers = {"branches": classic, "rules": rules}

        def sh(*cmd, cwd=None):
            code, out = answers["rules" if "/rules/" in cmd[2] else "branches"]
            return mock.Mock(returncode=code, stdout=out)

        with mock.patch.object(doctor, "sh", sh):
            doctor.check_protection("main")
        return self.lines[-1][0]

    def test_unprotected_warns(self):
        self.assertEqual("warn", self.check((0, "false\n"), (0, "\n")))
        self.assertIn("no approvals", self.lines[-1][2])

    def test_branch_protection_or_a_ruleset_is_enough(self):
        self.assertEqual("ok", self.check((0, "true\n"), (0, "\n")))
        self.assertEqual("ok", self.check((0, "false\n"), (0, "pull_request non_fast_forward\n")))

    def test_unreadable_warns_without_claiming_either_way(self):
        self.assertEqual("warn", self.check((1, ""), (1, "")))
        self.assertIn("couldn't read", self.lines[-1][2])


if __name__ == "__main__":
    unittest.main()
