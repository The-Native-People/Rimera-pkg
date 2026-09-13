from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .core import ForgeError, TARGETS, normalize_name

RECIPE_KEYS = {"before-build", "test-command", "environment", "skip"}


def load_recipe(recipes_dir: Path, package: str, target: str) -> dict[str, str]:
    if target not in TARGETS:
        raise ForgeError(f"Unknown recipe target: {target}")
    normalized = normalize_name(package)
    path = recipes_dir / f"{normalized}.toml"
    merged = {key: "" for key in RECIPE_KEYS}
    if not path.exists():
        return merged

    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    build = payload.get("build") or {}
    platform = (payload.get("platform") or {}).get(target) or {}
    _validate_section(path, "build", build)
    _validate_section(path, f"platform.{target}", platform)
    for source in (build, platform):
        for key, value in source.items():
            if not isinstance(value, str):
                raise ForgeError(f"{path}: {key} must be a string")
            merged[key] = value
    return merged


def _validate_section(path: Path, section: str, values: Any) -> None:
    if not isinstance(values, dict):
        raise ForgeError(f"{path}: [{section}] must be a table")
    unknown = set(values) - RECIPE_KEYS
    if unknown:
        raise ForgeError(f"{path}: unsupported keys in [{section}]: {sorted(unknown)}")
