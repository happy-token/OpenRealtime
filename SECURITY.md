# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting for this repository:
[github.com/happy-token/OpenRealtime/security/advisories/new](https://github.com/happy-token/OpenRealtime/security/advisories/new).
If that is unavailable, open a regular issue asking a maintainer to open a private channel —
do not include exploit details in that initial issue.

Include as much of the following as you can:

- Affected component/Seam (e.g. Transport Adapter, Endpoint Session, Policy Gateway)
- Steps to reproduce, or a minimal repro
- Impact assessment (what an attacker could do)
- Suggested fix, if you have one

We aim to acknowledge new reports within a few days.

## Scope and known limitations

OpenRealtime is a framework shipped with deterministic, dependency-free defaults and reference
conformers — it is **not** hardened for unauthenticated production exposure out of the box.
Known, already-tracked gaps (not new reports — see [docs/ISSUES.md](docs/ISSUES.md) for detail
and status):

- The data-plane WebSocket/UDP transports accept any connection by default; the control plane is
  deliberately loopback-only and unauthenticated
  ([ISSUE-0020](docs/ISSUES.md#issue-0020-the-data-plane-has-no-authentication)).
- There is no tenant/identity authentication across Endpoint/Agent/Device sessions by default
  ([ISSUE-0016](docs/ISSUES.md#issue-0016-no-identity-or-tenancy-model-across-the-three-session-abstractions)).
- Transport has no codec/heartbeat/backpressure hardening for a hostile network
  ([ISSUE-0019](docs/ISSUES.md#issue-0019-transport-is-not-deployable-over-a-real-network)).

If you find a *new* vulnerability distinct from these tracked items, please report it privately
as above rather than filing a public issue.

## Supported versions

This project is pre-1.0 and does not yet maintain parallel supported release branches; security
fixes land on `main`. See [docs/VERSIONING.md](docs/VERSIONING.md) for the versioning policy.
