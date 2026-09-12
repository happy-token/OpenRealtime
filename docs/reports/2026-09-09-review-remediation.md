# Review remediation — 2026-09-09

This report describes the follow-up to commit `2ff4984`. Existing uncommitted
Avatar motion work was preserved; changes here are still local pending review.

| Finding | Resolution | Evidence |
| --- | --- | --- |
| Multi-process file catalog updates can overwrite one another | Exclusive directory lock covers catalog transactions; bounded timeout; no unsafe stale-lock stealing | Three independent Node writers create 24 unique records; occupied-lock and failure-release tests |
| Confirmation dialog lacks keyboard containment/restoration | Native modal makes background inert; shared trap cycles Tab; Reject focused initially; Escape rejects; focus restored | Browser test covers forward/reverse Tab, Escape, restoration and strong-auth disabled approval |
| Avatar capability failures appear too late | Uncached admission/configuration endpoint plus homepage/library/create notices, login link, timeout/retry; unavailable startup disabled | Unit policy tests and browser login/retry cases |
| HeyGen session trusts a self-declared header | Same authenticated/local policy and same-origin mutation check as other asset APIs | Anonymous, cross-origin and authenticated route tests |
| Four Hook warnings | Stable source callback and correct effect dependencies; snapshot return-focus target before cleanup | ESLint: zero warnings/errors |
| Voice Hook concentrates semantic projection with device lifecycle | Pure transcript, revision, settlement and caption projection extracted into `src/voice/session/transcript.ts`; compatible re-exports retained | Existing transcript/revision tests plus browser voice/text paths |
| CI omits build and browsers; mypy failures ignored | Production build, deterministic browser smoke, failure artifacts, Node 22, blocking new-diagnostic gate | Local source-only build and tests; mypy gate run |
| Documentation calls implemented confirmations future work | README updated; product/deployment/test boundaries documented | `docs/RELIABILITY-OPERATIONS.md` |
| Earlier validation used a dirty worktree | Exported pushed HEAD and tested independently; then validated source-only remediation copy without ignored media | See verification below |

## Verification

The pushed HEAD production build passed. Its unit suite had four failures caused
by dependencies on ignored local media/evaluation evidence, not by the text fix.
The preparation route test now owns its own disposable fixture. Actual optional
media/evidence checks remain available under `pnpm test:media:local`; ordinary
unit tests explicitly skip three such checks instead of assuming the author's
machine contents exist everywhere.

- Source-only remediation snapshot: 624 unit tests passed, 3 explicit local-media
  checks skipped; production build passed.
- Installed media profile: all 7 tests passed on this machine.
- Python confirmation/transport and type-gate tests: 42 passed.
- Mypy regression gate: passed against 117 existing diagnostics.
- Real provider smoke using project-local credentials and fixed synthetic text:
  Doubao ASR, streaming Doubao TTS and DeepSeek response each passed (3 tests).
- Browser regressions verify text retry, capability login/retry and confirmation
  keyboard behavior. No paid avatar/GPU renderer session is claimed tested.

## Remaining boundaries

The mypy baseline is explicit existing debt, not a claim of a type-clean Python
codebase. Subsequent error fixes should shrink it. The file catalog requires a
shared persistent filesystem with atomic mkdir/rename and needs operator recovery
after an owner crash; it is not a distributed database. The voice Hook still
coordinates device lifecycle; the extraction is incremental. Provider smoke is a
point-in-time connectivity/contract check, not evidence of latency SLOs, browser
microphone quality, avatar lip-sync quality or all-vendor production readiness.
