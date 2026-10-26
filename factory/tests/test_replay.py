import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import commit, git, load_script, make_repo

job = load_script("job")

BASE = {"calc.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": "",
        "tests/test_calc.py": "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n"
                              "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"}
SHIPPED = {"calc.py": "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n",
           "tests/test_subtract.py": "import unittest\nfrom calc import subtract\n\n\nclass T(unittest.TestCase):\n"
                                     "    def test_subtract(self):\n        self.assertEqual(subtract(5, 3), 2)\n"}
CHECKS = "#!/usr/bin/env bash\nset -e\npython3 -m unittest discover -s tests -t . >/dev/null 2>&1\n"


class Replay(unittest.TestCase):
    def setUp(self):
        tmp, self.repo = make_repo(BASE)
        self.addCleanup(tmp.cleanup)
        self.base = git(self.repo, "rev-parse", "HEAD").strip()
        self.merge = commit(self.repo, SHIPPED, "Add subtract (#5)")
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        root = Path(self.work.name)
        (root / "factory").mkdir()
        (root / "factory" / "checks.sh").write_text(CHECKS)
        self.pr = {"number": 5, "title": "Add subtract", "state": "MERGED", "mergeCommit": {"oid": self.merge},
                   "closingIssuesReferences": [{"number": 3}], "additions": job.numstat_lines(git(self.repo, "diff", "--numstat", self.base, self.merge)), "deletions": 0,
                   "headRefName": "alice/subtract", "files": [{"path": "calc.py"}, {"path": "tests/test_subtract.py"}]}
        self.issue = {"number": 3, "title": "Add a subtract function", "body": "Please add subtract(a, b).",
                      "author": {"login": "alice"}, "url": "https://example.test/3"}
        self.gh_calls = []
        for p in (mock.patch.object(job, "REPO", self.repo), mock.patch.object(job, "JOBS", root / "jobs"),
                  mock.patch.object(job, "FACTORY", root / "factory"), mock.patch.object(job, "gh_json", self.fake_gh_json)):
            p.start()
            self.addCleanup(p.stop)
        job.JOBS.mkdir()

    def fake_gh_json(self, *args):
        self.gh_calls.append(args)
        return self.issue if args[0] == "issue" else self.pr if args[1] == "view" else [self.pr]

    def create(self):
        with contextlib.redirect_stdout(io.StringIO()):
            job.cmd_replay_create("5")
        j = job.load("replay-5")
        j["worktree"] = str(Path(self.work.name) / "wt")
        job.save(j)
        return j

    def build(self, j, files, round_gate="PASS"):
        """Stand in for the agents: make the snapshot, commit <files> to it, and record a gate result."""
        job.make_snapshot(j)
        commit(Path(j["worktree"]), files, "build")
        rd = job.job_dir(j["id"]) / "round-1"
        rd.mkdir()
        (rd / "checks.md").write_text(f"GATE: {round_gate}\nCOMMIT: x\nFLAGS: none\n\n")
        j["round"], j["stage"] = 1, "approve"
        (job.job_dir(j["id"]) / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        job.save(j)
        return j

    def finish(self, j):
        with contextlib.redirect_stdout(io.StringIO()):
            job.cmd_replay_finish(job.load(j["id"]))
        return job.load(j["id"])["replay"]["result"]

    def test_create_keeps_the_answer_out_of_the_job(self):
        j = self.create()
        d = job.job_dir("replay-5")
        self.assertEqual(self.base, j["replay"]["base"])
        self.assertIn("Please add subtract", (d / "issue.md").read_text())
        self.assertEqual(["issue.md", "job.json"], sorted(p.name for p in d.iterdir()))
        key = job.answer_key_dir(5)
        self.assertIn("subtract", (key / "shipped.diff").read_text())
        self.assertEqual(["calc.py", "tests/test_subtract.py"], (key / "shipped-files.txt").read_text().split())
        self.assertNotIn(".git", str(d))

    def test_the_snapshot_has_no_future_history(self):
        j = self.create()
        job.make_snapshot(j)
        wt = Path(j["worktree"])
        self.assertNotIn("subtract", (wt / "calc.py").read_text())
        self.assertFalse((wt / "tests/test_subtract.py").exists())
        self.assertEqual(1, int(git(wt, "rev-list", "--count", "--all").strip()))
        self.assertNotIn(self.merge, git(wt, "log", "--all", "--format=%H"))
        self.assertEqual(f"factory/replay-5", git(wt, "branch", "--show-current").strip())
        self.assertEqual(git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "origin/main"))

    def test_a_correct_build_is_equivalent(self):
        j = self.build(self.create(), SHIPPED)
        result = self.finish(j)
        self.assertEqual(("equivalent", "pass", 1.0), (result["label"], result["oracle"], result["recall"]))
        self.assertIn("RESULT: equivalent", (job.job_dir(j["id"]) / "replay.md").read_text())
        self.assertEqual("replayed", job.load(j["id"])["stage"])

    def test_a_build_that_passes_its_own_tests_but_behaves_differently_diverges(self):
        wrong = {"calc.py": "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a + b\n",
                 "tests/test_mine.py": "import unittest\nfrom calc import subtract\n\n\nclass T(unittest.TestCase):\n"
                                       "    def test_it(self):\n        self.assertEqual(subtract(1, 1), 2)\n"}
        j = self.build(self.create(), wrong)
        own = subprocess.run(["bash", str(job.FACTORY / "checks.sh")], cwd=j["worktree"])
        self.assertEqual(0, own.returncode)          # its own tests are green, so the failure below is the shipped test's
        result = self.finish(j)
        self.assertEqual(("diverges", "fail"), (result["label"], result["oracle"]))

    def test_nothing_built_is_a_failure(self):
        j = self.create()
        job.make_snapshot(j)
        j["round"] = 1
        job.save(j)
        self.assertEqual("failed", self.finish(j)["label"])

    def test_without_shipped_tests_the_best_it_can_be_is_plausible(self):
        self.pr["files"] = [{"path": "calc.py"}]
        key_files = {"calc.py": SHIPPED["calc.py"]}
        # a PR that shipped no tests: rebuild the history so the shipped commit has none
        git(self.repo, "reset", "-q", "--hard", self.base)
        self.merge = commit(self.repo, key_files, "Add subtract (#5)")
        self.pr["mergeCommit"] = {"oid": self.merge}
        self.pr["additions"] = 4
        result = self.finish(self.build(self.create(), key_files))
        self.assertEqual(("plausible", None), (result["label"], result["oracle"]))

    def test_a_replay_never_touches_github_when_it_advances(self):
        j = self.create()
        (job.job_dir(j["id"]) / "intake.md").write_text("DECISION: ACCEPT\nRISK: low\nSURFACES: none\nRESCOPED: no\n\n## Scope\nx\n")
        j["agents"] = {"builder": "sonnet", "reviewers": {"code": "haiku"}}
        job.save(job.sync(j))
        j = job.load(j["id"])
        before = list(self.gh_calls)
        # a real call would raise Refused("a replay job never talks to GitHub")
        with mock.patch.object(job, "run", wraps=job.run) as run:
            job.advance(j, "spec")
        self.assertEqual("spec", j["stage"])
        self.assertEqual(before, self.gh_calls)
        self.assertFalse(any(c.args[0][:1] == ["gh"] for c in run.call_args_list))
        wt = Path(j["worktree"])
        self.assertTrue((wt / "calc.py").exists())
        self.assertNotIn("subtract", (wt / "calc.py").read_text())      # the code before the PR, not after
        self.assertEqual(1, int(git(wt, "rev-list", "--count", "--all").strip()))
        self.assertNotIn(self.merge, git(wt, "log", "--all", "--format=%H"))
        self.assertFalse(job._offline)

    def test_the_offline_guard_stops_any_stray_github_call(self):
        job._offline = True
        self.addCleanup(lambda: setattr(job, "_offline", False))
        with self.assertRaisesRegex(job.Refused, "never talks to GitHub"):
            job.gh("issue", "list")
        job.comment("issue", 1, "x")   # comments and labels are silently skipped
        job.label("issue", 1, add="x")

    def test_a_replay_cannot_merge(self):
        j = self.create()
        j["stage"], j["round"] = "approve", 1
        rd = job.job_dir(j["id"]) / "round-1"
        rd.mkdir()
        (rd / "checks.md").write_text("GATE: PASS\nCOMMIT: x\nFLAGS: none\n\n")
        (job.job_dir(j["id"]) / "decision.md").write_text("APPROVE\n")
        with self.assertRaisesRegex(job.Refused, "never merges"):
            job.advance(j, "merging")

    def test_replays_are_invisible_to_issue_numbers(self):
        self.create()
        with self.assertRaises(SystemExit):
            job.resolve("3")   # issue 3 has a replay, but no real job
        self.assertIn("replay-5", [x["id"] for x in job.all_jobs()])

    def test_a_rebase_merge_is_refused(self):
        self.pr["additions"] = 99
        with self.assertRaisesRegex(job.Refused, "rebase merge"):
            job.cmd_replay_create("5")

    def test_an_unmerged_pr_or_one_without_an_issue_is_refused(self):
        self.pr["state"] = "OPEN"
        with self.assertRaisesRegex(job.Refused, "isn't merged"):
            job.cmd_replay_create("5")
        self.pr["state"], self.pr["closingIssuesReferences"] = "MERGED", []
        with self.assertRaisesRegex(job.Refused, "no request to replay"):
            job.cmd_replay_create("5")

    def test_list_keeps_small_human_prs_that_closed_an_issue_and_puts_tested_ones_first(self):
        small_untested = {**self.pr, "number": 6, "files": [{"path": "calc.py"}]}
        factory_made = {**self.pr, "number": 7, "headRefName": "factory/001-x"}
        no_issue = {**self.pr, "number": 8, "closingIssuesReferences": []}
        too_big = {**self.pr, "number": 9, "additions": 5000}
        self.fake_list = [small_untested, factory_made, no_issue, too_big, self.pr]
        with mock.patch.object(job, "gh_json", lambda *a: self.fake_list), contextlib.redirect_stdout(io.StringIO()) as out:
            job.cmd_replay_list()
        rows = out.getvalue().splitlines()[1:]
        self.assertEqual(["#5", "#6"], [r.split("\t")[0] for r in rows])
        self.assertEqual(["yes", "no"], [r.split("\t")[3] for r in rows])

    def test_clean_removes_the_snapshot_and_the_key(self):
        j = self.create()
        job.make_snapshot(j)
        with contextlib.redirect_stdout(io.StringIO()):
            job.cmd_replay_clean(job.load(j["id"]))
        self.assertFalse(Path(j["worktree"]).exists())
        self.assertFalse(job.answer_key_dir(5).exists())


if __name__ == "__main__":
    unittest.main()
