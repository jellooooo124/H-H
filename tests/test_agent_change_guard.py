"""Regression tests for developer-agent PR policy. No network, LLM, or patient data."""
import json
from pathlib import Path

from scripts.agent_change_guard import classify, evaluate_change, markdown_report
from scripts.evaluate_agent_guard import run

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_benchmark_is_stable():
    fixture = json.loads((ROOT / "examples/agent_guard_benchmark.json").read_text())
    report = run(fixture)
    assert report["summary"]["total"] >= 10
    assert report["summary"]["failed"] == 0
    assert report["summary"]["missed_high_risk_reviews"] == 0


def test_security_and_agent_policy_changes_need_all_fields():
    for path in (".github/workflows/tests.yml", "backend/app/security.py", "scripts/agent_change_guard.py"):
        result = evaluate_change([path], "- Validation evidence: tests\n- Rollback plan: revert")
        assert result["highest_class"] == "F"
        assert result["missing_evidence"] == ["Risk owner"]


def test_no_template_comments_or_placeholder_evidence():
    body = "<!-- - Validation evidence: pretend -->\n- Validation evidence: TODO\n- Rollback plan: revert"
    result = evaluate_change(["workflows/01_agentic_case_loop.json"], body)
    assert "Validation evidence" in result["missing_evidence"]


def test_unrecognized_file_is_high_risk_not_docs():
    assert classify("novel-agent/runner.ts") == "C"


def test_summary_escapes_untrusted_filename():
    report = evaluate_change(["docs/<script>alert(1)</script>|bad.md"])
    summary = markdown_report(report)
    assert "<script>" not in summary
    assert "&lt;script&gt;" in summary
    assert "&#124;" in summary


def test_no_files_does_not_demand_evidence():
    report = evaluate_change([])
    assert report["evidence_complete"] is True
    assert report["changed_file_count"] == 0
