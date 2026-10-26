"""jobs/ holds more than finished jobs, and every reader of it has to cope.

`job create` leaves `.claim-NNN` folders (they reserve job numbers) and makes a job's
folder a few seconds before its job.json exists. The dashboard reads that folder as an
HTML index, and one folder it cannot load used to stop the whole board.

The dashboard's JavaScript is NOT executed here (the test machine may have no JS engine),
so those tests read its source. They pin the two behaviours that broke; opening the
dashboard against a jobs/ folder with a `.claim-001/` and an empty job folder is the real check.
"""

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_script

job = load_script("job")
metrics = load_script("metrics")
DASHBOARD = (Path(__file__).resolve().parents[1] / "dashboard.html").read_text()


def load_jobs_source():
    m = re.search(r"async function loadJobs\(\) \{.*?\n\}\n", DASHBOARD, re.S)
    assert m, "dashboard.html has no loadJobs()"
    return m.group(0)


class WhatIsInTheJobsFolder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(job, "JOBS", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_creating_a_job_leaves_a_hidden_claim_folder_with_no_job_json(self):
        job_id = job.claim_job_dir("add-x")
        names = {p.name for p in job.JOBS.iterdir()}
        self.assertEqual({".claim-001", job_id}, names)
        self.assertFalse((job.JOBS / ".claim-001" / "job.json").exists())

    def test_a_job_folder_has_no_job_json_until_it_is_saved(self):
        job_id = job.claim_job_dir("add-x")
        self.assertFalse((job.job_dir(job_id) / "job.json").exists())

    def test_the_python_readers_ignore_both(self):
        job.claim_job_dir("pending")                      # a folder with no job.json yet, plus .claim-001
        done = job.claim_job_dir("done")
        job.save({"id": done, "issue": 1, "stage": "merged", "round": 0, "agents": None, "reviews": {}, "cost_usd": 0.0})
        self.assertEqual([done], [j["id"] for j in job.all_jobs()])
        with mock.patch.object(metrics, "JOBS", job.JOBS):
            self.assertEqual([done], [p.parent.name for p in sorted(metrics.JOBS.glob("*/job.json"))])


class DashboardSource(unittest.TestCase):
    def test_hidden_folders_are_not_jobs(self):
        source = load_jobs_source()
        self.assertRegex(source, r"!h\.startsWith\('\.'\)")

    def test_a_job_whose_file_is_missing_or_bad_does_not_stop_the_board(self):
        source = load_jobs_source()
        self.assertNotRegex(source, r"JSON\.parse\(await fetchText", "an unguarded fetch rejects Promise.all and blanks the board")
        self.assertEqual(2, len(re.findall(r"catch \{ return null \}|catch \{ problems\.push\([^)]*\); return null \}", source)))
        self.assertIn("filter(Boolean)", source)

    def test_a_malformed_job_json_is_reported_not_swallowed(self):
        self.assertIn("is not valid JSON", load_jobs_source())
        self.assertRegex(DASHBOARD, r"const problems = \[\.\.\.loadProblems\]")

    def test_the_state_is_declared_before_anything_can_use_it(self):
        self.assertLess(DASHBOARD.index("let loadProblems"), DASHBOARD.index("async function render()"))


if __name__ == "__main__":
    unittest.main()
