# Write your own plugin: a worked example (AsrEngine)

This walks through adding a real plugin for a Seam, using `AsrEngine` as the
concrete example. The same five steps apply to any Seam (`TtsEngine`,
`DualIntentClassifier`, `DelegationPolicy`, a `Driver`, ...) — only the
`Protocol` shape changes.

## 1. Read the Protocol, not just the default

`server/speech/asr.py` defines the contract:

```python
class AsrSession(Protocol):
    async def push_audio(self, pcm16: bytes, *, sample_rate_hz: int) -> None: ...
    async def consume_transcript(self) -> str: ...   # drains accumulated text
    async def peek_transcript(self) -> str: ...       # non-destructive read
    async def close(self) -> None: ...
    @property
    def is_alive(self) -> bool: ...                   # False once the backend has died

class AsrEngine(Protocol):
    async def start_session(self) -> AsrSession: ...
```

Read the docstrings, not just the signatures — they carry constraints the
type signature can't express. Here: `is_alive` exists so the Kernel can
detect a dead vendor connection and restart the session instead of pushing
audio into nothing; `peek_transcript` exists specifically for
`EotClassifier` to inspect text without consuming it. Skipping these and
implementing only the "obvious" methods produces a plugin that type-checks
but breaks reconnect/EOT behavior.

`server/speech/asr.py` also ships `PreloadedAsrEngine` — the
deterministic, no-network stand-in used by tests and demos. It's a
reference for the *shape* of the Protocol, not for how a real backend
should behave (it ignores all audio and returns one canned string).

## 2. Look at a real conformer for the same Seam

`server/speech/plugins/doubao_asr.py` (`DoubaoAsrEngine`) and
`server/speech/plugins/bella_asr.py` (`BellaAsrEngine`) are two real,
independent implementations of the same `AsrEngine`/`AsrSession` pair,
speaking two different vendor streaming protocols. Comparing both — not
just one — shows which parts are Protocol-mandated (session lifecycle,
`is_alive` flipping to `False` on a vendor error frame) versus
vendor-specific (auth headers, frame encoding, reconnect backoff).

## 3. Implement and place it under `plugins/`

New real conformers live in the matching Seam's `plugins/` subfolder —
`server/speech/plugins/your_engine.py` for a new `AsrEngine`,
`server/brain/plugins/` for a new `LlmClient`/`DelegationPolicy`,
`server/turn_policy/plugins/` for a new classifier, and so on. Never
put a real, vendor-backed implementation directly in the Seam's own file
(e.g. `speech/asr.py`) — that file holds only the `Protocol` and the
zero-dependency default.

Constraints to carry over from the Protocol read in step 1:
- Never treat your own endpointing/finality signal as a Turn Policy EOT
  signal — `EnergyVad` and (optionally) `EotClassifier` are the sole
  authority; an `AsrEngine` only answers "what did they say."
- Flip `is_alive` to `False` (don't raise) when the underlying connection
  dies, so the Kernel can discard and restart cleanly.
- Zero new third-party runtime dependencies without an ADR (ADR-0024) —
  vendor SDKs go through stdlib `urllib`/`asyncio` streams, not a new pip
  dependency, unless that's already an accepted exception.

## 4. Write a test next to the existing ones

`tests/speech/` mirrors `server/speech/plugins/` — `test_doubao_asr_session.py`
and `test_bella_asr.py` are the existing pattern to follow: a test double or
fake transport standing in for the vendor connection, asserting on
`push_audio`/`consume_transcript`/`is_alive` behavior, not on network calls
actually reaching a vendor. Add `tests/speech/test_your_engine.py` alongside
them. See [testing-patterns.md](testing-patterns.md) for the AAA/test-double
conventions those files follow.

If your plugin needs to be verified against the real vendor at least once,
that goes in `tests/live/` instead — skipped by default, opt-in via an env
var (see `tests/live/test_bella_voice_pipeline_live.py`) — not in the
default suite.

## 5. Wire it in

Nothing outside `speech/plugins/` needs to change: whatever constructs the
`ConversationKernel` passes an instance of your `AsrEngine` where it
previously passed `PreloadedAsrEngine` or another conformer. Check
`demos/basic_ws_server.py`/`demos/voice_web_server.py` for how the existing
conformers get selected and constructed today.
