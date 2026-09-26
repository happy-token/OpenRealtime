# Contributing to OpenRealtime

Thanks for considering a contribution. OpenRealtime is a framework, not an application: most
changes should add or improve a Protocol conformer rather than special-case the core Seams.

## Development setup

The public trial and self-hosted deployment have different credential boundaries; see [the deployment guide](docs/deployment/public-trial.md). Never include a real `.env`, provider token, private portrait, or licensed media in a pull request.

Follow [README.md](README.md)'s Requirements/Setup/Run sections to get the backend (`uv sync`)
and the web demo (`pnpm install && pnpm dev`) running locally. No provider credentials are
required for the deterministic default stack.

## Before opening a pull request

- **Tests.** New behavior needs a test that fails without your change. Prefer an
  interaction-outcome assertion over an FSM-transition-list assertion — see
  [ISSUE-0021](docs/ISSUES.md#issue-0021-the-test-suite-asserts-fsm-traversal-not-interaction-outcomes)
  for why that distinction matters here.
- **Run the full local check set:**
  ```bash
  uv run pytest
  uv run mypy server   # non-blocking in CI today; please still check your own diff
  pnpm lint
  pnpm exec tsc --noEmit
  pnpm test
  ```
- **Architecture decisions.** A change that introduces a new cross-cutting decision (a new
  Seam, a new persistence boundary, a reversed prior decision) should come with a short ADR in
  `docs/adr/` — see existing entries for the expected shape (a title plus 1-3 dense sentences).
- **Known gaps.** Check [docs/ISSUES.md](docs/ISSUES.md) and [ROADMAP.md](ROADMAP.md) first —
  your change may already be scoped, deferred for a stated reason, or an intentional divergence
  rather than an oversight.

## Commit and PR style

- Keep commits scoped to one logical change.
- Describe the *why* in the PR description, not just the diff.
- Link the relevant ADR/Issue/Roadmap entry when one exists.

## Reporting bugs and proposing features

Open a GitHub issue. For anything security-relevant, see [SECURITY.md](SECURITY.md) instead of
filing a public issue.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
