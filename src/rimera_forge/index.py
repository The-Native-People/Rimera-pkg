from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any, Callable

from .core import ForgeError, fetch_simple_project, normalize_name

SimpleFetcher = Callable[[str], dict[str, Any]]


def load_registry(registry_root: Path) -> dict[str, list[dict[str, Any]]]:
    packages: dict[str, list[dict[str, Any]]] = {}
    if not registry_root.exists():
        return packages
    for path in sorted(registry_root.glob("*/*.json")):
        record = json.loads(path.read_text())
        normalized = normalize_name(record["package"]["normalized"])
        packages.setdefault(normalized, []).append(record)
    return packages


def render_project_html(
    package: str,
    upstream: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    normalized = normalize_name(package)
    upstream_files = upstream.get("files") or []
    if not isinstance(upstream_files, list):
        raise ForgeError(f"Invalid Simple API file list for {normalized}")
    upstream_names = {str(item.get("filename")) for item in upstream_files}

    links: list[str] = []
    for item in upstream_files:
        links.append(_render_upstream_link(item))

    for record in records:
        for wheel in record.get("wheels", []):
            if wheel["filename"] in upstream_names:
                # Upstream wins automatically if the maintainer later publishes the file.
                continue
            attrs = {
                "href": f"{wheel['url']}#sha256={wheel['sha256']}",
                "data-rimera-build": "true",
            }
            if wheel.get("requires_python"):
                attrs["data-requires-python"] = wheel["requires_python"]
            links.append(_anchor(wheel["filename"], attrs))

    links.sort()
    body = "\n".join(f"    {link}" for link in links)
    return (
        "<!doctype html>\n"
        '<html><head><meta name="pypi:repository-version" content="1.3"></head><body>\n'
        f"{body}\n"
        "</body></html>\n"
    )


def _render_upstream_link(item: dict[str, Any]) -> str:
    filename = str(item.get("filename") or "")
    url = str(item.get("url") or "")
    if not filename or not url:
        raise ForgeError("PyPI Simple API returned a file without filename/url")
    hashes = item.get("hashes") or {}
    sha = hashes.get("sha256") if isinstance(hashes, dict) else None
    if sha:
        url = f"{url}#sha256={sha}"
    attrs: dict[str, str] = {"href": url}
    requires_python = item.get("requires-python")
    if requires_python:
        attrs["data-requires-python"] = str(requires_python)
    yanked = item.get("yanked")
    if yanked:
        attrs["data-yanked"] = "" if yanked is True else str(yanked)
    provenance = item.get("provenance")
    if provenance:
        attrs["data-provenance"] = str(provenance)
    core_metadata = item.get("core-metadata")
    if core_metadata:
        if isinstance(core_metadata, dict):
            if "sha256" in core_metadata:
                attrs["data-core-metadata"] = f"sha256={core_metadata['sha256']}"
        else:
            attrs["data-core-metadata"] = "true"
    return _anchor(filename, attrs)


def _anchor(filename: str, attrs: dict[str, str]) -> str:
    encoded = " ".join(
        f'{html.escape(key, quote=True)}="{html.escape(value, quote=True)}"'
        for key, value in attrs.items()
    )
    return f"<a {encoded}>{html.escape(filename)}</a>"


def build_static_index(
    registry_root: Path,
    output_dir: Path,
    *,
    fetcher: SimpleFetcher | None = None,
) -> list[str]:
    fetcher = fetcher or (lambda name: fetch_simple_project(name))
    packages = load_registry(registry_root)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    simple_root = output_dir / "simple"
    simple_root.mkdir(parents=True, exist_ok=True)
    (output_dir / ".nojekyll").write_text("")

    root_links: list[str] = []
    for normalized in sorted(packages):
        upstream = fetcher(normalized)
        project_dir = simple_root / normalized
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "index.html").write_text(
            render_project_html(normalized, upstream, packages[normalized])
        )
        root_links.append(f'<a href="{html.escape(normalized)}/">{html.escape(normalized)}</a>')

    root_body = "\n".join(f"    {link}" for link in root_links)
    (simple_root / "index.html").write_text(
        "<!doctype html>\n"
        '<html><head><meta name="pypi:repository-version" content="1.3"></head><body>\n'
        f"{root_body}\n"
        "</body></html>\n"
    )
    return sorted(packages)
