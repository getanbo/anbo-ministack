from ministack.core.docker_scope import managed_labels
from ministack.services import glue


class FakeContainer:
    def __init__(self, labels):
        self.id = "glue-container"
        self.labels = labels
        self.started = False
        self.stopped = False
        self.removed = False

    def put_archive(self, _path, _data):
        return True

    def start(self):
        self.started = True

    def wait(self, **_kwargs):
        return {"StatusCode": 0}

    def logs(self, **_kwargs):
        return b"ok"

    def stop(self, **_kwargs):
        self.stopped = True

    def remove(self, **_kwargs):
        self.removed = True


class FakeContainers:
    def __init__(self):
        self.created = []

    def get(self, _name):
        raise RuntimeError("not found")

    def create(self, **kwargs):
        container = FakeContainer(kwargs["labels"])
        self.created.append((kwargs, container))
        return container


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()


def _run():
    return {
        "Id": "01234567-89ab-cdef-0123-456789abcdef",
        "JobRunState": "RUNNING",
        "ErrorMessage": "",
    }


def _job():
    return {
        "GlueVersion": "4.0",
        "Timeout": 1,
    }


def test_scoped_glue_run_has_owned_name_and_is_not_orphaned(
    monkeypatch,
    tmp_path,
):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    docker = FakeDocker()
    run = _run()
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(glue, "DOCKER_NETWORK", "")
    monkeypatch.setattr(glue, "_ministack_network", "")

    glue._execute_spark_docker(
        run,
        _job(),
        "notes-job",
        {},
        str(script),
        docker,
    )

    kwargs, container = docker.containers.created[0]
    assert kwargs["name"].startswith("ministack-sandbox-a-")
    assert kwargs["labels"] == managed_labels(
        "glue",
        {"ministack": "glue", "job_name": "notes-job"},
    )
    assert container.started is True
    assert container.removed is True
    assert run["JobRunState"] == "SUCCEEDED"


def test_legacy_glue_keeps_upstream_name_and_labels(monkeypatch, tmp_path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    docker = FakeDocker()
    run = _run()
    monkeypatch.delenv("MINISTACK_INSTANCE_ID", raising=False)
    monkeypatch.setattr(glue, "DOCKER_NETWORK", "")
    monkeypatch.setattr(glue, "_ministack_network", "")

    glue._execute_spark_docker(
        run,
        _job(),
        "notes-job",
        {},
        str(script),
        docker,
    )

    kwargs, _container = docker.containers.created[0]
    assert kwargs["name"] == "ministack-glue-notes-job-01234567"
    assert kwargs["labels"] == {
        "ministack": "glue",
        "job_name": "notes-job",
    }
