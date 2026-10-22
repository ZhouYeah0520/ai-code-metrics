import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_code_metrics.adapters import parse_claude_output, parse_codex_output
from ai_code_metrics.git import add_ai_note, ratio


class GitMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.base = self.git("rev-parse", "HEAD")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True,
                              text=True, capture_output=True).stdout.strip()

    def test_ratio_uses_committed_changes_and_notes(self):
        (self.repo / "ai.txt").write_text("one\ntwo\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "AI change")
        ai_commit = self.git("rev-parse", "HEAD")
        add_ai_note(ai_commit, "test", self.repo)
        (self.repo / "human.txt").write_text("three\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "human change")

        result = ratio(self.base, "HEAD", self.repo)

        self.assertEqual(result["total_added"], 3)
        self.assertEqual(result["ai_added"], 2)
        self.assertEqual(result["ratio"], 0.6667)
        self.assertEqual(result["ai_commits"], 1)

    def test_empty_commit_range_has_null_ratio(self):
        result = ratio(self.base, self.base, self.repo)
        self.assertEqual(result["commits"], 0)
        self.assertEqual(result["total_added"], 0)
        self.assertIsNone(result["ratio"])


class AdapterParsingTests(unittest.TestCase):
    def test_claude_json_and_plain_fallback(self):
        self.assertEqual(parse_claude_output('{"result":"ok"}'), "ok")
        self.assertEqual(parse_claude_output("plain text"), "plain text")

    def test_codex_jsonl_extracts_agent_messages(self):
        event = {"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}
        self.assertEqual(parse_codex_output(json.dumps(event)), "done")


if __name__ == "__main__":
    unittest.main()
