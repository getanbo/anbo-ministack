#!/usr/bin/env python3
"""Fail when the downstream fork can accidentally publish upstream artifacts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"\buses:\s*[^\s@]+@([0-9a-f]{40})(?:\s*#.*)?$")
BANNED_PUBLISH_MARKERS = (
    "DOCKERHUB_TOKEN",
    "DOCKERHUB_USERNAME",
    "ghcr.io/ministackorg/ministack",
    "ministackorg/ministack-preview-build",
    "nahuelnucera/ministack",
    "pypa/gh-action-pypi-publish",
)
REQUIRED_DOWNSTREAM_PATHS = (
    ".github/downstream-docker-ownership.json",
    ".github/workflows/anbo-downstream-ci.yml",
    "DOWNSTREAM.md",
    "NOTICE",
    "scripts/check_docker_ownership.py",
    "tests_anbo",
)


def main() -> int:
    errors: list[str] = []
    workflow_files = sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))
    for workflow in workflow_files:
        text = workflow.read_text()
        for marker in BANNED_PUBLISH_MARKERS:
            if marker in text:
                errors.append(f"{workflow.relative_to(ROOT)} contains forbidden publishing marker {marker!r}")
        for line_number, line in enumerate(text.splitlines(), 1):
            if "uses:" in line and not PINNED_ACTION.search(line):
                errors.append(
                    f"{workflow.relative_to(ROOT)}:{line_number} must pin the action to a full commit SHA"
                )
        if "pull_request_target:" in text:
            if "actions/checkout@" in text or "secrets." in text:
                errors.append(
                    f"{workflow.relative_to(ROOT)} uses pull_request_target and must not checkout PR code or read secrets"
                )

    upstream = json.loads((ROOT / ".github" / "upstream.json").read_text())
    if upstream.get("repository") != "ministackorg/ministack":
        errors.append("upstream repository must remain ministackorg/ministack")
    if not re.fullmatch(r"[0-9a-f]{40}", upstream.get("commit", "")):
        errors.append("upstream commit must be a full lowercase Git SHA")

    readme = (ROOT / "README.md").read_text()
    if not readme.startswith("> **Anbo MiniStack distribution.**"):
        errors.append("README must retain the downstream distribution notice before upstream content")

    for relative_path in REQUIRED_DOWNSTREAM_PATHS:
        if not (ROOT / relative_path).exists():
            errors.append(f"required downstream path is missing: {relative_path}")

    ci_path = WORKFLOWS / "anbo-downstream-ci.yml"
    if ci_path.is_file():
        ci_text = ci_path.read_text()
        if not re.search(r"(?m)^  tests:\s*$", ci_text):
            errors.append("downstream CI must keep tests in a distinct tests job")
        if "python scripts/check_docker_ownership.py" not in ci_text:
            errors.append("downstream CI must run the Docker ownership policy guard")
        if not re.search(r"python -m pytest[^\n]*\btests_anbo\b", ci_text):
            errors.append("the downstream tests job must run tests from tests_anbo")
    else:
        errors.append(".github/workflows/anbo-downstream-ci.yml is required")

    downstream_doc_path = ROOT / "DOWNSTREAM.md"
    if (
        downstream_doc_path.is_file()
        and "MINISTACK_INSTANCE_ID" not in downstream_doc_path.read_text()
    ):
        errors.append("DOWNSTREAM.md must document the opt-in instance isolation boundary")

    if errors:
        print("Downstream policy violations:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Downstream policy passed for {len(workflow_files)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
