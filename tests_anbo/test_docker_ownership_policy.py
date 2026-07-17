import json

from scripts.check_docker_ownership import check_repository


def _policy_repository(tmp_path, expansion):
    services = tmp_path / "ministack" / "services"
    services.mkdir(parents=True)
    policy_dir = tmp_path / ".github"
    policy_dir.mkdir()

    policy = {
        "schemaVersion": 1,
        "requiredHelpers": [
            "is_owned",
            "isolation_enabled",
            "managed_labels",
            "scoped_name",
            "validated_launch_kwargs",
        ],
        "modules": {
            "ecs": {
                "service": "ecs",
                "launchCalls": {"create": 0, "run": 1},
            }
        },
    }
    (policy_dir / "downstream-docker-ownership.json").write_text(
        json.dumps(policy)
    )
    (services / "ecs.py").write_text(
        f"""
from ministack.core.docker_scope import (
    is_owned,
    isolation_enabled,
    managed_labels,
    scoped_name,
    validated_launch_kwargs,
)


def launch(client, kwargs, container):
    is_owned(container, "ecs")
    isolation_enabled()
    managed_labels("ecs")
    scoped_name("ministack-ecs-task")
    return client.containers.run(**{expansion})
"""
    )
    return tmp_path


def test_ownership_policy_requires_direct_launch_guard(tmp_path):
    root = _policy_repository(
        tmp_path,
        'validated_launch_kwargs("ecs", kwargs)',
    )

    assert check_repository(root) == []

    source_path = root / "ministack" / "services" / "ecs.py"
    source_path.write_text(source_path.read_text().replace(
        '**validated_launch_kwargs("ecs", kwargs)',
        "**kwargs",
    ))

    assert any(
        "must directly expand validated_launch_kwargs('ecs', ...)" in error
        for error in check_repository(root)
    )


def test_ownership_policy_rejects_wrong_launch_service(tmp_path):
    root = _policy_repository(
        tmp_path,
        'validated_launch_kwargs("rds", kwargs)',
    )

    assert any(
        "must use 'ecs', not 'rds'" in error
        for error in check_repository(root)
    )
