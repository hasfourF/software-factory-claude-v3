import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_script

metrics = load_script("metrics")


class Jobs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.n = 0

    def add(self, stage="merged", decision="APPROVE", risk="low", files=("src/a.py",), reworked=False, cost=0.5,
            replay=None, why="", surfaces=()):
        self.n += 1
        d = self.root / f"{self.n:03d}-job"
        (d / "round-1").mkdir(parents=True)
        job = {"id": d.name, "issue": self.n, "pr": self.n, "stage": stage, "round": 1, "cost_usd": cost,
               "intake": {"risk": risk, "surfaces": list(surfaces)}, "started": "2026-01-01T00:00:00Z",
               "ended": "2026-01-01T00:10:00Z" if stage in {"merged", "rejected"} else None}
        if replay:
            job["replay"] = replay
        (d / "job.json").write_text(json.dumps(job))
        if decision:
            (d / "decision.md").write_text(f"{decision}\n\n## Why\n{why}\n")
        (d / "round-1" / "changed-files.txt").write_text("".join(f"{f}\n" for f in files))
        if reworked:
            (d / "rework-1.md").write_text("x")
        return d

    def report(self, minimum=5):
        rows = [metrics.summarize(p.parent) for p in sorted(self.root.glob("*/job.json"))]
        return metrics.build(rows, minimum)


class Outcomes(Jobs):
    def test_classification(self):
        self.add()                                              # approver merged it
        self.add(reworked=True)                                 # merged, but a human sent it back first
        self.add(decision="ESCALATE", why="Touches auth.")      # a human merged an escalation
        self.add(stage="needs-human", decision="ESCALATE", why="Touches auth.")
        self.add(stage="rejected", decision=None)
        got = self.report()["outcomes"]
        self.assertEqual({"auto-merged": 1, "merged by a human": 2, "waiting on a human": 1, "rejected": 1}, got)

    def test_auto_merge_rate_counts_only_jobs_the_factory_decided(self):
        self.add()
        self.add(stage="needs-human", decision="ESCALATE", why="x")
        self.add(stage="rejected", decision=None)
        self.add(stage="build", decision=None)
        self.assertEqual(0.5, self.report()["auto_merge_rate"])

    def test_cost_and_time_are_per_merged_pr(self):
        self.add(cost=1.0)
        self.add(cost=3.0)
        self.add(stage="rejected", decision=None, cost=0.25)
        r = self.report()
        self.assertEqual((2.0, 10, 4.25), (r["cost_per_merged"], r["median_minutes_to_merge"], r["cost_total"]))

    def test_reasons(self):
        for text, want in (("The job has cost $9, over the cap", "cost cap"),
                           ("The reviewers repeated their findings", "repeated failure"),
                           ("This change is flagged: new-dependency.", "gate flag"),
                           ("The builder is blocked:", "builder blocked"),
                           ("Review rounds exhausted.", "rounds used up"),
                           ("Touches money.", "approver's call")):
            self.assertEqual(want, metrics.reason(text), text)


