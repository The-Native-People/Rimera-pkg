# Build recipes

Most packages should need no Rimera recipe. Forge first attempts a generic `cibuildwheel` build from the exact PyPI sdist.

Add `<normalized-package-name>.toml` only when a package needs a reviewed adjustment.

Supported keys:

```toml
[build]
before-build = ""
test-command = ""
environment = ""
skip = ""

[platform.macos-arm64]
before-build = "brew install something"
```

Platform values override the corresponding `[build]` value. Supported platform names are `linux-x86_64`, `linux-arm64`, `macos-arm64`, and `windows-x86_64`.

Recipes execute inside the **untrusted build job**, never the privileged publisher.
