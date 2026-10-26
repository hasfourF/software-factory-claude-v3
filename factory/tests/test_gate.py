import unittest

from support import commit, load_script, make_repo

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
