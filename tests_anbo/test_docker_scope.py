import json
import re
import sys
from types import SimpleNamespace

import pytest

from ministack.core import docker_scope


class FakeContainer:
    def __init__(self, labels=None, attrs=None):
        self.labels = labels
        self.attrs = attrs or {}
        self.stop_calls = []
        self.remove_calls = []

    def stop(self, **kwargs):
        self.stop_calls.append(kwargs)

    def remove(self, **kwargs):
        self.remove_calls.append(kwargs)


class FakeContainers:
    def __init__(self, candidates):
        self.candidates = candidates
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return list(self.candidates)


def _clear_isolation(monkeypatch):
    monkeypatch.delenv(docker_scope.INSTANCE_ID_ENV, raising=False)
    monkeypatch.delenv("DOCKER_NETWORK", raising=False)


def test_legacy_helpers_are_exact_pass_through(monkeypatch):
    _clear_isolation(monkeypatch)
    launch_kwargs = {"labels": object()}

    assert docker_scope.instance_id() is None
    assert docker_scope.instance_scope() is None
    assert docker_scope.isolation_enabled() is False
    assert docker_scope.scoped_name("ministack-rds-orders") == "ministack-rds-orders"
    assert docker_scope.scoped_volume_name("ministack-rds-orders-data") == "ministack-rds-orders-data"
    assert docker_scope.managed_labels("rds", {"db_id": "orders"}, region="us-east-1") == {
        "ministack": "rds",
        "db_id": "orders",
        "region": "us-east-1",
    }
    assert (
        docker_scope.validated_launch_kwargs("not-a-managed-service", launch_kwargs)
        is launch_kwargs
    )
    assert docker_scope.contract_metadata() is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        " leading-space",
        "slash/not-allowed",
        "non-ascii-\N{LATIN SMALL LETTER E WITH ACUTE}",
        "x" * 129,
    ],
)
def test_instance_id_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, value)

    with pytest.raises(ValueError, match="MINISTACK_INSTANCE_ID"):
        docker_scope.instance_id()


def test_scope_and_names_are_deterministic_safe_and_bounded(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "Agent.Branch_123")

    scope = docker_scope.instance_scope()
    assert scope == docker_scope.instance_scope()
    assert re.fullmatch(r"[a-z0-9-]+", scope)
    assert scope.startswith("agent-branch-123-")

    name = docker_scope.scoped_name("ministack-rds-orders")
    assert name == f"ministack-{scope}-rds-orders"
    assert len(name) <= 128

    long_name = docker_scope.scoped_name("ministack-" + ("database-" * 40))
    long_volume = docker_scope.scoped_volume_name("ministack-" + ("volume-" * 80))
    assert len(long_name) <= 128
    assert len(long_volume) <= 255
    assert long_name == docker_scope.scoped_name("ministack-" + ("database-" * 40))
    assert long_volume == docker_scope.scoped_volume_name("ministack-" + ("volume-" * 80))


def test_published_host_port_supports_docker_sdk_shapes():
    direct = SimpleNamespace(
        ports={"5432/tcp": [{"HostPort": "49152"}]},
        reload=lambda: None,
    )
    attrs = SimpleNamespace(
        ports=None,
        attrs={
            "NetworkSettings": {
                "Ports": {"9200/tcp": [{"HostPort": "49153"}]},
            },
        },
        reload=lambda: None,
    )

    assert docker_scope.published_host_port(direct, 5432) == 49152
    assert docker_scope.published_host_port(attrs, 9200) == 49153
    assert docker_scope.published_host_port(attrs, 5601) is None


