#!/usr/bin/env python3
"""Offline benchmark for the repository's PR risk policy, not an LLM evaluation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from agent_change_guard import evaluate_change  # noqa: E402


def run(dataset: dict) -> dict:
    cases = []
    for case in dataset["cases"]:
        result = evaluate_change(case["files"], case.get("pr_body", ""))
        correct = (
            result["highest_class"] == case["expected_class"]
            and result["evidence_complete"] == case["expected_evidence_complete"]
            and result["review_required"] == case["expected_review_required"]
        )
        cases.append({
            "id": case["id"],
            "actual_class": result["highest_class"],
            "expected_class": case["expected_class"],
            "evidence_complete": result["evidence_complete"],
            "expected_evidence_complete": case["expected_evidence_complete"],
            "review_required": result["review_required"],
            "expected_review_required": case["expected_review_required"],
            "passed": correct,
        })
    passed = sum(c["passed"] for c in cases)
    high_risk = [c for c in cases if c["expected_review_required"]]
    missed_reviews = sum(not c["review_required"] for c in high_risk)
    return {
        "summary": {
            "dataset": dataset["name"],
            "total": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "accuracy": round(passed / len(cases), 4) if cases else 0,
            "missed_high_risk_reviews": missed_reviews,
            "scope": "hand-authored deterministic path-based synthetic fixtures; NOT autonomous-agent quality or production safety",
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "examples" / "agent_guard_benchmark.json"))
    parser.add_argument("--output", help="optional JSON report destination")
    args = parser.parse_args()
    report = run(json.loads(Path(args.dataset).read_text(encoding="utf-8")))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["failed"] == 0 and report["summary"]["missed_high_risk_reviews"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
