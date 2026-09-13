# Rimera Package Forge

**Build missing Python wheels once. Verify where they came from. Reuse them everywhere.**

Rimera Forge is the binary-build side of the Rimera package registry. PyPI remains the source of truth. Rimera consumes an exact PyPI release, verifies the source-distribution hash, builds missing wheels on isolated GitHub-hosted runners, validates the result, records provenance, and publishes the generated wheels as GitHub Release assets.

```text
uv / pip
   |
   v
Rimera Registry
   |------------------> official PyPI wheel (preferred)
   |
   `--> missing wheel --> Rimera Forge --> reusable Rimera-built wheel
```

Rimera does **not** replace PyPI and does not rebuild an upstream wheel merely to own a copy. Official compatible wheels win. Forge exists for the annoying case where an installer falls back to an sdist and starts compiling C, C++, Rust, or Fortran on the developer's machine.

## Repository layout

- `src/rimera_forge/` — release resolution, exact-sdist verification, wheel validation, catalog generation, and the CI CLI.
- `.github/workflows/forge.yml` — Forge builds for Linux x86_64, Linux ARM64, macOS ARM64, Windows x86_64, or all four.
- `.github/workflows/pages.yml` — publishes a standards-compatible HTML Simple Repository view.
- `recipes/` — reviewed package-specific build adjustments for packages that cannot be built generically.
- `registry/` — small JSON records for Rimera-produced wheels. Wheel bytes live in GitHub Releases, not Git.

## Security model

Building a Python package executes package-controlled code, so Forge splits a run into two trust zones:

1. **Build job — untrusted.** The exact PyPI sdist is downloaded and SHA-256 verified before it is built. The job gets read-only repository permission, checkout does not persist credentials, and no publishing secret is provided. `cibuildwheel` runs here.
2. **Publish job — privileged but non-executing.** A fresh job downloads the wheel artifacts, re-validates filename/metadata and hashes using trusted Rimera code, creates GitHub artifact attestations, uploads the files to a GitHub Release, and updates only registry JSON. It never imports or executes the generated wheel.

An attestation proves build provenance and integrity; it is **not** a claim that arbitrary upstream code is safe. See [`SECURITY.md`](SECURITY.md).

## Build a wheel

From **Actions → Forge wheel → Run workflow**, provide a package such as `orjson`, an optional exact version, a CPython version such as `3.13`, and a target platform.

The workflow builds from the **PyPI sdist**, not GitHub `main` and not a guessed tag. This keeps `foo==1.2.3` tied to the exact source PyPI published for `1.2.3`.

You can exercise the tooling locally too:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .

rimera-forge resolve requests --version 2.32.5
rimera-forge prepare requests --version 2.32.5 --target macos-arm64 --out .rimera/input
```

## Registry compatibility

Python's Simple Repository API permits distribution files to be hosted somewhere other than the index. Rimera's generated Simple pages merge current upstream PyPI files with Rimera-produced wheels and preserve SHA-256 hashes, `Requires-Python`, yanked state, and upstream provenance links where available.

The static GitHub Pages index is useful as a wheelhouse and compatibility proof. The full Rimera registry service should remain the normal front door because it can content-negotiate the modern JSON Simple API and dynamically merge PyPI with Forge.

`uv` accepts PEP 503-compatible indexes. A development configuration can point at the eventual Rimera endpoint like this:

```toml
[[tool.uv.index]]
name = "rimera"
url = "https://YOUR-RIMERA-HOST/simple"
default = true
```

## $0 MVP rule

The initial architecture intentionally has no required monthly service bill:

- public repository
- standard GitHub-hosted Actions runners
- GitHub Releases for Rimera-created wheel bytes
- GitHub Pages for the public static catalog/index preview
- PyPI remains the origin for official artifacts, so Rimera does not mirror all of PyPI

This is an MVP cost strategy, not a promise that a huge public registry can use free infrastructure forever. Forge is separated from the registry protocol so builders and storage can be swapped later without changing client UX.

## Product direction

The useful promise is not “another PyPI cache.” It is:

> **uv speed without the surprise local compiler.**

Next layers: package trust reports, OSV advisory checks, `rimera warm uv.lock`, reproducibility checks, build-status pages, and an `ensure-wheel` API that the Rimera CLI can call before delegating installation to uv.
