from ministack.core.docker_scope import managed_labels
from ministack.services import lambda_svc


class _Images:
    def get(self, _image):
        return True


class _Containers:
    def __init__(self):
        self.created = []

    def run(self, **kwargs):
        self.created.append(kwargs)
        return object()


class _Docker:
    def __init__(self):
        self.images = _Images()
        self.containers = _Containers()


class _ManagedContainer:
    def __init__(self, labels):
        self.labels = labels
        self.stopped = False
        self.removed = False

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
