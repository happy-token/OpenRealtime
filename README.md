# OpenRealtime

**公开体验：** [realtime.happy-token.cn](https://realtime.happy-token.cn) · **源码：** [GitHub](https://github.com/happy-token/OpenRealtime)

Web 体验包含语音对话、实时数字人与离线动作编排。公开体验由站点运营方提供受限的语音额度；自行部署时可用 `.env` 配置平台服务。登录用户可在设置中保存个人供应商凭据和获得允许的口型对齐服务。完整部署需要 Next.js、Python WebSocket 服务和 PostgreSQL，参见[公开站部署指南](docs/deployment/public-trial.md)。

A universal, extensible voice-interaction agent framework: a runtime that owns the voice
interface (listening/speaking/turn-taking/dialogue-state) and delegates conversational
intelligence to a built-in or external Brain, over a vendor-neutral transport, ASR/TTS
speech Seam, and tool/knowledge/device-fleet integration surface.

See [CONTEXT.md](CONTEXT.md) for the glossary and [docs/adr/](docs/adr/) for the architectural
decisions behind the design. Every integration point is a Protocol with a deterministic,
dependency-free default plus one or more real conformers — this is a **framework, not an
application**: it ships the seams and one working example of each, not a production backend for
every vendor.

> Renamed from **VoiceAgent**. Existing `VOICEAGENT_*` environment variables,
> PostgreSQL `voiceagent` schemas, session cookies, object prefixes, URNs, and
> wire metadata remain supported so existing deployments and saved sessions
> continue to work without a data migration.

## Project status

- [公开站部署指南](docs/deployment/public-trial.md) — Cloudflare 前门、运行组件、密钥与发布检查。

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — consolidated Seam map and one-turn walkthrough.
- [docs/REALTIME-GROUNDING.md](docs/REALTIME-GROUNDING.md) — frozen date/time, live search, trust boundaries, and SentenceEnd prefetch.
- [docs/SEMANTIC-INTERRUPTION.md](docs/SEMANTIC-INTERRUPTION.md) — playback-time ASR revisions, latest-wins interruption classification, cancellation, and Turn admission.
- [docs/VOICE-RUNTIME-QUALITY.md](docs/VOICE-RUNTIME-QUALITY.md) — M5 live-turn evidence schema, grouped SLO report, and strict release commands.
- [CHANGELOG.md](CHANGELOG.md) — what's shipped, grouped by ADR.
- [docs/COMPLETION_STATUS.md](docs/COMPLETION_STATUS.md) — every PRD point vs. what's actually built.
- [ROADMAP.md](ROADMAP.md) — what's next, in order ([中文版](docs/ROADMAP.zh-CN.md)).
- [docs/ISSUES.md](docs/ISSUES.md) — tracked gaps, deferrals, and accepted design divergences.
- [docs/VERSIONING.md](docs/VERSIONING.md) — SemVer policy and the changelog-to-tag workflow.
- [LICENSE](LICENSE) (Apache-2.0) and [CONTRIBUTING.md](CONTRIBUTING.md) — how to contribute.

## What's implemented

- **Voice Session Runtime**: one server-authoritative lifecycle from startup through
  reconnect and closure, with a recovery barrier that restores bounded model context,
  active Agent work, and pending bound confirmations before the session becomes active.
- **Cascaded Realtime Engine**: the Phase 1 production runtime composes typed ASR,
  Turn Manager, Brain, tool/delegation, speech-rendering, and TTS capabilities behind
  one stateful command/event contract. Generation supersession and transport-detach
  settlement make stale output inert.
- **Conversation Journal and production state**: a server-owned Journal commits
  accepted user turns before model dispatch and one assistant item at the terminal
  boundary. Local development uses deterministic in-memory repositories;
  production can select direct PostgreSQL repositories. Large retained media and
  Agent artifacts remain behind the S3-compatible Artifact Store rather than the
  latency-critical audio path.
- **Turn Manager**: the full five-state / eleven-transition full-duplex dialogue FSM (see
  [docs/full-duplex-survey.md](docs/full-duplex-survey.md)) — user onset, barge-in, backchannel,
  third-party-speech filtering, hesitation/resume, covered by deterministic Realtime and
  Turn Policy contract tests.
- **Semantic interruption**: while the assistant is speaking, the same long-lived ASR
  session feeds partial revisions to an exact-rules + latest-wins LLM Gate. Obvious stop
  phrases cancel the current Generation before VAD silence; correction/interrupt wait for
  the independent semantic EOT before becoming a Brain/Agent turn, while pure stop and
  backchannel remain control-only. See
  [Semantic Interruption](docs/SEMANTIC-INTERRUPTION.md).
- **Transport Adapter**: production uses authenticated WebSocket protocol v2 with rotating
  resume tokens, input epochs, sequence acknowledgements, semantic recovery, and no detached
  raw-media replay. A raw UDP conformer remains non-production; RTC is explicitly deferred.
- **Speech Seam (ASR/TTS)**: `AsrEngine`/`TtsEngine` Protocols, each with a deterministic
  test/demo default (`PreloadedAsrEngine`, `SilentTtsEngine`) and a real conformer speaking
  Volcengine's direct Doubao `bigmodel` ASR and direct bidirectional Doubao TTS,
  with optional Bella adapters — see
  [ADR-0011](docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md) and
  [ADR-0058](docs/adr/0058-doubao-bigmodel-asr-default-and-latency-baseline.md).
  Realtime Speech capabilities deliver streaming audio with generation-aware cancellation,
  while the browser Device Output Runtime reports playback truth.
- **Brain / Router**: built-in `ChatBrain` (plain LLM reply) and `ToolCallingBrain` (Canonical
  Tool Schema, one tool call per turn), an `OpenAiCompatibleLlmClient` for any real
  OpenAI-compatible endpoint, and a `DelegationPolicy` seam that routes complex turns to an
  external `AgentSession`/`Driver` instead of answering directly.
- **Realtime Grounding**: credentialed `ChatBrain` turns use a small
  `TurnGrounder` to plan ordinary response vs. local clock vs. live lookup.
  The wall clock is frozen once per candidate; target-zone relative dates use
  calendar semantics; search returns typed, explicitly untrusted evidence and
  fails closed when no real provider key exists. The same speculative producer
  starts at SentenceEnd and is reused after semantic acceptance — see
  [Realtime Grounding](docs/REALTIME-GROUNDING.md).
- **Tool sources**: function-calling, skill-based, and MCP-shaped tool declarations all adapt
  into the same Canonical Tool Schema; a `KnowledgeBaseToolSource` exposes retrieval
  (RAG/知识库) as an ordinary tool call, alongside a `WebSearchToolSource` (`search_web`, live
  external results — `DeterministicWebSearch` by default, or `ByteWebSearch` for a real
  ByteDance-backed conformer, see [ADR-0016](docs/adr/0016-byte-web-search-conformer.md)) and a
  `ClockToolSource` (`get_current_datetime`) — see
  [ADR-0014](docs/adr/0014-web-search-and-clock-as-tool-sources.md).
- **Multi-modal Turn Content**: text (ASR transcript), audio metadata, and optional vision
  content (`VisionSource` plugin) bundled per turn; `ActionOutput` lets a Brain emit non-verbal
  gesture/emotion instructions alongside speech.
- **Plugins**: Wake Word, AddresseeClassifier (third-party-speech filtering),
  `SemanticInterruptionClassifier` (six-label playback-time arbitration, with
  `DualIntentClassifier` retained as the empty-ASR/disabled fallback), Voiceprint
  (informational speaker match), `StatusInquiryClassifier` (progress-check vs. new topic
  during a pending delegation), `EotClassifier` (LLM-only semantic completeness inside
  a SentenceEnd + VAD/ASR-idle dual latch — see
  [Semantic EoT](docs/SEMANTIC-EOT.md)) — all framework seams remain replaceable; the
  live web demo enables semantic interruption by default when composed.
- **Device Fleet**: the standardized activation/firmware/inventory contract for multi-device
  ecosystems (小智-style), with a minimal in-memory reference implementation.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

## Run the web demo

```bash
pnpm install
pnpm dev
```

Opens the Next.js frontend on `http://localhost:3000` and starts the Python WS/control-plane
server (ports 8765/8766) alongside it via `scripts/dev_server.sh` — one command for the whole
stack. GPU avatar rendering (LiveTalking/Wav2Lip) is a separate, optional local service
(`scripts/avatar_services.sh`) that is **off by default**
(`OPENREALTIME_AVATAR_RENDERER_MODE=disabled`); `pnpm dev` works without it, and enabling it
requires its own GPU runtime setup — see `.env.example` for the `managed`/`external` modes.
By default the backend uses `EchoLlmClient`/`PreloadedAsrEngine`/`SilentTtsEngine`
(deterministic, no network) when credentials are absent. The server advertises its speech
capabilities during the WebSocket handshake: when server ASR/TTS are absent, a compatible browser
may supply `SpeechRecognition`/`SpeechSynthesis` as an explicit demo fallback. A fatal browser
recognition error exits the listening state instead of retrying forever. Interim recognition and
cumulative assistant deltas are rendered as live text; final utterances become one user message
and one assistant message. Typed chat remains available even when browser speech is unavailable.

The zero-config launcher binds the Voice WebSocket to `127.0.0.1` and uses an
explicit fixed development identity; the server logs a warning so this cannot
be mistaken for production authentication. Client `SessionHello` identity
fields have no authorization power. A production-shaped single-principal
deployment can authenticate a trusted proxy `Authorization` header or secure
same-site cookie as follows:

```bash
export VOICEAGENT_ENDPOINT_AUTH_MODE=static_bearer
export VOICEAGENT_ENDPOINT_AUTH_TOKEN='replace-with-a-high-entropy-secret'
export VOICEAGENT_TENANT_ID=tenant-1
export VOICEAGENT_USER_ID=user-1
export VOICEAGENT_DEVICE_ID=browser
export VOICEAGENT_WS_HOST=127.0.0.1 # reverse proxy terminates public TLS
```

The cookie name is `openrealtime_endpoint_token`. Multi-user deployments
can use `VOICEAGENT_ENDPOINT_AUTH_MODE=public_ticket` with the website's Casdoor
login and PostgreSQL-backed public voice admission. Requested shared Threads are admitted only after the server-side
Thread authority confirms access; a Resume Token never grants Thread access.

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
facts rather than guess. See [Realtime Grounding](docs/REALTIME-GROUNDING.md).

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
See [ADR-0028](docs/adr/0028-server-rename-and-nextjs-web-client.md) for why the web client lives
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
[ADR-0029](docs/adr/0029-real-tool-calling-llm-client-and-search-hardening.md)). `get_current_datetime`
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
[ADR-0061](docs/adr/0061-two-speed-voice-tool-runtime.md). Protected tools stop at a persisted bound-confirmation request;
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

