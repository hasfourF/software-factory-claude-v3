import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_script

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


if __name__ == "__main__":
    unittest.main()
