#!/usr/bin/env python3
"""Read-only, deterministic PR risk triage. NOT a sandbox or an approval engine."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RANK = {"A": 1, "B": 2, "E": 3, "D": 4, "C": 5, "F": 6}
LABELS = {
    "A": "Documentation / maintenance",
    "B": "Isolated code / UI",
    "C": "Domain / authorization / data",
    "D": "Workflow / agent / RAG",
    "E": "CI / dependencies / build",
    "F": "Security-sensitive / externally visible",
}
EVIDENCE = {
    "A": (),
    "B": (),
    "C": ("Validation evidence", "Rollback plan"),
    "D": ("Validation evidence", "Rollback plan"),
    "E": ("Validation evidence", "Rollback plan"),
    "F": ("Validation evidence", "Risk owner", "Rollback plan"),
}
EMPTY = {"none", "n/a", "na", "todo", "tbd", "pending", "-", "placeholder", "not run"}


def classify(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    lower = p.lower()
    if not p or p.startswith("/") or ".." in p.split("/"):
        return "F"
    if (
        lower.startswith(".github/workflows/")
        or lower in {"agents.md", "security.md", "docker-compose.yml", ".env", ".env.example"}
        or lower.startswith("backend/app/presentation/auth")
        or lower.startswith("backend/app/security")
        or lower.startswith("backend/app/identity")
        or lower.startswith("backend/app/config")
        or lower.startswith("scripts/agent_change_guard")
        or lower.startswith("scripts/evaluate_agent_guard")
        or lower.startswith("scripts/generate_secrets")
    ):
        return "F"
    if (
        lower.startswith("backend/app/domain/")
        or lower.startswith("backend/app/application/")
        or lower.startswith("backend/app/infrastructure/")
        or lower.startswith("database/")
        or lower.startswith("backend/app/policy")
    ):
        return "C"
    if (
        lower.startswith("workflows/")
        or lower.startswith("knowledge/")
        or lower.startswith("backend/app/agents")
        or lower.startswith("backend/app/rag")
    ):
        return "D"
    if (
        lower.startswith(".github/")
        or lower.startswith("scripts/")
        or lower.endswith((".lock", "dockerfile"))
        or lower.startswith("backend/requirements")
        or lower in {"pytest.ini", ".dockerignore", ".gitignore"}
    ):
        return "E"
    if lower.startswith(("tests/", "backend/", "frontend/", "contracts/")):
        return "B"
    if (
        lower.startswith(("docs/", "examples/"))
        or lower.startswith("readme")
        or lower.endswith(".md")
    ):
        return "A"
    # New/unmapped paths are not silently accepted as low risk.
    return "C"


def evidence_from_body(body: str) -> dict[str, str]:
    # Markdown comments may contain templates; do not count them as evidence.
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.DOTALL)
    found: dict[str, str] = {}
    for key in ("Validation evidence", "Risk owner", "Rollback plan"):
        match = re.search(r"(?im)^\s*[-*]?\s*" + re.escape(key) + r"\s*:\s*(.+?)\s*$", body)
        if match:
            value = match.group(1).strip().strip("`*_")
            if value and value.lower() not in EMPTY and not value.startswith("<"):
                found[key] = value
    return found


def evaluate_change(paths: list[str], pr_body: str = "") -> dict:
    unique_paths = sorted(set(paths))
    by_path = [{"path": p, "class": classify(p)} for p in unique_paths]
    highest = max((x["class"] for x in by_path), key=lambda x: RANK[x], default="A")
    supplied = evidence_from_body(pr_body)
    required = EVIDENCE[highest] if unique_paths else ()
    missing = [name for name in required if name not in supplied]
    return {
        "schema_version": 1,
        "scope": "conservative path-based PR triage; does not inspect code semantics or verify reviewer approval",
        "highest_class": highest,
        "risk_label": LABELS[highest],
        "review_required": highest in {"C", "D", "E", "F"},
        "required_evidence": list(required),
        "missing_evidence": missing,
        "evidence_present": [key for key in required if key in supplied],
        "evidence_complete": not missing,
        "changed_file_count": len(unique_paths),
        "files": by_path,
    }


def markdown_report(report: dict) -> str:
    lines = [
        "## Agent-assisted change risk triage",
        "",
        f"- Highest task class: **{report['highest_class']} — {report['risk_label']}**",
        f"- Changed files: **{report['changed_file_count']}**",
        f"- Human review recommended: **{'yes' if report['review_required'] else 'no'}**",
        f"- Required PR evidence complete: **{'yes' if report['evidence_complete'] else 'no'}**",
    ]
    if report["missing_evidence"]:
        lines.append("- Missing: " + ", ".join(report["missing_evidence"]))
    lines += [
        "",
        "| File | Class |",
        "| --- | --- |",
    ]
    for row in report["files"][:100]:
        # Filenames are untrusted; prevent table/newline or HTML injection in step summary.
        safe = row["path"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe = safe.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
        lines.append(f"| {safe} | {row['class']} |")
    if len(report["files"]) > 100:
        lines.append("| (additional files omitted) | ... |")
    lines += [
        "",
        "_Advisory: path-based rules cannot prove code safety, agent sandboxing, reviewer identity, or completed tests. "
        "Configure GitHub branch protection/CODEOWNERS separately for enforced human approval._",
    ]
    return "\n".join(lines) + "\n"


def diff_paths(base: str, head: str) -> list[str]:
    # No shell invocation; -z preserves unusual file names.
    cp = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--diff-filter=ACMR", base, head],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return [x.decode("utf-8", errors="replace") for x in cp.stdout.split(b"\0") if x]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="trusted git base commit SHA")
    parser.add_argument("--head", required=True, help="PR head commit SHA")
    parser.add_argument("--pr-body-env", default="PR_BODY", help="name of environment variable containing PR description")
    parser.add_argument("--output", default="agent-change-report.json")
    parser.add_argument("--summary", default=None)
    parser.add_argument("--enforce-evidence", action="store_true")
    args = parser.parse_args()
    report = evaluate_change(diff_paths(args.base, args.head), os.getenv(args.pr_body_env, ""))
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = markdown_report(report)
    if args.summary:
        Path(args.summary).write_text(summary, encoding="utf-8")
    print(summary)
    return 2 if args.enforce_evidence and not report["evidence_complete"] else 0


if __name__ == "__main__":
    sys.exit(main())
