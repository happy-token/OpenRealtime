---
status: accepted
---

# Doubao direct ASR switches to single-key auth, wired as this demo's default (supersedes ADR-0038's "ASR unchanged")

> Endpoint selection is superseded by
> [ADR-0058](0058-doubao-bigmodel-asr-default-and-latency-baseline.md): direct
> ASR still uses the single-key authentication decided here, but now defaults
> to `bigmodel` rather than `bigmodel_async`.

ADR-0038 left ASR untouched: `doubao_asr.py`'s direct conformer existed but
authenticated with the legacy two-credential headers (`X-Api-App-Key`/
`X-Api-Access-Key`, `DOUBAO_APP_ID`/`DOUBAO_Token`) and wasn't wired into
`demos/voice_web_server.py`'s factory, which still defaulted ASR to Bella.

Two things changed this. First, spike-testing (throwaway scripts, deleted
after use) confirmed the same single-key auth style TTS already uses
(`X-Api-Key`/`DOUBAO_API_KEY`) is also accepted by the ASR
`bigmodel_async` endpoint — a 403 originally seen on the target resource
(`volc.seedasr.sauc.duration`) was a per-resource authorization gap on the
account, not an auth-mechanism mismatch or a broken endpoint. Second,
after the account purchased a usage package for this resource, a repeat
spike test confirmed `volc.seedasr.sauc.duration` itself now grants
successfully and transcribes real synthesized speech correctly
end-to-end, under both the single-key and legacy-dual-credential auth
styles.

Given one key now covers both ASR and TTS, keeping the legacy app_id/token
path in `doubao_asr.py` would be an unused second auth mechanism (YAGNI) —
it's removed. `DoubaoAsrEngine.__init__` now takes a single `api_key`
param (default `os.environ["DOUBAO_API_KEY"]`), sending `X-Api-Key`
instead of the two legacy headers. `RESOURCE_ID` stays
`volc.seedasr.sauc.duration` — that value was already correct in the
code; only the credential/header it was reached with needed to change.
`.env`'s `DOUBAO_APP_ID`/`DOUBAO_Token` are kept (not deleted, since
they're real provisioned credentials, not code) but relabeled as unused
legacy/reference values now that no conformer reads them.

`demos/voice_web_server.py`'s `_build_asr_engine()` now mirrors
`_build_tts_engine()`'s shape exactly: a `VOICEAGENT_ASR_BACKEND` env var
(default `"doubao-direct"`, opt-in `"bella"`) selects between
`DoubaoAsrEngine()` and `BellaAsrEngine()`, falling back to
`PreloadedAsrEngine("")` when neither credential is set. ASR and TTS now
both default to speaking directly to Volcengine with zero gateway
involvement, matching the user's original direction from ADR-0038 —
"后面可能需要把接口做一下替换" — for the ASR side that was still
outstanding.

`../bench/docs/apis/doubao-asr.md` already carries a verified-2026-08-07
update note recording the single-key auth finding and the two resource_id
grant results; no further doc changes needed there.
