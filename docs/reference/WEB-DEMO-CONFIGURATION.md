# Web demo configuration reference

Extracted from the previous README on 2026-10-11. These operational examples are retained for reference; consult [the documentation index](../README.md) and [.env.example](../../.env.example) for current entry points. Provider examples require compatible credentials. Console/demo adapters are not all production transports.

### Public voice trial and personal API Keys

The **My API Key** link requires ordinary account login. For local development,
fill the account variables listed in `.env.example` in an ignored `.env.local`:
Casdoor issuer, client ID and secret, this site's origin, user session secret,
credential encryption key, and PostgreSQL DSN. Register
`<VOICEAGENT_PUBLIC_ORIGIN>/api/user/callback` as the Casdoor application's
redirect URI. Apply migration 0020 before logging in. Until these values are
configured, `/settings/api-keys` displays setup guidance instead of opening a
nonfunctional login flow. The administrator login is separate and does not
identify an ordinary user's saved keys.

Public voice is disabled by default. Apply the PostgreSQL migrations, including
`0020_web_identity_and_provider_credentials.sql` and `0021_voice_admissions.sql`,
before enabling it. Configure `VOICEAGENT_POSTGRES_DSN`, a dedicated
`VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY` (32 random bytes in base64url), Casdoor
OIDC settings, and `VOICEAGENT_PUBLIC_ORIGIN`. Run the voice process with
`VOICEAGENT_ENDPOINT_AUTH_MODE=public_ticket`, proxy `/voice` to its WebSocket
port, and serve that path over WSS on an HTTPS website. Then set
`VOICEAGENT_PUBLIC_VOICE_ENABLED=true` in the web process. An explicit
`NEXT_PUBLIC_VOICE_WS_URL` can override the browser's default same-origin
`/voice` path. The web process refuses to issue trial tickets unless both
public-voice settings are enabled.

Visitors can start a complete voice conversation without logging in. The
operator's server-side `.env` keys fund missing provider credentials. A Casdoor
user can open `/settings/api-keys` to save, replace, or clear personal Anam,
Doubao, Bella, DashScope, DeepSeek, and MiniMax keys. Stored keys are encrypted in
PostgreSQL, displayed only by suffix, and used only for that user's requests.
For realtime providers, a saved personal key wins over the corresponding
platform key; removing it selects the platform key for the next session.
Changing or deleting a key revokes active voice admissions bound to its version.
The browser receives only an opaque, short-lived admission ticket and the
provider/source labels. It never receives a provider API Key.

Platform ASR and TTS each default to one concurrent conversation, controlled
independently by `VOICEAGENT_PLATFORM_ASR_CONCURRENCY` and
`VOICEAGENT_PLATFORM_TTS_CONCURRENCY`. Guest conversations and conversations
using either platform speech key have a server-enforced 180-second limit by
default (`VOICEAGENT_PLATFORM_VOICE_SESSION_SECONDS`). A full pool returns a
visible busy response with manual retry. LLM calls do not consume a speech
slot. No daily trial count or site-wide minute budget is imposed. Set hard
spending limits at the provider account before publishing the site. Anam
sessions using the platform key are limited to `ANAM_AVATAR_ID`; users with
their own Anam key may choose their own valid Avatar ID. Ordinary users cannot use the
administrator-only paid creation routes. HappyImage image generation is closed
to ordinary users until its personal-account quota path is implemented. The
standalone TTS preview route is also administrator-only because it does not
hold a voice admission slot.

Provider quota and credential failures are reported after the failed request;
no reliable read-only balance precheck is currently integrated. ASR/TTS
failures end the voice session and leave its transcript available. This public
mode still uses an in-memory Endpoint Session registry, so a reverse proxy
should keep reconnects on the same voice process. A lost process releases its
PostgreSQL speech reservation at lease expiry.

Voice Session admission is process-wide and reserves Session, ASR/TTS, memory,
event-loop and audio-queue capacity before device audio is released. The
`VOICEAGENT_MAX_*` settings in `.env.example` define the deployment profile.
A disconnect keeps realtime resources for the five-second fast-resume window;
after that it quiesces them and requires fresh admission while retaining the
same Session identity for the 60-second grace period.
If recovery exceeds its deadline or the owning process is gone, the browser
opens a fresh Session Continuation linked by `previous_voice_session_id`; the
original Thread is authorized again and reprojected into model context rather
than replaying raw media.

Direct provider speech is the default production-shaped path and requires
`DOUBAO_API_KEY`. To route ASR/TTS through Bella instead, set both backend selectors and its
credential:

```bash
export VOICEAGENT_ASR_BACKEND=bella
export VOICEAGENT_TTS_BACKEND=bella
export API_KEY=...
```

Alibaba Cloud Bailian can replace only the TTS side while keeping the current
ASR and LLM providers. The adapter uses the official bidirectional WebSocket
protocol: LLM text deltas enter through `continue-task` and mono 24 kHz PCM16
audio is returned incrementally. Digital-human mode forwards those PCM chunks
to the selected hosted avatar renderer without replacing OpenRealtime's agent.

