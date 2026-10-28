"""Exercise the installed commit hook with real, isolated Git commits.

Run directly: python3 tests/test_commit_attribution.py
No application, credentials, network, or user repository state is touched.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CommitAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lph-commit-policy-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith("GIT_"):
                self.env.pop(key)
        self.env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        self.env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + self.env.get("PATH", "")
        self.git("init", "--quiet")
        self.git("config", "user.name", "Test Maintainer")
        self.git("config", "user.email", "maintainer@example.test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(ROOT / ".githooks"))

    def git(self, *args, check=True, env=None):
        return subprocess.run(
            ["git"] + list(args), cwd=str(self.repo), env=env or self.env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
        )

    def commit(self, message, **identity):
        path = self.repo / "message.txt"
        path.write_text(message, encoding="utf-8")
        env = dict(self.env, **identity)
        return self.git("commit", "--allow-empty", "--quiet", "--file", str(path), check=False, env=env)

    def assert_blocked(self, result):
        self.assertNotEqual(result.returncode, 0, "Tool attribution was accepted by a real Git commit")
        self.assertIn("tool/bot attribution", result.stderr)
        self.assertNotEqual(self.git("rev-parse", "--verify", "HEAD", check=False).returncode, 0)

    def test_commandcode_coauthor_is_rejected(self):
        self.assert_blocked(self.commit(
            "fix: correct a regression\n\nCo-authored-by: CommandCodeBot <noreply@commandcode.ai>\n"
        ))

    def test_generated_with_advertising_is_rejected(self):
        self.assert_blocked(self.commit(
            "fix: correct a regression\n\n"
            "🤖 Generated with [Claude Code](https://claude.ai/code)\n"
        ))

    def test_other_tool_coauthors_are_rejected(self):
        for identity in (
            "Claude <noreply@anthropic.com>",
            "Codex <codex@openai.com>",
            "Hermes Agent <agent@example.test>",
            "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>",
        ):
            with self.subTest(identity=identity):
                self.assert_blocked(self.commit("fix: correct a regression\n\nCo-Authored-By: " + identity + "\n"))

    def test_tool_primary_author_is_rejected(self):
        self.assert_blocked(self.commit(
            "fix: correct a regression\n",
            GIT_AUTHOR_NAME="CommandCodeBot", GIT_AUTHOR_EMAIL="noreply@commandcode.ai",
        ))

    def test_tool_committer_is_rejected(self):
        self.assert_blocked(self.commit(
            "fix: correct a regression\n",
            GIT_COMMITTER_NAME="github-actions[bot]", GIT_COMMITTER_EMAIL="bot@example.test",
        ))

    def test_tahir_primary_author_and_human_signoff_are_preserved(self):
        message = (
            "fix: correct a regression\n\n"
            "Signed-off-by: Tahir Masood <103833906+tahirmasood2@users.noreply.github.com>\n"
        )
        result = self.commit(
            message, GIT_AUTHOR_NAME="Tahir Masood",
            GIT_AUTHOR_EMAIL="103833906+tahirmasood2@users.noreply.github.com",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.git("log", "-1", "--format=%an <%ae>").stdout.strip(),
            "Tahir Masood <103833906+tahirmasood2@users.noreply.github.com>",
        )
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.rstrip(), message.rstrip())

    def test_normal_tool_discussion_and_human_names_are_allowed(self):
        result = self.commit(
            "fix: handle Claude API responses\n\n"
            "Keep upstream copyright and licence notices intact.\n\n"
            "Co-authored-by: Claude Shannon <claude.shannon@example.test>\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tahir_human_coauthor_and_message_are_preserved(self):
        message = (
            "fix: correct a regression\n\n"
            "Co-authored-by: Tahir Masood <103833906+tahirmasood2@users.noreply.github.com>\n"
        )
        result = self.commit(message)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("log", "-1", "--format=%B").stdout.rstrip(), message.rstrip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
