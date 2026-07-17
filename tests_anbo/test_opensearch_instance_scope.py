from ministack.core.docker_scope import managed_labels
from ministack.services import opensearch


class FakeContainer:
    def __init__(self, container_id, labels, ports):
        self.id = container_id
        self.labels = labels
        self.attrs = {
            "NetworkSettings": {
                "Ports": {
                    f"{container_port}/tcp": [
                        {"HostPort": str(host_port)}
                    ]
                    for container_port, host_port in ports.items()
                },
                "Networks": {},
            },
        }

    def reload(self):
        return None


class FakeContainers:
    def __init__(self):
        self.created = []

    def run(self, **kwargs):
        exposed = next(iter(kwargs["ports"]))
        container_port = int(exposed.split("/")[0])
        host_port = 49200 if container_port == 9200 else 45601
        container = FakeContainer(
            f"container-{len(self.created)}",
            kwargs["labels"],
            {container_port: host_port},
        )
        self.created.append((kwargs, container))
        return container


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()


def test_scoped_dataplane_and_dashboard_are_isolated(monkeypatch):
    docker = FakeDocker()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(opensearch, "_docker_client", docker)
    monkeypatch.setattr(opensearch, "DATAPLANE_ENABLED", True)
    monkeypatch.setattr(opensearch, "DASHBOARDS_ENABLED", True)
    monkeypatch.setattr(opensearch, "DOCKER_NETWORK", "")
    monkeypatch.setattr(opensearch, "ENDPOINT_OVERRIDE", "")

    host, port, _cid, dashboard, _dashboard_cid = (
        opensearch._spawn_dataplane("notes-domain", "OpenSearch_2.15")
    )

    data_kwargs, _data_container = docker.containers.created[0]
    dashboard_kwargs, _dashboard_container = docker.containers.created[1]
    assert host == opensearch._MINISTACK_HOST
    assert port == 49200
    assert dashboard == f"{opensearch._MINISTACK_HOST}:45601"
    assert data_kwargs["ports"] == {"9200/tcp": None}
    assert dashboard_kwargs["ports"] == {"5601/tcp": None}
    assert data_kwargs["name"].startswith("ministack-sandbox-a-")
    assert dashboard_kwargs["name"].startswith("ministack-sandbox-a-")
    assert data_kwargs["labels"] == managed_labels(
        "opensearch",
        {
            "com.ministack.service": "opensearch",
            "com.ministack.domain": "notes-domain",
            "com.docker.compose.project": "ministack",
        },
    )
    assert (
        dashboard_kwargs["environment"]["OPENSEARCH_HOSTS"]
        == f"http://{data_kwargs['name']}:9200"
    )


def test_legacy_dataplane_keeps_upstream_contract(monkeypatch):
    docker = FakeDocker()
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    monkeypatch.setattr(opensearch, "_docker_client", docker)
    monkeypatch.setattr(opensearch, "DATAPLANE_ENABLED", True)
    monkeypatch.setattr(opensearch, "DASHBOARDS_ENABLED", False)
    monkeypatch.setattr(opensearch, "DOCKER_NETWORK", "")
    monkeypatch.setattr(opensearch, "ENDPOINT_OVERRIDE", "")
    opensearch._port_counter[0] = opensearch.BASE_PORT
    opensearch._dashboards_port_counter[0] = (
        opensearch.DASHBOARDS_BASE_PORT
    )

    _host, port, _cid, _dashboard, _dashboard_cid = (
        opensearch._spawn_dataplane("notes-domain", "OpenSearch_2.15")
    )

    kwargs, _container = docker.containers.created[0]
    assert port == opensearch.BASE_PORT
    assert kwargs["ports"] == {"9200/tcp": opensearch.BASE_PORT}
    assert kwargs["name"] == "ministack-opensearch-notes-domain"
    assert kwargs["labels"] == {
        "com.ministack.service": "opensearch",
        "com.ministack.domain": "notes-domain",
        "com.docker.compose.project": "ministack",
    }
