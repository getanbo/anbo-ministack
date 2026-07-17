from ministack.core.docker_scope import managed_labels
from ministack.services import eks


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
