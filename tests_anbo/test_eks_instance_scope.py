import pytest

from ministack.core.docker_scope import managed_labels
from ministack.services import eks


class _StartFailContainer:
    def __init__(self, labels):
        self.labels = labels
        self.removed = False

    def put_archive(self, _path, _data):
        return True

    def start(self):
        raise RuntimeError("start failed")

    def remove(self, **_kwargs):
        self.removed = True


class _Containers:
    def __init__(self):
        self.container = None

    def create(self, **kwargs):
        self.container = _StartFailContainer(kwargs["labels"])
        return self.container


class _Client:
    def __init__(self):
        self.containers = _Containers()


def test_scoped_eks_k3s_child_has_owned_name_labels_and_dynamic_port(monkeypatch):
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")

    kwargs = eks._k3s_run_kwargs("notes", None, ms_network="shared-net")

    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["ports"] == {"6443/tcp": None}
    assert kwargs["labels"] == managed_labels("eks", {"cluster_name": "notes"})
    assert kwargs["network"] == "shared-net"


def test_legacy_eks_k3s_child_contract_is_unchanged(monkeypatch):
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)

    kwargs = eks._k3s_run_kwargs("notes", 16443)

    assert kwargs["name"] == "ministack-eks-notes"
    assert kwargs["ports"] == {"6443/tcp": 16443}
    assert kwargs["labels"] == {"ministack": "eks", "cluster_name": "notes"}


@pytest.mark.parametrize(
    ("instance_id", "expected_removed"),
    [("sandbox-a", True), (None, False)],
)
def test_k3s_start_failure_cleanup_preserves_legacy_behavior(
    monkeypatch,
    instance_id,
    expected_removed,
):
    if instance_id is None:
        monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
        port = 16443
    else:
        monkeypatch.setenv("MINISTACK_INSTANCE_ID", instance_id)
        port = None
    client = _Client()
    kwargs = eks._k3s_run_kwargs("notes", port, ms_network="shared-net")

    with pytest.raises(RuntimeError, match="start failed"):
        eks._start_k3s_container(client, kwargs, b"mirrors: {}\n")

    assert client.containers.container is not None
    assert client.containers.container.removed is expected_removed
