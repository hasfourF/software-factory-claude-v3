"""The README, the skill, the scripts and config.json must agree, so the docs can't quietly go stale."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
SKILL = (ROOT / ".claude/skills/factory/SKILL.md").read_text()
CONFIG = json.loads((ROOT / "factory/config.json").read_text())


def script(name):
    return (ROOT / "factory/bin" / name).read_text()


def section(text, heading):
    m = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^#{{1,3}} |\Z)", text, re.M | re.S)
    assert m, f"README has no {heading!r} section"
    return m.group(1)


def table_rows(text):
    return [[c.strip() for c in line.strip().strip("|").split("|")] for line in text.splitlines()
            if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line)][1:]


def code(cell):
    return re.findall(r"`([^`]+)`", cell)


class Commands(unittest.TestCase):
    def test_every_slash_command_in_the_readme_is_in_the_skill_and_back(self):
        readme = set()
        for row in table_rows(section(README, "## Commands")):
            for cell in code(row[0]):
                m = re.match(r"/factory ([a-z]+)", cell)
                if m:
                    readme.add(m.group(1))
        skill = {m for m in re.findall(r"^### /factory ([a-z]+)", SKILL, re.M)}
        self.assertEqual(skill, readme)

    def test_the_skill_description_names_every_command(self):
        description = re.search(r"^description: (.*)$", SKILL, re.M).group(1)
        for h in re.findall(r"^### (/factory .*?)(?: \[.*)?$", SKILL, re.M):
            word = h.split()[1]
            if not word.startswith("<"):
                self.assertIn(f"/factory {word}", description, h)

    def test_every_job_subcommand_in_the_readme_exists(self):
        job = script("job")
        dispatched = set(re.findall(r'cmd == "([a-z-]+)"', job))
        for sub in set(re.findall(r"factory/bin/job ([a-z-]+)", README)):
            self.assertIn(sub, dispatched, f"README mentions `job {sub}`, which job does not have")

    def test_the_subcommands_the_readme_says_not_to_run_are_real(self):
        said = section(README, "### From the terminal").split("don't run its other subcommands")[1].split("The skill calls them")[0]
        names = set(re.findall(r"`([a-z-]+)`", said)) - {"gate", "route"}
        dispatched = set(re.findall(r'cmd == "([a-z-]+)"', script("job")))
        self.assertLessEqual(names, dispatched)
        listed = set(re.findall(r"factory/bin/job ([a-z-]+)", section(README, "### From the terminal")))
        listed |= {"replay-clean"}
        self.assertEqual(set(), (dispatched - names) - listed, "a job subcommand is in neither README list")

    def test_documented_flags_exist_in_the_scripts(self):
        for tool in ("metrics", "feed", "doctor"):
            flags = set(re.findall(r"(--[a-z-]+)", " ".join(
                row[0] for row in table_rows(section(README, "### From the terminal")) if f"bin/{tool}" in row[0])))
            for flag in flags:
                self.assertIn(flag, script(tool), f"{tool} has no {flag}")
        slash = " ".join(row[0] for row in table_rows(section(README, "## Commands")))
        for flag in set(re.findall(r"(--[a-z-]+)", slash)):
            self.assertTrue(flag in script("metrics") or flag in script("feed"), flag)

    def test_every_script_flag_is_documented(self):
        terminal = " ".join(row[0] for row in table_rows(section(README, "### From the terminal")))
        for tool, flags in {"metrics": ["--json", "--github", "--min"], "feed": ["--create", "--source"], "doctor": ["--skip-checks"]}.items():
            for flag in flags:
                self.assertIn(flag, terminal, f"{tool} {flag} is not in the README")


class ConfigAndLabels(unittest.TestCase):
    def test_labels_in_the_readme_exist_and_back(self):
        documented = {c for row in table_rows(section(README, "### Labels")) for c in code(row[0])}
        documented = {c for c in documented if c.startswith("factory")}
        real = {v for k, v in CONFIG["labels"].items() if k != "priority_prefix"}
        prefix = CONFIG["labels"]["priority_prefix"]
        self.assertEqual(real, documented - {f"{prefix}0", f"{prefix}1", f"{prefix}2"})

    def test_install_creates_every_label(self):
        install = (ROOT / "INSTALL.md").read_text()
        for label in {v for k, v in CONFIG["labels"].items() if k != "priority_prefix"} | {"factory:p0", "factory:p1", "factory:p2"}:
            self.assertIn(f"gh label create {label} ", install, label)

    def test_settings_in_the_readme_are_real_config_keys(self):
        for row in table_rows(section(README, "### Settings")):
            for name in code(row[0]):
                node = CONFIG
                for part in name.split("."):
                    self.assertIn(part, node, f"README documents setting `{name}`; config.json has no `{part}`")
                    node = node[part] if isinstance(node, dict) else None

    def test_documented_defaults_match_config_json(self):
        rows = {row[0]: row[1] for row in table_rows(section(README, "### Settings"))}
        self.assertEqual(f"`{CONFIG['concurrency']}`", rows["`concurrency`"])
        self.assertEqual(f"`{CONFIG['max_rounds']}`", rows["`max_rounds`"])
        self.assertEqual(f"`{CONFIG['plan_review']}`", rows["`plan_review`"])
        self.assertEqual(f"`{CONFIG['gate']['retries']}`", rows["`gate.retries`"])
        self.assertEqual(f"`{CONFIG['gate']['max_diff_lines']}`", rows["`gate.max_diff_lines`"])
        self.assertEqual("`[]`", rows["`gate.verify_allow`"])
        self.assertEqual(f"`{str(CONFIG['gate']['respect_codeowners']).lower()}`", rows["`gate.respect_codeowners`"])
        self.assertEqual(f"`{CONFIG['lessons']['curate_after']}`", rows["`lessons.curate_after`"])
        self.assertEqual(f"`{CONFIG['post_merge']}`", rows["`post_merge`"])
        limits = CONFIG["limits"]
        self.assertEqual(f"`${limits['max_cost_usd_per_job']:g}` a job, `${limits['max_cost_usd_per_run']:g}` a run, `{limits['stage_timeout_minutes']}` min",
                         rows["`limits`"])
        feeders = CONFIG["feeders"]
        self.assertTrue(feeders["ci"]["enabled"] and not feeders["deps"]["enabled"] and not feeders["todo"]["enabled"])
        self.assertIn(f"`max_open` {feeders['max_open']}", rows["`feeders`"] + " " + [r[2] for r in table_rows(section(README, "### Settings")) if r[0] == "`feeders`"][0])
        self.assertEqual(f"`{CONFIG['replay']['max_lines']}` lines", rows["`replay`"])


class Agents(unittest.TestCase):
    def test_the_file_tree_lists_exactly_the_agents_there_are(self):
        tree = section(README, "## What's in here")
        agents_block = tree.split("agents/")[1].split("factory/")[0]
        listed = set(re.findall(r"^\s+([a-z-]+)\.md\s+\w+ ", agents_block, re.M))
        real = {p.stem for p in (ROOT / ".claude/agents").glob("*.md")}
        self.assertEqual(real, listed)

    def test_the_file_tree_lists_the_scripts(self):
        tree = section(README, "## What's in here")
        for p in (ROOT / "factory/bin").iterdir():
            if p.is_file():                                  # not the __pycache__ the test loader leaves behind
                self.assertRegex(tree, rf"bin/{re.escape(p.name)}\s", p.name)


class Skill(unittest.TestCase):
    def test_every_job_subcommand_the_skill_calls_exists(self):
        dispatched = set(re.findall(r'cmd == "([a-z-]+)"', script("job")))
        called = set(re.findall(r"`factory/bin/job ([a-z-]+)", SKILL))      # commands in backticks, not prose
        self.assertGreater(len(called), 10, "the skill should call job in many places; has the pattern gone stale?")
        self.assertLessEqual(called, dispatched, f"the skill calls job {sorted(called - dispatched)}")

    def test_every_stage_the_skill_advances_to_is_a_stage(self):
        job = script("job")
        stages = set(re.findall(r'"([a-z-]+)":\s*\{', job.split("TRANSITIONS = {")[1].split("}\nTERMINAL")[0])) | {
            "merged", "rejected", "abandoned", "replayed", "spec", "build", "gate", "review", "approve", "merging", "needs-human", "needs-info"}
        for stage in re.findall(r"job advance <id> ([a-z-]+)", SKILL):
            self.assertIn(stage, stages, stage)

    def test_every_script_the_skill_runs_exists(self):
        for name in set(re.findall(r"factory/bin/([a-z]+)", SKILL)):
            self.assertTrue((ROOT / "factory/bin" / name).exists(), name)

    def test_every_agent_the_skill_spawns_exists(self):
        agents = {p.stem for p in (ROOT / ".claude/agents").glob("*.md")}
        for name in set(re.findall(r"Role: ([a-z-]+)\.", SKILL)) - {"intake", "agent"}:
            self.assertIn(name, agents, name)
        for name in set(re.findall(r"[Ss]pawn `([a-z-]+)`", SKILL)):
            self.assertIn(name, agents, name)


class Counts(unittest.TestCase):
    WORDS = {"eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "four": 4, "five": 5, "six": 6, "seven": 7}

    def test_design_counts_the_agents_and_scripts(self):
        design = (ROOT / "DESIGN.md").read_text()
        m = re.search(r"one skill,\s+(\w+)\s+agents,\s+(\w+)\s+scripts", design)
        self.assertTrue(m, "DESIGN.md should say 'one skill, N agents, N scripts'")
        self.assertEqual(len(list((ROOT / ".claude/agents").glob("*.md"))), self.WORDS[m.group(1)])
        self.assertEqual(len([p for p in (ROOT / "factory/bin").iterdir() if p.is_file()]), self.WORDS[m.group(2)])

    def test_design_names_every_stage_job_can_be_in(self):
        design = (ROOT / "DESIGN.md").read_text()
        job = script("job")
        stages = set(re.findall(r'"([a-z-]+)":\s*\{', job.split("TRANSITIONS = {")[1].split("}\nTERMINAL")[0])) | \
            set(re.findall(r'"([a-z-]+)"', re.search(r"TERMINAL = \{(.*?)\}", job).group(1)))
        for stage in stages:
            self.assertIn(f"`{stage}`", design, f"DESIGN.md never mentions the `{stage}` stage")


class Install(unittest.TestCase):
    def test_the_copy_list_is_exactly_what_ships(self):
        install = (ROOT / "INSTALL.md").read_text()
        listed = set(install.split("## 1. Copy")[1].split("```")[1].split())
        shipped = {str(p.relative_to(ROOT)) for p in list((ROOT / ".claude").rglob("*")) + list((ROOT / "factory").rglob("*"))
                   if p.is_file() and "__pycache__" not in p.parts
                   and not str(p.relative_to(ROOT)).startswith(("factory/tests", "factory/jobs"))}
        self.assertEqual(shipped, listed)

    def test_every_script_is_made_executable(self):
        install = (ROOT / "INSTALL.md").read_text()
        chmod = set(re.search(r"chmod \+x (.*)", install).group(1).split())
        scripts = {f"factory/bin/{p.name}" for p in (ROOT / "factory/bin").iterdir() if p.is_file()} | {"factory/checks.sh", "factory/setup.sh"}
        self.assertEqual(scripts, chmod)


class Links(unittest.TestCase):
    def test_in_page_anchors_exist(self):
        headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                    for h in re.findall(r"^#{1,3} (.*)$", README, re.M)}
        for anchor in re.findall(r"\]\(#([a-z0-9-]+)\)", README):
            self.assertIn(anchor, headings, anchor)

    def test_relative_links_point_at_files_that_exist(self):
        for target in re.findall(r"\]\((?!https?:|#|mailto:)([^)\s#]+)", README):
            self.assertTrue((ROOT / target).exists(), target)


if __name__ == "__main__":
    unittest.main()
