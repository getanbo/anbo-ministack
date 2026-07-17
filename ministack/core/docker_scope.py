"""Ownership helpers for Docker resources created by MiniStack.

The isolation contract is deliberately opt-in.  With
``MINISTACK_INSTANCE_ID`` unset, helpers return the legacy names and labels
unchanged.  When it is set, every managed child resource receives an
instance-specific name and an ownership label set that can be verified before
destructive operations.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from typing import Any

INSTANCE_ID_ENV = "MINISTACK_INSTANCE_ID"
CONTRACT_VERSION = 1

MANAGED_SERVICES = (
    "rds",
    "ecs",
    "elasticache",
    "eks",
    "lambda",
    "opensearch",
    "mwaa",
    "glue",
)

_INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DOCKER_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_DOCKER_NAME_START_RE = re.compile(r"^[A-Za-z0-9]")

_MANAGED_LABEL = "com.ministack.managed"
_INSTANCE_LABEL = "com.ministack.instance"
_SCOPE_LABEL = "com.ministack.scope"
_SERVICE_LABEL = "com.ministack.service"


def instance_id() -> str | None:
    """Return the configured instance ID, validating it when present."""
    if INSTANCE_ID_ENV not in os.environ:
        return None

    value = os.environ[INSTANCE_ID_ENV]
    if not _INSTANCE_ID_RE.fullmatch(value):
        raise ValueError(
            f"{INSTANCE_ID_ENV} must be 1-128 ASCII letters, digits, dots, "
            "underscores, or hyphens, and must start with a letter or digit"
        )
    return value


def isolation_enabled() -> bool:
    """Return whether instance isolation is enabled."""
    return instance_id() is not None


def instance_scope() -> str | None:
    """Return a short, deterministic, Docker-safe scope for the instance."""
    value = instance_id()
    if value is None:
        return None

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = slug[:24].rstrip("-") or "instance"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}"


def _validate_service(service: str) -> str:
    if service not in MANAGED_SERVICES:
        supported = ", ".join(MANAGED_SERVICES)
        raise ValueError(f"Unknown Docker-backed MiniStack service {service!r}; expected one of: {supported}")
    return service


def managed_labels(
    service: str,
    extra: Mapping[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build labels for a MiniStack-managed child container.

    ``extra`` and keyword fields make this usable as a drop-in replacement for
    existing service label dictionaries.  Reserved ownership labels are
    applied last so callers cannot accidentally forge a different owner.
    """
    service = _validate_service(service)
    labels: dict[str, Any] = {"ministack": service}
    if extra:
        labels.update(extra)
    labels.update(fields)
    labels["ministack"] = service

    value = instance_id()
    if value is None:
        return labels

    labels.update(
        {
            _MANAGED_LABEL: "true",
            _INSTANCE_LABEL: value,
            _SCOPE_LABEL: instance_scope(),
            _SERVICE_LABEL: service,
        }
    )
    return labels


def _safe_scoped_name(legacy_name: str, max_length: int) -> str:
    if not isinstance(legacy_name, str) or not legacy_name:
        raise ValueError("Docker resource name must be a non-empty string")

    scope = instance_scope()
    if scope is None:
        return legacy_name

    base = legacy_name[len("ministack-"):] if legacy_name.startswith("ministack-") else legacy_name
    base = _DOCKER_NAME_CHARS_RE.sub("-", base).strip("_.-")
    if not base:
        base = "resource"
    candidate = f"ministack-{scope}-{base}"
    if not _DOCKER_NAME_START_RE.match(candidate):
        candidate = f"ministack-{candidate}"
    if len(candidate) <= max_length:
        return candidate

    digest = hashlib.sha256(legacy_name.encode("utf-8")).hexdigest()[:12]
    head = candidate[: max_length - len(digest) - 1].rstrip("_.-")
    return f"{head}-{digest}"


def scoped_name(legacy_name: str) -> str:
    """Return an instance-scoped container name, or the exact legacy name."""
    return _safe_scoped_name(legacy_name, max_length=128)


def scoped_volume_name(legacy_name: str) -> str:
    """Return an instance-scoped volume name, or the exact legacy name."""
    return _safe_scoped_name(legacy_name, max_length=255)


def published_host_port(container: Any, container_port: int) -> int | None:
    """Return Docker's assigned TCP host port, when one is published."""
    try:
        container.reload()
    except Exception:
        pass

    bindings = getattr(container, "ports", None)
    if not bindings:
        attrs = getattr(container, "attrs", None)
        if isinstance(attrs, Mapping):
            network_settings = attrs.get("NetworkSettings")
            if isinstance(network_settings, Mapping):
                bindings = network_settings.get("Ports")

    if not isinstance(bindings, Mapping):
        return None
    entries = bindings.get(f"{container_port}/tcp") or []
    try:
        return int(entries[0]["HostPort"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def _container_labels(container: Any) -> Mapping[str, Any]:
    labels = getattr(container, "labels", None)
    if isinstance(labels, Mapping):
        return labels

    attrs = getattr(container, "attrs", None)
    if not isinstance(attrs, Mapping):
        return {}
    config = attrs.get("Config")
    if not isinstance(config, Mapping):
        return {}
    labels = config.get("Labels")
    return labels if isinstance(labels, Mapping) else {}


def is_owned(container: Any, service: str | None = None) -> bool:
    """Verify client-side that a container belongs to this MiniStack instance."""
    if service is not None:
        service = _validate_service(service)
    labels = _container_labels(container)

    value = instance_id()
    if value is None:
        if service is not None:
            return labels.get("ministack") == service
        return labels.get("ministack") in MANAGED_SERVICES

    container_service = labels.get(_SERVICE_LABEL)
    if service is not None and container_service != service:
        return False
    if container_service not in MANAGED_SERVICES:
        return False
    return (
        labels.get("ministack") == container_service
        and labels.get(_MANAGED_LABEL) == "true"
        and labels.get(_INSTANCE_LABEL) == value
        and labels.get(_SCOPE_LABEL) == instance_scope()
    )


def owned_containers(client: Any, service: str | None = None, all: bool = True) -> list[Any]:
    """List owned containers and verify every daemon result client-side."""
    if service is not None:
        service = _validate_service(service)

    value = instance_id()
    if value is None:
        label_filter: str | list[str]
        label_filter = f"ministack={service}" if service is not None else "ministack"
    else:
        label_filter = [
            f"{_MANAGED_LABEL}=true",
            f"{_INSTANCE_LABEL}={value}",
        ]
        if service is not None:
            label_filter.append(f"{_SERVICE_LABEL}={service}")

    candidates = client.containers.list(all=all, filters={"label": label_filter})
    return [container for container in candidates if is_owned(container, service)]


def remove_owned(
    container: Any,
    service: str | None = None,
    *,
    stop: bool = True,
    timeout: int = 5,
    remove_volumes: bool = True,
    force: bool = False,
) -> bool:
    """Stop and remove a container only after verifying current ownership."""
    if not is_owned(container, service):
        return False
    if stop:
        container.stop(timeout=timeout)
    container.remove(v=remove_volumes, force=force)
    return True


def contract_metadata() -> dict[str, Any] | None:
    """Return the public instance-isolation contract exposed by health."""
    value = instance_id()
    if value is None:
        return None
    return {
        "contract_version": CONTRACT_VERSION,
        "instance_id": value,
        "scope": instance_scope(),
        "docker_network": os.environ.get("DOCKER_NETWORK", ""),
    }
