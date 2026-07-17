#!/usr/bin/env python3
"""Guard the downstream Docker-child ownership integration.

The manifest is intentionally outside upstream service modules.  An upstream
release that adds a Docker-backed service or a new container launch path fails
this check until a maintainer reviews and scopes that path, then updates the
small downstream manifest.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github" / "downstream-docker-ownership.json"
DOCKER_SCOPE_MODULE = "ministack.core.docker_scope"
LAUNCH_METHODS = frozenset({"create", "run"})
MANDATORY_HELPERS = frozenset(
    {"is_owned", "isolation_enabled", "managed_labels", "scoped_name"}
)


def _launch_method(node: ast.Call) -> str | None:
    """Return the Docker collection launch method for a call, if any."""
    function = node.func
    if not isinstance(function, ast.Attribute) or function.attr not in LAUNCH_METHODS:
        return None
    collection = function.value
    if not isinstance(collection, ast.Attribute) or collection.attr != "containers":
        return None
    return function.attr


def _docker_scope_imports(tree: ast.AST) -> tuple[dict[str, str], set[str]]:
    """Return direct helper aliases and module aliases."""
    direct: dict[str, str] = {}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == DOCKER_SCOPE_MODULE:
            for name in node.names:
                direct[name.asname or name.name] = name.name
        elif isinstance(node, ast.Import):
            for name in node.names:
                if name.name == DOCKER_SCOPE_MODULE:
                    modules.add(name.asname or name.name)
    return direct, modules


def _called_scope_helpers(
    tree: ast.AST,
    direct: dict[str, str],
    modules: set[str],
) -> tuple[set[str], set[str]]:
    """Return called helper names and literal managed service labels."""
    helpers: set[str] = set()
    managed_services: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        helper = None
        if isinstance(node.func, ast.Name):
            helper = direct.get(node.func.id)
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in modules
        ):
            helper = node.func.attr
        if helper is None:
            continue

        helpers.add(helper)
        if helper != "managed_labels":
            continue
        service_arg: ast.AST | None = node.args[0] if node.args else None
        if service_arg is None:
            service_arg = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "service"),
                None,
            )
        if isinstance(service_arg, ast.Constant) and isinstance(service_arg.value, str):
            managed_services.add(service_arg.value)
    return helpers, managed_services


def _load_policy(root: Path, policy_path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        policy = json.loads(policy_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{policy_path.relative_to(root)} is not valid JSON: {exc}")
        return {}

    if policy.get("schemaVersion") != 1:
        errors.append(f"{policy_path.relative_to(root)} schemaVersion must be 1")
    if not isinstance(policy.get("requiredHelpers"), list):
        errors.append(f"{policy_path.relative_to(root)} requiredHelpers must be a list")
    if not isinstance(policy.get("modules"), dict):
        errors.append(f"{policy_path.relative_to(root)} modules must be an object")
    return policy


def check_repository(root: Path = ROOT) -> list[str]:
    """Return actionable ownership-policy violations for ``root``."""
    errors: list[str] = []
    services_path = root / "ministack" / "services"
    policy_path = root / ".github" / "downstream-docker-ownership.json"
    policy = _load_policy(root, policy_path, errors)
    raw_required_helpers = policy.get("requiredHelpers") or []
    required_helpers = {
        helper for helper in raw_required_helpers if isinstance(helper, str)
    }
    if len(required_helpers) != len(raw_required_helpers):
        errors.append(
            f"{policy_path.relative_to(root)} requiredHelpers entries must be strings"
        )
    omitted_helpers = sorted(MANDATORY_HELPERS - required_helpers)
    if omitted_helpers:
        errors.append(
            f"{policy_path.relative_to(root)} may not omit mandatory helpers: "
            f"{', '.join(omitted_helpers)}"
        )
    configured_modules = policy.get("modules") or {}
    if not isinstance(configured_modules, dict):
        configured_modules = {}

    discovered: dict[str, tuple[Path, ast.Module, list[tuple[int, str]]]] = {}
    for path in sorted(services_path.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (OSError, SyntaxError) as exc:
            errors.append(f"{path.relative_to(root)} could not be parsed: {exc}")
            continue

        launches = [
            (node.lineno, method)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for method in [_launch_method(node)]
            if method is not None
        ]
        if launches:
            discovered[path.stem] = (path, tree, launches)

    new_modules = sorted(set(discovered) - set(configured_modules))
    for module in new_modules:
        path, _, launches = discovered[module]
        locations = ", ".join(f"{method}:{line}" for line, method in launches)
        errors.append(
            f"{path.relative_to(root)} launches Docker children ({locations}) but is not reviewed in "
            f"{policy_path.relative_to(root)}"
        )

    missing_modules = sorted(set(configured_modules) - set(discovered))
    for module in missing_modules:
        errors.append(
            f"{policy_path.relative_to(root)} still lists {module!r}, but that service has no Docker child launch calls"
        )

    for module in sorted(set(discovered) & set(configured_modules)):
        path, tree, launches = discovered[module]
        module_policy = configured_modules[module]
        if not isinstance(module_policy, dict):
            errors.append(f"{policy_path.relative_to(root)} module {module!r} must be an object")
            continue

        expected_service = module_policy.get("service")
        expected_launches = module_policy.get("launchCalls")
        if not isinstance(expected_service, str) or not expected_service:
            errors.append(f"{policy_path.relative_to(root)} module {module!r} requires a service label")
            continue
        if not isinstance(expected_launches, dict):
            errors.append(f"{policy_path.relative_to(root)} module {module!r} requires launchCalls")
            continue

        actual_counts = Counter(method for _, method in launches)
        for method in sorted(LAUNCH_METHODS):
            expected = expected_launches.get(method)
            if not isinstance(expected, int) or expected < 0:
                errors.append(
                    f"{policy_path.relative_to(root)} module {module!r} launchCalls.{method} must be a non-negative integer"
                )
            elif actual_counts[method] != expected:
                locations = ", ".join(
                    str(line) for line, launch_method in launches if launch_method == method
                ) or "none"
                errors.append(
                    f"{path.relative_to(root)} has {actual_counts[method]} containers.{method} calls "
                    f"(lines {locations}); reviewed policy expects {expected}"
                )

        direct, module_aliases = _docker_scope_imports(tree)
        called_helpers, managed_services = _called_scope_helpers(tree, direct, module_aliases)
        missing_helpers = sorted(required_helpers - called_helpers)
        if missing_helpers:
            errors.append(
                f"{path.relative_to(root)} must call docker_scope helpers: {', '.join(missing_helpers)}"
            )
        if expected_service not in managed_services:
            errors.append(
                f"{path.relative_to(root)} must call managed_labels({expected_service!r}, ...)"
            )
        unexpected_services = sorted(managed_services - {expected_service})
        if unexpected_services:
            errors.append(
                f"{path.relative_to(root)} uses unexpected managed_labels services: "
                f"{', '.join(unexpected_services)}"
            )

        for line, method in launches:
            call = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and node.lineno == line
                and _launch_method(node) == method
            )
            keyword_names = {keyword.arg for keyword in call.keywords}
            if None not in keyword_names and not {"labels", "name"}.issubset(keyword_names):
                errors.append(
                    f"{path.relative_to(root)}:{line} containers.{method} must receive name and labels "
                    "or expand reviewed scoped kwargs"
                )

    return errors


def main() -> int:
    errors = check_repository()
    if errors:
        print("Docker ownership policy violations:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    policy = json.loads(POLICY.read_text())
    module_count = len(policy["modules"])
    launch_count = sum(
        sum(module["launchCalls"].values())
        for module in policy["modules"].values()
    )
    print(
        f"Docker ownership policy passed for {module_count} services and "
        f"{launch_count} reviewed launch calls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
