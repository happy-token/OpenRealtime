# ADR 0153: Authorized Session recording references and segment replay

Date: 2026-10-07
Status: Accepted for recording HTTP/Agent access and UI integration. Preservation UI and confirmed renderer joins remain open.

## Decision

Wire ADR0152 readers through the existing private control-plane HTTP, CLI and production composition. Recording routes require a loopback Host and, when supplied, loopback Origin. This prevents a remote browser's DNS rebinding path from bypassing the public gate. They are private deployment endpoints, not a new public login system. Catalog/audio use no-store; errors disclose static reasons, never provider keys or internal exceptions.

Public `GET /api/observability/sessions/{sessionId}/recordings` and `.../recordings/{artifactId}/audio` reuse signed-in admin authorization or the existing 15-minute exact-Session Agent read grant. An Authorization header is authoritative and never falls back to cookies. Grants are not forwarded to the private control plane or inserted in URLs. Original Artifact ownership is resolved by Journal evidence, not the administrator account. Agent diagnostic read scope now includes that Session's restricted recording references and audio; it grants no preservation, deletion or global listing capability.

Catalog pagination is independent (`after_sequence`, 1–200 rows, decimal bigint cursor). Public projection validates Session provenance, schema, monotonic sequences, capture/sample bounds, digest and seven-day policy, and forwards only whitelisted fields. The generated audio URL is a same-origin protected route. `available` means verified metadata; actual object availability is checked only during the audio request.

Audio responses require matching Session/Artifact/digest headers and bounded Content-Length. Stream reads enforce a 4 MiB + 44 byte response limit and verify the complete digest before publishing bytes. Single browser byte ranges are served from verified bytes; malformed/multiple/unsatisfiable ranges return 416. Catalog response limit is 1 MiB. Requests share a ten-second upstream deadline and request cancellation. Unconsumed bodies receive best-effort cancellation without waiting on a noncooperative cancellation promise. These limits do not prove hard SDK peak memory for a corrupt oversized object: the private object adapter still loads a complete blob before validation, as documented in ADR0152.

Unified diagnostics expose `audio.status=not-queried` and `audio.catalog_url`, not a fabricated availability result. Agent credential bundles add an independent recording endpoint/cursor instruction. Ordinary diagnostic exports do not gain a bearer token.

The same-theme Session page offers a separate “查看录音” entry, available even when another diagnostic source fails. Manual catalog loading has a 15-second UI deadline, duplicate-click guard, independent cursor, retained rows/cursor on failure and retry. Session/refresh keys isolate stale responses and unmount the old player. Only one selected segment renders native audio controls; preload is none and playback is user initiated. The page caps displayed rows at 2000 and explicitly preserves incompleteness when more exist. Preview disables private reads. Input and actual sent tracks are distinguished; sent is never called confirmed playback.

## Validation and remaining work

Real ApplicationRuntime/Journal/Artifact/private HTTP regression covers catalog, actual verified WAV, foreign Session, invalid pagination/IDs and malicious Host/Origin. Public route regressions cover admin/grant denial, no cookie fallback or upstream bearer, source identity/digest/size, strict enum shape, private projection, bigint pagination, range and cancellation. SSR tests and isolated Chrome desktop/mobile preview verify the entry/theme/disabled private access; they do not prove real browser audio rendering. Formal controlled-hook regressions and independent reviewer probes verify UI duplicate/retry/refresh/late-result fencing; they do not replace real DOM/audio lifecycle acceptance.

No running user service was restarted, production migration performed, secret configured, real provider/S3 called or remote commit pushed. Deployment requires matching frontend/backend versions and controlled migrations 0035–0037. Existing Sessions are not backfilled. Session preservation UI, confirmed renderer epoch/speech/sample joins, full recording completeness, real S3/deployment/admin/external Agent acceptance and all original G0–G5 experiments remain open.
