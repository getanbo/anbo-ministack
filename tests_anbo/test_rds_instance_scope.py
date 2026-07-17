from ministack.core.docker_scope import managed_labels
from ministack.services import rds


class _Container:
    id = "rds-child"

    def __init__(self, labels):
        self.labels = labels
        self.attrs = {
            "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": "49200"}]}}
        }

    def reload(self):
        return None


class _Containers:
    def __init__(self):
        self.created = []

    def get(self, _name):
        raise RuntimeError("not found")

    def run(self, **kwargs):
        container = _Container(kwargs["labels"])
        self.created.append((kwargs, container))
        return container


class _Docker:
    def __init__(self):
        self.containers = _Containers()


def _instance():
    return {
        "Engine": "postgres",
        "EngineVersion": "17.1",
        "MasterUsername": "admin",
        "_MasterUserPassword": "secret",
        "DBName": "notes",
        "Endpoint": {},
    }


def test_scoped_rds_child_uses_dynamic_port_and_owned_resources(monkeypatch):
    docker = _Docker()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(rds, "_get_docker", lambda: docker)
    monkeypatch.setattr(rds, "_get_ministack_network", lambda _client: None)

    instance = _instance()
    rds._start_rds_container_for_instance("notes", instance)

    kwargs, _container = docker.containers.created[0]
    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["ports"] == {"5432/tcp": None}
    assert kwargs["labels"] == managed_labels(
        "rds", db_id="notes", account_id="000000000000", region="us-east-1"
    )
    assert instance["_HostPort"] == 49200
    assert instance["Endpoint"] == {"Address": rds._MINISTACK_HOST, "Port": 49200}


def test_legacy_rds_names_remain_unchanged(monkeypatch):
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)

    scope = rds._rds_docker_scope()
    assert rds._rds_docker_name("notes") == f"ministack-rds-{scope}-notes"
    assert rds._rds_docker_volume_name("notes") == f"ministack-rds-{scope}-notes-data"
