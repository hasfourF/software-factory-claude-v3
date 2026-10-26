import json
import tempfile
import threading
import unittest
from pathlib import Path

from support import commit, git, load_script, make_repo

job = load_script("job")


class Quiet:
    """Replace the GitHub side effects of a transition with no-ops."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = {k: getattr(job, k) for k in ("JOBS", "comment", "label", "notify", "post_needs_human")}
        job.JOBS = Path(self.tmp.name)
        job.comment = lambda *a, **k: None
        job.label = lambda *a, **k: None
        job.notify = lambda *a, **k: None
        job.post_needs_human = lambda j: None
        self.addCleanup(lambda: [setattr(job, k, v) for k, v in self.saved.items()])

    def make(self, **fields):
        base = {"id": "001-x", "issue": 1, "pr": 5, "branch": "factory/001-x", "worktree": self.tmp.name,
                "stage": "intake", "round": 0, "round_limit": 3, "intake": None, "agents": None, "gate": None,
                "reviews": {}, "cost_usd": 0.0, "spec_revisions": 0, "failures": []}
        base.update(fields)
        job.job_dir(base["id"]).mkdir(parents=True, exist_ok=True)
        return base

    def dir(self, j):
        return job.job_dir(j["id"])


class Transitions(unittest.TestCase):
    def test_every_target_is_a_known_stage(self):
        known = set(job.TRANSITIONS) | job.TERMINAL
        for old, targets in job.TRANSITIONS.items():
            self.assertLessEqual(targets, known, old)

    def test_terminal_stages_have_no_way_out(self):
        self.assertFalse(job.TERMINAL & set(job.TRANSITIONS))

    def test_nothing_skips_the_gate_or_the_reviews(self):
        self.assertNotIn("review", job.TRANSITIONS["build"])
        self.assertNotIn("approve", job.TRANSITIONS["gate"])
        self.assertNotIn("merging", job.TRANSITIONS["review"])
        self.assertNotIn("merged", job.TRANSITIONS["approve"])

    def test_the_spec_can_wait_for_a_human(self):
        self.assertIn("spec-review", job.TRANSITIONS["spec"])
        self.assertEqual({"spec", "build"}, job.TRANSITIONS["spec-review"])

    def test_every_stage_is_reachable(self):
        seen, todo = {"intake"}, ["intake"]
        while todo:
            for nxt in job.TRANSITIONS.get(todo.pop(), set()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        self.assertLessEqual(set(job.TRANSITIONS), seen)
        self.assertLessEqual({"merged", "rejected", "needs-human", "spec-review"}, seen)


class Parsing(unittest.TestCase):
    def test_depends_on(self):
        self.assertEqual([3, 4, 9], job.depends_on("Fix it.\nDepends on: #4, #3\n\ndepends-on: #9 and nothing"))
        self.assertEqual([], job.depends_on("this depends on #3"))
        self.assertEqual([], job.depends_on(None))

    def test_priority(self):
        self.assertEqual(0, job.priority_of(["factory", "factory:p0", "factory:p2"]))
        self.assertEqual(9, job.priority_of(["factory", "bug"]))

    def test_fingerprint_ignores_numbers_and_spacing(self):
        a = job.fingerprint("FAIL test_x  (0.12s) line 40")
        b = job.fingerprint("fail test_x (3.90s)\nline 41")
        self.assertEqual(a, b)
        self.assertNotEqual(a, job.fingerprint("FAIL test_y (0.12s) line 40"))

    def test_header_and_section(self):
        p = Path(tempfile.mkdtemp()) / "f.md"
        p.write_text("GATE: PASS\nFLAGS: a, b\n\n## Findings\nNone.\n\n## Notes\nx\n")
        self.assertEqual({"GATE": "PASS", "FLAGS": "a, b"}, job.header(p))
        self.assertEqual("None.", job.section(p, "Findings"))
        self.assertIsNone(job.section(p, "Nope"))

    def test_planned_files(self):
        p = Path(tempfile.mkdtemp()) / "spec.md"
        p.write_text("# T\n\n## Files to touch\n- `calc.py` add it\n- `tests/*.py`\n\n## Out of scope\n`other.py`\n")
        self.assertEqual({"calc.py", "tests/*.py"}, job.planned_files(p))


class Numbering(Quiet, unittest.TestCase):
    def test_numbers_continue_after_existing_jobs(self):
        job.job_dir("004-old").mkdir()
        self.assertEqual("005-new", job.claim_job_dir("new"))

    def test_concurrent_creators_never_share_a_number(self):
        ids, lock = [], threading.Lock()

        def create(i):
            got = job.claim_job_dir(f"job{i}")
            with lock:
                ids.append(got.split("-")[0])

        threads = [threading.Thread(target=create, args=(i,)) for i in range(25)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(25, len(set(ids)))


class Refusals(Quiet, unittest.TestCase):
    def test_illegal_move(self):
        with self.assertRaises(job.Refused):
            job.advance(self.make(stage="intake"), "build")

    def test_spec_needs_spec_md(self):
        j = self.make(stage="spec", round=0)
        with self.assertRaisesRegex(job.Refused, "spec.md"):
            job.advance(j, "build")

    def test_review_cannot_approve_with_changes(self):
        j = self.make(stage="review", round=1, agents={"reviewers": {"code": "haiku"}}, reviews={"code": "CHANGES"})
        rd = self.dir(j) / "round-1"
        rd.mkdir()
        (rd / "review-code.md").write_text("VERDICT: CHANGES\n\n## Findings\n1. x\n")
        with self.assertRaisesRegex(job.Refused, "CHANGES"):
            job.advance(j, "approve")

    def test_review_needs_every_review_file(self):
        j = self.make(stage="review", round=1, agents={"reviewers": {"code": "haiku", "ux": "sonnet"}},
                      reviews={"code": "PASS", "ux": "pending"})
        rd = self.dir(j) / "round-1"
        rd.mkdir()
        (rd / "review-code.md").write_text("VERDICT: PASS\n")
        with self.assertRaisesRegex(job.Refused, "missing reviews from: ux"):
            job.advance(j, "approve")

    def test_a_repeated_finding_goes_to_a_human_not_another_build(self):
        j = self.make(stage="review", round=1, agents={"reviewers": {"code": "haiku"}}, reviews={"code": "CHANGES"})
        d = self.dir(j)
        for n, line in ((1, "1. calc.py:3 divide by zero is not handled (took 0.2s)"),
                        (2, "1. calc.py:9 divide by zero is not handled (took 1.9s)")):
            (d / f"round-{n}").mkdir(exist_ok=True)
            (d / f"round-{n}" / "review-code.md").write_text(f"VERDICT: CHANGES\n\n## Findings\n{line}\n")
        job.advance(j, "build")                       # round 1: a first failure is allowed to retry
        self.assertEqual(2, j["round"])
        j["stage"], j["reviews"] = "review", {"code": "CHANGES"}
        with self.assertRaisesRegex(job.Refused, "same findings"):
            job.advance(j, "build")                   # round 2 said the same thing
        job.advance(j, "needs-human")
        self.assertEqual("needs-human", j["stage"])
        self.assertIn("repeated", (d / "decision.md").read_text())

    def test_the_last_round_goes_to_a_human(self):
        j = self.make(stage="review", round=3, round_limit=3, agents={"reviewers": {"code": "haiku"}},
                      reviews={"code": "CHANGES"})
        rd = self.dir(j) / "round-3"
        rd.mkdir()
        (rd / "review-code.md").write_text("VERDICT: CHANGES\n\n## Findings\n1. x\n")
        with self.assertRaisesRegex(job.Refused, "needs-human"):
            job.advance(j, "build")
        self.assertEqual("needs-human", job.advance(j, "needs-human")["stage"])

    def test_gate_failure_repeating_goes_to_a_human(self):
        tmp, repo = make_repo({"a.txt": "a"})
        self.addCleanup(tmp.cleanup)
        head = git(repo, "rev-parse", "HEAD").strip()
        j = self.make(stage="gate", round=1, worktree=str(repo))
        d = self.dir(j)
        for n, took in ((1, "0.1"), (2, "7.4")):
            (d / f"round-{n}").mkdir(exist_ok=True)
            (d / f"round-{n}" / "checks.log").write_text(f"FAIL: test_add\nRan 1 test in {took}s\n")
            (d / f"round-{n}" / "checks.md").write_text(f"GATE: FAIL\nCOMMIT: {head}\nFLAGS: none\n\n## Protected paths\nNone changed.\n")
        job.advance(j, "build")
        self.assertEqual(2, j["round"])
        j["stage"] = "gate"
        with self.assertRaisesRegex(job.Refused, "same failure"):
            job.advance(j, "build")
        self.assertEqual("needs-human", job.advance(j, "needs-human")["stage"])

    def test_gate_adds_the_security_review_the_diff_calls_for(self):
        tmp, repo = make_repo({"a.txt": "a"})
        self.addCleanup(tmp.cleanup)
        head = git(repo, "rev-parse", "HEAD").strip()
        j = self.make(stage="gate", round=1, worktree=str(repo), agents={"builder": "sonnet", "reviewers": {"code": "haiku"}})
        (self.dir(j) / "round-1").mkdir()
        (self.dir(j) / "round-1" / "checks.md").write_text(f"GATE: PASS\nCOMMIT: {head}\nFLAGS: security-path\n\n")
        job.advance(j, "review")
        self.assertEqual({"code": "haiku", "security": "opus"}, j["agents"]["reviewers"])
        self.assertEqual({"code": "pending", "security": "pending"}, j["reviews"])

    def test_flagged_changes_cannot_be_approved_by_an_agent(self):
        j = self.make(stage="approve", round=1)
        rd = self.dir(j) / "round-1"
        rd.mkdir()
        (rd / "checks.md").write_text("GATE: PASS\nCOMMIT: abc\nFLAGS: new-dependency\n\n")
        (self.dir(j) / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        with self.assertRaisesRegex(job.Refused, "new-dependency"):
            job.advance(j, "merging")
        self.assertEqual("ESCALATE", (self.dir(j) / "decision.md").read_text().splitlines()[0])
        self.assertEqual("needs-human", job.advance(j, "needs-human")["stage"])

    def test_unflagged_approval_goes_through(self):
        j = self.make(stage="approve", round=1, intake={"risk": "low"})
        rd = self.dir(j) / "round-1"
        rd.mkdir()
        (rd / "checks.md").write_text("GATE: PASS\nCOMMIT: abc\nFLAGS: security-path, off-plan\n\n")
        (self.dir(j) / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        self.assertEqual("merging", job.advance(j, "merging")["stage"])

    def approved(self, risk, flags="none"):
        j = self.make(stage="approve", round=1, intake={"risk": risk})
        rd = self.dir(j) / "round-1"
        rd.mkdir(exist_ok=True)
        (rd / "checks.md").write_text(f"GATE: PASS\nCOMMIT: abc\nFLAGS: {flags}\n\n")
        (self.dir(j) / "decision.md").write_text("APPROVE\n\n## Why\nfine\n")
        return j

    def with_auto_merge(self, **value):
        saved = job.CONFIG.get("auto_merge")
        job.CONFIG["auto_merge"] = value
        self.addCleanup(lambda: job.CONFIG.__setitem__("auto_merge", saved))

    def test_a_risk_outside_auto_merge_goes_to_a_human(self):
        self.with_auto_merge(risks=["low"], areas=None)
        with self.assertRaisesRegex(job.Refused, "risk-high"):
            job.advance(self.approved("high"), "merging")
        self.assertEqual("merging", job.advance(self.approved("low"), "merging")["stage"])

    def test_an_unearned_area_cannot_be_auto_merged(self):
        with self.assertRaisesRegex(job.Refused, "unearned-area"):
            job.advance(self.approved("low", "unearned-area"), "merging")

    def test_conflict_needs_a_conflict_note(self):
        j = self.make(stage="merging", round=1)
        with self.assertRaisesRegex(job.Refused, "conflict"):
            job.advance(j, "build")
        (self.dir(j) / "conflict-1.md").write_text("# Conflict 1\n")
        self.assertEqual(2, job.advance(j, "build")["round"])


class PlanReview(Quiet, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.issue = {"number": 1, "labels": [], "comments": [], "author": {"login": "author"}}
        self.saved_fetch, self.saved_op = job.fetch_issue, job.operator
        job.fetch_issue = lambda n: self.issue
        job.operator = lambda: "boss"
        self.addCleanup(lambda: (setattr(job, "fetch_issue", self.saved_fetch), setattr(job, "operator", self.saved_op)))

    def spec_job(self, risk="low", **fields):
        j = self.make(stage="spec", round=0, intake={"risk": risk}, **fields)
        (self.dir(j) / "spec.md").write_text("# Spec\n")
        return j

    def comment(self, who, body, factory=False):
        self.issue["comments"].append({"author": {"login": who}, "body": (job.MARKER + "\n" if factory else "") + body,
                                       "createdAt": "2026-01-01T00:00:00Z"})

    def test_modes(self):
        job.CONFIG["plan_review"] = "high"
        self.addCleanup(lambda: job.CONFIG.__setitem__("plan_review", "high"))
        self.assertFalse(job.plan_wanted(self.spec_job("low")))
        self.assertTrue(job.plan_wanted(self.spec_job("high")))
        job.CONFIG["plan_review"] = "never"
        self.assertFalse(job.plan_wanted(self.spec_job("high")))
        job.CONFIG["plan_review"] = "always"
        self.assertTrue(job.plan_wanted(self.spec_job("low")))

    def test_the_label_asks_for_a_review_whatever_the_mode(self):
        job.CONFIG["plan_review"] = "never"
        self.addCleanup(lambda: job.CONFIG.__setitem__("plan_review", "high"))
        self.issue["labels"] = [{"name": job.LABELS["plan"]}]
        self.assertTrue(job.plan_wanted(self.spec_job("low")))

    def test_a_spec_that_waits_cannot_skip_to_the_build(self):
        job.CONFIG["plan_review"] = "always"
        self.addCleanup(lambda: job.CONFIG.__setitem__("plan_review", "high"))
        with self.assertRaisesRegex(job.Refused, "waits for a human"):
            job.advance(self.spec_job(), "build")

    def test_plan_states(self):
        j = self.make(stage="spec-review")
        self.assertEqual("waiting", job.plan_state(j))
        self.comment("boss", "x", factory=True)
        self.assertEqual("waiting", job.plan_state(j))
        self.comment("author", "please also handle empty input")
        self.assertEqual("feedback", job.plan_state(j))
        self.comment("stranger", "/approve")
        self.assertEqual("feedback", job.plan_state(j))      # only the operator can approve by comment
        self.comment("author", "/approve")
        self.assertEqual("feedback", job.plan_state(j))      # not even the issue's author
        self.comment("boss", "/approve")
        self.assertEqual("approved", job.plan_state(j))
        self.comment("author", "wait, one more thing")
        self.assertEqual("feedback", job.plan_state(j))      # latest word wins

    def test_the_approval_label_approves(self):
        self.issue["labels"] = [{"name": job.LABELS["plan_approved"]}]
        self.assertEqual("approved", job.plan_state(self.make(stage="spec-review")))

    def test_revision_files_the_old_draft_and_is_capped(self):
        j = self.spec_job()
        j["stage"] = "spec-review"
        job.write_issue_md = lambda jb: None
        self.comment("boss", "x", factory=True)
        self.comment("author", "also cover negatives")
        job.advance(j, "spec")
        self.assertTrue((self.dir(j) / "spec-1.md").exists())
        self.assertFalse((self.dir(j) / "spec.md").exists())
        self.assertEqual(1, j["spec_revisions"])
        j["stage"] = "spec-review"
        j["spec_revisions"] = job.cfg("max_spec_revisions", default=2)
        with self.assertRaisesRegex(job.Refused, "most times"):
            job.advance(j, "spec")

    def test_building_needs_approval(self):
        j = self.make(stage="spec-review")
        with self.assertRaisesRegex(job.Refused, "isn't approved"):
            job.advance(j, "build")
        self.comment("boss", "/approve")
        self.assertEqual(1, job.advance(j, "build")["round"])


class Lessons(Quiet, unittest.TestCase):
    def test_keeps_only_the_latest_entries(self):
        saved = job.FACTORY
        job.FACTORY = Path(self.tmp.name)
        self.addCleanup(lambda: setattr(job, "FACTORY", saved))
        j = self.make()
        for k in range(1, job.LESSONS_KEPT + 6):
            job.append_lessons(j, f"001-x, rework {k}", [("2026-01-01T00:00:00Z", "boss", "calc.py:3", f"lesson   number {k}")])
        text = (Path(self.tmp.name) / "lessons.md").read_text()
        self.assertEqual(job.LESSONS_KEPT, text.count("\n## "))
        self.assertIn("lesson number 35", text)
        self.assertNotIn("lesson number 5\n", text)
        self.assertIn("calc.py:3: lesson number", text)


class Overlap(Quiet, unittest.TestCase):
    def test_active_jobs_planning_the_same_file(self):
        a = self.make(id="001-a", stage="build")
        b = self.make(id="002-b", stage="spec")
        c = self.make(id="003-c", stage="needs-human")
        for j, files in ((a, "`calc.py`"), (b, "`calc.py`"), (c, "`calc.py`")):
            (self.dir(j) / "spec.md").write_text(f"# s\n\n## Files to touch\n- {files}\n")
            (self.dir(j) / "job.json").write_text(json.dumps(j))
        import io, contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            job.cmd_overlap(b)
        self.assertEqual(["001-a: calc.py"], out.getvalue().splitlines())


if __name__ == "__main__":
    unittest.main()
