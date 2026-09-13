from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rimera_forge.core import ForgeError
from rimera_forge.recipes import load_recipe


class RecipeTests(unittest.TestCase):
    def test_platform_recipe_overrides_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "demo-pkg.toml").write_text(
                '[build]\n'
                'before-build = "base"\n'
                'test-command = "python -c test"\n'
                '\n[platform.macos-arm64]\n'
                'before-build = "mac"\n'
            )
            recipe = load_recipe(root, "Demo_Pkg", "macos-arm64")
            self.assertEqual(recipe["before-build"], "mac")
            self.assertEqual(recipe["test-command"], "python -c test")

    def test_unknown_recipe_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "demo.toml").write_text('[build]\nsecret-command = "nope"\n')
            with self.assertRaises(ForgeError):
                load_recipe(root, "demo", "linux-x86_64")


if __name__ == "__main__":
    unittest.main()
