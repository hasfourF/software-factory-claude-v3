import json
import re
import subprocess
import unittest
from pathlib import Path

from support import BIN, load_script

policy = load_script("policy")
AGENTS = Path(__file__).resolve().parents[2] / ".claude/agents"


class Verdicts(unittest.TestCase):
    def test_what_the_agents_do_is_allowed(self):
        for command in ["cd /w && git push -u origin factory/001-x", "git push origin HEAD:factory/001-x",
                        "git push --force-with-lease origin +factory/001-x",
                        'git commit -m "docs: never git push origin main"',
                        "gh pr create --draft --head factory/001-x --title t --body 'Closes #1'",
                        "gh pr view 5 --json title,body,files", "gh pr diff 5", "gh api repos/o/r/pulls/5/files",
                        "gh api graphql -f query='{ viewer { login } }'", "git fetch origin && git diff origin/main...HEAD"]:
            self.assertIsNone(policy.verdict(command), command)

    def test_merges_are_refused(self):
        for command in ["gh pr merge 5 --squash", "gh -R o/r pr merge 5", "cd /w && gh pr merge 5",
                        "bash -c 'gh pr merge 5'", "gh api -X PUT repos/o/r/pulls/5/merge",
                        "gh api --method=PUT repos/o/r/pulls/5/merge"]:
            self.assertRegex(policy.verdict(command) or "", "merge|never write", command)

    def test_pushes_outside_factory_branches_are_refused(self):
        for command in ["git push origin main", "git -C /w push origin main", "git push origin factory/001-x:main",
                        "git push origin factory/001-x main", "git push origin :main", "git push origin refs/tags/v1",
                        "git status\ngit push origin main", "eval git push origin main", "sh -c 'git push origin main'"]:
            self.assertIn("only factory/*", policy.verdict(command) or "", command)

    def test_pushes_that_name_no_branch_or_every_branch_are_refused(self):
        for command in ["git push", "git push origin", "git push --all origin", "git push --tags origin",
                        "git push --mirror origin", "git push --prune origin factory/001-x"]:
            self.assertRegex(policy.verdict(command) or "", "without a branch|reaches", command)

    def test_writes_through_gh_api_are_refused(self):
        for command in ["gh api repos/o/r/issues/5/comments -f body=hi", "gh api -X DELETE repos/o/r/git/refs/heads/main",
                        "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'"]:
            self.assertIn("never write", policy.verdict(command) or "", command)

    def test_unreadable_quoting_is_refused_only_when_it_pushes_or_calls_github(self):
        self.assertIsNone(policy.verdict("echo 'it's fine"))
        self.assertIn("can't be read", policy.verdict("git push origin 'main") or "")


class Hook(unittest.TestCase):
    def run_hook(self, event):
        return subprocess.run([str(BIN / "policy")], input=event, capture_output=True, text=True)

    def test_a_refused_command_exits_2_with_the_reason(self):
        res = self.run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 5"}}))
        self.assertEqual(2, res.returncode)
        self.assertIn("factory policy: only `factory/bin/job merge`", res.stderr)

    def test_an_allowed_command_and_other_tools_pass(self):
        for event in ({"tool_name": "Bash", "tool_input": {"command": "git push -u origin factory/1"}},
                      {"tool_name": "Write", "tool_input": {"file_path": "x"}}):
            self.assertEqual(0, self.run_hook(json.dumps(event)).returncode)

    def test_input_it_cannot_read_is_refused(self):
        self.assertEqual(2, self.run_hook("not json").returncode)


class Agents(unittest.TestCase):
    def test_every_agent_with_a_shell_runs_the_policy_before_bash(self):
        for path in AGENTS.glob("*.md"):
            front = path.read_text().split("---\n")[1]
            if re.search(r"^tools:.*\bBash\b", front, re.M):
                self.assertRegex(front, r"PreToolUse:\n\s+- matcher: Bash\n\s+hooks:\n\s+- type: command\n\s+command: factory/bin/policy\n",
                                 path.name)


if __name__ == "__main__":
    unittest.main()
