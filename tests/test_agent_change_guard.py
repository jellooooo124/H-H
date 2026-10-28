"""Regression tests for developer-agent PR policy. No network, LLM, or patient data."""
import json
import unittest
from pathlib import Path

from scripts.agent_change_guard import classify, evaluate_change, markdown_report
from scripts.evaluate_agent_guard import run

ROOT = Path(__file__).resolve().parents[1]


class AgentChangeGuardTests(unittest.TestCase):
    def test_synthetic_benchmark_is_stable(self):
        fixture = json.loads((ROOT / "examples/agent_guard_benchmark.json").read_text())
        report = run(fixture)
        self.assertGreaterEqual(report["summary"]["total"], 10)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["missed_high_risk_reviews"], 0)

    def test_security_and_agent_policy_changes_need_all_fields(self):
        for path in (".github/workflows/tests.yml", "backend/app/security.py", "scripts/agent_change_guard.py", ".env"):
            result = evaluate_change([path], "- Validation evidence: tests\n- Rollback plan: revert")
            self.assertEqual(result["highest_class"], "F")
            self.assertEqual(result["missing_evidence"], ["Risk owner"])

    def test_no_template_comments_or_placeholder_evidence(self):
        body = "<!-- - Validation evidence: pretend -->\n- Validation evidence: TODO\n- Rollback plan: revert"
        result = evaluate_change(["workflows/01_agentic_case_loop.json"], body)
        self.assertIn("Validation evidence", result["missing_evidence"])

    def test_unrecognized_file_is_high_risk_not_docs(self):
        self.assertEqual(classify("novel-agent/runner.ts"), "C")

    def test_summary_escapes_untrusted_filename(self):
        report = evaluate_change(["docs/<script>alert(1)</script>|bad.md"])
        summary = markdown_report(report)
        self.assertNotIn("<script>", summary)
        self.assertIn("&lt;script&gt;", summary)
        self.assertIn("&#124;", summary)

    def test_no_files_does_not_demand_evidence(self):
        report = evaluate_change([])
        self.assertTrue(report["evidence_complete"])
        self.assertEqual(report["changed_file_count"], 0)


if __name__ == "__main__":
    unittest.main()
