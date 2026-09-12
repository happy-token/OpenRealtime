# Reliability operations

## Product boundary and capability preflight

OpenRealtime's Python voice runtime is the reusable framework. The Next.js
workbench is a reference application for voice, text and digital-human workflows.
Provider configuration does not imply that an external service is healthy.
The current homepage wires Anam for hosted sessions; HeyGen/custom selections
remain unavailable there even if the separate session API is configured.

`GET /api/avatar-capabilities` returns configuration/admission states for asset
management, Anam, HeyGen and local rendering. It is uncached, contains no keys or
internal service URLs, and uses the same access policy as the respective APIs.
The homepage explains missing access/configuration before avatar startup, offers
administrator login when applicable, and allows retry when preflight fails. Text
input remains available inside an active session; the homepage has no separate
text-chat entry. Creation
and library pages show the asset-access notice. Session APIs still enforce access
on every request; the capability response never authorizes an operation.

Anam and HeyGen require an authenticated admin session or the explicitly enabled,
same-origin local development policy. A client-supplied header does not authorize
a paid session. Local rendering additionally requires the preview policy.

## Avatar catalog concurrency and recovery

The file repository uses a `.catalog-lock` directory acquired through exclusive
`mkdir` for the complete read/modify/write operation. All cooperating processes
using the same filesystem path therefore serialize changes. Reads that also
purge expired records and reads of replaceable image bytes participate in the
same lock. Catalog writes retain atomic temporary-file replacement. Invalid
catalog records stop reads and writes rather than being silently filtered.

Set `AVATAR_CATALOG_DIR` to one persistent shared directory when running multiple
processes. The filesystem must support atomic directory creation and rename.
Separate replica-local filesystems do not share data; this backend is unsuitable
for deployments that cannot meet these conditions. The Python PostgreSQL state
setting does not migrate Avatar metadata. A transactional database adapter is a
future deployment option, not part of this file-backend change.

Acquisition waits up to five seconds, then reports a retriable error. A crashed
writer may leave a lock behind. We deliberately do not remove a lock based on
age, since a paused but living process may still own it. To recover:

1. Stop every application process using the directory.
2. Back up the directory and inspect `catalog.json` for valid JSON and schema.
3. Remove the empty `.catalog-lock` directory with `rmdir`.
4. Restart the application and verify the catalog can be listed.

Do not remove the lock while any writer remains active. Restore a damaged
catalog from backup before restarting; do not replace it with an empty array.

## Explicit confirmations

The browser renders a native modal dialog using the server-owned summary. Focus
starts on Reject, background controls are inert, Tab remains within the dialog,
and focus returns to the initiating control when it closes. Escape rejects.
Strong-auth actions cannot be approved by this interface. Decisions carry the
confirmation ID and action digest and are validated by the server. Pending
confirmations are re-emitted during recovery; a UI click alone does not prove
that a protected action completed.

## Verification profiles

- `pnpm test`: deterministic unit/contract checks. No external services or
  untracked local media are required. Three installed-media/evidence checks are
  explicitly skipped here.
- `pnpm test:media:local`: checks those actual optional media and research evidence
  files, failing when they have not been installed. It does not synthesize or
  substitute evidence for the original evaluation runs.
- `pnpm build`: production compilation and framework checks.
- `pnpm exec playwright test tests-e2e/text-fallback.spec.ts tests-e2e/confirmation-access.spec.ts tests-e2e/avatar-capabilities.spec.ts`:
  deterministic browser regressions, including text retry and keyboard access.
- `uv run python scripts/check_mypy.py`: blocking gate against
  `config/mypy-baseline.json`. Diagnostic identity includes file, message and error
  code, with occurrence counts. Source line movement does not create a regression;
  additional errors or checker execution failures fail the gate. The baseline is
  reviewed technical debt, not a suppression of all future errors. Shrink it when
  fixing old errors; do not expand it merely to pass CI.
- `pnpm test:voice:live`: real-provider smoke, requiring explicit credentials.
  Passing deterministic tests does not verify current network, audio quality,
  vendor quota, or GPU renderer health.

CI runs Python tests and the type-regression gate, web lint/typecheck/unit tests,
production build, and the browser regression subset. Browser failures retain
screenshots/traces as CI artifacts. Node 22 and frozen dependency lockfiles keep
these checks reproducible.

## Frontend state boundaries

`src/voice/session/transcript.ts` owns pure semantic transcript/caption projection:
turn identity, ASR revisions, assistant settlement and spoken/display selection.
It has no React or browser audio dependency. `use-voice-session` keeps compatible
re-exports while coordinating transport and device input/output runtimes. This is
an incremental separation; extracting the remaining runtime coordination is a
future refactor, not a claim that the complete hook has been rewritten.
