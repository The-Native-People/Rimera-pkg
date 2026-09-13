from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any, Callable

from packaging.utils import parse_wheel_filename
from packaging.version import Version

PYPI_BASE = "https://pypi.org"
SIMPLE_ACCEPT = "application/vnd.pypi.simple.v1+json"
USER_AGENT = "Rimera-Forge/0.1 (+https://github.com/The-Native-People/Rimera-pkg)"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_WHEEL_MEMBERS = 100_000


class ForgeError(RuntimeError):
    """A user-facing Forge validation or resolution error."""


JsonFetcher = Callable[[str, str | None], dict[str, Any]]


def normalize_name(name: str) -> str:
    value = re.sub(r"[-_.]+", "-", name.strip()).lower()
    if not value or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", value):
        raise ForgeError(f"Invalid Python project name: {name!r}")
    return value


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def fetch_json(url: str, accept: str | None = None) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(_request(url, accept), timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ForgeError(f"Could not fetch JSON from {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ForgeError(f"Expected a JSON object from {url}")
    return payload


def resolve_release(
    package: str,
    version: str | None = None,
    *,
    fetcher: JsonFetcher = fetch_json,
) -> dict[str, Any]:
    normalized = normalize_name(package)
    if version is None:
        latest = fetcher(f"{PYPI_BASE}/pypi/{urllib.parse.quote(normalized)}/json", None)
        info = latest.get("info") or {}
        version = str(info.get("version") or "").strip()
        if not version:
            raise ForgeError(f"PyPI did not report a current version for {normalized}")

    exact_url = (
        f"{PYPI_BASE}/pypi/{urllib.parse.quote(normalized)}/"
        f"{urllib.parse.quote(version)}/json"
    )
    payload = fetcher(exact_url, None)
    info = payload.get("info") or {}
    reported_name = str(info.get("name") or normalized)
    reported_version = str(info.get("version") or version)
    if normalize_name(reported_name) != normalized:
        raise ForgeError(
            f"PyPI returned project {reported_name!r} while resolving {normalized!r}"
        )
    if Version(reported_version) != Version(version):
        raise ForgeError(
            f"PyPI returned version {reported_version!r} while resolving {version!r}"
        )

    files = payload.get("urls") or []
    if not isinstance(files, list):
        raise ForgeError("PyPI release JSON contained an invalid urls field")

    sdists = [entry for entry in files if entry.get("packagetype") == "sdist"]
    if not sdists:
        raise ForgeError(f"{normalized}=={version} has no source distribution on PyPI")
    sdists.sort(
        key=lambda entry: (
            0 if str(entry.get("filename", "")).endswith(".tar.gz") else 1,
            str(entry.get("filename", "")),
        )
    )
    sdist = _file_record(sdists[0])
    if not sdist["sha256"]:
        raise ForgeError(f"PyPI did not provide SHA-256 for {sdist['filename']}")

    upstream_wheels = [
        _file_record(entry)
        for entry in files
        if entry.get("packagetype") == "bdist_wheel"
    ]

    return {
        "schema": 1,
        "package": {"name": reported_name, "normalized": normalized},
        "version": reported_version,
        "requires_python": info.get("requires_python"),
        "project_urls": info.get("project_urls") or {},
        "source": sdist,
        "upstream_wheels": upstream_wheels,
        "pypi_json_url": exact_url,
    }


def _file_record(entry: dict[str, Any]) -> dict[str, Any]:
    digests = entry.get("digests") or {}
    return {
        "filename": entry.get("filename"),
        "url": entry.get("url"),
        "sha256": digests.get("sha256"),
        "size": entry.get("size"),
        "upload_time": entry.get("upload_time_iso_8601"),
        "requires_python": entry.get("requires_python"),
        "yanked": bool(entry.get("yanked", False)),
        "yanked_reason": entry.get("yanked_reason"),
    }


def fetch_simple_project(
    package: str, *, fetcher: JsonFetcher = fetch_json
) -> dict[str, Any]:
    normalized = normalize_name(package)
    return fetcher(
        f"{PYPI_BASE}/simple/{urllib.parse.quote(normalized)}/", SIMPLE_ACCEPT
    )


def download_verified(url: str, expected_sha256: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    try:
        with os.fdopen(tmp_fd, "wb") as output:
            try:
                with urllib.request.urlopen(_request(url), timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
            except urllib.error.URLError as exc:
                raise ForgeError(f"Could not download {url}: {exc}") from exc
        actual = digest.hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise ForgeError(
                f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}"
            )
        os.replace(tmp_name, destination)
        return actual
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_wheel(path: Path, expected_name: str, expected_version: str) -> dict[str, Any]:
    try:
        parsed_name, parsed_version, build, tags = parse_wheel_filename(path.name)
    except Exception as exc:
        raise ForgeError(f"Invalid wheel filename {path.name!r}: {exc}") from exc

    normalized = normalize_name(expected_name)
    if str(parsed_name) != normalized:
        raise ForgeError(
            f"Wheel filename name mismatch: expected {normalized}, got {parsed_name}"
        )
    if parsed_version != Version(expected_version):
        raise ForgeError(
            f"Wheel filename version mismatch: expected {expected_version}, got {parsed_version}"
        )

    try:
        with zipfile.ZipFile(path) as wheel:
            members = wheel.infolist()
            if len(members) > MAX_WHEEL_MEMBERS:
                raise ForgeError(f"Wheel {path.name} contains too many archive members")
            metadata_members = [
                item for item in members if item.filename.endswith(".dist-info/METADATA")
            ]
            if len(metadata_members) != 1:
                raise ForgeError(
                    f"Wheel {path.name} must contain exactly one .dist-info/METADATA"
                )
            metadata_info = metadata_members[0]
            if metadata_info.file_size > MAX_METADATA_BYTES:
                raise ForgeError(f"Wheel {path.name} contains oversized Core Metadata")
            metadata = BytesParser(policy=email_policy).parsebytes(
                wheel.read(metadata_info)
            )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ForgeError(f"Could not inspect wheel {path.name}: {exc}") from exc

    metadata_name = metadata.get("Name")
    metadata_version = metadata.get("Version")
    if not metadata_name or normalize_name(metadata_name) != normalized:
        raise ForgeError(
            f"Wheel Core Metadata name mismatch: expected {normalized}, got {metadata_name!r}"
        )
    if not metadata_version or Version(metadata_version) != Version(expected_version):
        raise ForgeError(
            f"Wheel Core Metadata version mismatch: expected {expected_version}, got {metadata_version!r}"
        )

    return {
        "filename": path.name,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "build_tag": list(build) if build else None,
        "tags": sorted(str(tag) for tag in tags),
        "requires_python": metadata.get("Requires-Python"),
    }


def collect_validated_wheels(
    root: Path, expected_name: str, expected_version: str
) -> list[tuple[Path, dict[str, Any]]]:
    discovered = sorted(root.rglob("*.whl"))
    if not discovered:
        raise ForgeError(f"No wheel files found under {root}")

    by_filename: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in discovered:
        record = validate_wheel(path, expected_name, expected_version)
        current = by_filename.get(path.name)
        if current and current[1]["sha256"] != record["sha256"]:
            raise ForgeError(
                f"Two targets produced {path.name} with different SHA-256 digests"
            )
        by_filename[path.name] = (path, record)
    return [by_filename[name] for name in sorted(by_filename)]


def release_tag_for(package: str, version: str) -> str:
    normalized = normalize_name(package)
    digest = hashlib.sha256(f"{normalized}\0{version}".encode()).hexdigest()[:12]
    return f"rimera-{normalized}-{digest}"


def registry_version_key(version: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", version).strip("-.")
    if not safe:
        safe = hashlib.sha256(version.encode()).hexdigest()[:16]
    return safe


def prepare_publication(
    *,
    package: str,
    version: str,
    wheels_root: Path,
    output_dir: Path,
    registry_root: Path,
    repository: str,
    release_tag: str | None = None,
    fetcher: JsonFetcher = fetch_json,
) -> tuple[dict[str, Any], Path]:
    plan = resolve_release(package, version, fetcher=fetcher)
    normalized = plan["package"]["normalized"]
    release_tag = release_tag or release_tag_for(normalized, version)
    validated = collect_validated_wheels(wheels_root, normalized, version)

    record_path = registry_root / normalized / f"{registry_version_key(version)}.json"
    existing: dict[str, Any] = {}
    if record_path.exists():
        existing = json.loads(record_path.read_text())

    wheel_map: dict[str, dict[str, Any]] = {
        item["filename"]: item for item in existing.get("wheels", [])
    }
    output_wheels = output_dir / "wheels"
    output_wheels.mkdir(parents=True, exist_ok=True)
    quoted_tag = urllib.parse.quote(release_tag, safe="")
    for path, details in validated:
        target = output_wheels / path.name
        shutil.copy2(path, target)
        details = dict(details)
        details["url"] = (
            f"https://github.com/{repository}/releases/download/{quoted_tag}/"
            f"{urllib.parse.quote(path.name, safe='')}"
        )
        details["origin"] = "rimera-forge"
        wheel_map[path.name] = details

    record = {
        "schema": 1,
        "package": plan["package"],
        "version": plan["version"],
        "release_tag": release_tag,
        "source": plan["source"],
        "upstream_wheel_count": len(plan["upstream_wheels"]),
        "wheels": [wheel_map[name] for name in sorted(wheel_map)],
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "release-manifest.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    notes = (
        f"Rimera Forge wheel build for `{normalized}=={version}`.\n\n"
        f"Source: `{plan['source']['filename']}`  \n"
        f"Source SHA-256: `{plan['source']['sha256']}`\n\n"
        "These are Rimera-generated wheels, not upstream maintainer uploads. "
        "See `release-manifest.json` and GitHub artifact attestations for provenance.\n"
    )
    (output_dir / "release-notes.md").write_text(notes)
    return record, record_path


def python_selector(version: str) -> str:
    if not re.fullmatch(r"3\.\d{1,2}", version):
        raise ForgeError("Forge currently accepts CPython versions like 3.12, 3.13, or 3.14")
    major, minor = version.split(".")
    return f"cp{major}{minor}"


TARGETS: dict[str, dict[str, str]] = {
    "linux-x86_64": {
        "target": "linux-x86_64",
        "runner": "ubuntu-24.04",
        "platform": "linux",
        "arch": "x86_64",
    },
    "linux-arm64": {
        "target": "linux-arm64",
        "runner": "ubuntu-24.04-arm",
        "platform": "linux",
        "arch": "aarch64",
    },
    "macos-arm64": {
        "target": "macos-arm64",
        "runner": "macos-15",
        "platform": "macos",
        "arch": "arm64",
    },
    "windows-x86_64": {
        "target": "windows-x86_64",
        "runner": "windows-2025",
        "platform": "windows",
        "arch": "AMD64",
    },
}


def target_matrix(target: str) -> dict[str, list[dict[str, str]]]:
    if target == "all":
        selected = [TARGETS[name] for name in TARGETS]
    elif target in TARGETS:
        selected = [TARGETS[target]]
    else:
        raise ForgeError(f"Unknown Forge target: {target}")
    return {"include": selected}
