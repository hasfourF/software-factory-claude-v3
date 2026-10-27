import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from support import commit, git, load_script, make_repo

gate = load_script("gate")


class Diff(unittest.TestCase):
    def setUp(self):
        self.tmp, self.repo = make_repo({"calc.py": "def add(a, b):\n    return a + b\n", "tests/test_calc.py": "x\n",
                                         "package.json": "{}\n"})
        self.addCleanup(self.tmp.cleanup)

    def test_protected_paths_only_count_edits_and_deletes(self):
        saved = gate.CONFIG["protected_paths"]
        gate.CONFIG["protected_paths"] = ["tests/*", ".github/workflows/*"]
        self.addCleanup(lambda: gate.CONFIG.__setitem__("protected_paths", saved))
        commit(self.repo, {"tests/test_new.py": "new\n", ".github/workflows/ci.yml": "on: push\n"})
        self.assertEqual([], gate.protected_changes(self.repo))
        commit(self.repo, {"tests/test_calc.py": "changed\n"})
        self.assertEqual(["M tests/test_calc.py"], gate.protected_changes(self.repo))

    def test_secrets_are_found_by_line_and_never_echoed(self):
        commit(self.repo, {"conf.py": "x = 1\nAPI_KEY = 'abcd1234efgh5678ijkl'\ny = 2\n",
                           "k.pem": "-----BEGIN RSA PRIVATE KEY-----\n"})
        hits = gate.find_secrets(self.repo)
        self.assertEqual(["conf.py:2 hard-coded credential", "k.pem:1 private key"], sorted(hits))
        self.assertFalse(any("abcd1234" in h for h in hits))

    def test_credentials_with_a_prefix_or_suffix_are_found(self):
        commit(self.repo, {"a.py": 'SECRET_KEY = "abcdefghijklmnop1234"\n', "b.js": 'const githubToken = "abcdefghijklmnop1234";\n',
                           "c.yml": 'db_password: "abcdefghijklmnop1234"\n'})
        self.assertEqual(["a.py:1 hard-coded credential", "b.js:1 hard-coded credential", "c.yml:1 hard-coded credential"],
                         sorted(gate.find_secrets(self.repo)))

    def test_prose_and_lookups_are_not_credentials(self):
        commit(self.repo, {"a.py": 'password_hint = "enter your password here"\ntoken = os.environ["API_TOKEN_NAME_X"]\n'})
        self.assertEqual([], gate.find_secrets(self.repo))

    def test_ordinary_code_is_clean(self):
        commit(self.repo, {"calc.py": "def add(a, b):\n    token = next(parts)\n    return a + b\n"})
        self.assertEqual([], gate.find_secrets(self.repo))

    def test_only_added_lines_are_scanned(self):
        commit(self.repo, {"old.py": "PASSWORD = 'hunter2hunter2hunter2'\n"})
        gate.git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        commit(self.repo, {"new.py": "ok = 1\n"})
        self.assertEqual([], gate.find_secrets(self.repo))

    def test_size_counts_added_and_deleted_lines(self):
        commit(self.repo, {"calc.py": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"})
        self.assertEqual(4, gate.diff_lines(self.repo))

    def test_changes_report_the_new_path(self):
        commit(self.repo, {"package.json": '{"a": 1}\n', "docs/new.md": "x\n"})
        self.assertEqual({("M", "package.json"), ("A", "docs/new.md")}, {(s, p) for s, p, _ in gate.changes(self.repo)})


class Planned(unittest.TestCase):
    def test_reads_backticked_paths_under_files_to_touch(self):
        tmp, root = make_repo({"spec.md": "# s\n\n## Files to touch\n- `calc.py`\n- `tests/test_*.py` tests\n\n## Out of scope\n`x.py`\n"})
        self.addCleanup(tmp.cleanup)
        self.assertEqual({"calc.py", "tests/test_*.py"}, gate.planned(root))

    def test_none_when_the_spec_lists_no_files(self):
        tmp, root = make_repo({"spec.md": "# s\n\n## Requirements\n1. x\n"})
        self.addCleanup(tmp.cleanup)
        self.assertIsNone(gate.planned(root))


class Retries(unittest.TestCase):
    def test_a_flaky_check_passes_on_retry_and_says_so(self):
        tmp, root = make_repo({"count": "0\n"})
        self.addCleanup(tmp.cleanup)
        script = root / "checks.sh"
        script.write_text('n=$(cat count); echo $((n+1)) > count; [ "$n" -ge 1 ]\n')
        saved = gate.CHECKS
        gate.CHECKS = script
        self.addCleanup(lambda: setattr(gate, "CHECKS", saved))
        code, _, _, failed_first = gate.run_checks(root, retries=2)
        self.assertEqual((0, 1), (code, failed_first))

    def test_no_retries_means_one_run(self):
        tmp, root = make_repo({"count": "0\n"})
        self.addCleanup(tmp.cleanup)
        script = root / "checks.sh"
        script.write_text("exit 3\n")
        saved = gate.CHECKS
        gate.CHECKS = script
        self.addCleanup(lambda: setattr(gate, "CHECKS", saved))
        self.assertEqual((3, 0), gate.run_checks(root)[::3])


if __name__ == "__main__":
    unittest.main()


class Verification(unittest.TestCase):
    def test_parses_ac_lines_with_or_without_backticks(self):
        tmp, root = make_repo({"spec.md": "# s\n\n## Verification\nAC1: pytest -q\nAC2: `curl -fsS localhost:5100/health`\n"
                                          "not a command\nAC3:\n\n## Out of scope\nAC9: rm -rf /\n"})
        self.addCleanup(tmp.cleanup)
        self.assertEqual([("AC1", "pytest -q"), ("AC2", "curl -fsS localhost:5100/health")], gate.verification(root))

    def test_no_spec_or_no_section(self):
        tmp, root = make_repo({"spec.md": "# s\n"})
        self.addCleanup(tmp.cleanup)
        self.assertEqual([], gate.verification(root))
        self.assertEqual([], gate.verification(root / "nowhere"))

    def test_only_allowed_commands_run_and_each_gets_its_result(self):
        tmp, root = make_repo({"ok.txt": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "true"), ("AC2", "false"), ("AC3", "ls ok.txt"), ("AC4", "git status")],
                                  ["true", "false", "ls"], 5, 5100)
        self.assertEqual(["pass", "fail", "pass", "skipped"], [r[2] for r in got])
        self.assertEqual("not on gate.verify_allow", got[3][3])

    def test_nothing_runs_when_nothing_is_allowed(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", f"touch {root}/pwned")], [], 5, 5100)
        self.assertEqual("skipped", got[0][2])
        self.assertFalse((root / "pwned").exists())

    def test_no_shell_so_metacharacters_are_just_arguments(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "echo hi; touch pwned"), ("AC2", "echo $(touch pwned2)"),
                                         ("AC3", "echo hi | tee pwned3")], ["echo"], 5, 5100)
        self.assertEqual(["pass", "pass", "pass"], [r[2] for r in got])
        self.assertEqual([], [p.name for p in root.iterdir() if p.name.startswith("pwned")])

    def test_an_allowed_prefix_must_match_whole_words(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "npm run test:e2e"), ("AC2", "npm install evil"), ("AC3", "npmx run test:e2e")],
                                  ["npm run test:e2e"], 5, 5100)
        self.assertEqual(["fail", "skipped", "skipped"], [r[2] for r in got])   # AC1 is allowed; npm just isn't installed here

    def test_allowing_a_command_does_not_allow_one_that_merely_starts_with_it(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "ls"), ("AC2", "lsof -i"), ("AC3", "ls-files")], ["ls"], 5, 5100)
        self.assertEqual(["pass", "skipped", "skipped"], [r[2] for r in got])

    def test_timeout_unparseable_and_missing_binary(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "sleep 5"), ("AC2", "echo 'unclosed"), ("AC3", "no-such-tool-xyz")],
                                  ["sleep", "echo", "no-such-tool-xyz"], 1, 5100)
        self.assertEqual(["timeout", "skipped", "fail"], [r[2] for r in got])

    def test_the_command_sees_the_jobs_port(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        got = gate.run_acceptance(root, [("AC1", "printenv FACTORY_PORT")], ["printenv"], 5, 5130)
        self.assertEqual("exit 0\n5130", got[0][3])

    def test_ports_follow_the_skills_formula(self):
        self.assertEqual(5130, gate.job_port("003-add-x"))
        self.assertEqual(5150, gate.job_port("replay-5"))      # replay PR number modulo 50


class CodeOwners(unittest.TestCase):
    def rules(self, text):
        return [(p.split()[0], gate.owner_regex(p.split()[0]), p.split()[1:]) for p in text.strip().splitlines()]

    def test_patterns(self):
        r = self.rules("""
            /docs/ @docs
            *.js @web
            /src/*.py @py
            src/**/gen.py @gen
            billing @pay
        """)
        owned = gate.owned(["docs/a/b.md", "x/docs/c.md", "app.js", "web/lib/app.js", "src/a.py", "src/deep/a.py",
                            "src/x/y/gen.py", "billing/charge.py", "svc/billing/x.py", "README.md"], r)
        self.assertEqual({"docs/a/b.md": ["@docs"], "app.js": ["@web"], "web/lib/app.js": ["@web"], "src/a.py": ["@py"],
                          "src/x/y/gen.py": ["@gen"], "billing/charge.py": ["@pay"], "svc/billing/x.py": ["@pay"]}, owned)

    def test_the_last_matching_rule_wins_and_a_rule_without_owners_clears_it(self):
        r = self.rules("/src/ @core\n/src/vendor/ @vendor\n/src/vendor/tmp/\n")
        self.assertEqual({"src/a.py": ["@core"], "src/vendor/x.py": ["@vendor"]},
                         gate.owned(["src/a.py", "src/vendor/x.py", "src/vendor/tmp/y.py"], r))

    def test_the_repo_wide_default_does_not_count(self):
        self.assertEqual({}, gate.owned(["anything.py"], self.rules("* @team\n")))
        self.assertEqual({"a/b.py": ["@a"]}, gate.owned(["a/b.py", "c.py"], self.rules("* @team\n/a/ @a\n")))

    def test_rules_come_from_the_base_branch_so_a_branch_cannot_delete_them(self):
        tmp, root = make_repo({".github/CODEOWNERS": "# owners\n/billing/ @pay  # money\n", "billing/p.py": "x"})
        self.addCleanup(tmp.cleanup)
        git(root, "rm", "-q", ".github/CODEOWNERS")
        git(root, "commit", "-q", "-m", "drop owners")
        rules = gate.codeowner_rules(root)
        self.assertEqual([("/billing/", ["@pay"])], [(p, o) for p, _, o in rules])
        self.assertFalse((root / ".github/CODEOWNERS").exists())

    def test_no_codeowners_file(self):
        tmp, root = make_repo({"a": "x"})
        self.addCleanup(tmp.cleanup)
        self.assertEqual([], gate.codeowner_rules(root))


class WholeGate(unittest.TestCase):
    """gate() end to end on a throwaway repo, reading the checks.md it writes."""

    def setUp(self):
        tmp, self.repo = make_repo({"calc.py": "x = 1\n", ".github/CODEOWNERS": "/billing/ @pay\n"})
        self.addCleanup(tmp.cleanup)
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.fdir = Path(self.work.name) / "factory"
        self.jdir = self.fdir / "jobs" / "004-x"
        (self.jdir / "round-1").mkdir(parents=True)
        (self.jdir / "job.json").write_text(json.dumps({"id": "004-x", "round": 1, "worktree": str(self.repo)}))
        self.write("checks.sh", "exit 0\n")
        self.spec("AC1: true\nAC2: false")
        saved = {k: getattr(gate, k) for k in ("FACTORY", "CHECKS")}
        gate.FACTORY, gate.CHECKS = self.fdir, self.fdir / "checks.sh"
        self.addCleanup(lambda: [setattr(gate, k, v) for k, v in saved.items()])
        cfg = gate.CONFIG["gate"]
        before = dict(cfg)
        cfg.update(verify_allow=["true", "false"], verify_timeout=5, verify_script_timeout=5, retries=0)
        self.addCleanup(lambda: (cfg.clear(), cfg.update(before)))
        commit(self.repo, {"calc.py": "x = 2\n"})

    def write(self, name, text):
        (self.fdir / name).write_text(text)

    def spec(self, verification):
        (self.jdir / "spec.md").write_text(f"# s\n\n## Files to touch\n- `calc.py`\n\n## Verification\n{verification}\n")

    def run_gate(self):
        with self.assertRaises(SystemExit) as stop, contextlib.redirect_stdout(io.StringIO()):
            gate.gate("004-x", merge=False)
        return stop.exception.code, (self.jdir / "round-1" / "checks.md").read_text()

    def test_a_failing_acceptance_command_fails_the_gate(self):
        code, md = self.run_gate()
        self.assertEqual(1, code)
        self.assertIn("- AC1 PASS: `true`", md)
        self.assertIn("- AC2 FAIL: `false`", md)

    def test_passing_commands_pass_the_gate(self):
        self.spec("AC1: true")
        code, md = self.run_gate()
        self.assertEqual(0, code)
        self.assertTrue(md.startswith("GATE: PASS"))

    def test_with_nothing_allowed_no_command_runs_and_the_gate_does_not_fail_on_that(self):
        gate.CONFIG["gate"]["verify_allow"] = []
        code, md = self.run_gate()
        self.assertEqual(0, code)
        self.assertIn("gate.verify_allow is empty", md)

    def test_failed_checks_skip_the_slow_verification(self):
        self.write("checks.sh", "exit 3\n")
        self.write("verify.sh", "touch ran-verify\n")
        code, md = self.run_gate()
        self.assertEqual(1, code)
        self.assertIn("Not run: checks.sh failed first", md)
        self.assertFalse((self.repo / "ran-verify").exists())

    def test_a_failure_the_base_branch_shares_is_marked_red_and_cached(self):
        runs = Path(self.work.name) / "runs"
        self.write("checks.sh", f"echo run >> {runs}\nexit 3\n")
        code, md = self.run_gate()
        self.assertEqual(1, code)
        base = git(self.repo, "merge-base", "HEAD", "origin/main").strip()
        self.assertIn(f"BASE: red {base}", md.split("\n\n")[0])
        self.assertIn("The branch didn't cause this failure", md)
        self.assertEqual(2, len(runs.read_text().splitlines()))         # the branch, then the base
        self.run_gate()
        self.assertEqual(3, len(runs.read_text().splitlines()))         # the base result was cached
        self.assertEqual("red", json.loads((self.fdir / "jobs" / ".base" / f"{base}.json").read_text())["result"])
        self.assertEqual([], [l for l in git(self.repo, "worktree", "list").splitlines()[1:]])  # scratch checkout gone

    def test_a_failure_only_the_branch_has_is_marked_green(self):
        self.write("checks.sh", "grep -q 'x = 1' calc.py\n")             # the base has x = 1, the branch x = 2
        code, md = self.run_gate()
        self.assertEqual(1, code)
        self.assertRegex(md.split("\n\n")[0], r"\nBASE: green [0-9a-f]{40}$")
        self.assertIn("so the branch caused this failure", md)

    def test_a_passing_gate_never_checks_the_base(self):
        self.spec("AC1: true")
        code, md = self.run_gate()
        self.assertEqual(0, code)
        self.assertNotIn("BASE:", md)
        self.assertFalse((self.fdir / "jobs" / ".base").exists())

    def test_verify_script_failure_fails_the_gate_and_gets_the_job_and_port(self):
        self.spec("AC1: true")
        self.write("verify.sh", 'echo "job=$FACTORY_JOB port=$FACTORY_PORT"; exit 7\n')
        code, md = self.run_gate()
        self.assertEqual(1, code)
        self.assertIn("## verify.sh\nFAILED", md)
        self.assertIn("job=004-x port=5140", md)

    def test_verify_script_passing(self):
        self.spec("AC1: true")
        self.write("verify.sh", "exit 0\n")
        code, md = self.run_gate()
        self.assertEqual(0, code)
        self.assertIn("## verify.sh\nPassed", md)

    def test_an_owned_path_is_flagged(self):
        self.spec("AC1: true")
        commit(self.repo, {"billing/charge.py": "pay = 1\n"})
        code, md = self.run_gate()
        self.assertEqual(0, code)
        self.assertIn("owned-path", md.splitlines()[2])
        self.assertIn("- billing/charge.py: @pay", md)