class Trust(Jobs):
    def many(self, n, **kw):
        for _ in range(n):
            self.add(**kw)

    def test_an_area_with_enough_clean_auto_merges_is_earned(self):
        self.many(5)
        r = self.report()
        self.assertEqual("earned", r["by_area"]["src"]["verdict"])
        self.assertEqual(["src"], r["earned_areas"])

    def test_not_enough_data_is_not_earned(self):
        self.many(4)
        self.assertEqual("needs 1 more", self.report()["by_area"]["src"]["verdict"])
        self.assertEqual([], self.report()["earned_areas"])

    def test_a_human_heavy_area_is_not_earned(self):
        self.many(4)
        self.add(reworked=True)
        self.assertEqual("earned", self.report()["by_area"]["src"]["verdict"])       # 4/5 is exactly 80%
        self.many(2, reworked=True)
        self.assertEqual("not yet", self.report()["by_area"]["src"]["verdict"])      # 4/7
        self.many(5, reworked=True)
        self.assertEqual("keep a human on it", self.report()["by_area"]["src"]["verdict"])   # 4/12

    def test_a_revert_ends_trust_whatever_the_rate(self):
        self.many(10)
        rows = [metrics.summarize(p.parent) for p in sorted(self.root.glob("*/job.json"))]
        rows[0]["reverted"] = True
        r = metrics.build(rows, 5)
        self.assertEqual("keep a human on it", r["by_area"]["src"]["verdict"])
        self.assertEqual([], r["earned_areas"])

    def test_areas_are_counted_separately_and_a_job_counts_under_each(self):
        self.many(5, files=("src/a.py", "docs/x.md"))
        self.many(5, files=("billing/pay.py",), reworked=True)
        r = self.report()
        self.assertEqual({"src", "docs", "billing"}, set(r["by_area"]))
        self.assertEqual(5, r["by_area"]["docs"]["jobs"])
        self.assertEqual(["docs", "src"], sorted(r["earned_areas"]))   # billing needed rework every time

    def test_root_files_and_unknown_areas(self):
        self.add(files=("README.md",))
        self.add(files=())
        r = self.report(minimum=1)
        self.assertEqual({".", "?"}, set(r["by_area"]))
        self.assertNotIn("?", r["earned_areas"])      # an unknown area can't be earned, however clean

    def test_the_suggested_config_is_printed(self):
        self.many(5)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.show(self.report(), 5)
        self.assertIn('"auto_merge": { "risks": ["low", "medium", "high"], "areas": ["src"] }', out.getvalue())


class Recipes(Jobs):
    def test_jobs_are_grouped_by_the_recipe_intake_chose(self):
        for recipe, reworked in (("add-endpoint", False), ("add-endpoint", False), (None, True)):
            d = self.add(reworked=reworked)
            job = json.loads((d / "job.json").read_text())
            job["intake"]["recipe"] = recipe
            (d / "job.json").write_text(json.dumps(job))
        by = self.report()["by_recipe"]
        self.assertEqual({"add-endpoint", "none"}, set(by))
        self.assertEqual((2, 1.0, 1, 0.0), (by["add-endpoint"]["jobs"], by["add-endpoint"]["auto_rate"], by["none"]["jobs"], by["none"]["auto_rate"]))

    def test_the_recipe_table_only_shows_when_a_recipe_was_used(self):
        self.add()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.show(self.report(), 5)
        self.assertNotIn("By recipe", out.getvalue())


class Replays(Jobs):
    def test_replays_are_reported_apart_and_never_count_as_jobs(self):
        self.add()
        for label, recall in (("equivalent", 1.0), ("diverges", 0.5), ("equivalent", 0.8)):
            self.add(stage="replayed", decision="APPROVE", replay={"pr": 1, "result": {
                "label": label, "recall": recall, "cost_usd": 0.4}})
        r = self.report()
        self.assertEqual(1, r["jobs"])
        self.assertEqual({"equivalent": 2, "diverges": 1}, r["replay"]["labels"])
        self.assertEqual(0.67, round(r["replay"]["equivalent_rate"], 2))
        self.assertEqual(0.77, r["replay"]["avg_recall"])
        self.assertEqual(1.2, r["replay"]["cost"])

    def test_only_replays_still_print_the_replay_line_and_no_empty_outcomes(self):
        self.add(stage="replayed", replay={"pr": 1, "result": {"label": "equivalent", "recall": 1.0, "cost_usd": 0.4}})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.show(self.report(), 5)
        self.assertIn("Replays: 1 run, 1 equivalent", out.getvalue())
        self.assertNotIn("Outcomes:", out.getvalue())

    def test_nothing_to_show(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            metrics.show(self.report(), 5)
        self.assertIn("No jobs yet", out.getvalue())


if __name__ == "__main__":
    unittest.main()
