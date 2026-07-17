from ministack.core.docker_scope import managed_labels
from ministack.services import elasticache


class FakeContainer:
    def __init__(self, container_id, labels, host_port=49123):
        self.id = container_id
        self.labels = labels
        self.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "6379/tcp": [{"HostPort": str(host_port)}],
                },
                "Networks": {},
            },
        }
        self.stopped = False
        self.removed = False

    def reload(self):
        return None

    def stop(self, **_kwargs):
        self.stopped = True

    def remove(self, **_kwargs):
        self.removed = True


class FakeContainers:
    def __init__(self):
        self.created = []
        self.listed = []

    def run(self, **kwargs):
        container = FakeContainer(
            f"container-{len(self.created)}",
            kwargs["labels"],
        )
        self.created.append((kwargs, container))
        return container

    def list(self, **kwargs):
        return list(self.listed)


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()


def test_scoped_spawn_uses_owned_name_labels_and_dynamic_port(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(elasticache, "_docker", docker)
    monkeypatch.setattr(elasticache, "DOCKER_NETWORK", "")

    host, port, _container_id = elasticache._spawn_redis_container(
        "ministack-elasticache-account-region-cache",
        "redis",
        "7.1",
        {
            "ministack": "elasticache",
            "cluster_id": "cache",
        },
    )

    kwargs, _container = docker.containers.created[0]
    assert host == elasticache._MINISTACK_HOST
    assert port == 49123
    assert kwargs["ports"] == {"6379/tcp": None}
    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["labels"] == managed_labels(
        "elasticache",
        {
            "ministack": "elasticache",
            "cluster_id": "cache",
        },
    )


def test_scoped_reset_does_not_remove_foreign_container(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(elasticache, "_docker", docker)

    owned = FakeContainer(
        "owned",
        managed_labels("elasticache", {"cluster_id": "ours"}),
    )
    with monkeypatch.context() as foreign_context:
        foreign_context.setenv("MINISTACK_INSTANCE_ID", "sandbox-b")
        foreign_labels = managed_labels(
            "elasticache",
            {"cluster_id": "theirs"},
        )
    foreign = FakeContainer("foreign", foreign_labels)
    docker.containers.listed = [owned, foreign]

    elasticache.reset()

    assert owned.removed is True
    assert foreign.stopped is False
    assert foreign.removed is False


def test_legacy_spawn_keeps_exact_name_labels_and_fixed_port(monkeypatch):
    docker = FakeDocker()
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    monkeypatch.setattr(elasticache, "_docker", docker)
    monkeypatch.setattr(elasticache, "DOCKER_NETWORK", "")
    elasticache._port_counter[0] = elasticache.BASE_PORT
    labels = {"ministack": "elasticache", "cluster_id": "cache"}
    name = "ministack-elasticache-account-region-cache"

    _host, port, _container_id = elasticache._spawn_redis_container(
        name,
        "redis",
        "7.1",
        labels,
    )

    kwargs, _container = docker.containers.created[0]
    assert port == elasticache.BASE_PORT
    assert kwargs["ports"] == {"6379/tcp": elasticache.BASE_PORT}
    assert kwargs["name"] == name
    assert kwargs["labels"] == labels