```bash
export VOICEAGENT_TTS_BACKEND=bailian
export DASHSCOPE_API_KEY=...
export DASHSCOPE_WORKSPACE_ID=llm-your-workspace
export BAILIAN_API_HOST=llm-your-workspace.cn-beijing.maas.aliyuncs.com
export BAILIAN_TTS_MODEL=cosyvoice-v3-flash
export BAILIAN_TTS_VOICE=longanhuan_v3
```

`BAILIAN_TTS_VOICE` can later be replaced with a CosyVoice clone/design voice
ID. When using `cosyvoice-v3.5-flash`, a clone or designed voice is required;
that model does not accept the system voice shown in the quick-start example.
`BAILIAN_TTS_WS_URL` is available for an exact endpoint override, but the
workspace host is sufficient for the Beijing business-space endpoint.

### Anam realtime renderer

The default digital-human renderer uses Anam Audio Passthrough. OpenRealtime
keeps ASR, LLM, tools, Bailian TTS, memory, and interruption; Anam receives the
mono 24 kHz PCM16 chunks and returns the lip-synced WebRTC audio/video stream.

```bash
ANAM_API_KEY=...
ANAM_AVATAR_ID=...
ANAM_AVATAR_MODEL=cara-4
```

Signed-in users save personal Anam and MiniMax keys on `/settings/api-keys`.
The keys are encrypted in PostgreSQL and remain scoped to the account. Personal
MiniMax video generation requires the user's own key and never falls back to the
platform key. Administrator-only creation routes remain behind administrator
access checks, and paid video generation remains disabled in production until
its durable task paths and opt-in switch are configured.

The API key stays on the server. `/api/anam/session` returns only a short-lived
token with `enableAudioPassthrough: true`. The browser sends chunks through
`createAgentAudioInputStream()` and calls both `interruptPersona()` and
`endSequence()` when the current OpenRealtime generation is interrupted.

### HeyGen LiveAvatar renderer (optional comparison)

The previous HeyGen LiveAvatar **LITE** adapter remains available as a quality
comparison. It uses the same renderer boundary: OpenRealtime still owns ASR,
LLM, tools, Bailian TTS, and barge-in.

```bash
LIVEAVATAR_API_KEY=...
# Optional in sandbox: defaults to HeyGen's public demo avatar.
LIVEAVATAR_AVATAR_ID=dd73ea75-1218-4ef3-92ce-606d5f7fbc0a
LIVEAVATAR_SANDBOX=true
```

The API key remains server-side. `/api/liveavatar/session` returns only a
short-lived LITE session token. If the key, avatar, or renderer is unavailable,
the page keeps the local image and automatically falls back to ordinary audio.
The current public SDK closes an utterance on every `repeatAudio()` call, so
the adapter submits audio after the OpenRealtime response finishes instead of
breaking lip-sync at arbitrary network chunk boundaries. A future incremental
renderer transport can reduce this extra first-frame delay without changing
the voice-session contract.

Direct Doubao ASR defaults to `bigmodel`. A deployment can select another
compatible endpoint without changing code:

```bash
export DOUBAO_ASR_WS_URL=wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
```

Realtime endpointing is configured in the project-root `.env`. The web demo
defaults to a 256ms Silero VAD silence window and asks Doubao ASR to finalize
after a 256ms internal end window. Browser audio reaches the local WebSocket in
exact 32ms Silero windows, while the Doubao adapter combines them into the
provider-recommended 100ms packets:

```bash
VOICEAGENT_VAD_SILENCE_MS=256
DOUBAO_ASR_END_WINDOW_MS=256
DOUBAO_ASR_PACKET_MS=100
DOUBAO_ASR_COMMIT_WAIT_MS=512
VOICEAGENT_EOT_LLM_TIMEOUT_MS=5000
```

Lower values reduce stop-to-response latency but can split an utterance when a
speaker pauses between phrases. `VOICEAGENT_EOT_ASR_IDLE_MS` remains the slower
fallback for ASR providers that do not produce a timely sentence-final event.
The remote semantic EoT judge remains enabled with a five-second hard bound.
After commit, raw SSE text deltas flow into one Doubao synthesis session while
audio deltas flow out; there is no 12/24-character session split.

`DEEPSEEK_API_KEY` selects the low-latency DeepSeek V4 Flash path; `API_KEY`
selects the Bella-backed LLM when a DeepSeek/generic LLM key is absent. Without
any LLM credential the demo uses the visibly streaming deterministic Echo
model. On the ordinary (tools-off) voice path, a real LLM also enables the
read-only Turn Grounder: clock questions are resolved locally, and current
facts use Byte search only when `BYTE_WEB_SEARCH_API_KEY` is configured. Without
that search key the assistant is instructed to say it cannot verify realtime
facts rather than guess. See [Realtime Grounding](../../docs/REALTIME-GROUNDING.md).

The web demo uses ephemeral in-memory state by default. To use the production
PostgreSQL Journal/repository conformers, apply the versioned migrations through
your deployment process, install the optional dependency (`uv sync --extra
postgres`), and set:

