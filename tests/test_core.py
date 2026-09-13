from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from rimera_forge.core import (
    ForgeError,
    collect_validated_wheels,
    download_verified,
    normalize_name,
    prepare_publication,
    python_selector,
    release_tag_for,
    resolve_release,
    target_matrix,
    validate_wheel,
)


def release_payload() -> dict:
    return {
        "info": {
            "name": "Demo.Pkg",
            "version": "1.2.3",
            "requires_python": ">=3.10",
            "project_urls": {"Source": "https://example.invalid/source"},
        },
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "filename": "demo_pkg-1.2.3-py3-none-any.whl",
                "url": "https://files.invalid/demo.whl",
                "digests": {"sha256": "b" * 64},
                "size": 12,
            },
            {
                "packagetype": "sdist",
                "filename": "demo_pkg-1.2.3.zip",
                "url": "https://files.invalid/demo.zip",
                "digests": {"sha256": "c" * 64},
                "size": 13,
            },
            {
                "packagetype": "sdist",
                "filename": "demo_pkg-1.2.3.tar.gz",
                "url": "https://files.invalid/demo.tar.gz",
                "digests": {"sha256": "a" * 64},
                "size": 14,
                "upload_time_iso_8601": "2026-01-01T00:00:00Z",
            },
        ],
    }


def make_wheel(path: Path, name: str = "Demo-Pkg", version: str = "1.2.3") -> None:
    metadata = (
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
        "Requires-Python: >=3.10\n\n"
    )
    with zipfile.ZipFile(path, "w") as wheel:
        wheel.writestr("demo_pkg-1.2.3.dist-info/METADATA", metadata)
        wheel.writestr(
            "demo_pkg-1.2.3.dist-info/WHEEL",
            "Wheel-Version: 1.0\nTag: py3-none-any\n",
        )


class CoreTests(unittest.TestCase):
    def test_normalize_name(self) -> None:
        self.assertEqual(normalize_name("Some_Pkg.Name"), "some-pkg-name")
        with self.assertRaises(ForgeError):
            normalize_name("not a package!")

    def test_release_resolution_prefers_tar_gz_sdist(self) -> None:
        payload = release_payload()

        def fetcher(url: str, accept: str | None = None) -> dict:
            self.assertIn("demo-pkg/1.2.3/json", url)
            return payload

        plan = resolve_release("Demo_Pkg", "1.2.3", fetcher=fetcher)
        self.assertEqual(plan["package"]["normalized"], "demo-pkg")
        self.assertEqual(plan["source"]["filename"], "demo_pkg-1.2.3.tar.gz")
        self.assertEqual(plan["source"]["sha256"], "a" * 64)
        self.assertEqual(len(plan["upstream_wheels"]), 1)

    def test_verified_download_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            source.write_bytes(b"exact source bytes")
            good_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = root / "download.bin"
            self.assertEqual(
                download_verified(source.as_uri(), good_hash, destination), good_hash
            )
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            with self.assertRaises(ForgeError):
                download_verified(source.as_uri(), "0" * 64, root / "bad.bin")
            self.assertFalse((root / "bad.bin").exists())

    def test_wheel_validation_checks_embedded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "demo_pkg-1.2.3-py3-none-any.whl"
            make_wheel(wheel)
            result = validate_wheel(wheel, "demo-pkg", "1.2.3")
            self.assertEqual(result["filename"], wheel.name)
            self.assertEqual(
                result["sha256"], hashlib.sha256(wheel.read_bytes()).hexdigest()
            )
            self.assertEqual(result["requires_python"], ">=3.10")

            make_wheel(wheel, name="Other")
            with self.assertRaises(ForgeError):
                validate_wheel(wheel, "demo-pkg", "1.2.3")

    def test_duplicate_filename_with_different_bytes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            name = "demo_pkg-1.2.3-py3-none-any.whl"
            make_wheel(left / name)
            make_wheel(right / name)
            with zipfile.ZipFile(right / name, "a") as wheel:
                wheel.writestr("different.txt", "different bytes")
            with self.assertRaises(ForgeError):
                collect_validated_wheels(root, "demo-pkg", "1.2.3")

    def test_publication_record_uses_release_assets(self) -> None:
        payload = release_payload()

        def fetcher(url: str, accept: str | None = None) -> dict:
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheels = root / "incoming"
            wheels.mkdir()
            make_wheel(wheels / "demo_pkg-1.2.3-py3-none-any.whl")
            record, record_path = prepare_publication(
                package="demo-pkg",
                version="1.2.3",
                wheels_root=wheels,
                output_dir=root / "publication",
                registry_root=root / "registry",
                repository="The-Native-People/Rimera-pkg",
                fetcher=fetcher,
            )
            self.assertTrue(record_path.exists())
            self.assertEqual(record["source"]["sha256"], "a" * 64)
            self.assertIn(
                "github.com/The-Native-People/Rimera-pkg/releases/download/",
                record["wheels"][0]["url"],
            )
            self.assertEqual(json.loads(record_path.read_text())["version"], "1.2.3")

    def test_ci_target_helpers(self) -> None:
        self.assertEqual(python_selector("3.13"), "cp313")
        self.assertEqual(len(target_matrix("all")["include"]), 4)
        self.assertEqual(
            target_matrix("macos-arm64")["include"][0]["arch"], "arm64"
        )
        self.assertEqual(
            release_tag_for("Demo_Pkg", "1.2.3"),
            release_tag_for("demo-pkg", "1.2.3"),
        )


if __name__ == "__main__":
    unittest.main()
