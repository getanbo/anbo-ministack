import pytest

from ministack.services import elasticache, glue, mwaa


@pytest.mark.parametrize(
    ("module", "store_name", "record"),
    [
        (elasticache, "_clusters", {}),
        (glue, "_databases", {}),
        (mwaa, "_environments", {"_host_port": None}),
    ],
)
def test_scoped_reset_clears_state_when_docker_listing_fails(
    monkeypatch,
    module,
    store_name,
    record,
):
    monkeypatch.setenv("MINISTACK_INSTANCE_ID", "sandbox-a")
    monkeypatch.setattr(module, "_get_docker", lambda: object())

    def _raise_listing_error(*_args, **_kwargs):
        raise RuntimeError("daemon unavailable")

    monkeypatch.setattr(module, "owned_containers", _raise_listing_error)
    store = getattr(module, store_name)
    store["listing-failure"] = dict(record)

    module.reset()

    assert "listing-failure" not in store