```bash
export VOICEAGENT_STATE_BACKEND=postgres
export VOICEAGENT_POSTGRES_DSN=postgresql://user:password@host/database
export VOICEAGENT_POSTGRES_SCHEMA=voiceagent  # optional
```

Startup does not create or migrate the schema and never falls back to memory if
PostgreSQL was explicitly selected. S3 is used only for configured retained audio
or large artifacts; it is not on the live first-audio path. RTC also remains a
later Transport Adapter, so this foundation does not depend on Pipecat or an RTC
vendor.

`pnpm build && pnpm start` runs the same pairing against a production Next.js build.
See [ADR-0028](../../docs/adr/0028-server-rename-and-nextjs-web-client.md) for why the web client lives
at the repo root instead of under `clients/`.

## Run the console demo

Start the server:

```bash
uv run python demos/basic_ws_server.py
```

In another terminal, start the interactive client:

```bash
uv run python clients/websocket/client.py
```

Type a line and press Enter — it is sent as a simulated ASR transcript (`user_text` frame), the
server runs it through Turn Policy and the Brain, and the reply comes back over the socket.

By default the server uses `ChatBrain` backed by `EchoLlmClient`, a deterministic stand-in that
requires no network access. To talk to a real OpenAI-compatible endpoint instead, set:

```bash
export VOICEAGENT_LLM_API_KEY=sk-...
export VOICEAGENT_LLM_BASE_URL=https://api.openai.com/v1   # optional, this is the default
export VOICEAGENT_LLM_MODEL=gpt-4o-mini                     # optional
uv run python demos/basic_ws_server.py
```

To try the delegation demo (a message containing `帮我查一下` or `delegate:` gets an immediate
ack, then a delegated-result reply about a second later), set `VOICEAGENT_DEMO_DELEGATION=1`.

Voice Runtime tool-calling exposes `get_current_datetime` and `search_web` when
`VOICEAGENT_DEMO_TOOLS=1`. The checked-in `.env.example` enables it. This swaps in
`ToolCallingBrain` wired to `ClockToolSource` and `WebSearchToolSource`:

```bash
export VOICEAGENT_DEMO_TOOLS=1
uv run python demos/basic_ws_server.py
```

With no other configuration this uses `EchoToolCallingLlmClient` (deterministic, no network) and
`DeterministicWebSearch`. `VOICEAGENT_LLM_API_KEY` (same as above) additionally switches the tool
calling itself to `OpenAiCompatibleToolCallingLlmClient`, a real conformer that lets the model pick
and call these tools (see
[ADR-0029](../../docs/adr/0029-real-tool-calling-llm-client-and-search-hardening.md)). `get_current_datetime`
reports in `VOICEAGENT_CLOCK_TIMEZONE` (an IANA name; defaults to `Asia/Shanghai`) rather than a
naive, unzoned timestamp, so the model never has to guess what "now" means for the user. It
is a `FAST` tool and stays in the inline `LLM → tool → LLM` path. `search_web`
is a bounded `VARIABLE` Voice Runtime tool: the assistant first says
“我查一下，马上告诉你。”, performs the search asynchronously without blocking
audio intake, then feeds the result back to the same response for the final LLM
and TTS output. Transient TLS, connection, timeout, HTTP 429, and HTTP 5xx
failures are retried up to `BYTE_WEB_SEARCH_MAX_ATTEMPTS=3`; invalid or empty
responses are not retried. `BACKGROUND` tools do not execute in this loop; they belong to
Agent Runtime delegation.

In the Voice Web Demo (`pnpm dev` / `demos/voice_web_server.py`), tool mode uses
the canonical Conversation Engine path: model request → `CallToolAction` →
server Policy Gateway → per-turn Fast Tool Loop → durable Journal result →
correlated model continuation. Clock runs inline; public search uses the
acknowledge-then-defer Voice Runtime path from
[ADR-0061](../../docs/adr/0061-two-speed-voice-tool-runtime.md). Protected tools stop at a persisted bound-confirmation request;
the browser displays the server-owned action summary and sends an explicit decision
bound to its confirmation ID and digest. The server validates the decision;
strong-auth actions remain unapprovable from the voice UI. Recovery re-emits
pending confirmations, and free-form speech never counts as authorization.
The dialog confines keyboard focus and Escape rejects the operation.

`search_web` separately uses `DeterministicWebSearch` (no network) unless a real vendor is
configured. To use `ByteWebSearch` (ByteDance's search API) instead, set:

```bash
export BYTE_WEB_SEARCH_API_KEY=...
export BYTE_WEB_SEARCH_BASE_URL=https://open.feedcoopapi.com/search_api/web_search  # optional, this is the default
```

`WEB_SEARCH_API_KEY` is accepted as a deprecated compatibility alias for
existing VoiceLoop environments; `BYTE_WEB_SEARCH_API_KEY` takes precedence
when both are present.

The old Kernel-based UDP demo has been removed from the production examples.
UDP/ESP32 remains deferred until it implements the v2 Voice Session contract;
the low-level UDP adapter and its protocol tests remain available for that work.
