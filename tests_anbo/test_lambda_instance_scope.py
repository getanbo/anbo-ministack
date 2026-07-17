import io
import zipfile

import pytest

from ministack.core.docker_scope import managed_labels
from ministack.services import lambda_svc


class _Images:
    def get(self, _image):
        return True


class _Containers:
    def __init__(self):
        self.created = []
        self.container = None
        self.start_error = False

    def run(self, **kwargs):
        self.created.append(kwargs)
        return object()

    def create(self, **kwargs):
        self.container = _ManagedContainer(
            kwargs["labels"],
            start_error=self.start_error,
        )
        self.created.append(kwargs)
        return self.container


class _Docker:
    def __init__(self):
        self.images = _Images()
        self.containers = _Containers()


class _ManagedContainer:
    def __init__(self, labels, start_error=False):
        self.labels = labels
        self.start_error = start_error
        self.started = False
        self.stopped = False
        self.removed = False

    def start(self):
        self.started = True
        if self.start_error:
            raise RuntimeError("start failed")

    def stop(self, **_kwargs):
        self.stopped = True

    def remove(self, **_kwargs):
        self.removed = True


def _image_config():
    return {
        "FunctionName": "notes-worker",
        "FunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:notes-worker",
        "PackageType": "Image",
        "ImageUri": "notes:latest",
        "Timeout": 3,
    }


def _zip_config():
    return {
        "FunctionName": "notes-worker",
        "FunctionArn": "arn:aws:lambda:us-east-1:000000000000:function:notes-worker",
        "PackageType": "Zip",
        "Runtime": "python3.12",
        "Handler": "index.handler",
        "Timeout": 3,
    }


def _zip_code():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("index.py", "def handler(event, context): return event")
    return archive.getvalue()


def test_scoped_lambda_child_has_owned_name_and_labels(monkeypatch):
    docker = _Docker()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(lambda_svc, "_get_docker_client", lambda: docker)

    lambda_svc._spawn_lambda_container(_image_config(), None)

    kwargs = docker.containers.created[0]
    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["labels"] == managed_labels("lambda")
    assert kwargs["ports"] == {"8080/tcp": None}


def test_legacy_lambda_child_keeps_unnamed_docker_contract(monkeypatch):
    docker = _Docker()
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    monkeypatch.setattr(lambda_svc, "_get_docker_client", lambda: docker)

    lambda_svc._spawn_lambda_container(_image_config(), None)

    kwargs = docker.containers.created[0]
    assert "name" not in kwargs
    assert kwargs["labels"] == {"ministack": "lambda"}


@pytest.mark.parametrize(
    ("instance_id", "expected_removed"),
    [("sandbox-a", True), (None, False)],
)
@pytest.mark.parametrize("failure_stage", ["copy", "start"])
def test_lambda_partial_create_cleanup_preserves_legacy_behavior(
    monkeypatch,
    instance_id,
    expected_removed,
    failure_stage,
):
    docker = _Docker()
    docker.containers.start_error = failure_stage == "start"
    if instance_id is None:
        monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    else:
        monkeypatch.setenv("MINISTACK_INSTANCE_ID", instance_id)
    monkeypatch.setattr(lambda_svc, "_get_docker_client", lambda: docker)
    monkeypatch.setattr(lambda_svc, "_running_in_container", lambda: True)
    monkeypatch.setattr(lambda_svc, "LAMBDA_DOCKER_VOLUME_MOUNT", "")
    monkeypatch.setattr(lambda_svc, "LAMBDA_DOCKER_NETWORK", "")
    monkeypatch.setattr(lambda_svc, "LAMBDA_DOCKER_FLAGS", "")

    def _copy(_container, _source, _destination, **_kwargs):
        if failure_stage == "copy":
            raise RuntimeError("copy failed")

    monkeypatch.setattr(lambda_svc, "_docker_cp_dir", _copy)

    with pytest.raises(RuntimeError, match=f"{failure_stage} failed"):
        lambda_svc._spawn_lambda_container(_zip_config(), _zip_code())

    assert docker.containers.container is not None
    assert docker.containers.container.removed is expected_removed


def test_lambda_pool_cleanup_does_not_remove_sibling_container(monkeypatch):
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    sibling = _ManagedContainer(
        {
            "ministack": "lambda",
            "com.ministack.managed": "true",
            "com.ministack.instance": "sandbox-b",
            "com.ministack.scope": "sandbox-b-47a5c68de5",
            "com.ministack.service": "lambda",
        }
    )

    lambda_svc._kill_pool_entry({"container": sibling})

    assert sibling.stopped is False
    assert sibling.removed is False
