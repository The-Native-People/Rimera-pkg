# Rimera Forge security model

## Trust boundaries

The following inputs are untrusted:

- every PyPI source distribution and wheel
- build-system dependencies fetched by an upstream project
- arbitrary commands declared by upstream build backends
- generated wheel bytes and filenames until the privileged validation job accepts them

The following inputs are reviewed/trusted within the Rimera project:

- this repository's workflow definitions
- Rimera Forge validation code
- files under `recipes/`

## Required invariants

1. A Forge build starts from an exact PyPI release and verifies the advertised SHA-256 of the selected sdist before executing package build code.
2. The build job has `contents: read`, receives no repository secret, and checkout uses `persist-credentials: false`.
3. Package-controlled code never runs in the job that has release/push permissions.
4. The publish job uses a fresh checkout and validates a wheel without importing it or extracting its contents to the filesystem.
5. A wheel's normalized `Name` and PEP 440 `Version` in its embedded Core Metadata must match the requested PyPI release.
6. If two build targets produce the same wheel filename with different SHA-256 digests, publication stops instead of choosing one silently.
7. Rimera-generated files are labelled as Rimera builds. They are not represented as maintainer-published PyPI wheels.
8. An upstream wheel is preferred when PyPI later publishes an equivalent compatible file.

## What an attestation means

Rimera uses GitHub artifact attestations for generated wheels. This gives a cryptographically verifiable statement connecting an artifact to a GitHub repository/workflow and digest.

It does **not** prove the upstream source is benign, vulnerability-free, or worthy of trust. Rimera's package-policy/security layer is a separate concern.

## Current MVP limitations

- GitHub-hosted runners are ephemeral but are not a malware sandbox. A malicious build can use the build job's network and compute resources while that job is running.
- Generic builds will fail for packages that need unavailable system libraries or unusual build steps. Reviewed recipes are the escape hatch.
- Forge does not yet scan source for malware or query OSV before publication.
- Forge does not yet prove reproducible builds by comparing independent builders.
- A successful wheel build proves buildability, not runtime correctness. Package-specific smoke tests can be added in recipes.

Security issues should be reported privately to the repository maintainers rather than filed with exploit details in a public issue.
