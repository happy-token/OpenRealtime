---
status: accepted
---

# Voiceprint embedding, matching, and enrollment service

ADR-0005 shipped `VoiceprintMatcher` as a Protocol with only
`match(generation) -> VoiceprintResult | None` and a `NoVoiceprintMatching`
default — deliberately, since no real conformer existed yet and the seam
had no audio-input method to build one against. This ADR adds the real
conformer and the pieces it's built from, in a new `voiceagent/voiceprint/`
subpackage. `voiceagent/signals/voiceprint.py`'s `VoiceprintMatcher`
Protocol and `NoVoiceprintMatching` default stay exactly where they are —
Kernel wiring (opt-in matcher, `NoVoiceprintMatching` unless one is passed)
is unchanged; this ADR is purely additive.

**`voiceagent/voiceprint/embedding.py`**: `SpeakerEmbedder` Protocol
(`async def embed(self, pcm16: bytes, *, sample_rate_hz: int) -> list[float] | None`)
and `PreloadedSpeakerEmbedder`, a deterministic no-network stand-in —
mirrors `PreloadedAsrEngine`/`EchoLlmClient` elsewhere in this framework.
The real conformer, `voiceagent/voiceprint/plugins/bella_speaker_embedder.py`'s
`BellaSpeakerEmbedder`, follows `web_search/plugins/byte_web_search.py`'s
pattern (stdlib `urllib.request` wrapped in `asyncio.to_thread`) rather than
`speech/plugins/bella_asr.py`'s WebSocket pattern, since a speaker embedding
is a single request/response call over one recording, not a persistent
stream. `API_KEY` is read from the environment and never logged; on any
request, network, or response-shape failure it returns `None` rather than
raising, matching `PreloadedSpeakerEmbedder`'s "None means embedding
failed" contract.

**`voiceagent/voiceprint/matching.py`**: `VoiceprintProfile` (frozen
dataclass: `profile_id`, `display_name`, `centroid: list[float]`),
`cosine_distance(a, b)`, `VoiceprintRepository` Protocol +
`InMemoryVoiceprintRepository` default, and
`EnrolledSpeakerVoiceprintMatcher` — the real `VoiceprintMatcher` conformer.

**`voiceagent/signals/voiceprint.py`**'s `VoiceprintMatcher` Protocol gains
one additive member: `async def add_audio(self, pcm16: bytes, *,
sample_rate_hz: int, generation: int) -> None` (no-op on
`NoVoiceprintMatching`). This is the actual reason no real conformer existed
until now — the original Protocol had no audio-input method at all.
`EnrolledSpeakerVoiceprintMatcher.add_audio` buffers pcm16, resetting the
buffer whenever `generation` changes (mirroring the ASR session's own
last-write-wins turn-boundary handling — no new turn-boundary event is
invented for this).

One deliberate asymmetry between `add_audio` and `match`: `add_audio` only
eagerly computes and caches a result once `min_audio_ms` of audio has
accumulated for the current generation, while `match(generation)` computes
from whatever is buffered immediately, with no minimum-duration gate. This
isn't an inconsistency — `add_audio`'s eager path exists specifically to
have a result ready *before* `match()` would otherwise be called (see the
`VoiceprintGate` rationale in ADR-0023), so it can afford to wait for enough
signal; `match()` remains the Kernel's own direct, no-additional-audio-
required fallback for callers that never call `add_audio` at all, so it errs
towards using whatever exists rather than blocking a turn on it.

`voiceagent/kernel/conversation_kernel.py`'s `_handle_audio_chunk` (LISTEN)
and `_feed_asr_session` (SPEAK/DUAL) each gain one small, unconditional,
additive plumbing call — `await self._voiceprint_matcher.add_audio(...)` —
right alongside the existing `_asr_session.push_audio` calls. This purely
feeds audio into a seam that was previously unusable; it adds no gating
logic, and `NoVoiceprintMatching`'s no-op keeps unregistered behavior
identical to before.

**`voiceagent/voiceprint/enrollment.py`**: `enroll_recording(embedder,
pcm16, sample_rate_hz, display_name, repository)` for static enrollment —
embeds one recording and activates it immediately, raising
`VoiceprintEnrollmentError` if the embedding fails (an explicit,
host-invoked action reports failure rather than swallowing it, unlike the
Kernel's own fail-open plugins). `AdaptiveEnrollment` captures the first
`target_turns` turns via `observe_turn`, embeds each, and once enough turns
are captured runs a minimal pure-Python 2-means split (via
`matching.cosine_distance`) to separate a single dominant speaker's samples
from any incidental second-speaker audio, keeping whichever cluster has the
greater total captured duration. Activation runs as a background
`asyncio.Task`, decoupled from any connection/session lifetime — a host
drives `observe_turn` from its own per-turn audio capture, mirroring
voiceloop's "activates at the next turn boundary, independent of connection
lifetime" property without this needing a dependency on any
transport/session object.
