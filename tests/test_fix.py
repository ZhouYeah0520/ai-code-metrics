import unittest
from unittest.mock import Mock, patch

from ai_code_metrics.fix import auto_fix
from ai_code_metrics.adapters import normalize_exit_code, run_agent
from ai_code_metrics.cli import main


class AutoFixTests(unittest.TestCase):
    def test_converges_after_agent_fixes(self):
        with patch("ai_code_metrics.fix.run_tests",
                   side_effect=[(False, "FAIL"), (True, "PASS")]), \
             patch("ai_code_metrics.fix.run_agent",
                   return_value=Mock(ok=True)) as ra:
            result = auto_fix("claude-code", ["pytest", "-q"], cwd=".")
        self.assertTrue(result["fixed"])
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(ra.call_count, 1)

    def test_gives_up_after_rounds(self):
        with patch("ai_code_metrics.fix.run_tests", return_value=(False, "FAIL")), \
             patch("ai_code_metrics.fix.run_agent",
                   return_value=Mock(ok=True)) as ra:
            result = auto_fix("claude-code", ["pytest", "-q"], cwd=".", rounds=2)
        self.assertFalse(result["fixed"])
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(ra.call_count, 2)

    def test_skips_agent_when_tests_pass(self):
        with patch("ai_code_metrics.fix.run_tests", return_value=(True, "PASS")), \
             patch("ai_code_metrics.fix.run_agent") as ra:
            result = auto_fix("codex", ["pytest", "-q"], cwd=".")
        self.assertTrue(result["fixed"])
        self.assertEqual(result["rounds"], 0)
        ra.assert_not_called()

    def test_stops_on_agent_error(self):
        with patch("ai_code_metrics.fix.run_tests", return_value=(False, "FAIL")), \
             patch("ai_code_metrics.fix.run_agent",
                   return_value=Mock(ok=False, error="CLI not found")) as ra:
            result = auto_fix("claude-code", ["pytest", "-q"], cwd=".")
        self.assertFalse(result["fixed"])
        self.assertEqual(result["agent_error"], "CLI not found")
        self.assertEqual(ra.call_count, 1)

    def test_codex_edit_mode_uses_current_workspace_write_flags(self):
        fake = Mock(returncode=0, stdout="{}", stderr="")
        with patch("ai_code_metrics.adapters.shutil.which", return_value="codex"), \
             patch("ai_code_metrics.adapters.subprocess.run", return_value=fake) as run:
            result = run_agent("codex", "fix it", edit=True)
        self.assertTrue(result.ok)
        command = run.call_args.args[0]
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertNotIn("--full-auto", command)

    def test_cli_returns_failure_when_fix_does_not_converge(self):
        with patch("ai_code_metrics.cli.auto_fix", return_value={
            "rounds": 1, "fixed": False, "final_output": "FAIL",
        }):
            exit_code = main(["fix", "--tool", "codex", "--rounds", "1"])
        self.assertEqual(exit_code, 1)

    def test_provider_error_is_failure_even_when_wrapper_exits_zero(self):
        self.assertEqual(
            normalize_exit_code(0, "", "[claude-code:unrecognized_model] bad model"), 1,
        )
        self.assertEqual(normalize_exit_code(0, "OK", ""), 0)


if __name__ == "__main__":
    unittest.main()