## Run the tests

```bash
uv run pytest -q
uv run ruff check server demos tests
pnpm test          # vitest unit tests (lib/audio.ts)
pnpm test:e2e      # Playwright tests against the Next.js app
pnpm test:media:local # optional installed media/evaluation evidence checks
pnpm test:voice    # deterministic voice regression: Realtime + ASR/TTS + browser E2E
```

Run `pnpm exec playwright install chromium` once on a new machine before the
browser suite. The default voice regression never calls external AI services.
Use `pnpm test:voice:live` only when `DOUBAO_API_KEY` and/or
`DEEPSEEK_API_KEY` are configured and real provider smoke coverage is wanted.

## Package layout

The repo splits four ways: `server/` is the framework itself, `demos/` holds runnable
service-side launcher scripts, the root Next.js app (`app/`, `components/`, `hooks/`, `lib/`) is
the browser frontend, and `clients/` holds reference usage code for the remaining device/transport
types that talk to the service — organized by device type, not a distributable SDK package (see
[ADR-0025](docs/adr/0025-examples-vs-clients-directory-split.md),
[ADR-0028](docs/adr/0028-server-rename-and-nextjs-web-client.md)).

Each Seam directory in `server/` holds its `Protocol` contract plus the framework's
deterministic, zero-config default conformer. Seams with a real, vendor-backed conformer nest it
under their own `plugins/` subfolder — that's where you add your own integration.

