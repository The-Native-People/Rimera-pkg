from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rimera_forge.index import build_static_index, render_project_html


UPSTREAM = {
    "meta": {"api-version": "1.4"},
    "name": "demo-pkg",
    "files": [
        {
            "filename": "demo_pkg-1.2.3.tar.gz",
            "url": "https://files.pythonhosted.org/demo.tar.gz",
            "hashes": {"sha256": "a" * 64},
            "requires-python": ">=3.10",
            "yanked": False,
            "provenance": "https://pypi.org/integrity/demo/1.2.3/source/provenance",
        }
    ],
}

RECORD = {
    "schema": 1,
    "package": {"name": "Demo-Pkg", "normalized": "demo-pkg"},
    "version": "1.2.3",
    "release_tag": "rimera-demo-pkg-123",
    "source": {"sha256": "a" * 64},
    "wheels": [
        {
            "filename": "demo_pkg-1.2.3-py3-none-any.whl",
            "sha256": "b" * 64,
            "url": "https://github.com/example/release/demo.whl",
            "requires_python": ">=3.10",
            "origin": "rimera-forge",
        }
    ],
}


class IndexTests(unittest.TestCase):
    def test_project_html_merges_upstream_and_rimera(self) -> None:
        page = render_project_html("demo-pkg", UPSTREAM, [RECORD])
        self.assertIn("files.pythonhosted.org/demo.tar.gz#sha256=", page)
        self.assertIn('data-provenance="https://pypi.org/integrity/', page)
        self.assertIn('data-rimera-build="true"', page)
        self.assertIn("demo_pkg-1.2.3-py3-none-any.whl", page)

    def test_upstream_file_wins_on_identical_filename(self) -> None:
        upstream = dict(UPSTREAM)
        upstream["files"] = list(UPSTREAM["files"]) + [
            {
                "filename": "demo_pkg-1.2.3-py3-none-any.whl",
                "url": "https://files.pythonhosted.org/upstream.whl",
                "hashes": {"sha256": "c" * 64},
            }
        ]
        page = render_project_html("demo-pkg", upstream, [RECORD])
        self.assertIn("upstream.whl", page)
        self.assertNotIn('data-rimera-build="true"', page)

    def test_static_index_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_path = root / "registry" / "demo-pkg" / "1.2.3.json"
            record_path.parent.mkdir(parents=True)
            record_path.write_text(json.dumps(RECORD))
            packages = build_static_index(
                root / "registry",
                root / "site",
                fetcher=lambda package: UPSTREAM,
            )
            self.assertEqual(packages, ["demo-pkg"])
            self.assertTrue((root / "site" / ".nojekyll").exists())
            self.assertIn(
                "demo-pkg/",
                (root / "site" / "simple" / "index.html").read_text(),
            )
            self.assertIn(
                "demo_pkg-1.2.3-py3-none-any.whl",
                (root / "site" / "simple" / "demo-pkg" / "index.html").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
