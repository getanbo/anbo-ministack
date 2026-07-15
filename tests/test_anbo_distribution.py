import json
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.anbo_distribution import capability_hash, create_manifest, validate_version


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def test_downstream_version_matches_pinned_upstream():
    assert validate_version("1.4.2-anbo.1", "v1.4.2") == "1.4.2-anbo.1"


@pytest.mark.parametrize(
    "version",
    ["v1.4.2-anbo.1", "1.4.2", "1.4.2-anbo.0", "1.4.3-anbo.1", "1.4.2-anbo.latest"],
)
def test_downstream_version_rejects_ambiguous_or_mismatched_values(version):
    with pytest.raises(ValueError):
        validate_version(version, "v1.4.2")


def test_capability_hash_is_deterministic_and_content_addressed(tmp_path):
    (tmp_path / "ministack" / "services").mkdir(parents=True)
    (tmp_path / "ministack" / "core").mkdir()
    (tmp_path / "ministack" / "services" / "s3.py").write_text("surface = 's3'\n")
    (tmp_path / "ministack" / "app.py").write_text("app = True\n")
    (tmp_path / "ministack" / "core" / "router.py").write_text("routes = []\n")
    before = capability_hash(tmp_path)
    assert before.startswith("sha256:")
    assert before == capability_hash(tmp_path)
    (tmp_path / "ministack" / "services" / "s3.py").write_text("surface = 's3-v2'\n")
    assert capability_hash(tmp_path) != before


def test_release_manifest_records_exact_digests(tmp_path):
    (tmp_path / ".github").mkdir()
    (tmp_path / "ministack" / "services").mkdir(parents=True)
    (tmp_path / "ministack" / "core").mkdir()
    (tmp_path / "ministack" / "app.py").write_text("app = True\n")
    (tmp_path / "ministack" / "core" / "router.py").write_text("routes = []\n")
    (tmp_path / ".github" / "upstream.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "repository": "ministackorg/ministack",
                "ref": "v1.4.2",
                "commit": "c" * 40,
            }
        )
    )
    args = Namespace(
        root=tmp_path,
        version="1.4.2-anbo.2",
        source_sha=SHA,
        regular_digest=DIGEST,
        full_digest="sha256:" + "d" * 64,
    )
    manifest = create_manifest(args)
    assert manifest["version"] == "1.4.2-anbo.2"
    assert manifest["images"]["regular"]["reference"].endswith(f"@{DIGEST}")
    assert manifest["capabilities"]["hash"].startswith("sha256:")
