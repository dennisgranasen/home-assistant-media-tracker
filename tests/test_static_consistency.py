"""Static regression checks for coordinator and award interfaces."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _class(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def test_coordinator_private_calls_and_keywords_resolve() -> None:
    coordinator = _class(
        ROOT / "custom_components/media_watch/coordinator.py",
        "MediaWatchCoordinator",
    )
    methods = {
        node.name: node
        for node in coordinator.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    missing: list[tuple[int, str]] = []
    invalid_keywords: list[tuple[int, str, str]] = []
    for call in (
        node for node in ast.walk(coordinator) if isinstance(node, ast.Call)
    ):
        func = call.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
            and func.attr.startswith("_")
        ):
            continue

        target = methods.get(func.attr)
        if target is None:
            missing.append((call.lineno, func.attr))
            continue

        accepted = {
            arg.arg
            for arg in (
                *target.args.posonlyargs,
                *target.args.args,
                *target.args.kwonlyargs,
            )
        }
        if target.args.kwarg is None:
            invalid_keywords.extend(
                (call.lineno, func.attr, keyword.arg)
                for keyword in call.keywords
                if keyword.arg is not None and keyword.arg not in accepted
            )

    assert missing == []
    assert invalid_keywords == []


def test_sensor_private_module_calls_resolve() -> None:
    path = ROOT / "custom_components/media_watch/sensor.py"
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = [
        (call.lineno, call.func.id)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id.startswith("_")
        and call.func.id not in functions
    ]

    assert missing == []


def test_all_registered_award_adapters_implement_interface() -> None:
    adapter_dir = ROOT / "custom_components/media_watch/award_adapters"
    classes: dict[str, ast.ClassDef] = {}
    for path in adapter_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes.update(
            {
                node.name: node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
            }
        )

    registry_path = ROOT / "custom_components/media_watch/award_registry.py"
    registry = ast.parse(
        registry_path.read_text(encoding="utf-8"),
        filename=str(registry_path),
    )
    comprehension = next(
        node for node in ast.walk(registry) if isinstance(node, ast.DictComp)
    )
    registered = [
        item.id
        for item in comprehension.generators[0].iter.elts
        if isinstance(item, ast.Name)
    ]

    def methods_for(class_name: str) -> dict[str, ast.AST]:
        cls = classes[class_name]
        methods: dict[str, ast.AST] = {}
        for base in cls.bases:
            if isinstance(base, ast.Name) and base.id in classes:
                methods.update(methods_for(base.id))
        methods.update(
            {
                node.name: node
                for node in cls.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        )
        return methods

    expected = {
        "async_categories": ["self", "media_type"],
        "async_latest_award_year": ["self", "media_type"],
        "async_filter_titles": [
            "self",
            "media_type",
            "year_from",
            "year_to",
            "category",
            "status",
        ],
    }
    errors: list[str] = []
    for class_name in registered:
        methods = methods_for(class_name)
        for method_name, wanted in expected.items():
            method = methods.get(method_name)
            if method is None:
                errors.append(f"{class_name} is missing {method_name}")
                continue
            actual = [
                arg.arg
                for arg in (
                    *method.args.posonlyargs,
                    *method.args.args,
                    *method.args.kwonlyargs,
                )
            ]
            if actual != wanted:
                errors.append(
                    f"{class_name}.{method_name}: {actual!r} != {wanted!r}"
                )

    assert len(registered) == 9
    assert errors == []


def test_config_profile_fields_match_coordinator_expectations() -> None:
    config = _class(
        ROOT / "custom_components/media_watch/config_flow.py",
        "MediaWatchOptionsFlow",
    )
    coordinator = _class(
        ROOT / "custom_components/media_watch/coordinator.py",
        "MediaWatchCoordinator",
    )
    current_fields = {
        "id",
        "name",
        "media_type",
        "source",
        "award_source",
        "award_preset",
        "award_category",
        "award_status",
        "award_year_from",
        "award_year_to",
        "provider_scope",
        "min_rating",
        "min_votes",
        "include_genres",
        "exclude_genres",
        "genre_match",
        "release_year_from",
        "release_year_to",
        "release_max_age_years",
        "sort_by",
        "max_pages",
        "limit",
    }
    recognized_fields = current_fields | {
        "award_filter",
        "release_date_gte",
        "release_date_lte",
    }

    config_constants = {
        node.value
        for node in ast.walk(config)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    coordinator_get_fields = {
        call.args[0].value
        for call in ast.walk(coordinator)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "profile"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }

    assert current_fields <= config_constants
    assert coordinator_get_fields == recognized_fields


def test_optional_profile_years_use_number_selectors() -> None:
    config = _class(
        ROOT / "custom_components/media_watch/config_flow.py",
        "MediaWatchOptionsFlow",
    )
    expected_fields = {
        "award_year_from",
        "award_year_to",
        "release_year_from",
        "release_year_to",
        "release_max_age_years",
    }
    selectors: dict[str, str] = {}

    for mapping in (
        node for node in ast.walk(config) if isinstance(node, ast.Dict)
    ):
        for key, value in zip(mapping.keys, mapping.values, strict=True):
            if key is None or not isinstance(value, ast.Call):
                continue
            fields = {
                node.value
                for node in ast.walk(key)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in expected_fields
            }
            if not fields:
                continue
            if isinstance(value.func, ast.Name):
                for field in fields:
                    selectors[field] = value.func.id

    assert selectors == {
        field: "NumberSelector" for field in expected_fields
    }


def test_new_entries_do_not_store_global_discovery_defaults() -> None:
    source = (
        ROOT / "custom_components/media_watch/config_flow.py"
    ).read_text(encoding="utf-8")

    assert "CONF_MIN_RATING" not in source
    assert "CONF_MIN_VOTES" not in source
    assert "CONF_DISCOVERY_LIMIT" not in source