def test_managed_labels_add_reserved_ownership_fields(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")

    labels = docker_scope.managed_labels(
        "lambda",
        {
            "function_name": "notes",
            "com.ministack.instance": "forged",
        },
        region="eu-west-2",
    )

    assert labels == {
        "ministack": "lambda",
        "function_name": "notes",
        "com.ministack.instance": "sandbox-a",
        "region": "eu-west-2",
        "com.ministack.managed": "true",
        "com.ministack.scope": docker_scope.instance_scope(),
        "com.ministack.service": "lambda",
    }


def test_launch_guard_accepts_current_instance_ownership(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    kwargs = {
        "name": docker_scope.scoped_name("ministack-lambda-notes"),
        "labels": docker_scope.managed_labels("lambda", function_name="notes"),
    }

    assert docker_scope.validated_launch_kwargs("lambda", kwargs) is kwargs


@pytest.mark.parametrize(
    ("service", "name", "labels", "match"),
    [
        (
            "lambda",
            "ministack-lambda-notes",
            lambda: docker_scope.managed_labels("lambda"),
            "scoped_name",
        ),
        (
            "lambda",
            lambda: docker_scope.scoped_name("ministack-lambda-notes"),
            None,
            "managed_labels",
        ),
        (
            "lambda",
            lambda: docker_scope.scoped_name("ministack-lambda-notes"),
            lambda: docker_scope.managed_labels("ecs"),
            "ownership labels",
        ),
    ],
)
def test_launch_guard_rejects_unowned_scoped_kwargs(
    monkeypatch, service, name, labels, match
):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    resolved_name = name() if callable(name) else name
    resolved_labels = labels() if callable(labels) else labels

    with pytest.raises(ValueError, match=match):
        docker_scope.validated_launch_kwargs(
            service,
            {"name": resolved_name, "labels": resolved_labels},
        )


def test_owned_containers_filters_and_verifies_daemon_results(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    owned = FakeContainer(docker_scope.managed_labels("ecs", task="one"))
    foreign = FakeContainer(
        {
            "ministack": "ecs",
            "com.ministack.managed": "true",
            "com.ministack.instance": "sandbox-b",
            "com.ministack.scope": "sandbox-b-deadbeef00",
            "com.ministack.service": "ecs",
        }
    )
    malformed = FakeContainer({"ministack": "ecs"})
    containers = FakeContainers([owned, foreign, malformed])
    client = SimpleNamespace(containers=containers)

    assert docker_scope.owned_containers(client, "ecs") == [owned]
    assert containers.list_calls == [
        {
            "all": True,
            "filters": {
                "label": [
                    "com.ministack.managed=true",
                    "com.ministack.instance=sandbox-a",
                    "com.ministack.service=ecs",
                ]
            },
        }
    ]


def test_is_owned_reads_docker_attrs_and_remove_guard_blocks_foreign(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    owned = FakeContainer(
        labels=None,
        attrs={"Config": {"Labels": docker_scope.managed_labels("mwaa", env_name="dev")}},
    )
    foreign = FakeContainer({"ministack": "mwaa"})

    assert docker_scope.is_owned(owned, "mwaa") is True
    assert docker_scope.remove_owned(owned, "mwaa", timeout=2) is True
    assert owned.stop_calls == [{"timeout": 2}]
    assert owned.remove_calls == [{"v": True, "force": False}]

    assert docker_scope.is_owned(foreign, "mwaa") is False
    assert docker_scope.remove_owned(foreign, "mwaa") is False
    assert foreign.stop_calls == []
    assert foreign.remove_calls == []


def test_contract_metadata_has_stable_public_shape(monkeypatch):
    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    monkeypatch.setenv("DOCKER_NETWORK", "anbo-runtime-a")

    assert docker_scope.contract_metadata() == {
        "contract_version": 1,
        "instance_id": "sandbox-a",
        "scope": docker_scope.instance_scope(),
        "docker_network": "anbo-runtime-a",
    }


def test_health_shape_is_unchanged_in_legacy_mode(monkeypatch):
    from ministack import app

    _clear_isolation(monkeypatch)
    status, _, body = app._handle_health_request("/_ministack/health", "request-id")
    payload = json.loads(body)

    assert status == 200
    assert set(payload) == {"services", "edition", "version", "ready_scripts"}


def test_health_exposes_instance_contract_only_in_scoped_mode(monkeypatch):
    from ministack import app

    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    monkeypatch.setenv("DOCKER_NETWORK", "anbo-runtime-a")
    status, _, body = app._handle_health_request("/_ministack/health", "request-id")
    payload = json.loads(body)

    assert status == 200
    assert payload["instance_isolation"] == docker_scope.contract_metadata()


def test_app_legacy_cleanup_retains_global_service_filters(monkeypatch):
    from ministack import app

    _clear_isolation(monkeypatch)
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker.invalid:2375")
    containers = FakeContainers([])
    client = SimpleNamespace(containers=containers)
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))

    app._stop_docker_containers()

    assert containers.list_calls == [
        {"all": True, "filters": {"label": f"ministack={service}"}}
        for service in ("rds", "ecs", "elasticache", "eks", "lambda")
    ]


def test_app_scoped_cleanup_never_removes_foreign_container(monkeypatch):
    from ministack import app

    monkeypatch.setenv(docker_scope.INSTANCE_ID_ENV, "sandbox-a")
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker.invalid:2375")
    owned = FakeContainer(docker_scope.managed_labels("glue", job_name="etl"))
    foreign = FakeContainer(
        {
            "ministack": "glue",
            "com.ministack.managed": "true",
            "com.ministack.instance": "sandbox-b",
            "com.ministack.scope": "sandbox-b-deadbeef00",
            "com.ministack.service": "glue",
        }
    )
    containers = FakeContainers([owned, foreign])
    client = SimpleNamespace(containers=containers)
    monkeypatch.setitem(sys.modules, "docker", SimpleNamespace(from_env=lambda: client))

    app._stop_docker_containers()

    assert containers.list_calls == [
        {
            "all": True,
            "filters": {
                "label": [
                    "com.ministack.managed=true",
                    "com.ministack.instance=sandbox-a",
                ]
            },
        }
    ]
    assert owned.stop_calls == [{"timeout": 5}]
    assert owned.remove_calls == [{"v": True, "force": False}]
    assert foreign.stop_calls == []
    assert foreign.remove_calls == []
