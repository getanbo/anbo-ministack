#!/usr/bin/env python3
"""Validate Anbo downstream versions and create immutable release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

RELEASE_VERSION = re.compile(r"^(?P<upstream>\d+\.\d+\.\d+)-anbo\.(?P<revision>[1-9]\d*)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")


def validate_version(version: str, upstream_ref: str) -> str:
    match = RELEASE_VERSION.fullmatch(version)
    if not match:
        raise ValueError(
            f"invalid downstream version {version!r}; expected X.Y.Z-anbo.N with N >= 1"
        )
    expected_upstream = upstream_ref.removeprefix("v")
    if match.group("upstream") != expected_upstream:
        raise ValueError(
            f"downstream version targets {match.group('upstream')}, but upstream.json records {expected_upstream}"
        )
    return version


def capability_hash(root: Path) -> str:
    """Hash the complete Python runtime surface shipped by MiniStack."""
    paths = sorted((root / "ministack").rglob("*.py"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        contents = path.read_bytes()
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return f"sha256:{digest.hexdigest()}"


def load_upstream(root: Path) -> dict:
    upstream = json.loads((root / ".github" / "upstream.json").read_text())
    if upstream.get("schemaVersion") != 1:
        raise ValueError(".github/upstream.json must use schemaVersion 1")
    if not SOURCE_SHA.fullmatch(upstream.get("commit", "")):
        raise ValueError("upstream commit must be a full lowercase Git SHA")
    return upstream


def create_manifest(args: argparse.Namespace) -> dict:
    root = args.root.resolve()
    upstream = load_upstream(root)
    version = validate_version(args.version, upstream["ref"])
    if not SOURCE_SHA.fullmatch(args.source_sha):
        raise ValueError("source SHA must be a full lowercase Git SHA")
    for name, digest in (("regular", args.regular_digest), ("full", args.full_digest)):
        if not DIGEST.fullmatch(digest):
            raise ValueError(f"{name} image digest must be sha256 followed by 64 lowercase hex characters")

    image = "ghcr.io/getanbo/anbo-ministack"
    return {
        "schemaVersion": 1,
        "distribution": "Anbo MiniStack",
        "version": version,
        "source": {
            "repository": "https://github.com/getanbo/anbo-ministack",
            "commit": args.source_sha,
        },
        "upstream": {
            "repository": f"https://github.com/{upstream['repository']}",
            "ref": upstream["ref"],
            "commit": upstream["commit"],
        },
        "images": {
            "regular": {
                "tag": f"{image}:{version}",
                "digest": args.regular_digest,
                "reference": f"{image}@{args.regular_digest}",
            },
            "full": {
                "tag": f"{image}:{version}-full",
                "digest": args.full_digest,
                "reference": f"{image}@{args.full_digest}",
            },
        },
        "runtimeCompatibility": {
            "instanceIsolation": {
                "contractVersion": 1,
                "environment": "MINISTACK_INSTANCE_ID",
                "healthField": "instance_isolation",
            },
        },
        "capabilities": {"hash": capability_hash(root)},
        "supplyChain": {
            "provenance": "GitHub artifact attestation and OCI BuildKit provenance",
            "sbom": "CycloneDX release assets and OCI SPDX attestation",
            "signature": "Sigstore keyless signature over each image index digest",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-version")
    validate.add_argument("version")

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--source-sha", required=True)
    manifest.add_argument("--regular-digest", required=True)
    manifest.add_argument("--full-digest", required=True)
    manifest.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    upstream = load_upstream(args.root.resolve())
    if args.command == "validate-version":
        print(validate_version(args.version, upstream["ref"]))
        return 0

    result = create_manifest(args)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
