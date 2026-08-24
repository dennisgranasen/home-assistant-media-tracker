"""Fail if hass.services.async_register has an invalid positional-argument count."""

from __future__ import annotations

import ast
from pathlib import Path

path = Path("custom_components/media_watch/__init__.py")
tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

errors: list[str] = []

for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue

    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "async_register":
        continue

    owner = func.value
    if (
        not isinstance(owner, ast.Attribute)
        or owner.attr != "services"
        or not isinstance(owner.value, ast.Name)
        or owner.value.id != "hass"
    ):
        continue

    # ServiceRegistry.async_register(domain, service, service_func, ...).
    # Everything after service_func should be passed by keyword in this repo.
    if len(node.args) != 3:
        errors.append(
            f"Line {node.lineno}: async_register has "
            f"{len(node.args)} positional arguments; expected exactly 3"
        )

if errors:
    raise SystemExit("\n".join(errors))

print("Service registrations OK")
