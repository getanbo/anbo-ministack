from ministack.core.docker_scope import managed_labels
from ministack.services import ecs


def test_scoped_ecs_task_child_has_owned_name_labels_and_dynamic_port(monkeypatch):
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")

    assert ecs._docker_port_bindings({
        "portMappings": [{"containerPort": 8080, "hostPort": 8080}],
    }) == {"8080/tcp": None}
    assert ecs._docker_host_mode({"networkMode": "host"}) is False

    kwargs = ecs._build_run_kwargs(
        {"name": "api"}, {"family": "notes", "revision": 2}, {},
        {"8080/tcp": None}, "shared-net", False, "1234567890abcdef",
        "task-arn", None, "cluster-arn",
    )

    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["ports"] == {"8080/tcp": None}
    assert kwargs["labels"] == managed_labels(
        "ecs",
        {
            "com.amazonaws.ecs.cluster": "cluster-arn",
            "com.amazonaws.ecs.container-name": "api",
            "com.amazonaws.ecs.task-arn": "task-arn",
            "com.amazonaws.ecs.task-definition-family": "notes",
            "com.amazonaws.ecs.task-definition-version": "2",
        },
    )


def test_legacy_ecs_task_child_contract_is_unchanged(monkeypatch):
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)

    assert ecs._docker_port_bindings({
        "portMappings": [{"containerPort": 8080, "hostPort": 8181}],
    }) == {"8080/tcp": 8181}
    assert ecs._docker_host_mode({"networkMode": "host"}) is True

    kwargs = ecs._build_run_kwargs(
        {"name": "api"}, {"family": "notes", "revision": 2}, {},
        {"8080/tcp": 8080}, "shared-net", False, "1234567890abcdef",
        "task-arn", None, "cluster-arn",
    )

    assert kwargs["name"] == "ministack-ecs-12345678-api"
    assert kwargs["ports"] == {"8080/tcp": 8080}
    assert kwargs["labels"] == {
        "ministack": "ecs",
        "com.amazonaws.ecs.cluster": "cluster-arn",
        "com.amazonaws.ecs.container-name": "api",
        "com.amazonaws.ecs.task-arn": "task-arn",
        "com.amazonaws.ecs.task-definition-family": "notes",
        "com.amazonaws.ecs.task-definition-version": "2",
    }