```
server/
├── application/      # Process composition root and durable application services
├── voice_session/    # Lifecycle, reconnect barrier, context/control recovery, quality gates
├── realtime/         # Stateful Engine contract, Cascaded runtime, capabilities and WS bridge
├── conversation_journal/ # Canonical semantic history Protocol + in-memory conformer
├── persistence/      # In-memory UoW + direct PostgreSQL repositories/migrations
├── artifacts/        # S3-compatible Artifact Store contracts/adapters
├── core/             # Generation Lease, Turn Content — shared value objects
├── turn_policy/      # The five-state / eleven-transition dialogue FSM, plus its plugins
│                      # (Wake Word, AddresseeClassifier, DualIntentClassifier, EotClassifier)
│   └── plugins/      # LlmDualIntentClassifier, LlmEotClassifier
├── signals/          # EnergyVad, VisionSource, Voiceprint
├── speech/           # AsrEngine/TtsEngine Protocols + deterministic defaults
│   └── plugins/      # DoubaoAsrEngine, DoubaoTtsEngine, BellaAsrEngine
├── brain/            # Brain/LlmClient Protocols, ChatBrain, ToolCallingBrain, Router,
│                      # read-only realtime Grounder, DelegationPolicy, StatusInquiryClassifier
│   └── plugins/      # OpenAiCompatibleLlmClient, KeywordDelegationPolicy
├── tools/            # Canonical Tool Schema + function-calling/skill/MCP/knowledge-base/
│                      # web-search/clock sources
├── knowledge_base/   # Retrieval Protocol (RAG/知识库) + in-memory reference implementation
├── web_search/       # Retrieval Protocol for live web results + deterministic default
│   └── plugins/      # ByteWebSearch
├── agent_session/    # Agent Session Protocol (delegate a whole turn to an external Agent)
│   └── plugins/      # AcpDriver
├── device_fleet/     # Device activation/firmware/inventory contract (小智-style ecosystems)
├── endpoint_session/ # EndpointSession/Registry — reconnect/resume over any Transport Adapter
├── transport/        # TransportAdapter Protocol + deterministic wire framing
│   └── plugins/      # WebSocketTransportAdapter, UdpTransportAdapter
├── hooks/            # Hook Point — dual synchronous/async extension mechanism
└── ledger/           # Event Ledger — async Observer fan-out
```

