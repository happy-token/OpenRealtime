# Versioning policy

OpenRealtime follows [Semantic Versioning](https://semver.org/)
(`MAJOR.MINOR.PATCH`). Version `0.2.0` is the first annotated release tag;
`0.3.0` is the first completed M0–M6 Voice Runtime release;
`package.json` and `pyproject.toml` carry the same canonical version.

## Release scope

Each version identifies one tested Git commit and annotated tag. The Python
package is not yet published to PyPI and the web application is not published
to npm; until those distribution channels exist, Git tags and the changelog
are the release authority.

## Pre-1.0 policy (`0.y.z`)

Per SemVer's own rule for initial development, **`0.y.z` carries no
compatibility guarantee** — any Protocol (`AsrEngine`, `TtsEngine`,
`TransportAdapter`, `WebSearch`, `Brain`, etc.) may change shape in any
`0.y.0` bump. This matches where the project actually is: the Seam
Protocols are still being discovered and adjusted increment-by-increment
(see the ADR history), not yet frozen.

- **`0.y.0` (minor)**: a new Seam, plugin interface, or real conformer
  ships (i.e., anything that would earn its own ADR and its own
  `### Added` block in the changelog).
- **`0.y.z` (patch)**: a bug fix or documentation-only change with no new
  Protocol surface.

## Reaching `1.0.0`

`1.0.0` is warranted once the core Seam Protocols — Transport Adapter, Turn
Policy, Speech Seam (`AsrEngine`/`TtsEngine`), Brain/Router, Response
Scheduler — are considered stable enough that a downstream consumer
building against them would not expect breaking changes across a `1.x`
line. Until then, treat every Protocol in [docs/ARCHITECTURE.md](ARCHITECTURE.md)'s
Seam table as provisional.

## Changelog-to-tag workflow

1. Land changes under `CHANGELOG.md`'s `## [Unreleased]` section as they're
   built (already the practice — see [CHANGELOG.md](../CHANGELOG.md)).
2. At release time: rename `## [Unreleased]` to `## [x.y.z] - YYYY-MM-DD`,
   open a fresh empty `## [Unreleased]` above it, bump `pyproject.toml`'s
   `version` to match, commit, and tag (`git tag vx.y.z`).
3. Never edit a released section after the fact except to fix a factual
   error — new work always goes in the next `Unreleased` section.
