from ministack.core.docker_scope import managed_labels
from ministack.services import mwaa


class FakeThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        return None


class FakeContainer:
    id = "airflow-container"

    def __init__(self, labels, host_port=48080):
        self.labels = labels
        self.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "8080/tcp": [{"HostPort": str(host_port)}],
                },
                "Networks": {},
            },
        }

    def reload(self):
        return None


class FakeContainers:
    def __init__(self):
        self.created = []

    def get(self, _name):
        raise RuntimeError("not found")

    def run(self, **kwargs):
        container = FakeContainer(kwargs["labels"])
        self.created.append((kwargs, container))
        return container


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()


def _environment():
    return {
        "Name": "notes-airflow",
        "AirflowVersion": "3.0.6",
        "AirflowConfigurationOptions": {},
        "Status": "CREATING",
    }


def test_scoped_airflow_uses_dynamic_port_owned_name_and_volumes(monkeypatch):
    docker = FakeDocker()
    env = _environment()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(mwaa, "_docker", docker)
    monkeypatch.setattr(mwaa, "_ministack_network", "")
    monkeypatch.setattr(mwaa, "DOCKER_NETWORK", "")
    monkeypatch.setattr(mwaa, "MWAA_PERSIST", True)
    monkeypatch.setattr(mwaa.threading, "Thread", FakeThread)

    mwaa._start_airflow_container("notes-airflow", env)

    kwargs, _container = docker.containers.created[0]
    assert kwargs["ports"] == {"8080/tcp": None}
    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["labels"] == managed_labels(
        "mwaa",
        {"ministack": "mwaa", "env_name": "notes-airflow"},
    )
    assert len(kwargs["volumes"]) == 2
    assert all(
        volume.startswith("ministack-sandbox-a-")
        for volume in kwargs["volumes"]
    )
    assert env["_host_port"] == 48080
    assert env["WebserverUrl"] == "localhost:48080"


def test_legacy_airflow_keeps_upstream_name_labels_and_volumes(monkeypatch):
    docker = FakeDocker()
    env = _environment()
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    monkeypatch.setattr(mwaa, "_docker", docker)
    monkeypatch.setattr(mwaa, "_ministack_network", "")
    monkeypatch.setattr(mwaa, "DOCKER_NETWORK", "")
    monkeypatch.setattr(mwaa, "MWAA_PERSIST", True)
    monkeypatch.setattr(mwaa.threading, "Thread", FakeThread)
    mwaa._port_counter[0] = mwaa.BASE_PORT
    mwaa._allocated_ports.clear()
    mwaa._freed_ports.clear()

    mwaa._start_airflow_container("notes-airflow", env)

    kwargs, _container = docker.containers.created[0]
    assert kwargs["ports"] == {"8080/tcp": mwaa.BASE_PORT}
    assert kwargs["name"] == "ministack-mwaa-notes-airflow"
    assert kwargs["labels"] == {
        "ministack": "mwaa",
        "env_name": "notes-airflow",
    }
    assert set(kwargs["volumes"]) == {
        "ministack-mwaa-notes-airflow-dags",
        "ministack-mwaa-notes-airflow-db",
    }