```
clients/
├── websocket/        # Raw WebSocket demo client (client.py)
├── udp/              # Raw UDP demo client (client.py)
└── esp32/            # Reference device-side client for the 小智-style Device Fleet contract
```

```
src/
├── app/              # Next.js App Router entry (layout.tsx, page.tsx)
├── components/       # OpenRealtimeApp, call/chat views, config drawer, shared UI
├── hooks/            # useConversationEngine — WS reconnect/backoff, mic capture, playback
├── lib/              # Frame types + pure audio helpers (base64/PCM), unit-tested
└── styles/           # oklch design tokens, dark/light theme

public/voice-input-worklet.js # v2 Device Audio Input Runtime worklet
public/voice-input-worklet.js # v2 device input epoch/buffer worklet
```

## Reliability and deployment boundaries

The voice runtime is the framework; the Next.js digital-human workbench is its
reference application. The file-backed Avatar catalog is separate from the
Python PostgreSQL Journal. See [reliability operations](docs/RELIABILITY-OPERATIONS.md)
for shared-directory locking, crash recovery, capability preflight, test profiles,
and the Python type-error baseline. Local voice and text chat require no paid
provider credentials. Hosted avatar sessions require authorized access and
provider configuration; the UI checks these before offering startup.

Signed-in users can save a completed personal MiniMax video on `/services/motion`,
create a private Avatar, and attach the saved motion to that Avatar. These assets
are stored separately from the administrator Avatar catalog and are served only
to the owning web session. Set `OPENREALTIME_PERSONAL_MOTION_PATH` to an absolute,
durable directory in production. The private Avatar appears in the digital-human
catalog; motion management remains on `/services/motion`.
The owner can bind that Avatar to a private role on `/roles/new`, choose its
voice, and start a conversation in motion-video mode. The video loops as a
visual preview while speech plays separately; it is not synchronized lip sync.
Private roles and their knowledge bindings are scoped to the signed-in owner.
