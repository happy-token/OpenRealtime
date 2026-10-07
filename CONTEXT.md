# OpenRealtime

A universal, extensible voice-interaction agent framework: a runtime that owns the voice interface (listening/speaking/dialogue-state) and delegates conversational intelligence to a built-in or external Brain, over a vendor-neutral transport.

## Language

**Seam**:
An architectural extension point in the framework's backbone — a place where a module has a defined contract and can be replaced or extended without touching the rest of the system. Backbone Seams: Voice Session Runtime, Endpoint Session/Transport Adapter, Realtime Engine, Turn Manager, speech capabilities, fast-tool execution, Agent Task Supervisor/Store, Conversation Journal, Artifact Store, and Event Ledger. Each Seam's directory holds its `Protocol` plus the framework's zero-config default; a Seam with a real, vendor-backed conformer nests it under that directory's own `plugins/` subfolder (e.g. `speech/plugins/`, `brain/plugins/`) — that's where a real integration physically lives.
_Avoid_: Layer, component (too generic — use Seam when referring to one of the defined extension points specifically)

**Brain**:
The unit that decides what to say next in a turn — either the framework's built-in default Chat Brain (simple, local, handles natural conversation) or a user-registered external Agent (handles complex/delegated tasks). Brain is deliberately architecture-agnostic about where the intelligence lives.
_Avoid_: Agent (reserve "Agent" for an external Brain specifically, not the concept generally), Model, LLM

**Personal Voice Assistant**:
A persistent user-facing assistant with a stable persona and an ongoing relationship with its user across conversations. It can hold natural voice dialogue and coordinate work without being identified with any one Brain, Agent, voice, or visual embodiment.
_Avoid_: Brain, Agent, Avatar, Voice Session

**Voice Session Runtime**:
The live-session boundary that keeps one Voice Session coherent from opening through recovery and closure, including realtime interaction, transport continuity, trusted control coordination, context projection, playback truth, and operational state. It does not own durable persona or memory, external Agent execution, Avatar rendering, or any specific transport provider.
_Avoid_: Voice Runtime (ambiguous), Realtime Engine (only one part of the Runtime), Application Control Plane, product backend

**Realtime Engine**:
The replaceable, stateful execution boundary for one live voice conversation. It owns conversational intelligence and realtime speech interaction as one capability, whether realized by a Native Realtime Engine or assembled as a Cascaded Realtime Engine; callers do not depend on that choice.
_Avoid_: Realtime module (too vague), Conversation Engine (legacy narrower term), RealtimeSession (conflicts with Endpoint Session), Voice model, LLM pipeline

**Realtime Conversation**:
The stateful interaction handle opened by a Realtime Engine for one Voice Session. It accepts correlated realtime commands and emits one ordered event stream for its lifetime, including input understanding, dialogue state, response output, tool requests, cancellation, and closure.
_Avoid_: Realtime Session (conflicts with Endpoint Session and Voice Session), response stream (only one response within the conversation), connection (transport-specific)

**Realtime Reconfiguration Barrier**:
The explicit boundary for replacing a bound Realtime Engine or cascaded capability implementation during an ongoing Voice Session. It stabilizes transcript and playback facts, completes or cancels active work, closes the old Realtime Conversation, rebuilds context from Conversation Journal, and opens a replacement without pretending stateful providers were hot-swapped.
_Avoid_: Hot reload, provider fallback (a policy that may request this barrier), session reconnect (transport continuity only)

**Capability Failure Policy**:
The explicit configured response to failure of a bound realtime capability or plugin: fail, bounded restart of the same implementation, safe bypass, migration through a Reconfiguration Barrier, or a declared degraded mode. Every non-fatal transition is observable; silent provider fallback is forbidden.
_Avoid_: Retry flag, best effort, automatic fallback

**Plugin Manifest**:
The versioned, declarative identity and capability description of a registered realtime extension, including its typed slot, contract version, configuration schema, placement, media formats, latency budget, data access, and failure policy. Runtime configuration selects a manifest identity rather than an implementation import path.
_Avoid_: Python package metadata, arbitrary plugin config, provider credentials

**Capability Context**:
The minimum pseudonymous identity, correlation, and timing envelope exposed to one capability or audio plugin according to its approved Data Grants. The Realtime Engine reattaches full Interaction Context to accepted plugin events after the plugin boundary.
_Avoid_: Interaction Context, request context, plugin metadata

**Data Grant**:
A registry-approved permission for one plugin identity and placement to receive a specific class of audio, transcript, speaker reference, artifact, or network access. A Realtime Profile may reduce but never expand these permissions.
_Avoid_: Plugin config flag, OAuth scope, user consent (a separate policy input)

**Capability Bridge**:
An adapter that presents a sidecar or remote implementation as the same Cascaded Capability Session used by an in-process binding. It translates transport and serialization without exposing those details or the full public Realtime Event stream to the plugin.
_Avoid_: Realtime Engine Adapter, Sideband Connection, remote plugin protocol

**Realtime Requirements**:
The required, preferred, and optional capabilities requested before opening a Realtime Conversation. Required capabilities must be satisfied before media starts; preferred capabilities may use an explicitly observable degradation, while optional capabilities may remain disabled.
_Avoid_: Feature flags, provider config, optimistic capability probing

**Realtime Engine Capabilities**:
The versioned declaration of commands, events, media formats, context modes, speech-input behavior, delivery precision, audio taps, turn-management form, and safe configuration updates supported by one Engine binding. It is matched against Realtime Requirements before opening the conversation.
_Avoid_: Provider documentation, runtime feature detection, Plugin Manifest

**Realtime Profile**:
The versioned user-facing declaration selecting a Native or Cascaded Realtime Engine, typed capability and audio-plugin identities, safe configuration, requirements, and failure policies. It references server-resolved secrets and registered plugin identities rather than implementation imports or credentials.
_Avoid_: Environment-variable bundle, provider settings, resolved runtime wiring

**Resolved Realtime Profile**:
The validated, immutable session binding produced from a Realtime Profile after schema, capability, media-graph, permission, and dependency checks. It records exact implementation versions and a diagnostic digest so a Voice Session's behavior is reproducible.
_Avoid_: Realtime Profile, mutable session config, plugin registry

**Realtime Engine Contract Suite**:
The executable behavioral specification every Native and Cascaded Realtime Engine binding must pass for command idempotency, event ordering, context visibility, speech delivery, interruption, control correlation, recovery, capability negotiation, and closure. Type conformance alone never establishes compatibility.
_Avoid_: Unit tests, provider smoke test, interface type checking

**Capability Contract Suite**:
The typed behavioral specification a VAD, ASR, Turn Manager, TTS, Speech Renderer, Audio Processor, Analyzer, or Sink plugin must pass before the registry may advertise it as compatible. Each suite tests only the permissions and semantics of its declared slot.
_Avoid_: Realtime Engine Contract Suite, plugin certification claim, import test

**Realtime Command**:
An explicit, correlated intent sent into an active Realtime Conversation, such as adding input or context, requesting a response, supplying tool output, updating configuration, cancelling work, or closing the conversation. A command is not evidence that the requested transition or delivery occurred.
_Avoid_: Client event (one possible source), provider event, Conversation Action, command string

**Realtime Event**:
An immutable, strongly typed fact emitted by a Realtime Conversation through its single ordered public stream. Lifecycle, input, dialogue, response, and control-request events share Interaction Context, event identity, conversation sequence, timestamp, schema version, and applicable correlation identities.
_Avoid_: Voice Event and Conversation Action (legacy split types), provider event, Transport Frame, Event Ledger entry, string event

**Voice Session Event**:
An immutable, runtime-owned fact about Voice Session lifecycle, readiness, recovery, or closure that may exist before, between, or after Realtime Conversations. Voice Session Events and Realtime Events may share one client control channel, but retain distinct ownership and ordering identities.
_Avoid_: Realtime Event, Transport Frame, connection event, Dialogue State

**Semantic Session Resume**:
Recovery of a detached Voice Session from authoritative lifecycle, Conversation Journal, work, and playback facts plus an ordered event tail, never by replaying stale wire frames or media chunks. A resumed connection may reuse the Voice Session identity only after the recovery barriers pass.
_Avoid_: Frame replay, reconnect, Engine restart, conversation replay

**Voice Session Resume Token**:
A high-entropy, short-lived bearer proof issued for one Voice Session and accepted only together with matching authenticated endpoint identity while that Session is detached within grace. The owner Registry stores only its hash, rotates it after successful resume, and never treats it as user login or Thread authorization.
_Avoid_: Voice Session ID, API key, login session, reconnect URL parameter

**Voice Session Continuation**:
The explicit relationship by which a new Voice Session continues the same persistent thread after an earlier live session can no longer be resumed. It receives a new `voice_session_id`, references the previous Voice Session, and rebuilds semantic context and durable work from their authorities.
_Avoid_: Semantic Session Resume, reconnect, same session, thread fork

**Voice Session Snapshot**:
A server-authored, sequence-bounded projection of the current Voice Session phase, visible conversation state, active work, and playback facts used when an incremental resume tail is unavailable or incomplete.
_Avoid_: Conversation Journal, database backup, client cache, Realtime Profile

**Voice Session Admission**:
The server-authoritative capacity decision made before a starting Voice Session may become active or release device prebuffer. It accounts for live-session, event-loop, memory, audio-queue, and provider capacity, returns an explicit retryable rejection when unavailable, and never treats device identity as an exclusive media lease.
_Avoid_: Authentication, rate limiting alone, WebSocket acceptance, provider connection pool

**Voice Session Failure**:
A safe, versioned failure envelope carrying stable machine-readable code, lifecycle phase, retryability, optional retry delay, session disposition, user-safe message, and diagnostic error identity. Clients act on these fields rather than parsing text, while sensitive provider or resource-existence details remain server-side.
_Avoid_: Exception string, Realtime Capability Failure, HTTP status alone, UI toast

**Model Context Restoration Barrier**:
The recovery boundary that prevents a Voice Session from becoming active or requesting a new model response until authoritative Conversation Journal history, corrected by speech-delivery facts, is visible to the current Realtime Engine through a declared thread sequence.
_Avoid_: Prompt injection, chat-history string, Session Snapshot, Memory retrieval

**Response Stream**:
The ordered, cancelable subset of Realtime Events emitted while one Realtime Engine resolves a response. It may interleave response lifecycle markers, display/spoken/audio deltas, control requests, and terminal outcome, all correlated by Interaction Context, `response_id`, and sequence. A Response Stream may buffer only to reach a meaningful protocol boundary—such as one speakable text segment or a complete tool-argument object—never the entire ordinary reply.
_Avoid_: SSE stream, audio stream (both are provider- or media-specific subsets), complete response

**Realtime Session Plane**:
The latency-critical, client-facing path that carries live audio and realtime session events through Endpoint Session, Transport Adapter, and the active Realtime Engine. It owns media delivery and connection continuity, but never trusted business authorization, tool execution, Agent delegation, or long-lived provider credentials.
_Avoid_: Media server (one possible implementation), RTC plane (WebSocket is supported too), Control Plane

**Application Control Plane**:
The trusted server-side path that owns identity binding, policy, permissions, budgets, Fast Tool Loop execution, confirmation, Work Registry, and named-Agent delegation. It observes and controls the Realtime Session Plane through canonical Realtime Commands and Realtime Events; it may run in the same process initially without collapsing the logical boundary.
_Avoid_: Backend (too generic), tool server, Sideband (a provider-specific connection pattern into this plane)

**Sideband Connection**:
A provider-specific server connection attached to the same native realtime session as a client media connection, allowing Application Control Plane to monitor the session, update it, and answer tool calls without exposing trusted logic to the client. It is one Native Realtime Engine deployment mechanism, not the universal internal protocol.
_Avoid_: Control Plane, second Voice Session, media connection

**Conversation Journal**:
The server-owned, append-only semantic history for one persistent thread and the only authoritative source used to restore or project conversation context. It records committed user/assistant items, tool calls/results, delegation outcomes, confirmations, and session boundaries at meaningful protocol boundaries—not raw provider events or every streaming delta. Provider sessions, model prompts, and Agent histories are rebuildable projections of it.
_Avoid_: Event Ledger (operational observation), provider conversation, transcript (only one content view), memory (too broad)

**Conversation Item**:
One versioned semantic record in Conversation Journal, identified by `item_id` and ordered by a server-assigned thread sequence. It carries Interaction Context, typed content, causal correlation, visibility, and terminal status; later corrections or redactions are new records rather than silent mutation.
_Avoid_: Realtime Event (a runtime fact), message (not every item is dialogue), provider item

**Spoken Content**:
The text intentionally submitted for voice delivery during a live conversation. It may be a concise spoken projection of a richer Conversation Item, remains causally correlated to its source when one exists, and is distinct from both display content and an observed audio transcript.
_Avoid_: TTS text (one implementation), transcript (an observation of audio), assistant message (one possible contextual projection)

**Semantic Content**:
The complete meaning and structured result carried by a Conversation Item for durable history and model projection. It may contain detail or structure unsuitable for direct display or speech.
_Avoid_: Display Content, Spoken Content, raw Agent payload

**Display Content**:
The user-interface representation of a Conversation Item, including rich text, Markdown, code, lists, and artifact references. It may be more detailed and differently formatted than Spoken Content without becoming a separate conversational turn.
_Avoid_: Semantic Content, transcript, assistant message

**Delivered Speech Transcript**:
The best known text projection of Spoken Content that was actually delivered to the listener, bounded by acknowledged playback progress and any truncation or Barge-in. It is a delivery fact used for context reconciliation and diagnostics, not a new Conversation Item.
_Avoid_: Spoken Content (intended speech), output transcript (may include unplayed generated audio), playback buffer

**Interrupted Context Policy**:
The configurable rule for projecting an interrupted assistant delivery into subsequent realtime model context. It defaults to `DELIVERED_ONLY`; any policy that includes full intended content must also preserve the interrupted state and delivered range rather than implying the listener heard everything.
_Avoid_: Keep-full-text boolean, truncation flag, Conversation Journal retention policy

**Playback Progress**:
The playback endpoint's correlated report of audio actually rendered for one speech output, expressed on the negotiated media timeline by speech identity, audio sequence, and played samples. Generated, sent, or buffered audio is not delivered speech; missing acknowledgements produce estimated rather than exact delivery facts.
_Avoid_: Audio sent, TTS completed, browser clock, speaking duration estimate

**Device Audio Output Runtime**:
The single device-side playback boundary that converts received assistant Audio Frames into generation-aware rendered audio and Playback Progress. It owns local decode/resample, the playback clock and bounded queue, output-device routing, volume, immediate cancel/clear, and played-position observation; WebSocket scheduling and future RTC remote-track playback are conformers to the same behavior.
_Avoid_: TTS, Speech Lane, Transport Adapter, browser audio element, Delivery Record

**Client Voice Session Controller**:
The device-side coordinator that follows server Voice Session Events and binds Endpoint Transport, Device Audio Input Runtime, Device Audio Output Runtime, and UI state for the current session/epoch. It executes correlated `release/reset/cancel/clear` locally but never becomes authority for Voice Session Phase, policy, Journal, or durable work.
_Avoid_: Voice Session Runtime, client state store, media player, Transport Adapter

**Agent Result Item**:
A durable, idempotently appended Conversation Item containing the correlated outcome of one Delegated Task, including its worker, source turn, result version, structured content, artifacts, and completion status. It is not an assistant message and does not imply that the result has been displayed or spoken.
_Avoid_: Agent reply, callback payload, assistant message, tool result

**Item Delivery**:
The separately scheduled act of presenting a committed Conversation Item through model-generated response, direct speech, display-only notification, or no immediate presentation. Delivery timing and priority never determine whether the authoritative item is committed to Conversation Journal.
_Avoid_: Append Item, Agent callback, immediate notification

**Append Speech Text**:
A stateful Realtime Engine input that incrementally adds externally authored Spoken Content to one correlated speech output. Its context policy is explicit and defaults to making the completed speech available to subsequent model reasoning.
_Avoid_: Append Text (ambiguous about speech), Speak (suggests a complete one-shot utterance), TTS request (not valid for Native Realtime Engine)

**Speech Output**:
One explicitly identified, append-only voice delivery lifecycle opened, incrementally supplied, committed, cancelled, or failed through Realtime Commands. Text increments are idempotently ordered by `speech_id` and text sequence; committing closes text input, while cancellation also reconciles unplayed audio and delivery state.
_Avoid_: TTS request (one implementation), audio response (only one output representation), assistant message

**Speech Draft**:
The recoverable, append-only working state of a Speech Output before final settlement. Accepted text may be batch-checkpointed outside Conversation Journal; commit, cancellation, failure, or recovery resolves the draft into correlated Spoken Content, conversation context according to policy, and a Delivery Record.
_Avoid_: Conversation Item, text buffer (not recoverable or correlated), TTS session

**Speech Lane**:
The single ordered delivery channel for one playback endpoint. Multiple Speech Outputs may prepare or wait concurrently, but ordinary assistant audio is never mixed; a scheduler chooses the sole active speech by timing, priority, preemption, user-floor, and supersession policy.
_Avoid_: Audio track (transport-specific), TTS queue (Native engines also conform), response stream

**Speech Context Policy**:
The rule governing how completed Spoken Content enters conversation context. `AUTO` attaches it to its source Conversation Item when present or creates an assistant item otherwise; `APPEND` always creates a new assistant item; `NONE` excludes it from model context while retaining delivery diagnostics.
_Avoid_: Persist flag (context and persistence are different), write-to-history boolean (cannot express source-item correlation)

**Audio Frame**:
A timestamped, sequenced unit of audio carried across a negotiated media stream. Its encoding, sample rate, channels, and duration are explicit directly or through its epoch's immutable format descriptor; no public Realtime Engine or cascaded capability contract assumes PCM16, 16 kHz, or a fixed packet duration.
_Avoid_: PCM chunk (one encoding), WebSocket packet (one transport), 32ms frame (one configuration)

**Input Epoch**:
A single uninterrupted device-capture timeline with one immutable effective Device Capture Profile and audio format. Its frame sequence and sample position start at zero; device/graph/format replacement, reconnect reset, overflow, or explicit stop closes it, and frames from a closed or different `input_epoch` cannot be joined into the current user Turn.
_Avoid_: Voice Session, Generation, WebSocket connection, utterance

**Device Audio Input Runtime**:
The single device-side boundary that turns microphone capture into epoch-bound, timestamped Audio Frames for one Voice Session. It owns the local capture graph, format conversion, framing, bounded prebuffer, `release/reset/mute`, and capture-health telemetry; the desktop-Web conformer is centered on AudioWorklet, while native and embedded clients implement the same behavioral contract with platform audio primitives.
_Avoid_: AudioWorklet (one browser mechanism), Transport Adapter, server Audio Graph, VAD, ASR

**Device Capture Profile**:
The versioned device-side configuration applied by Device Audio Input Runtime, including capture constraints, negotiated output format, frame duration, preprocessing ownership, prebuffer limits, energy threshold, pre-roll, and overflow policy. Runtime observations report the effective profile and browser/device overrides rather than assuming requested constraints were honored; each AEC, noise-suppression, or gain effect has at most one effective owner across device and server.
_Avoid_: Realtime Profile, Audio Graph configuration, browser defaults, microphone permission

**Audio Graph**:
The Cascaded Realtime Engine facility that negotiates audio capabilities and performs shared decoding, resampling, channel conversion, and reframing on one common media timeline. VAD, ASR, TTS, playback, and network packet sizes may each have different preferred frame durations without defining separate clocks.
_Avoid_: Audio plugin (the graph coordinates plugins), codec adapter (only one responsibility), media transport

**Audio Gap**:
An explicit interval on the common media timeline for which one required consumer did not receive valid audio. VAD, ASR, and Turn Manager must observe relevant gaps; sampling or dropped frames in optional Analyzer and Sink branches remain measured rather than silently affecting the critical path.
_Avoid_: Silence, packet loss estimate, empty frame

**Realtime Backpressure Policy**:
The bounded queue, buffer-duration, latency-budget, and overflow rules assigned to each realtime data edge. Critical audio, speech text, and semantic events cannot be silently dropped or placed in unbounded queues; optional analysis and sink branches may use declared sampling or drop policies with observable gaps.
_Avoid_: Queue size alone, best effort, retry policy

**Cascaded Capability Session**:
A stateful, asynchronous command/event handle opened for one bound VAD, ASR, Turn Manager, or TTS capability inside a Cascaded Realtime Engine. Capability Sessions never call each other directly; the Engine owns bounded routing, ordering, backpressure, cancellation, and lifecycle.
_Avoid_: Plugin callback, service client (one implementation), Realtime Conversation (the public aggregate)

**Audio Processor Plugin**:
An ordered Audio Graph extension that transforms Audio Frames while preserving their media timeline. Noise suppression, echo cancellation, gain control, and similar effects belong here and must declare format, latency, side-input, and bypass capabilities.
_Avoid_: Audio Analyzer Plugin, codec utility, arbitrary middleware

**Audio Analyzer Plugin**:
A read-only Audio Graph extension that observes Audio Frames and emits correlated evidence without changing the media stream. Voiceprint, speaker change, acoustic-scene, and quality analysis belong here; their evidence is not execution authority.
_Avoid_: Audio Processor Plugin, identity provider, Turn Manager

**Audio Sink Plugin**:
A non-authoritative Audio Graph extension that consumes correlated audio or media events for storage, forwarding, monitoring, or diagnostics without modifying audio or deciding dialogue state.
_Avoid_: Audio Processor Plugin, Event Ledger, transport

**Avatar Renderer**:
The optional session-scoped presentation capability that turns OpenRealtime-authored Spoken Content or speech audio and non-verbal actions into a synchronized visual embodiment. A Renderer may own managed TTS when its declared input is text, but OpenRealtime remains the authority for dialogue, cancellation, intended speech, and delivery reconciliation. A Renderer may be browser-native, hosted, or self-managed, but never becomes the character's Brain or memory authority.
_Avoid_: Digital Human (too broad), Avatar Agent, video player, Brain

**Avatar Renderer Stability Evidence**:
Long-running evidence that one pinned Hosted Avatar and Renderer continue producing timely renderer updates under a repeated speech stimulus. It does not establish visible speaking-frame latency, lip-sync accuracy, AV drift, interruption behavior, queue health, thermal safety, or end-to-end realtime readiness.
_Avoid_: Realtime acceptance, digital-human stability, successful callback count

**Persona**:
The editable behavioral identity of a Personal Voice Assistant, including its governing prompt, identity, personality, language, and memory instructions. A Persona is independent of the selected Voice and Avatar, so naming a Persona does not create, select, or authorize use of a matching person's likeness.
_Avoid_: Avatar, Voice, model configuration, provider context

**Avatar**:
The top-level managed representation of one person's or character's visual likeness, identified by one stable Avatar ID and containing a display name, authorized source imagery, mode-specific provider bindings, and zero or more Avatar Actions. Multiple actions never create duplicate Avatars.
_Avoid_: Persona, Hosted Avatar, provider resource, Renderer asset, preview image

**Private Avatar**:
An Avatar owned by the authenticated user who explicitly saved it, visible and mutable only to that owner and authorized administrators. User-generated images, actions, and Renderer assets remain private by default even when HappyImage generation used the owner's account quota.
_Avoid_: personal browser draft, shared catalog entry, anonymous asset, unpublished Hosted Avatar

**Shared Avatar**:
An administrator-provided built-in Avatar, a synchronized provider stock Avatar, or a Private Avatar explicitly published into the workspace catalog. An Anam stock item receives an OpenRealtime Avatar ID and binds its Provider Avatar ID plus platform-accepted model, but its provider preview remains display metadata and grants only realtime use—not source-image reuse, action creation, duplication, or segmented rendering. Publishing a Private Avatar is a separate authorized action and never occurs automatically because an image was generated, an action became ready, or an administrator can technically read the asset.
_Avoid_: Private Avatar, automatic publication, provider official label, public object URL

**Avatar Owner**:
The authenticated user identified by the authoritative account subject recorded when an Avatar is saved. Ownership governs management, deletion, model backfill, and private media access and is not inferred from a HappyImage task, browser, display name, or provider account.
_Avoid_: task submitter metadata, current browser, provider account owner, Avatar display name

**HappyImage Identity Delegation**:
The seamless server-to-server authorization used when an OpenRealtime-authenticated user generates an Avatar image through HappyImage. OpenRealtime signs a short-lived, audience-bound, replay-resistant assertion carrying the verified Casdoor subject and minimum generation/result scopes; HappyImage trusts only the registered OpenRealtime service, maps the subject to its own user and quota record, and provisions that record on first use when absent. The browser neither opens a HappyImage authorization flow nor receives or shares either application's session cookie, API key, or long-lived token.
_Avoid_: shared cookie or session store, forwarded browser cookie, iframe session, browser API key, arbitrary user impersonation

**HappyImage Generation Availability**:
The external capability state shown inside Avatar Studio for the authenticated user's HappyImage generation account. It reports remaining quota separately from service availability: insufficient quota disables only AI generation and links to HappyImage account management in a new page, while a provider or integration outage reports `服务不可用`; neither condition blocks local upload or choosing an existing Avatar source. The system never substitutes anonymous, administrator, or shared OpenRealtime quota.
_Avoid_: Avatar processing billing, shared quota, anonymous fallback, whole-studio unavailable state

**Avatar Recycle Bin**:
The 30-day recoverable deletion state for one complete Avatar aggregate. Entering it immediately removes the Avatar and all of its actions from catalogs, new session choices, direct tests, and ordinary management while retaining its private source image, actions, Renderer assets, and bindings for whole-aggregate restoration; expiry permanently removes OpenRealtime-owned records and media. HappyImage source records remain independent, and an external provider resource is destroyed only when it is exclusively owned by the Avatar and the provider confirms deletion capability—otherwise permanent deletion only removes the binding and reports the retained external resource.
_Avoid_: archived Avatar, hidden catalog filter, immediate hard delete, HappyImage deletion

**Avatar Action Deletion**:
The independent 30-day recoverable deletion of one Avatar Action without deleting, disabling, or recreating the parent Avatar or sibling actions. The action immediately leaves normal lists and new session choices but retains its original Avatar Action ID, video, and Renderer assets in the parent Avatar's `已删除动作` area until restoration or expiry; permanent expiry removes its media and derivatives. A deleted action cannot become an orphaned top-level asset, and deleting one that is live triggers Active Avatar Revocation.
_Avoid_: Avatar deletion, image deletion, action unbinding, readiness reset, immediate hard delete

**Active Avatar Revocation**:
The immediate withdrawal of a deleted Avatar or Avatar Action from every live session using it. After an impact-aware confirmation reports the affected session count, the Avatar Renderer stops and each conversation continues in an explicitly labeled audio-only state; the runtime never substitutes another Avatar, image, or action, and restoring the asset never silently rebinds an existing session.
_Avoid_: conversation deletion, automatic Avatar fallback, deferred visual deletion, restore-and-resume

**Avatar ID**:
The canonical stable identifier for one Avatar across management, creation, and session selection. Unqualified `avatar_id` always means this product aggregate; provider and Renderer identifiers must use qualified names.
_Avoid_: Digital Human ID, Visual Identity ID, Provider Avatar ID, Renderer Asset ID

**Avatar Routes**:
The canonical page family rooted at `/avatars`: `/avatars` for asset management, `/avatars/create` for a new Avatar draft, `/avatars/{avatar_id}` for detail, `/avatars/{avatar_id}/actions/create` for the same Studio prebound to an existing parent, and `/avatars/trash` for recoverable deletion. Braces denote a dynamic value in product and API documentation only; a real URL contains the concrete ID, while Next.js source uses `[avatarId]` according to framework convention. Only management and creation appear as primary Avatar navigation destinations.
_Avoid_: `/digital-human-*`, literal colon or braces in a URL, separate action-creation product page

**Avatar MVP Baseline**:
The frozen first-release scope covering the unified Avatar aggregate and routes, separate management and Studio pages on the shared glass visual shell, private upload/existing/HappyImage source acquisition, optional manually accepted Anam realtime binding, repeatable manually accepted LivePortrait actions, required Lip-sync Model preparation plus demand-driven session-start preparation, private/built-in library scopes, durable jobs, direct home-workbench launch handoff, recoverable deletion, and direct legacy-name migration with preserved ID values. It explicitly excludes image quality/face/safety gates, Avatar-processing billing, single-frame pose editing, automatic action creation or switching, multiple session-bound actions, non-Anam provider selection, HappyImage iframe/shared Cookie integration, and runtime compatibility aliases or routes.
_Avoid_: post-MVP wishlist, implicit provider expansion, hidden compatibility layer, unconfirmed scope

**Provider Avatar ID**:
The provider-scoped identifier of one hosted avatar resource linked to an Avatar. It is never used as the Avatar ID, even when an upstream API names its field `avatar_id`.
_Avoid_: Avatar ID, unqualified avatar_id, Renderer Asset ID

**Visual Identity** (legacy):
The removed name for the former separately identified likeness aggregate, now represented by an Avatar and its authorized source imagery. The one-time migration reads `visual_identity_id` only from the pre-migration schema and preserves its value as Avatar ID; no post-migration field, API alias, type, or route uses this term.
_Avoid_: runtime alias, new domain field, second identity record, provider resource ID

**Legacy Avatar Asset Migration**:
The one-time consolidation of existing source-image and motion records through their authoritative tenant, owner, and `visual_identity_id` relationships into Avatar aggregates and child Avatar Actions. Resolved records preserve identifier values while the canonical field names change: the former `visual_identity_id` value becomes `avatar_id`, and the former `motion_base_id` value becomes `avatar_action_id`, so sessions, object paths, and Renderer assets require no identity remapping. Only records whose existing relationships resolve are migrated; the migration never fabricates a source image from a video or presents placeholder/orphan cards. Unresolved legacy records and their exclusively owned derivatives are listed by a pre-apply audit and then deleted rather than carried into the new domain.
_Avoid_: face matching, name matching, extracted-frame source, orphan Avatar, silent best-effort merge

**Avatar Display Name**:
The user-editable, non-unique authoritative label used to recognize one Avatar throughout OpenRealtime. New Avatars suggest a numbered suffix when the same label already exists, while the stable Avatar ID remains authoritative. Renaming updates OpenRealtime immediately and best-effort synchronizes only the currently accepted Anam binding as `user label · short Avatar ID`; provider failure leaves the local name and realtime capability intact, exposes `Provider 名称待同步`, and can be retried. Historical, rejected, failed, and superseded provider attempts are never renamed, and the operation never changes Persona name, linked media, ownership, or identifiers.
_Avoid_: Persona name, Provider as naming authority, Avatar ID, character identity, rename rollback

**Avatar Image Candidate**:
One uploaded, generated, or edited image being reviewed in the Avatar creation workspace before it becomes authorized source material. A HappyImage generation may show a candidate grid, but the active Avatar draft selects exactly one image; a result remains a candidate until the user names it and explicitly saves it to an Avatar, and saving another candidate requires a separate draft and `avatar_id`. Generation success, account quota use, or preview selection never creates a formal asset by itself.
_Avoid_: Identity Source Image, Avatar, saved gallery image, automatic asset

**Avatar Source Image**:
The immutable, private master image copied into Avatar-owned object storage when the user explicitly saves an Avatar. OpenRealtime imports the bytes through an authorized server-to-server path and records its content hash and provenance such as the HappyImage task/result identifier without retaining a runtime dependency on the HappyImage URL or object lifecycle. One saved Avatar ID remains bound to this master for its lifetime: a new likeness creates a new Avatar ID rather than replacing the image beneath existing actions, provider bindings, Renderer assets, or session references. The MVP adds no product-level face, quality, compatibility, or safety-check step before save; ordinary transport and object-storage constraints are implementation boundaries, not a user-facing approval flow. Deleting or expiring the HappyImage result cannot break the Avatar, and deleting the Avatar does not implicitly delete its HappyImage source.
_Avoid_: HappyImage URL, remote image reference, public source image, browser-uploaded result URL, in-place image replacement

**Identity Source Image**:
An uploaded or AI-generated image accepted as authorized source material for one Avatar. Saving it does not create a provider resource or Avatar Action: realtime providers initialize it on demand from an explicit home-workbench session start, while reusable actions require the separate manual preview-and-acceptance flow.
_Avoid_: Hosted Avatar, Motion Base Video, automatic generation input, preview-only image

**Create Avatar Entry** (legacy, removed):
The former first-card creation affordance inside the Hosted Realtime catalog. Creation now belongs to the primary `创建数字人` destination and an Avatar detail's scoped action command, never to a fake selectable catalog card.
_Avoid_: new navigation entry, selected identity, inline provider task

**Hosted Avatar**:
A provider-specific, runnable resource belonging to one Avatar and identified by a Provider Avatar ID. It is selectable only for a compatible Hosted Realtime Renderer; synchronization links it to the Avatar but does not turn it into a Motion Base Video.
_Avoid_: Avatar, stock person, provider profile, product aggregate

**Realtime Avatar Binding Creation**:
The explicit, optional Avatar Studio stage that uploads the saved private Avatar Source Image through OpenRealtime's server to a supported realtime provider and records the returned Provider Avatar ID. The MVP has only Anam, so the stage is labeled `实时驱动（Anam）` and shows no one-item provider selector. The server calls `POST /v1/avatars` with the image file, display name, and an organization-available Avatar model; a one-item model set is selected silently, while multiple authorized models expose a selector with the recommended version preselected. One `avatar_id + provider + avatar_model` admits at most one unfinished candidate, and a persisted idempotency key makes double-click, refresh recovery, and network retry return that same task. Abandoning stops local waiting but reconciles any provider-accepted result into attempt history before another candidate may start. Creation and preview state remain durable across navigation. After Anam returns an ID, the binding remains `生成预览中` until a preview is available and the user clicks `确认实时驱动效果`; no checkbox is required, and only the accepted state is selectable in the home workbench. Skipping, failing, or leaving a binding unaccepted never invalidates the Avatar image or segmented sources.
_Avoid_: automatic save-time upload, session-start provider creation, browser API key, whole-Avatar readiness

**Realtime Avatar Binding Acceptance**:
The user's explicit `确认实时驱动效果` command after Anam creation and preview. Acceptance pins the exact Provider Avatar ID and public Avatar model version shown by that preview as one binding; the home workbench cannot switch either component. The returned Provider Avatar ID is durable before acceptance, but the binding cannot enter a session choice until a preview is available and the user accepts it; preview polling and failures continue across navigation. Re-creation or model replacement produces a candidate under the same product Avatar while the currently accepted binding stays usable, and only accepting the new candidate atomically replaces it for future sessions; rejected, failed, and superseded Provider Avatar IDs remain provider-attempt history rather than independent Avatars. Official provider built-ins are treated as platform-accepted Shared Avatars.
_Avoid_: API 201 response as acceptance, checkbox, preview URL presence alone, automatic enablement

**Realtime Provider Initialization** (legacy, removed):
The superseded proposal to create a provider resource during home-workbench session startup. Realtime provider resources are now created explicitly in Avatar Studio or from an Avatar detail before they can be selected for a conversation.
_Avoid_: new implementation, hidden upload during startup, automatic provider binding

**Hosted Avatar Preview Image**:
Provider-supplied display metadata used only to recognize a Hosted Avatar in the unified Avatar catalog. It is not an Identity Source Image and cannot be downloaded, duplicated, or submitted to LivePortrait or another renderer; a provider stock Avatar is labeled `Anam 内置 · 仅实时驱动`, while segmented creation requires a separately owned authorized source image.
_Avoid_: Identity Source Image, reusable provider asset, source master, cross-provider input

**Avatar Provider Connection**:
A shared connection to one commercial Avatar Renderer provider whose operator-owned credentials, service readiness, and built-in catalog are administered by authenticated administrators or the administrator-equivalent Local Avatar Test Mode. It is distinct from a user's Personal Provider Credential and does not authorize spending the shared allowance on that user's Avatar creation.
_Avoid_: Personal Provider Credential, Hosted Avatar, renderer selection

**Provider Generation Entitlement**:
The server-authoritative permission to create a cost-bearing asset through a shared commercial provider account. In the first release, Vidu generation, credit balance, and task lookup require an authenticated administrator or the administrator-equivalent Local Avatar Test Mode; a client checkbox or published request header can acknowledge cost but can never grant this permission.
_Avoid_: credits confirmation, API Key ownership, frontend feature flag, workspace membership

**Vidu Generation Submission Lock**:
The server-owned first-release rule that permits at most one unfinished Vidu task for the shared provider account. Creation requires an idempotency key; duplicate clicks, refresh recovery, and network retries return the existing task instead of creating another billable task, and client button state is only a secondary guard.
_Avoid_: frontend busy flag, credits checkbox, unlimited test concurrency, provider task ID

**Vidu Queue Policy**:
The first-release default of submitting Vidu generation with `off_peak=true` to prioritize discounted cost while continuously disclosing that the task may wait up to 48 hours. An administrator or Local Avatar Test Mode may explicitly disable off-peak for a faster test; normal-queue submission is never an invisible fallback.
_Avoid_: free API generation, automatic priority upgrade, hidden queue choice, fixed off-peak only

**Vidu Submission Lock Release**:
The rule that an unfinished Vidu task releases the shared-account submission lock only after Vidu explicitly reports a terminal success, failure, or reliable cancellation. Hiding, abandoning, timing out, or deleting the local task view never proves remote cancellation and never permits a second billable submission.
_Avoid_: local abandon, UI cancel, timeout unlock, parallel priority task

**Local Avatar Test Mode**:
An explicit administrator-equivalent bypass for the current single-tester phase that is valid only when enabled in a non-production environment and the request resolves to localhost. It may access all avatar management and provider operations without a login; production must reject or ignore the flag and require normal administrator authentication.
_Avoid_: anonymous production access, development default, client header, public demo mode

**Avatar Catalog Synchronization**:
A read-only reconciliation that imports or refreshes Hosted Avatar metadata from one Avatar Provider Connection and links it to local Visual Identities. It never creates provider assets, transfers assets between providers, or generates Motion Base Videos.
_Avoid_: Avatar creation, cross-provider migration, asset upload, video generation

**Workspace Hosted Avatar Catalog**:
The set of Shared Hosted Avatars synchronized through an administrator-managed Avatar Provider Connection. Private user Avatars never enter it without explicit publication; provider labels such as personally created and official describe asset provenance, not application-user ownership or privacy.
_Avoid_: personal avatar library, per-user provider connection, public catalog, Visual Identity catalog

**Anonymous Avatar Consumer**:
A first-release test-phase visitor without an application account who may browse, select, and use only assets explicitly published for consumption. Anonymous access never grants provider credentials, generation entitlement, upload, acceptance, synchronization, catalog management, or access to private source and candidate media.
_Avoid_: workspace member, administrator, public asset owner, authenticated user

**Public Trial**:
A time-limited, full realtime conversation with a published Avatar that an unauthenticated website visitor may use through Platform Provider Credentials for rendering, speech recognition, dialogue, and speech synthesis. It grants no Avatar creation or paid generation entitlement.
_Avoid_: administrator session, unlimited provider access, generation entitlement

**Platform Speech Admission**:
The decision to start a realtime conversation that will consume the operator's ASR or TTS capacity. ASR and TTS have separate capacities, so using platform ASR does not occupy a TTS slot and vice versa; a full capacity rejects the affected attempt immediately with a visible busy state and manual retry. Use of the operator's LLM key alone takes neither speech slot.
_Avoid_: browser-only busy flag, LLM usage as speech capacity, unbounded wait queue, automatic retry

**Platform Provider Credential**:
A provider API key supplied by the website operator through server-side configuration for eligible realtime conversations. It is never a Personal Provider Credential and cannot fund ordinary users' paid Avatar creation or video generation.
_Avoid_: another user's key, browser-exposed key, public generation entitlement

**API Credential Choice**:
The visible source, for each paid capability in an eligible realtime conversation: the authenticated user's Personal Provider Credential when saved, otherwise the Platform Provider Credential, including after the user deliberately removes their key. An invalid or exhausted personal key produces a visible failure without switching sources; there is no separate source toggle.
_Avoid_: automatic platform-key fallback on failure, silent account switching, provider connection

**Personal Provider Credential**:
A provider API key supplied by an authenticated user for that user's own requested operations and saved to their account until they remove it. An unauthenticated visitor cannot submit one; the platform never spends it on another person's request or a Public Trial.
_Avoid_: Platform Provider Credential, Avatar Provider Connection, transferable account credit

**Hosted Avatar Unavailability**:
The explicit blocked state of a previously selected Hosted Avatar that the provider has deleted, disabled, or made inaccessible. The local record and reason remain visible for diagnosis, but Hosted Realtime cannot start until the user synchronizes or selects another asset; the system never silently changes the person or rendering mode.
_Avoid_: automatic fallback avatar, audio-only fallback, catalog deletion, renderer retry

**Avatar Provider Linking**:
The reconciliation of a provider-specific resource with its Avatar. An existing Provider Avatar ID updates its current link; an unseen resource creates a separate Avatar unless a user explicitly merges it, and names or visual similarity never authorize automatic merging.
_Avoid_: Name matching, face recognition, catalog synchronization, automatic deduplication

**Mode-specific Avatar Selection** (legacy, removed):
The former independently persisted current asset for each Avatar Rendering Mode, replaced by a temporary Avatar Session Choice in Preflight and the complete Last Successful Avatar Session Choice after startup. Asset management now records availability and compatibility rather than a hidden current-session default.
_Avoid_: using this term for current session selection, automatic cross-mode switch, renderer fallback

**Avatar Rendering Mode**:
The first configuration decision for a digital-human experience, labeled `数字人渲染模式` in the product UI. Its values are `实时托管` (a Hosted Avatar rendered by a compatible commercial provider) and `分段式合成` (an Avatar, Avatar Action, and Lip-sync Model pipeline); it is not called a generation mode because Hosted Realtime does not pre-generate a video.
_Avoid_: digital-human generation mode, avatar type, display mode, model choice

**Avatar Asset Management**:
The independent management surface labeled `数字人资产管理`, whose catalog presents one top-level card per Avatar and manages its source image, provider bindings, child actions, and model-readiness state within that Avatar's detail. A top scope switch defaults to `我的 Avatar` and offers `内置 Avatar`; search by display name or Avatar ID applies within the active scope. Private cards expose authorized creation, rename, and deletion commands, while built-ins expose only detail and supported conversation entry instead of disabled owner-only controls. It never splits images and actions into unrelated top-level libraries, creates another page for built-ins, owns creation drafts, or embeds the creation workspace inside a management dialog.
_Avoid_: Avatar Session Preflight, current-session selector, Avatar Studio, asset creation dialog, Digital Human Asset Configuration

**Avatar Conversation Launch Handoff**:
The navigation from an Avatar card's `开始对话` command to the existing home Session Configuration Workbench with that `avatar_id` fixed as the initial selection. The workbench expands its Avatar configuration and prefills the Avatar's Last Successful Avatar Session Choice when one exists, while keeping rendering mode, image/action source, and compatible Lip-sync Model editable; only the workbench's existing final `开始对话` command starts services. It is not a new dialog, a third Avatar page, or permission to start from hidden defaults.
_Avoid_: conversation launch panel, direct card startup, Avatar Studio preview, automatic session

**Avatar Session-start Preparation**:
The explicit, one-source/one-model preparation started by the home Session Configuration Workbench when the user presses `开始对话` with an image or accepted action that lacks a ready Renderer asset for the selected Lip-sync Model. The chosen configuration remains intact while a minimizable waiting dialog reports stage, expected time, and failure details. The durable job continues after minimization or navigation: success automatically continues startup only while the user remains in the workbench, otherwise it emits a completion notice and requires a new user start command; cancellation abandons the requested startup but retains any valid derived result already committed. It is demand-driven preparation for the current choice, not automatic fleet backfill.
_Avoid_: bulk model backfill, disabled action, hidden fallback, offline preview

**Avatar Availability Summary**:
The capability summary shown on one Avatar card: its source image is usable, whether a realtime provider binding exists, its accepted action count, any actions awaiting model adaptation, and any currently running creation or preparation jobs. It is not a single aggregate ready/unready flag. Having zero actions appears only as the informational `尚未创建动作`, and a provider-, action-, or model-level failure remains attached to that capability instead of making the image-capable Avatar look unavailable.
_Avoid_: Avatar readiness, unconfigured Avatar, unavailable Avatar, aggregate failure badge

**Avatar Session Preflight**:
The pre-session selection and confirmation step entered from the `数字人模式` home card. It previews an already available Avatar choice and verifies readiness, but starts its Avatar Renderer and model services only after explicit confirmation; creation and detailed asset administration remain in Avatar Studio and Avatar Asset Management.
_Avoid_: Avatar Studio, automatic session start, Persona selection, Page Form

**Avatar Session Choice**:
The complete runnable binding selected in Avatar Session Preflight: one Avatar, Avatar Rendering Mode, a compatible Avatar Visual Source or Hosted Avatar, and the required Renderer and model-service readiness. Selecting one never changes Persona, Voice, or Brain and never silently substitutes another Avatar or rendering path.
_Avoid_: Avatar alone, Persona, preview card, automatic renderer fallback

**Last Successful Avatar Session Choice**:
The Avatar Session Choice committed only after its model services, Avatar Renderer, audio binding, and Voice Session have all become ready. It is the shared default shown by later Preflight and settings; preview browsing, cancellation, and failed startup never replace it.
_Avoid_: Preflight draft, highlighted card, configured asset alone, last attempted choice

**Avatar Visual Degraded Mode**:
The explicit active-session state entered when the bound Avatar Renderer loses visual output but the ordinary speech path remains safe. It retains the chosen Avatar as a static surface, reports bounded recovery, and may continue as visibly labeled audio-only interaction without switching to Orb or another Avatar Session Choice.
_Avoid_: Orb fallback, silent audio fallback, automatic avatar substitution, infinite reconnect

**Avatar Studio**:
The independent Avatar-creation workspace labeled `创建数字人`. It supports authorized source-image creation and reusable action creation. Uploading or saving a new generated candidate creates a new Avatar, while choosing an existing Avatar from the asset library targets that same `avatar_id` and adds actions beneath it without copying the source image or aggregate. Accepted-asset maintenance remains in Avatar Asset Management and realtime experience selection remains outside the workspace.
_Avoid_: asset manager, asset-management dialog, Avatar Session Preflight, provider console

**Studio Config Overlay**:
The narrow-viewport control in Avatar Studio that collapses its configuration card into a settings-style toggle floating over the persistent preview, rather than stacking the two side by side. It applies uniformly across every Avatar Studio tool and step; the desktop/tablet side-by-side layout is unaffected.
_Avoid_: Page Form, Experience Surface, mobile drawer, bottom sheet

**Existing Avatar Action Creation**:
The Avatar Studio path entered by selecting an existing Avatar source image from the library or using `创建动作` from its detail. It fixes the parent `avatar_id`, shows the Avatar name and immutable source image as a completed read-only first stage, and places focus directly on action creation; changing the selection returns to the library and targets another Avatar without mutating either asset. Entry from an Avatar detail bypasses the picker, and the persistent preview continues to show the chosen likeness and generated motion. This path creates only new child Avatar Actions and never a duplicate Avatar. `创建副本` is a separate explicit command that creates a new Avatar ID from a new draft and never copies actions automatically.
_Avoid_: image reuse as new identity, implicit Avatar copy, action library import, source-image replacement

**Avatar Studio Draft**:
One identified unsaved Avatar creation state. A tool may retain multiple drafts but exposes only one Active Studio Draft at a time; saving, clearing, or expiring one draft never changes another draft or implies asset acceptance.
_Avoid_: saved asset, shared workspace state, sidebar selection, generation task authority

**Avatar Studio Completion**:
The explicit `完成` command available after a new source image has been saved and received its Avatar ID, regardless of whether the user created any actions or whether accepted-action preparation is still running. Completion navigates to that Avatar's detail, where `尚未创建动作`, background progress, `创建动作`, and `开始对话` are presented as applicable; it never starts a conversation or drops the user at an unscoped catalog.
_Avoid_: automatic conversation start, asset-list redirect, implicit action creation, preparation wait gate

**Active Studio Draft**:
The one Avatar Studio Draft currently open for editing in a selected tool. Switching tools or activating another draft preserves it without confirmation, while leaving the workspace with any non-empty draft requires a leave-or-discard decision.
_Avoid_: only tool draft, saved asset, current catalog selection, generation task

**Studio Draft Display Name**:
The user-editable label used only to recognize one Avatar Studio Draft. It is suggested from the Avatar, action preset, and creation time, while changing it never renames an Avatar, action, candidate, or other accepted asset.
_Avoid_: Avatar Display Name, asset name, immutable draft ID, generation task name

**Full Studio Draft Recovery**:
Restoration of every retained Avatar Studio Draft after refresh or reopening in the same browser, including each tool's Active Studio Draft, text, selections, current step, privately staged local media, upload progress, unfinished generation work, and current candidate preview. Staged media remains an unsaved draft asset and never enters a formal catalog without explicit acceptance.
_Avoid_: form-only recovery, saved asset, browser file handle, automatic asset acceptance

**Studio Draft Retention**:
The rolling seven-day lifetime of each Avatar Studio Draft after its own last edit. The workspace exposes the Active Studio Draft's expiry and an immediate-clear command; expiry or manual clearing removes only that draft's staged media and unsaved candidates, never accepted assets or any other draft.
_Avoid_: permanent draft, asset retention, shared expiry, browser cache lifetime

**Studio Draft Limit**:
The maximum of ten retained Avatar Studio Drafts per creation tool. Reaching the limit blocks new drafts until the user saves or clears one; the workspace never auto-deletes an unexpired draft to make room.
_Avoid_: shared workspace limit, automatic oldest-draft eviction, accepted asset limit, generation concurrency

**Motion Base Studio**:
The action-creation stage inside Avatar Studio: a guided, revisable journey with a persistent Avatar library, continuous Driving Performance selection, a Motion Creation configuration area, and a result preview. It creates only loopable video candidates that may become Avatar Actions; single-frame pose editing, provider diagnostics, future-model catalogs, and model benchmark experiments are not part of it.
_Avoid_: internal lab, model evaluation page, provider console, digital-human video factory

**Avatar Library**:
The persistent Avatar catalog available to creation flows. It combines accepted Avatars, curated references, OpenTalking source materials, search, category filtering, and authorized upload; selecting an entry changes only the current Studio Draft until the user explicitly saves or applies a resulting asset.
_Avoid_: workbench tool navigation, on-demand identity drawer, Motion Base catalog, automatic asset selection

**Motion Creation Service**:
A currently available, user-selectable service that creates a Motion Base Candidate from an Identity Source Image and service-specific creative input. Its selection card identifies the product capability and actual service together with suitability, limits, expected completion time, estimated charge, and current availability. The user explicitly chooses among available services such as generative image-to-video or motion-driven portrait animation; the product never silently routes the request to another service or displays unavailable future services as choices.
_Avoid_: automatic provider routing, TODO model card, generation method without a runnable service, provider diagnostic

**Initial Motion Creation Scope**:
The first user-facing Motion Base Studio offers only `自然交互动作复刻` through LivePortrait, driven by one continuous Natural Interaction Performance rather than a mutually exclusive single-action preset. LivePortrait creates non-verbal motion only; speech audio and lip synthesis remain exclusively downstream, while `智能生成`, Vidu, service selection, provider credits, prompts, future-service entries, and lip-sync evaluation are absent until a later product decision introduces another complete service.
_Avoid_: single-action preset picker, hidden Vidu path, disabled intelligent-generation card, future-model teaser, automatic service choice

**Motion Base Upload**:
The Motion Base Studio input path that ingests an existing authorized silent video as a Motion Base Candidate for the draft's selected Avatar. It creates an unsaved candidate for review and never changes Avatar Asset Management until the user explicitly saves and applies it.
_Avoid_: video generation service, third creation method, Provider generation, automatic Motion Base selection

**Avatar Action**:
A named reusable action belonging to exactly one Avatar and identified by its own stable Avatar Action ID. An Avatar may have zero or many actions; each action owns one accepted motion video and its independent Lip-sync Model Preparation state without creating another Avatar.
_Avoid_: Avatar, action preset, Driving Performance, finished speaking video

**Avatar Action Acceptance**:
The user's explicit `确认并创建动作` command after previewing a generated or uploaded action's identity stability, motion quality, closed-mouth behavior, camera stability, and loop. The command itself is the acceptance act and requires no redundant confirmation checkbox; deterministic media failures block it, while visible quality risks remain part of the user's preview judgment. Selecting or saving an Avatar source image never creates, accepts, or silently derives an Avatar Action.
_Avoid_: automatic static action, image acceptance, generation success, implicit segmented readiness

**Avatar Action ID**:
The stable identifier of one Avatar Action, exposed as `avatar_action_id` in APIs and storage and `avatarActionId` in TypeScript. It remains stable across preparation retries and media renditions and is never inferred from an action name or array position.
_Avoid_: action index, Motion Base ID, Renderer Asset ID, Avatar ID

**Avatar Action Display Name**:
The user-editable, non-empty label used to recognize an Avatar Action within its parent Avatar. A template suggests its plain-language name, a custom driver suggests a numbered `自定义动作`, and duplicate labels receive a numbered suggestion; renaming never changes the Avatar Action ID or retriggers model preparation.
_Avoid_: Avatar Display Name, action type, Avatar Action ID, model preparation key

**Avatar Session Action**:
The single Avatar Action bound by one first-release Avatar Session Choice. An Avatar may offer many actions for preview and selection, but the session never switches between them automatically; semantic action routing requires a separate future Renderer contract.
_Avoid_: action set, automatic state mapping, all actions on an Avatar, Driving Performance

**Avatar Visual Source**:
The explicit segmented-rendering source selected for one Avatar Session Choice: either the Avatar's accepted Identity Source Image or one accepted Avatar Action. Renderer-specific image derivatives may be created during model preparation, but they never become or receive the identity of an Avatar Action.
_Avoid_: automatic action, Hosted Avatar, Renderer Asset, implicit fallback source

**Image-bound Avatar Conversation Test**:
A user-started segmented conversation test that binds an Avatar's accepted source image directly, without requiring an offline effect preview, action creation, or action acceptance. It prepares only the Lip-sync Model selected for that test, reuses a matching cached Renderer asset when available, and starts automatically when just-in-time preparation succeeds; other models never delay the current test.
_Avoid_: Avatar Action preview, image acceptance flow, automatic action, offline lip-sync comparison

**Motion Base Video**:
A silent, naturally closed-mouth reusable video belonging to one Avatar Action and prepared for segmented lip-sync rendering. It may be built in, uploaded, or generated, but it contains no synthesized speech mouth motion, is not a Hosted Avatar, and does not define the character's Persona.
_Avoid_: Hosted Avatar, source image, finished speaking video, Avatar Identity

**Built-in Avatar Pack**:
A curated set of example Avatars available without user upload. Every entry includes recognizable source imagery and may include an Avatar Action paired only with that same Avatar; a paired video is never a cross-Avatar action template.
_Avoid_: generic action library, shared driving-video pack, processed avatar cache, Hosted Avatar catalog

**Motion Base Candidate**:
A generated, uploaded, or provider-hosted video awaiting identity, closed-mouth, camera, format, and rights review. It is previewable but not selectable as a Motion Base Video, and its provider URL may be temporary until the user explicitly accepts and durably saves it.
_Avoid_: Motion Base Video, automatically imported asset, selected avatar, Lip-sync Test Preview

**Current Motion Base Candidate**:
The single unsaved generation result shown in Motion Base Studio. A regeneration keeps the current preview visible until the replacement succeeds, replaces it only on success, and retains it when regeneration fails; the product does not expose candidate history or multi-result comparison.
_Avoid_: candidate gallery, generation history, three-result comparison, automatic saved asset

**Motion Base Acceptance**:
The explicit approval of one Motion Base Candidate that copies its original provider or uploaded media into configured object storage as an immutable source master, together with its metadata, source, content hash, and Avatar link. Acceptance never destructively normalizes or overwrites that master and does not imply an Avatar Session Choice; Preflight state and any playback rendition remain separately recorded even when one workflow proceeds directly to experience.
_Avoid_: generation success, upload completion, automatic catalog entry, current selection

**Save and Experience Motion Base**:
The user-facing command labeled `保存并体验` that approves the current Motion Base Candidate, completes required media preparation, and opens Avatar Session Preflight with the resulting Avatar Action as a temporary choice. It never starts services or commits the Last Successful Avatar Session Choice; `仅保存到动作库` performs the same acceptance while remaining in Motion Base Studio.
_Avoid_: Save and Use, automatic selection, automatic session start, generation success

**Motion Base Source Master**:
The immutable original media retained when a Motion Base Candidate is accepted, preserving its provider or upload duration, aspect ratio, frame rate, codec, and audio facts. Mobile and desktop presentation requirements never overwrite the master; any derived playback media remains separately traceable to it.
_Avoid_: playback rendition, normalized five-second clip, temporary provider URL, current selection

**Motion Base Rendition Profile**:
One target-specific playback derivative linked to a Motion Base Source Master. The first release requires independently previewed and stored Mobile Fullscreen (720x1280) and Desktop Fullscreen (1280x720) profiles, both 25 fps, H.264, and silent, each with its own administrator-approved crop position; neither profile overwrites or becomes the source master.
_Avoid_: source master, responsive CSS only, second Motion Base Video, destructive normalization

**Motion Base Readiness**:
The state in which at least one Mobile Fullscreen or Desktop Fullscreen Rendition Profile has passed acceptance, making the Motion Base Video selectable. If the current device lacks its accepted profile, the player applies Rendition Fit Policy temporarily and labels the result as a temporary aspect adaptation rather than blocking selection or pretending a stored profile exists.
_Avoid_: both-renditions gate, silent fallback, persisted temporary rendition, source-only readiness

**Required Lip-sync Model Set**:
The versioned set of currently enabled, deployed, and compatible Lip-sync Models that a newly created motion asset must prepare before becoming available. Catalog-only experiments, unavailable runtimes, and models requiring incompatible source material are excluded; later additions create maintenance work for existing assets without revoking their previously established availability.
_Avoid_: every catalog entry, preferred model, evaluation candidate, permanent global list

**Lip-sync Model Preparation**:
The model-specific processing of one Avatar Visual Source into reusable renderer material, tracked independently for each source, model, and model version. Successful work is retained across retries, and preparing an image or one model never creates an Avatar Action or stands in for another model's readiness.
_Avoid_: Wav2Lip preparation, runtime session startup, Lip-sync Test Preview, whole-asset readiness

**Avatar Action Readiness**:
The lifecycle assigned after one motion asset receives its stable action ID: `processing` while its Required Lip-sync Model Set is being prepared, `needs-attention` when any required preparation fails, and `available` only when every required preparation succeeds. Failed preparation retains the accepted video and successful model outputs, while a later model addition appears as pending maintenance rather than invalidating models that were already available.
_Avoid_: Motion Base Readiness, generation task state, all-or-nothing retry, automatic invalidation

**Avatar Model Backfill**:
The user-triggered preparation of one newly enabled Lip-sync Model for selected compatible existing Avatar Actions from Avatar Asset Management. Enabling a model marks eligible actions `待适配` without automatically consuming compute or revoking existing model readiness; individual and bulk jobs remain independently observable and retryable after navigation. This maintenance operation is distinct from the explicit one-source/one-model preparation authorized when a user starts a conversation with a currently unprepared image or action. Avatar action generation, preparation, and backfill expose state and expected time but have no paid/free classification or charge authorization in the current product scope.
_Avoid_: automatic fleet migration, image test preparation, action regeneration, readiness invalidation

**Rendition Fit Policy**:
The first-release rule for adapting a Motion Base Source Master into a target Rendition Profile: preserve the detected person safe area, use an administrator-adjustable crop when sufficient scene area exists, and otherwise fill missing canvas with a blurred copy or configured solid color. Forced face/body clipping and generative video outpainting are not first-release behavior.
_Avoid_: CSS cover, black bars, AI outpainting, destructive crop

**Motion Base Playback Duration Policy**:
The rule that an accepted Motion Base Rendition preserves its Source Master's duration and loops during segmented rendering. A Lip-sync Comparison Run may temporarily trim or repeat that rendition to a fixed five-second test window, but the temporary window is not saved as another Motion Base Video.
_Avoid_: fixed five-second asset, duration rejection, persisted test clip, source overwrite

**Motion Base Loop Window**:
The administrator-approved loop start, loop end, and short crossfade duration stored independently on each Motion Base Rendition Profile. The system may suggest values, but acceptance requires continuous-loop preview and adjustment; hard end-to-start jumps and ping-pong reversal are not the default.
_Avoid_: source trim, video duration, CSS loop flag, ping-pong playback

**Avatar Artifact Object Store**:
The S3-compatible durable blob store for Identity Source Images, Driving Performances, Motion Base Candidates pending retention, Motion Base Source Masters, derived playback media, and Lip-sync Test Previews. The first deployment uses Cloudflare R2 through a provider-neutral adapter; object metadata never replaces authoritative application records.
_Avoid_: local Artifact Store, database blob column, R2-specific domain API, temporary provider URL

**Avatar Media Access Grant**:
A short-lived signed object-store URL issued only after the server authorizes the current principal or verifies that one asset is explicitly published for anonymous consumption. The R2 bucket remains private, permanent public URLs are forbidden, and ordinary playback does not proxy all media bytes through the application server.
_Avoid_: public bucket URL, application authentication token, permanent CDN link, media proxy endpoint

**Avatar Asset Registry**:
The PostgreSQL authority for Visual Identities, mode-specific assets, generation tasks, ownership category, rights status, content hashes, acceptance decisions, availability, and object-store references. R2 stores media bytes only; object paths or object metadata never become authoritative application state.
_Avoid_: R2 metadata, JSON catalog, filesystem manifest, provider task list

**Generative Image-to-Video (I2V)**:
A Motion Base Video creation method labeled `智能生成` in the product UI, asking a generative video model to evolve one identity image into motion from a text prompt or preset. The model invents motion and pixels probabilistically; it does not copy a specific performance and its result must be normalized and accepted before becoming a Motion Base Video.
_Avoid_: Motion-driven Portrait Animation, image animation, lip-sync, finished speaking video

**Motion-driven Portrait Animation**:
A Motion Base Video creation method labeled `动作复刻` in the product UI, also called portrait reenactment or motion transfer, that applies facial expression extracted from a Driving Performance to an Avatar source image. LivePortrait is one implementation of this method, not the name of the product capability; the first release transfers the face region only, so the Avatar's head and body remain at their source pose.
_Avoid_: Generative Image-to-Video, LivePortrait generation, lip-sync, prompt-generated motion

**Driving Performance**:
A user-uploaded or curated video, pose sequence, or privacy-preserving motion template whose movement controls Motion-driven Portrait Animation. It supplies motion rather than identity and is not itself the resulting Motion Base Video.
_Avoid_: Motion Base Video, identity image, prompt template, finished speaking video

**Natural Interaction Performance**:
A continuous non-verbal Driving Performance for conversational presentation whose facial expression (blinking, gaze, micro-expression, and closed-mouth non-verbal motion) drives the Avatar. Head pose, breathing presence, and body sway may appear in the reference but are not transferred; the Avatar's head and body stay at the source pose. It is transferred as one timed performance and previewed as a loop, never decomposed into a mutually exclusive blink, nod, or smile preset and never treated as lip-sync input.
_Avoid_: single-action preset, gesture clip, finished talking video, random motion collection

**Motion Base Mouth Neutrality**:
The requirement that a Motion Base Candidate and accepted Motion Base Video remain naturally closed-mouth, contain no synthesized speech mouth motion, and carry no audible source track. LivePortrait owns non-verbal motion creation only; the selected downstream Lip-sync Model exclusively creates mouth motion from actual reply audio.
_Avoid_: LivePortrait lip-sync, talking driving output, muted speech mouth motion, source audio retention

**Speaking-mouth Reference Rejection**:
The server-authoritative refusal of a custom Natural Interaction Performance containing sustained mouth opening, visible speech articulation, or large mouth motion. The user must replace or re-record it as a closed-mouth non-verbal performance; automatic mouth erasure never converts a failing reference into an accepted input.
_Avoid_: warning-only check, silent lip transfer, automatic mouth suppression, downstream Wav2Lip validation

**Natural Interaction Performance Duration Policy**:
The first-release duration contract requiring curated Natural Interaction Performances to last eight to ten seconds and custom uploads or recordings to be trimmed to five to fifteen seconds. Advanced configuration tests use a disposable three-second excerpt, while a full Motion Base Candidate preserves and loop-previews the complete selected performance duration.
_Avoid_: fixed three-second asset, unlimited reference video, silent duration truncation, test-preview duration

**Motion Transfer Profile**:
A reproducible, capability-valid set of motion region, amplitude, stabilization, compositing, crop, and output controls applied while transferring one Driving Performance to an Avatar. A recommended profile calibrates a specific reference performance, while an advanced custom profile lets a user override supported controls without redefining the performance's semantic interaction style.
_Avoid_: Driving Performance, interaction style, raw provider config, lip-sync model config

**Advanced Motion Configuration**:
The user-facing expansion of a Motion Transfer Profile beyond its reference-specific recommended values. Its main controls expose only parameters that the bound Motion Creation Service declares effective for the current input form, while imported inactive or unknown fields remain visible only through Motion Parameter Compatibility details. It records every override and compatibility state with the candidate and requires a short test preview before full generation.
_Avoid_: always-visible model console, unsupported control, global default, provider debug form

**Offline Motion Generation Priority**:
The product priority for Motion-driven Portrait Animation as asynchronous asset creation: motion naturalness, identity stability, reproducibility, and parameter preservation take precedence over completion latency. It defines no realtime-generation expectation and allows the user to leave Avatar Studio while the server-owned task continues.
_Avoid_: realtime preview SLA, browser-bound generation, speed-first parameter removal, synchronous page request

**Motion Parameter Compatibility**:
The capability status recorded for every field in an OpenTalking-compatible Motion Transfer Profile: `native` fields execute directly in the bound runtime; first-release `offline extension` fields are explicitly experimental OpenRealtime motion-template transformations that do not claim numeric equivalence to another runtime and require a newly confirmed three-second Test Preview before full generation; `retained inactive` fields are preserved but prohibited by the current non-verbal Motion Base boundary; and `unknown` fields are preserved losslessly without execution. Only effective fields appear as editable creation controls; all others remain auditable in read-only compatibility details and survive supported import-export round trips.
_Avoid_: silent field deletion, stored-means-effective, fake supported control, provider-config passthrough

**Motion Profile Interchange**:
The YAML or JSON import and export boundary for an OpenTalking-compatible Motion Transfer Profile. Import first produces a non-mutating Parameter Mapping Report that groups every field as native effective, experimental effective, retained inactive, or unknown; only explicit confirmation applies effective fields to the draft and attaches the remaining compatibility data. It preserves source format, version, inactive fields, unknown names, and original values; raw configuration remains read-only, and only typed controls may change an effective profile before it is saved or applied.
_Avoid_: raw configuration editor, lossy import, partial parse overwrite, untyped provider passthrough

**Parameter Mapping Report**:
The review state created before an imported Motion Transfer Profile can change a Studio Draft. It shows each source field and value, its mapped user-facing control or inactivity reason, and one of the four Motion Parameter Compatibility states; parsing, viewing, canceling, or closing the report never mutates the draft, while explicit confirmation applies the complete reviewed result atomically.
_Avoid_: import log, partial configuration application, silent compatibility warning, post-apply summary

**Saved Motion Transfer Profile**:
A user-named reusable Motion Transfer Profile that can be applied across compatible Avatar Studio drafts. Applying it copies a parameter snapshot into the draft, so later profile edits or deletion never mutate existing drafts, tasks, candidates, or accepted assets; incompatible profiles are blocked with explicit reasons.
_Avoid_: live-linked global config, draft state, provider preset, candidate metadata only

**Workspace Motion Transfer Profile Catalog**:
The shared set of Saved Motion Transfer Profiles published and maintained by authenticated administrators or Local Avatar Test Mode. Ordinary creators may apply a profile and make draft-local overrides, but cannot overwrite, rename, copy, or delete a shared profile.
_Avoid_: personal preset library, provider configuration, draft-local overrides, anonymous profile publishing

**Driving Performance Catalog**:
The set of curated Natural Interaction Performances plus upload or recording of a custom continuous performance within Motion-driven Portrait Animation. It is presented as previewable driving-performance cards such as `甜美元气`, `纯欲柔光`, `冷艳夜色`, `知性温柔`, and `忧郁共鸣`, each backed by a distinct facial-expression character, duration, and recommended transfer amplitude; each entry is previewed as a whole timed performance with its interaction character, duration, and loop behavior. Blinking, gaze shifts, and micro-expression are descriptive ingredients rather than separate choices, and every output still enters the catalog as a Motion Base Candidate rather than inheriting approval from its driver.
_Avoid_: single-action catalog, Motion Base Video catalog, prompt templates, public stock-video library, automatic approval

**Motion Generation Worker**:
An OpenRealtime-managed asynchronous server worker that runs Motion-driven Portrait Animation and reports the same submitted, queued, processing, failed, and candidate-ready lifecycle used by commercial generation providers. Development may bind LivePortrait to Mac MPS or CPU while deployment may replace it with a remote GPU worker; browsers never install or execute the model.
_Avoid_: browser inference, external generation link, Realtime Renderer, Vidu adapter

**Avatar Generation Coordinator**:
The PostgreSQL-backed server coordinator that owns Vidu and LivePortrait task state independently of any browser page, schedules serial provider polling or worker execution, and resumes unfinished work after process restart. Pages observe its durable state; they never become the authority for task lifetime, locks, or terminal transitions.
_Avoid_: browser polling owner, localStorage task, Provider webhook only, overlapping interval polling

**Lip-sync Test Preview**:
A short, disposable speaking preview produced by applying one Lip-sync Model to a Motion Base Video and test audio. It is comparison evidence only: it neither replaces the Motion Base Video nor becomes an exported finished speaking video.
_Avoid_: Motion Base Video, production render, published video, renderer session

**Lip-sync Comparison Run**:
A controlled evaluation that applies the same Motion Base Video and fixed test audio to at least two Lip-sync Models and presents their Lip-sync Test Previews side by side. The first release compares Wav2Lip 96 with DH_live_mini; MuseTalk remains a later candidate.
_Avoid_: finished speaking video, single-model preview, voice comparison, production render

**Lip-sync Comparison Input**:
The administrator-selected primary Motion Base Rendition used once as the shared visual input for a Lip-sync Comparison Run. Wav2Lip 96 and DH_live_mini both consume that exact rendition and fixed five-second audio; another device aspect is temporarily adapted after lip-sync rather than triggering a second pair of model runs.
_Avoid_: Source Master, four-preview aspect matrix, per-model crop, production input

**End-to-End Realtime Avatar Rendering**:
The hosted rendering path from accepting OpenRealtime-authored Spoken Content or streaming speech audio through producing synchronized, interruptible avatar media on the client. Its end-to-end boundary covers optional managed TTS, avatar inference, transport, playback, and cleanup only; it excludes user speech recognition, Brain reasoning, persona, memory, and tool execution.
_Avoid_: End-to-End Digital Human, Full Agent, Turnkey Avatar Agent, full conversational pipeline

**Managed Speech Avatar Rendering**:
A hosted Avatar Renderer mode that accepts OpenRealtime-authored streaming Spoken Content, performs TTS and face generation as one provider pipeline, and returns synchronized audio and video. OpenRealtime supplies the Brain output and retains correlation and interruption authority; the provider voice is part of presentation configuration rather than character intelligence.
_Avoid_: Turnkey Persona (would include provider Brain), Audio Passthrough (accepts audio instead of text), native Realtime Engine

**Avatar Surface**:
The client presentation boundary that displays one Avatar Renderer's output, such as a WebRTC video track or a browser-rendered Live2D/VRM scene. It owns visual attachment and cleanup but not dialogue, speech generation, or provider credentials.
_Avoid_: Avatar Renderer (the rendering capability), video element (one implementation), page layout

**Experience Surface**:
The single client presentation instance bound to one active Presentation Mode: the configured Orb visual in `对话模式` or the bound Avatar Surface in `数字人模式`. Page Forms arrange this instance without replacing or restarting it, so Renderer, audio ownership, dialogue visualization, and current semantic state remain continuous.
_Avoid_: Page Form, duplicated preview, remounted renderer, layout panel

**Presentation Mode**:
The session-start choice of Experience Surface: `对话模式` binds the configured Orb visual theme, while `数字人模式` starts and binds the configured Avatar Renderer and model services. It is independent of Page Form but remains immutable for an active Voice Session; selecting another Presentation Mode requires ending that Session and starting another.
_Avoid_: Experience Mode, Chat Mode, Avatar Mode, Character selection, Brain mode, Realtime Profile

**Page Form**:
The independently selected spatial form of a live experience: Fullscreen Form, Sidecar Form, or Content Form. It determines the prominence and placement of historical conversation content and the active Experience Surface, while either Presentation Mode may use any Page Form.
_Avoid_: Presentation Mode, Avatar Surface, six combined experience modes

**Fullscreen Form**:
A Page Form in which the Experience Surface is the primary full-window visual and historical conversation content is not shown. The current user or assistant semantic unit may appear transiently, but the form is not a conversation-history browser.
_Avoid_: Stage, kiosk mode, Presentation Mode

**Sidecar Form**:
A Page Form with historical conversation content on the left and the active Experience Surface on the right.
_Avoid_: split Presentation Mode, companion mode, Content Form

**Content Form**:
A Page Form in which conversation content is primary and the active Experience Surface remains visible in a small companion window. Activating that surface enters Fullscreen Form without opening another Voice Session.
_Avoid_: Chat Mode, picture-in-picture mode, Sidecar Form

**Speaker Evidence**:
A time-bounded, model-versioned voiceprint or speaker-analysis observation with confidence and provenance. It may inform Turn Manager or Control Plane policy but never replaces authenticated user identity or independently authorizes a protected action.
_Avoid_: User identity, voice authentication, speaker truth

**Speech Renderer**:
The replaceable Cascaded Realtime Engine capability that derives Spoken Content from Semantic or Display Content when no explicit Spoken Content was supplied. The default renderer is deterministic and formatting-aware but never summarizes or invents facts; any model-backed summarizing renderer is an explicit, separately metered choice.
_Avoid_: TTS (synthesis only), text cleaner (too narrow), Brain (owns conversational intelligence rather than speech presentation)

**Conversation Projection**:
A derived, provider- or Agent-specific context view built from Conversation Journal for a bounded model context window. It may summarize, filter, redact, or translate canonical Conversation Items but never becomes authoritative and can be rebuilt after reconnect, provider replacement, or process restart.
_Avoid_: Conversation Journal, prompt, provider history

**Context Budget**:
The versioned token allowance within which one Conversation Projection must fit after reserving capacity for model output, tools, governing instructions, current input, and safety margin. Every projected section reports its measured or conservatively estimated cost and priority.
_Avoid_: Model context window (the provider ceiling), character limit, truncation length

**Context Policy**:
The versioned Application Control Plane policy that defines Context Budget allocation, projection priority, summary compatibility, and the independently selected Context Compressor. It applies consistently across Realtime Engines and is not inherited implicitly from a Realtime Profile or chat model.
_Avoid_: Realtime Profile, prompt template, model settings, Memory policy

**Conversation Summary Checkpoint**:
A versioned, derived Conversation Item that compresses an exact source sequence range while preserving provenance, unresolved work, material decisions, and invalidation metadata. It can replace its covered raw items only inside a Conversation Projection; it never replaces or rewrites them in Conversation Journal.
_Avoid_: Memory, Conversation Projection, chat title, destructive compaction

**Context Compressor**:
The background derivation capability that combines deterministic extraction of typed work and references with model-assisted narrative compression to produce a validated Conversation Summary Checkpoint. It cannot mutate authoritative Journal, task, confirmation, or artifact state.
_Avoid_: Conversation Projector, Memory extractor, Brain, summarizing Speech Renderer

**Context Visibility Barrier**:
A minimum committed thread sequence that a Realtime Conversation must successfully project before it may execute a dependent response request. It orders Agent-result and other Journal-first injections against generation without making a provider conversation authoritative.
_Avoid_: Database lock, response delay, provider item ID

**Event Ledger**:
The best-effort operational fan-out used by read-only Observers for logs, metrics, and diagnostics. It may contain high-volume runtime events and may be lossy depending on its conformer; it is never the durable conversation history, an ordering authority, or a message bus.
_Avoid_: Conversation Journal, event store, command bus

**Persistence Unit of Work**:
The transaction boundary that atomically coordinates PostgreSQL-backed Conversation Journal, Agent Task Store, tool/confirmation state, Workspace Leases, delivery state, and Transactional Outbox. It preserves modular repository Protocols while preventing cross-store dual writes inside one database.
_Avoid_: database session (implementation detail), Conversation Kernel transaction, distributed transaction

**Transactional Outbox**:
PostgreSQL rows written in the same transaction as authoritative state and later claimed for at-least-once delivery with idempotent consumers. It is the only supported bridge from committed database state to asynchronous dispatch; publishing directly before commit is forbidden.
_Avoid_: Event Ledger, task queue (a downstream transport), Agent Task Store

**Artifact Store**:
The S3-compatible object-storage Seam for raw audio when retention permits, generated media, large Agent results, archives, patches, and other blobs. PostgreSQL owns artifact metadata/lifecycle; conversation/task records refer only to opaque `artifact_id`, never public URLs or provider-specific bucket keys.
_Avoid_: Conversation Journal, filesystem workspace, S3 bucket (one implementation)

**Artifact Reference**:
An immutable, tenant-scoped reference containing `artifact_id`, media type, size, digest, classification, and lifecycle/retention metadata. Resolving it to a short-lived download/upload URL is an authorized Artifact Store operation; the URL itself is not durable conversation content.
_Avoid_: URL, file path, inline blob

**Native Realtime Engine** / **Cascaded Realtime Engine**:
The two supported Realtime Engine forms. A Native Realtime Engine uses an end-to-end realtime voice model; a Cascaded Realtime Engine composes independently replaceable speech, dialogue, and Brain capabilities behind the same stateful session contract.
_Avoid_: Pipeline Engine, RealtimeSession, legacy engine, fallback engine

**Conversation Kernel** (legacy, removed):
The former per-connection coordinator, removed in the Phase 1 M6 replacement. New code uses Voice Session Runtime for lifecycle/recovery and Realtime Engine for live conversational execution; the term remains only in historical ADRs.
_Avoid_: using this term for current runtime code

**Router**:
The framework Seam that decides, per turn, whether to answer via the built-in default Chat Brain or delegate to a registered external Agent. Ships with a default policy and is itself user-customizable/replaceable.
_Avoid_: Delegation logic, dispatcher

**Endpoint Session**:
The Seam owning logical transport continuity independent of any one physical Transport Adapter connection. `EndpointSession` conforms to the Transport Adapter contract (`receive`/`send`/`close`), while `EndpointSessionRegistry` owns protocol negotiation, authenticated hello/resume, rotating single-use resume tokens, attach/detach, and the grace timer. It does not restore semantic Journal, model, Work, or confirmation state; the Voice Session Runtime recovery barrier owns that. `InMemoryEndpointSession` is single-process only. See [ADR-0019](docs/adr/0019-endpoint-session-reconnect-resume.md) and [Voice Runtime Alignment](docs/VOICE-RUNTIME-ALIGNMENT.md).
_Avoid_: Session (too generic), Connection (a physical Transport Adapter instance, not the logical session that outlives it)

**Transport Adapter**:
A pluggable implementation of the Endpoint Session's wire protocol (e.g. Raw WebSocket, LiveKit/RTC, MQTT, raw UDP) behind one protocol-agnostic contract. v1 ships Raw WebSocket + raw UDP; LiveKit/MQTT remain contract-only, since a generic stub would be indistinguishable from the existing `FakeTransport` test double — each needs either a live external service or a new SDK dependency, a decision deferred rather than papered over. `UdpTransportAdapter` demultiplexes the connectionless socket by peer address to preserve the same per-connection adapter shape as WebSocket.
_Avoid_: Protocol handler, connector

**Turn Manager**:
The sole replaceable Seam in a Cascaded Realtime Engine that owns Dialogue State, end-of-turn decisions, turn admission, and conversational-floor arbitration. It consumes VAD, ASR, playback, timing, and semantic signals; only the Turn Manager may commit or reject a user turn or declare a Barge-in.
_Avoid_: Turn Policy (legacy narrower term), dialogue-state module (does not express turn authority), VAD module, ASR endpointing

**Dialogue State**:
One of five states — IDLE (no active stream), LISTEN (user speaking, assistant silent), SPEAK (assistant speaking, user silent), WAIT (assistant paused mid-turn after user hesitation, monitoring before resuming — not the same as IDLE), DUAL (both streams active with genuine mutual integration, not just simultaneous audio). Canonical model adopted from the full-duplex survey (arXiv 2606.19453) §6. See [full-duplex-survey.md](docs/full-duplex-survey.md) for the full state/transition reference.
_Avoid_: Turn phase, conversation state (project uses "Dialogue State" specifically for this 5-value FSM)

**Voice Session Phase**:
The lifecycle of one live voice interaction: INACTIVE, STARTING, ACTIVE, RECONNECTING, STOPPING, or CLOSED. It is independent of Dialogue State and says whether the session can accept work, not who currently holds the conversational floor.
_Avoid_: Session state, Dialogue State, connection state

**Voice Session**:
One user-facing live voice interaction, identified by `voice_session_id`, that owns its phase, dialogue state, work registry, and conversation correlation across reconnects. It is distinct from an Endpoint Session, which provides transport continuity, and from a persistent thread, which may outlive a live voice interaction.
_Avoid_: Session (too generic), Endpoint Session, thread

**Interaction Context**:
The immutable identity and correlation envelope carried across every Seam. It identifies tenant, user, device, Voice Session, thread, turn, generation, and—when applicable—the correlated tool call, Delegated Task, confirmation, or handoff.
_Avoid_: Metadata, request context, tracing context

**Turn ID**:
The stable identity of one accepted user turn. It remains unchanged while that turn produces tools, delegated work, and results; Generation is a separate monotonic supersession token that may invalidate output without changing identity semantics.
_Avoid_: Generation, request ID

**Work Registry**:
The live, session-local projection of active fast-tool calls, Delegated Tasks, and pending confirmations for one voice interaction. It supports fast orchestration queries but is not restart authority: Agent Task Store and other execution backends own durable lifecycle, while Conversation Journal owns semantic history. Independent work may coexist and complete out of order.
_Avoid_: Work state, task state machine, pending work flag

**L0/L1/L2/L3 (Architectural Hierarchy)**:
Classification of WHERE a duplex/turn-taking decision is computed, from the full-duplex survey §4. L0 = external module pipeline (VAD/EoT/turn-classifier feeding a text LLM) — this project's Cascaded Turn Manager is L0 by construction, since it is a pluggable-module framework, not an end-to-end trained duplex model (L1 = hidden-state predictor, L2 = token-level, L3 = shared-latent, unrealized by any system). The project explicitly accepts the "L0 ceiling": DUAL-state discrimination (backchannel vs. barge-in vs. third-party) is achieved via bolt-on classifier plugins, not native architectural integration. See [full-duplex-survey.md](docs/full-duplex-survey.md).
_Avoid_: Duplex level, tier (use "L0/L1/L2/L3" verbatim — it's the paper's own notation and cross-references it directly)

**Backchannel**:
A short listener-support utterance from the user during assistant SPEAK (e.g. "嗯"/"对") that must NOT stop the assistant. Corresponds to survey ontology cell (T3,I2,R1) — DUAL→SPEAK via τ8 then τ10, continue. See [full-duplex-survey.md](docs/full-duplex-survey.md).
_Avoid_: Interruption (backchannel is explicitly not an interruption — conflating the two is the single most-cited failure mode in the survey)

**Barge-in**:
The user reclaiming the floor while the assistant is speaking, requiring the assistant to stop within ~200ms. Corresponds to survey ontology cell (T3,I4,R2) — DUAL→LISTEN via τ8 then τ9, yield. See [full-duplex-survey.md](docs/full-duplex-survey.md).
_Avoid_: Interruption (use Barge-in when specifically meaning cooperative floor-reclaiming; "interruption" is not a canonical term in this project)

**Third-party speech**:
Audio detected during assistant SPEAK that is not addressed to the assistant (e.g. user talking to a colleague) and must be ignored. Corresponds to survey ontology cell (T3,I7,R5) — DUAL→SPEAK via τ8 then τ11, ignore. Same destination state as Backchannel but driven by a different intent classification. See [full-duplex-survey.md](docs/full-duplex-survey.md).
_Avoid_: Noise, off-topic speech

**Canonical Tool Schema**:
The single versioned internal description of a tool. MCP servers, function-calling declarations, skills, and Agent permission requests are normalized into this shape before policy or model exposure. Its public Tool Descriptor is separate from its private Tool Binding/executor, so models see schemas and approved metadata but never handlers, credentials, or authority. See [ADR-0001](docs/adr/0001-two-layer-external-agent-integration.md) and [ADR-0051](docs/adr/0051-server-authoritative-tool-policy-gateway-and-bound-confirmation.md).
_Avoid_: Tool schema, function schema (use "Canonical Tool Schema" specifically for the normalized, post-adaptation shape)

**Tool Request**:
An untrusted, correlated request to invoke one versioned Canonical Tool with proposed arguments. It may originate from a Realtime Engine, MCP provider, external Agent, or application code, but carries no execution authority until Tool Policy Gateway returns an Execution Grant.
_Avoid_: Tool call (ambiguous between request and execution), command, permission

**Tool Policy Gateway**:
The sole Application Control Plane authority that validates a Tool Request, resolves its Tool Descriptor, evaluates identity/policy/risk/budget, obtains confirmation when required, and returns allow, confirmation, background-delegation, or deny. Provider adapters and Agent Drivers cannot bypass or duplicate it.
_Avoid_: Tool Registry (discovery/binding only), Tool Executor, confirmation handler

**Execution Grant**:
A short-lived, single-purpose authorization produced by Tool Policy Gateway and bound to subject, Voice Session, tool name/version, canonical argument digest, scopes, budget, expiry, and idempotency key. Tool Executor accepts a grant rather than trusting a model- or client-originated request directly.
_Avoid_: API key, permission boolean, confirmation result

**Bound Confirmation**:
A user approval decision tied to one exact action digest, subject, prompt, expiry, and `confirmation_id`. It can satisfy only the matching pending Tool Request; a generic or replayed spoken "yes" has no authority over another action.
_Avoid_: Consent (too broad), voice authentication, permission policy

**Fast Tool Loop**:
The bounded sequence of Canonical Tool calls a Realtime Engine may request while resolving one response. It is constrained by call count, elapsed time, cost, permissions, and cancellation; work that cannot stay within those bounds belongs in background delegation.
_Avoid_: Agent loop, unlimited tool loop, single tool call

**Agent Driver Protocol**:
The universal capability/lifecycle contract Agent Task Supervisor uses for every external Agent backend: start idempotently, resume/reattach, query status, stream typed events, provide input, cancel, and close. Each backend Driver translates its native thread/run/session protocol into this contract and declares unsupported capabilities explicitly. See [ADR-0053](docs/adr/0053-isolated-agent-execution-sessions-and-codex-first-driver.md).
_Avoid_: Agent Session Protocol (legacy v1), ACP, delegation protocol

**Agent Session Protocol** (legacy v1):
The existing `create_session`/`send_turn`/`latest_update`/`cancel`/`result` interface used by current ACP and in-memory Drivers. It remains a migration adapter but is too weak for durable deduplication, resume, capability negotiation, status reconciliation, and multi-backend supervision; new production work targets Agent Driver Protocol.
_Avoid_: Agent Driver Protocol (the accepted target), Conversation Session

**Delegated Task**:
A durable background unit of work assigned to one named external Agent through Agent Task Supervisor and tracked by `worker_id`. Multiple Delegated Tasks may coexist; each has one strict lifecycle, stable idempotency identity, progress, cancellation, result, and budget. Reconnect, replay, or duplicate callbacks must resolve to the existing record rather than spawn again.
_Avoid_: Turn task (a local coroutine for one conversational turn), Agent worker, pending delegation

**Agent Task Supervisor**:
The Application Control Plane authority for accepting, deduplicating, starting, observing, cancelling, recovering, and completing Delegated Tasks across named Agent Drivers. It persists state before side effects, owns concurrency/lease/fan-out budgets, and is the only module allowed to create an Agent execution.
_Avoid_: Work Registry (live projection), Agent Session Protocol (backend contract), Router, worker pool

**Agent Task Store**:
The durable, revisioned store of Agent Task Records and dispatch state. It provides atomic create-or-get, lifecycle compare-and-swap, lease/fencing, idempotent callback ingestion, and restart reconciliation; it is not the semantic Conversation Journal.
_Avoid_: Work Registry, Conversation Journal, queue

**Delegation Request ID**:
The stable idempotency identity of one requested Agent execution, preserved across provider retries, reconnects, and delivery retries. Within its tenant/thread scope, identical ID plus identical canonical request returns the existing `worker_id`; identical ID with changed content is a conflict.
_Avoid_: `worker_id` (identity of the accepted task), task fingerprint (best-effort duplicate hint), Turn ID

**Agent Selection Plan**:
The immutable, policy-produced plan for one Delegated Task: primary Agent, ordered explicitly allowed fallbacks, required capabilities, cost/latency limits, workspace/security constraints, and confirmation rules. It is evaluated against BackendCatalog and health before backend start; no Driver may invent an unlisted fallback.
_Avoid_: Agent name, Router result, load-balancer policy

**Agent Backend Health**:
A time-bounded capability/auth/runtime assessment of one BackendCatalog entry: AVAILABLE, DEGRADED, UNAVAILABLE, or UNKNOWN, with reason and observed Driver/model/schema versions. It informs pre-start selection but is never proof that a previously issued start did not execute.
_Avoid_: process alive, circuit breaker (one input), Agent task state

**Backend Commit Point**:
The irreversible orchestration boundary at which Supervisor issues the first backend start side effect for a `worker_id`. Before it, an allowed fallback may be selected within the same task; after it, target Agent is locked and any migration requires a new `worker_id` plus explicit Handoff Package.
_Avoid_: task accepted, AgentRunStarted callback (may arrive after the side effect), result commit

**Result Delivery Policy**:
The policy that decides when and how a completed Delegated Task becomes user-visible: announce when idle, queue a notification, remain silent until asked, or—only with server-authorized urgency—preempt. Agent callbacks can report results but cannot speak directly or mark themselves urgent.
_Avoid_: Response Scheduler (delivery mechanism), Generation lease, Agent callback

**Agent Execution Session**:
The isolated logical backend conversation owned by exactly one `worker_id` while a Delegated Task runs. A shared CLI process, daemon, or connection pool may host many Agent Execution Sessions, but their history, permissions, workspace lease, backend IDs, and event streams cannot leak across tasks.
_Avoid_: Driver process, Voice Session, provider thread (one backend representation)

**Agent Capability Descriptor**:
The versioned facts a Driver reports about its backend—resume, status lookup, idempotent start, event streaming, steering/input, cancellation, permission bridge, workspace isolation, structured result, and artifact support. Supervisor plans only from declared capabilities and fails explicitly when a required one is absent.
_Avoid_: Tool Descriptor, feature flags, BackendCatalog config

**Workspace Lease**:
A time-bounded, task-scoped grant describing which workspace an Agent Execution Session may access and in what mode: read-only, private writable worktree/copy, or explicitly exclusive shared workspace. It carries a fencing token and is released/reconciled by Agent Task Supervisor.
_Avoid_: `cwd` string, sandbox profile, repository lock

**Handoff Package**:
The explicit, immutable context passed when work moves between Agents: objective, constraints, selected Conversation Item references, artifact references, source `worker_id`, unresolved questions, permissions, and remaining budget. Hidden backend session memory and mutable shared cwd are never treated as handoff context.
_Avoid_: Prompt, Conversation Projection, shared memory

**Driver** (backend driver):
The backend-specific conformer registered against Agent Driver Protocol. It translates native thread/run/session identifiers, streaming events, permission requests, resume/status, cancellation, and result shapes without owning orchestration policy, deduplication, budgets, or delivery. Agent Task Supervisor—not Router—invokes named Drivers selected through BackendCatalog. `InMemoryDriver` remains deterministic/test-only; `CodexAppServerDriver` is the first selected full-conformance target.
_Avoid_: Transport Adapter, Agent Task Supervisor, backend policy

**BackendCatalog**:
A declarative name-to-versioned-backend-config mapping from an Agent name to Driver kind, launch/endpoint/auth profile, capability requirements, workspace policy, and version constraints. A Driver Factory builds heterogeneous Agent Driver Protocol conformers such as Codex App Server, ACP/Hermes, or Claude stream-json. It no longer assumes every entry is one `AcpDriver`. See [ADR-0031](docs/adr/0031-backend-catalog-and-delegation-policy-agent-selection.md) and [ADR-0053](docs/adr/0053-isolated-agent-execution-sessions-and-codex-first-driver.md).
_Avoid_: Backend registry, agent registry (use "BackendCatalog" for this specific name→launch-config mapping)

**Observer**:
An async, read-only subscriber to the Event Ledger's fan-out — used for logging, analytics, and other side effects. Cannot mutate the pipeline. See [ADR-0002](docs/adr/0002-dual-hook-mechanism.md).
_Avoid_: Listener, Hook (reserve "Hook" for the general concept; "Observer" specifically means the read-only, async variant)

**Hook Point**:
A named, synchronous, in-line interception point inside a Seam's default implementation (e.g. `asr.before_turn_policy`) where user middleware may transform or veto a value in flight. Default behavior is a no-op passthrough. Distinct from Observer, which cannot mutate. See [ADR-0002](docs/adr/0002-dual-hook-mechanism.md).
_Avoid_: Middleware (use "Hook Point" for the named site; middleware is what a user attaches to one), Filter

**Device Fleet**:
The Seam owning device activation, OTA firmware distribution, and device inventory for multi-device ecosystems (e.g. Xiaozhi-style hardware). The framework defines and ships only the standardized contract (`activate`/`checkFirmware`/`listDevices`) plus a minimal in-memory default — never a production-grade fleet-management implementation. Distinct from Transport Adapter (wire protocol) and Tool Normalization (device-side tool announcement), which are separate Seams covering the other two device-ecosystem concerns. `InMemoryDeviceFleet` is its first implementation — deterministic and test/demo-controllable only, not a real backend integration. See [ADR-0003](docs/adr/0003-device-fleet-as-standardized-seam.md).
_Avoid_: Device management, fleet manager (use "Device Fleet" for the Seam specifically)

**Knowledge Base**:
The retrieval contract (`search(query, top_k) -> list[str]`) for grounding a Brain's answer with external passages (PRD point 8: RAG/知识库/MCP等外部知识注入). Deliberately not a Seam — retrieval is exposed to Brains via `KnowledgeBaseToolSource`, a `ToolSource` adapting it into the existing Canonical Tool Schema, since search is exactly a tool call (arguments in, text out). `InMemoryKnowledgeBase` is its first implementation — deterministic, in-process, case-insensitive substring match, never a real vector-search/RAG backend. See [ADR-0010](docs/adr/0010-knowledge-base-as-tool-source.md).
_Avoid_: RAG (reserve for the general technique; "Knowledge Base" is this project's specific retrieval contract), vector store (an implementation detail a real `KnowledgeBase` backend might use, not the contract itself)

**WebSearch**:
The retrieval contract (`search(query, top_k) -> LookupEvidence`) for grounding a Brain's answer with live, external web results. Each result keeps title, URL, summary, source, optional publication time, and retrieval time; the evidence projection is always marked `untrusted`, while provider errors use one typed failure vocabulary. It is exposed both through `WebSearchToolSource` (`search_web`) and through the read-only per-turn Grounder used by the default ChatBrain. It remains separate from `KnowledgeBase`, whose documents have different trust/freshness semantics. `DeterministicWebSearch` is the no-network test conformer; `ByteWebSearch` is the real conformer. See [Realtime Grounding](docs/REALTIME-GROUNDING.md), [ADR-0014](docs/adr/0014-web-search-and-clock-as-tool-sources.md), and [ADR-0059](docs/adr/0059-speculative-realtime-date-and-search-grounding.md).
_Avoid_: Knowledge Base (a distinct retrieval contract grounded in deployer-registered documents, not the live web — see Knowledge Base)

**Turn Grounder**:
The read-only Brain-layer seam that resolves one stable transcript into explicit trusted clock context plus optional untrusted web evidence. `RealtimeGroundingCoordinator` owns the respond/clock/lookup plan, one frozen wall-clock instant, bounded provider call, and safe failure context; it does not execute arbitrary tools or Agent tasks. In the Voice Web Demo it runs inside the same speculative response producer started at SentenceEnd, so a stable commit reuses the work and candidate invalidation cancels it. See [Realtime Grounding](docs/REALTIME-GROUNDING.md) and [ADR-0059](docs/adr/0059-speculative-realtime-date-and-search-grounding.md).
_Avoid_: Combined Brain (the Grounder does not own the main reply, Turn Manager, or tool execution)

**Turn Content**:
The multimodal content bundle assembled per turn and passed to the Brain Gateway/Router — text (ASR transcript), audio metadata, and optional vision content (periodic snapshot or async vision-model text description). Vision is content on this bundle, never a Turn Manager input signal. Wired end-to-end as `TurnContent.vision_text` via an optional `VisionSource` plugin (`NoVisionSource` default), same Protocol/no-op shape as Voiceprint — no built-in Brain reads it; that's a Brain author's choice.
_Avoid_: Prompt, context (too generic — use "Turn Content" for this specific per-turn bundle)

**Action Output**:
An optional Brain metadata contract for non-verbal action/gesture instructions (for example `emotion="smile"`, `gesture="wave"`). It is not projected by the Phase 1 production Voice Session transport; digital-human integration must define an explicit Avatar Renderer event contract before this becomes a live output path.
_Avoid_: Gesture output, animation trigger

**AddresseeClassifier**:
The single plugin interface that gates both τ1 (IDLE→LISTEN, user-onset) and τ11 (DUAL→SPEAK, third-party-speech ignore) in Turn Manager, deciding whether detected speech is addressed to the assistant. Default (unregistered) behavior treats all speech as addressed to the assistant. See [ADR-0004](docs/adr/0004-unified-addressee-classifier.md).
_Avoid_: Addressee detection (reserve for the general problem; "AddresseeClassifier" is the specific plugin interface), wake word (a distinct, separately-gating optional plugin — see Wake Word)

**Wake Word** (plugin):
An optional Hook Point on τ1 (IDLE→LISTEN): with a Wake Word plugin registered, the absence of a wake event keeps Turn Manager in IDLE. Independent of and stacks with AddresseeClassifier. Default (unregistered) behavior allows entry to LISTEN. See [ADR-0005](docs/adr/0005-voiceprint-informational-wakeword-gating.md).
_Avoid_: Wake gate (use "Wake Word" for the plugin concept itself)

**Voiceprint** (plugin):
An optional plugin that attaches a speaker-match result (`match`/`no_match`/`unavailable`/`adaptive`) to Turn Content as metadata. Informational only — never silently blocks a turn; the Brain or deployer decides how to act on the result. Explicitly not identity authentication. `server/voiceprint/` supplies embedding, repository, matching, and enrollment conformers. It is not wired into the Phase 1 production Voice Session runtime by default; a future composition may feed device audio into it explicitly. See [ADR-0005](docs/adr/0005-voiceprint-informational-wakeword-gating.md), [ADR-0022](docs/adr/0022-voiceprint-embedding-matching-enrollment-service.md), and [ADR-0023](docs/adr/0023-opt-in-voiceprint-manual-confirm-gate.md).
_Avoid_: Speaker verification, voice biometric authentication (voiceprint here is a filtering signal, not an auth mechanism)

**DualIntentClassifier**:
The plugin interface that disambiguates τ9 (floor-claim, assistant yields) from τ10 (backchannel, assistant continues) once Turn Manager is in DUAL and `AddresseeClassifier` has ruled out third-party speech. `classify()` takes the overlap duration and (when an `AsrEngine` is configured) the peeked, non-destructive transcript accumulated during SPEAK/DUAL. Default (unregistered, or no ASR configured) behavior is a duration-threshold heuristic — sustained overlap reads as a floor-claim, brief overlap reads as a backchannel — see [ADR-0007](docs/adr/0007-duration-threshold-dual-intent-classifier.md). `LlmDualIntentClassifier` is a content-aware conformer built on the existing `LlmClient` Protocol, falling back to the duration heuristic on empty/ambiguous/unparseable replies. See [ADR-0015](docs/adr/0015-content-aware-dual-intent-classifier.md). `LlmDualIntentClassifier` also checks a bilingual `stop_phrases` set before ever calling the LLM (an obvious match returns `FLOOR_CLAIM` immediately, skipping the network round-trip), and parses a confidence value alongside the label — a reply below `confidence_threshold` (default 0.8) demotes to the same duration-heuristic fallback used for unparseable replies, rather than manufacturing a `FLOOR_CLAIM` from a low-confidence signal. See [ADR-0020](docs/adr/0020-rules-first-confidence-threshold-dual-intent-classifier.md).
_Avoid_: Intent classifier (too generic — use "DualIntentClassifier" for this specific DUAL-state plugin interface), AddresseeClassifier (a distinct, earlier-gating plugin that rules out third-party speech before this one runs — see AddresseeClassifier)

**Semantic Interruption Gate**:
The provider-neutral interruption policy used while an assistant response is being arbitrated. It classifies six labels (`stop`, `correction`, `interrupt`, `backchannel`, `ignore`, `uncertain`). In the coordinated runtime, stable punctuation chunks, five unsent semantic units (Chinese characters, English words and numeric units), or speech-stop sealing trigger immutable candidates; every partial does not trigger a request. Candidates run with bounded concurrency (product default 2, local API default 1), independently of shared JEV slots. `RuleFirstInterruptionClassifier` / `ExactInterruptionRules` check the local chunk and contextual safeguards first; a feedback shortcut requires every valid preceding chunk to have confirmed feedback evidence, rather than treating pending results as feedback. Model requests retain the independent `transcript` and explicitly classify the frozen `cumulative_transcript` through that candidate; the verdict is bound to the same cumulative scope. ASR rewrites invalidate affected prefixes, while ordinary growth retains valid in-flight candidates. Before STOP is issued, accepted current full-input `ignore/backchannel` evidence supersedes a late stopping prefix; after STOP is issued, the decision is locked against contradictory results from that batch. Only the coordinator actor changes business state. `stop/correction/interrupt` project onto Turn Manager τ9 and Generation cancellation; `correction/interrupt` require speech-stop and service-side yield acknowledgement before input admission. That acknowledgement is not client playback-stop confirmation. Overlap input never invokes semantic EOT. `LlmSemanticInterruptionClassifier` and `JevSemanticInterruptionClassifier` remain independently configurable; `DualIntentClassifier` is the empty-ASR/disabled compatibility fallback. The legacy adapter retains its partial debounce and single-flight behavior. See [Semantic Interruption](docs/SEMANTIC-INTERRUPTION.md), [ADR-0060](docs/adr/0060-latest-wins-semantic-interruption-gate.md), and [ADR-0135](docs/adr/0135-bounded-parallel-semantic-candidates.md).
_Avoid_: Semantic EOT (it decides when the user is done), DualIntentClassifier (the older quiet-boundary binary fallback), playback cancellation (Generation owns the cancellation mechanism)

**EotClassifier**:
The provider-neutral semantic-completeness plugin shared by `SemanticEndpointGate` and the coordinated runtime. It returns `EotClassification(decision, confidence, wait_ms, source)` for a frozen candidate. In the coordinated runtime, independent chunk boundaries trigger bounded concurrent requests, but each model request evaluates cumulative input through that candidate, preserving original ASR punctuation and excluding later text. Concurrency 1 and 2 use the same input semantics and prompts; bounded prior-chunk context is supplementary, not a replacement for cumulative meaning. Only a result covering the current effective full input may decide endpoint state, and turn admission also requires speech-stop evidence. SentenceEnd alone cannot commit a turn. Equivalent revision/punctuation/whitespace updates preserve accepted evidence and the original absolute commit deadline; changed semantic content or renewed acoustic speech invalidates that deadline. The default coordinated policy caps positive `wait_ms` hints at 5000ms for `INCOMPLETE` and 300ms for `UNCERTAIN`, using those ceilings when the hint is absent; classifier errors enter the uncertain path rather than manufacturing `COMPLETE`. Deadline admission is distinct from a model completeness conclusion. In the legacy adapter, SentenceEnd starts the classifier and side-effect-free main-response prefetch; the Gate independently waits for `EndpointStop` from acoustic VAD or a revision-bound 1000ms ASR-idle fallback, and new speech/text or Generation supersession invalidates its candidate before `USER_EOT_CONFIRMED`. `LlmEotClassifier` and `JevEotClassifier` remain independently configurable; JEV transport is shared at application scope and closed on shutdown. Coordinated prefetch uses the same Journal projection as committed responses, with stable-input preparation and revision/continuation/target/close invalidation. The demo enables LLM prefetch and disables TTS prefetch by default; tool intents skip speculative preparation; punctuation/`EnsembleEotClassifier` is not part of live composition. See [Semantic EoT](docs/SEMANTIC-EOT.md), [ADR-0057](docs/adr/0057-sentence-end-semantic-race-and-speculative-response.md), and [ADR-0135](docs/adr/0135-bounded-parallel-semantic-candidates.md).
_Avoid_: AddresseeClassifier, DualIntentClassifier (they solve addressedness/barge-in); SentenceEnd (an ASR observation and precompute trigger, not a committed end of turn)

**Generation**:
A monotonically-increasing counter tracking the current conversational turn-cycle, incremented whenever a new user turn supersedes prior in-flight work. The Generation-lease mechanism checks a delegated result's originating generation against the current one before injecting it, so results (success or error) from a superseded turn are discarded/logged rather than spoken. See [ADR-0001](docs/adr/0001-two-layer-external-agent-integration.md). Since [ADR-0036](docs/adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md) a confirmed barge-in (τ9) also advances it, which is what actually stops an in-flight reply, and the lease additionally guards the speaking budget and Turn Manager signals — see **Invariant T** in that ADR: at most one live turn task holds a current lease, and every other one is observationally inert.
_Avoid_: Turn ID, session ID (Generation specifically tracks supersession for the lease check, not identity)

**Turn task**:
The cancelable Realtime Engine work for one committed user turn. Provider, Brain, and TTS producers are cancelled cooperatively, while Generation remains the final guard that makes late output inert. It is subordinate to the Voice Session lifecycle and is settled when the physical transport detaches. See [ADR-0036](docs/adr/0036-concurrent-turn-execution-and-real-barge-in-cancellation.md) and [ADR-0048](docs/adr/0048-end-to-end-streaming-conversation-engine-and-output-contract.md).
_Avoid_: Worker, thread (it is one coroutine per turn on the session's own event loop, not a pool)

**Playback Progress**:
Device-reported playback truth scoped to output epoch, speech item, and Generation. Started/progress/finished/stopped reports let the Realtime Engine settle the exact current output; stale epochs or generations are inert. The browser Device Output Runtime is authoritative for what it actually scheduled and heard. See [ADR-0037](docs/adr/0037-re-armable-vad-utterances-and-client-reported-playback.md) and [ADR-0071](docs/adr/0071-device-audio-output-runtime-and-playback-truth.md).
_Avoid_: Playback position, heartbeat (it reports completion of one generation's audio, not a continuous position, and it is not a liveness ping)

**Delegation Ack**:
The single spoken acknowledgment the Realtime Delegation Controller may emit once after a configured latency gate when a turn becomes an external Agent task — never a scheduled or tiered filler sequence. Work starts before the gate; a result that arrives inside it skips the Ack. After an Ack, the system stays silent until the task completes, the user asks about progress, or an error is reported. See [ADR-0006](docs/adr/0006-delegation-latency-ack-pull-status-error-gating.md) and [ADR-0061](docs/adr/0061-two-speed-voice-tool-runtime.md).
_Avoid_: Filler, filler tier (project explicitly rejected periodic/tiered filler content in favor of one Ack)

**DelegationPolicy**:
The plugin interface Router consults per turn to decide whether to delegate and to return an `AgentSelectionPlan | None` (`None` = stay on the local conversation path). The plan names one primary Agent and only the fallbacks policy explicitly permits; Agent Task Supervisor performs capability/health selection and locks the chosen target at Backend Commit Point. `choose_agent(content) -> str | None` remains a compatibility adapter that produces a no-fallback plan. See [ADR-0031](docs/adr/0031-backend-catalog-and-delegation-policy-agent-selection.md) and [ADR-0054](docs/adr/0054-explicit-agent-selection-plans-and-no-silent-fallback.md).
_Avoid_: Delegation logic, dispatch policy (use "DelegationPolicy" for this specific plugin interface)

**StatusInquiryClassifier**:
The plugin interface that, while one or more Delegated Tasks are active, tells a progress check ("how's it going?") apart from a genuinely new topic. It classifies intent only; selecting which active task a progress query refers to is an orchestration decision. Default is `KeywordStatusInquiryClassifier`, a small builtin phrase set, same "minimal shipped heuristic" shape as `AddresseeClassifier`/`DualIntentClassifier`. See [ADR-0008](docs/adr/0008-status-inquiry-classifier-and-single-inflight-delegation.md) and [ADR-0045](docs/adr/0045-multiple-concurrent-delegated-tasks-across-named-agents.md).
_Avoid_: Progress classifier, follow-up classifier (use "StatusInquiryClassifier" for this specific plugin interface)

**AsrEngine** / **AsrSession**:
The plugin interface a Cascaded Realtime Engine uses to turn audio into transcript events. An ASR provider may emit endpoint hints, but those hints are only signals to Turn Manager and never authority to commit a user turn. `PreloadedAsrEngine` is the deterministic test conformer; `DoubaoAsrEngine` and `BellaAsrEngine` are vendor conformers. See [ADR-0011](docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md).
_Avoid_: ASR module, speech-to-text (use "AsrEngine" for this specific plugin interface)

**TtsEngine**:
The provider adapter used by the Cascaded Realtime Speech capability to synthesize assistant text into audio. `SilentTtsEngine` is the deterministic test/demo stand-in; Doubao direct and Bella-backed conformers provide real synthesis. Playback delivery and cancellation belong to Realtime Speech plus the Device Output Runtime, not to the adapter. See [ADR-0011](docs/adr/0011-doubao-asr-tts-as-swappable-speech-seam.md).
_Avoid_: TTS module, text-to-speech (use "TtsEngine" for this specific plugin interface)

**StreamingTtsEngine**:
A provider interface for chunked audio delivery: `synthesize_stream(text) -> AsyncIterator[SynthesizedAudioChunk]`. The Cascaded Realtime TTS capability re-checks Generation before delivery and closes the producer on cancellation; for WebSocket providers this tears down the vendor stream rather than relying on a client-side filter. `SilentTtsEngine` supplies a deterministic conformer. See [ADR-0012](docs/adr/0012-streaming-tts-as-a-separate-protocol.md).
_Avoid_: streaming TTS module (use "StreamingTtsEngine" for this specific plugin interface)

**DuplexStreamingTtsEngine**:
The legacy Cascaded adapter interface for simultaneous incremental text input and audio output: `synthesize_duplex(text_stream) -> AsyncIterator[SynthesizedAudioChunk]`. It remains behind the migration adapter until the target session-scoped TTS capability adopts the Speech Output command/event lifecycle. See [ADR-0062](docs/adr/0062-duplex-text-audio-streaming-tts.md) and [ADR-0063](docs/adr/0063-stateful-realtime-engine-command-event-contract.md).
_Avoid_: TTS segment stream (use "DuplexStreamingTtsEngine" when both directions stream)

**Silent Base Motion（静默动作底片）**:
用于视频通话、供后续口型对齐使用的人物动作视频。人物不做说话或发声口型，脸部与嘴部持续清晰可见，以正面姿态和自然细微动作呈现通话中的互动感。
_Avoid_: 说话视频、口型对齐成片

**Session Diagnostics（会话诊断）**:
以一场 Voice Session 为单位关联对话内容、输入输出音频、模块执行事实、交互延迟和异常的排查视图。诊断同时呈现证据与采集完整度，缺失证据不等于没有异常。
_Avoid_: 请求日志（单次请求不足以代表一场语音会话）、运行总览（跨会话聚合）

**Interaction Response Latency（交互响应延迟）**:
用户一轮表达的最后有效语音结束到客户端开始播放对应回复的时间，包含轮次确认与回复执行的等待。模块可能并行执行，各模块耗时之和不代表这段延迟。
_Avoid_: 模型首文本延迟、服务端首音发包延迟（两者是不同测量边界）

**Effective Interruption Latency（有效打断延迟）**:
用户开始一段被判定为有效打断的语音到客户端停止对应旧输出的时间。附和、忽略和自然播放结束不作为有效打断样本。
_Avoid_: 确认打断到收到停播回执（该代理指标漏掉检测等待且包含回传时间）

### 2026-10-04 链路模块化继续

预生成生命周期抽为 `server/realtime/capabilities/response_prefetch_controller.py`；独立 chunk 队列抽为 `server/turn_policy/semantic_chunk_scheduler.py`；客户端播放路由/取消/重置/音量抽为 `src/voice/audio/playback-output-controller.ts` 并接入 useVoiceSession。协调器保留状态机与模型调用，供应商接口和规则优先行为保留。增加单飞/合并/文本改写、预生成去重清理、迟到音频取消回归。全量 Python 1465 passed + 新增控制器单测 3 passed，前端 1215 passed/7 skipped。全局 tsc 有既有 model-services 路由非法导出错误，详见验证报告。

### 2026-10-04 真实浏览器 E2E

Chrome 文件麦克风 + 本地真实 Cascaded 服务两项 E2E 通过（普通完整回合含实际音频启动；播放中挂断后活动 AudioBufferSourceNode 清零），最终 26.8s。真实供应商 ASR/TTS/LLM 10 passed，WebSocket/chunk/规则集成 41 passed。修复 tests-e2e/voice-runtime-live.spec.ts 的中文语言初始化、主页入口、菜单 hover，增加挂断音频探针与 Session ID/消息类型附件。全站旧 E2E 和旧模拟语音 E2E 仍有过期定位/交互失败，未全通过；真实说话语义打断和数字人停播尚未浏览器验收。报告 docs/reports/2026-10-04-voice-e2e-validation.md。

### 2026-10-04 E2E 暴露问题修复

恢复 SessionControlBar 的会话设置入口（原 onOpenSettings 有传入但未渲染），补按钮回归并通过浏览器降噪切换/epoch 重建验证。Next 路由非法导出 isPersonalModelKind 移到 src/lib/personal-model-kind.ts，tsc 通过。修复 voice-agent 旧 E2E 的中文/默认角色隔离、主页入口、仅拦截语音 WS、idle 状态判断和握手基线；6 passed/1 skipped。修复本次数字人失败范围 5 项：资源工作台选择/复用、主视频画布、详情播放和缩略图。前端全量 1216 passed/7 skipped，修改文件 lint 通过。Playwright 独立测试服务器默认 public voice false，显式环境变量可覆盖，不改项目实际运行配置。

### 2026-10-04 数据日志入口 Failed to fetch

实际在应用内浏览器复现：未登录/会话失效时 /admin 服务端 redirect 到 /api/user/login，Next RSC fetch 跟随外部 OIDC 地址，产生 “Failed to fetch RSC payload ... /api/user/login?next=%2Fadmin”。有效 Chrome 管理员会话可以正常显示真实数据。修复 /admin 的无登录分支为 AdminLoginRedirect 客户端文档跳转边界（location.replace + 原生 a 兜底），保留已登录管理员直接进入看板和未授权账号拒绝。端到端新增 admin-login-navigation.spec.ts，模拟跨域 SSO 跳转并断言登录请求都是 document navigation、无 Failed to fetch/RSC console error：1 passed。权限/代理/设置导航单测 31 passed；全局类型和修改文件 lint 通过。

### 2026-10-04 附和与不确定打断决策修复

JEV instructions 明确短附和、未知输入和首播前证据要求。协调器不再把 UNCERTAIN 的 admit_input 自动转换成 yield；IGNORE 不创建轮次；首播前 VAD onset 不取消回复，恢复 deadline 不升级抢话。floor_claim_confirmed 区分有效打断与自然结束，防止未知输入在旧回复结束后被提交。WebSocket 定向取消从未结束 playback state 补查生成已完成回复的 generation。新增不确定/恢复、首播前附和、自然结束和定向停播回归；真实音频无播放回执仍需浏览器验收，详见 backchannel-session-diagnosis 报告。


## 2026-10-05 semantic candidate concurrency and correction roadmap

ADR-0135 implements bounded parallel semantic candidates in SemanticChunkScheduler and the coordinated actor. Production voice_web_server defaults VOICEAGENT_SEMANTIC_CHUNK_CONCURRENCY to 2; the low-level adapter/scheduler defaults to 1 for compatibility. Each chunk has an independent task/request token; input revisions invalidate affected candidates. EOT classifies cumulative meaning; a late prefix cannot overwrite the current full-input result. A confirmed interruption cancels its task family and locks the executed floor claim. Shared JEV provider slots remain independent.

The detailed requirements are docs/requirements/2026-10-05-voice-interaction-correction.md; implementation stages are docs/design/2026-10-05-voice-correction-implementation-plan.md. ADRs 0136—0138 are Proposed: reply revision correction, actual sentence-boundary handoff, and misinterruption recovery are NOT yet implemented by the parallel scheduling change. Playback evidence and renderer protocol support must be established before claiming those features.

ADR-0139 execution boundary: SemanticTaskRegistry owns tasks/request tokens; classifier_execution owns generic deadlines and task-local diagnostics. The turn actor no longer imports the JEV plugin. Current/future framework diagram: docs/design/2026-10-05-voice-framework-boundaries.md. ReplyRevisionController and actual sentence handoff remain planned.

## 2026-10-06 requirements and experiment review

Unified product baseline: docs/requirements/2026-10-06-voice-platform-requirements.md. Detailed state rules and ADR0135—0139 were clarified; implementation order now starts with experiment/playback contract baseline and parallel hardening before ADR0136. Experiment design: docs/design/2026-10-06-voice-interaction-experiment-plan.md. Review findings: docs/reports/2026-10-06-requirements-and-plan-review.md.

The user confirmed: before STOP is sent, accepted latest full-input no-interruption evidence supersedes a later older positive prefix; after STOP is sent, lock the action against contradictory same-batch results. Current code still needs that guard and regression. Capacity1/2 currently changes EOT input construction, so unify semantics before concurrency attribution. Existing yield_ack is server cancellation completion, not renderer stopped evidence. Output completion must not invalidate meaningful unresolved input. General supplement keeps only an exact current-sentence playback permit; pre-generation must separate confirmed_heard from permitted_current_sentence and revalidate at handoff. ReplyRevisionController remains an actor-driven ledger, not a second decision actor.

This turn changed documentation only, without new runtime fixes or real-model experiments. Three real short-turn runs remain smoke evidence, not causal latency/P95 validation. Default audio recording storage, machine read-only diagnostics identity, full sentence handoff and misinterruption recovery are still not implemented/fully accepted by evidence. Preserve these gaps in future status updates.

## 2026-10-06 first implementation batch after user authorization

The preceding review entry describes the documentation-only round; after the user said “开始”, runtime hardening was implemented. Capacity1/2 now uses the same cumulative EOT text/prompts. Interruption calls still trigger from independent sealed chunks; local transcript stays available to rules, while optional cumulative_transcript freezes the model's whole-prefix scope and binds candidate/verdict to it. Raw cumulative snapshots preserve punctuation. Before STOP, accepted latest full-input IGNORE/BACKCHANNEL supersedes late older stopping prefixes; after STOP, lock the action. Equivalent normalized ASR snapshots retain evidence and the original commit deadline. Commit timers bind a semantic prefix and still validate acoustic identity, so revision-only updates cannot orphan the deadline and real rewrites cannot reuse it.

Prior feedback must be confirmed by actor policy (non-fallback BACKCHANNEL, no stop and no admission) before a local tail backchannel rule may discard the whole input. Latest full-snapshot no-stop arbitration uses the separate general classification threshold: partial BACKCHANNEL can reject stale STOP while retaining input. “Full” means cumulative snapshot scope, not SentenceEnd. Whole lifecycle exits clear jobs and queued request tokens; completed chunk jobs retire but business timer markers remain. ClassificationExecutor bounds async caller waiting and residual task count; uncooperative calls occupy slots until finished. Cooperative cancellation handoff waits at most 50ms inside the same absolute deadline, observed separately; provider call exposes configured and effective remaining timeout. Close invalidates results and wakes current owners without cancelling retired owners' later work. No CPU-blocking plugin isolation or remote cancellation guarantee is claimed.

Final Python tree: 1594 passed / 62 skipped / 3 subtests passed (38.46s), after timer and feedback-proof fixes plus the separate no-stop/discard contract regression. Parallel actor: 55 passed; playback/mock renderer: 31 passed in 6 files. Final code and Python independent reviews approved; scoped Ruff and 5 core-module Mypy checks passed. Report: docs/reports/2026-10-06-parallel-hardening-implementation.md. Playback capability baseline: docs/reports/2026-10-06-playback-capability-baseline.md. No new real-model calls, explicit server restart, or Git commit this batch.

G0/G1 are partial, not accepted in full. SemanticChunkBuffer retains effective full chunk history plus cumulative prefixes with quadratic copies; pending/message counts do not bound payload bytes. Long-input budgets, safe persisted evidence/readback and offset-based representation remain prerequisites alongside ADR0136. Meaningful UNCERTAIN supplement exit, reply correction, actual sentence handoff, misinterruption recovery, recording storage and machine diagnostics identity remain unimplemented/fully unaccepted. Four existing WAVs lack validated semantic/timing oracle; 31 mock tests do not prove physical device stop. Continue the remaining resource/evidence work before claiming G1 or performance/P95 acceptance.

## 2026-10-06 diagnostics overview/list unavailable

Live reproduction: both control-plane GETs for observability overview/sessions at localhost:8766 failed with connection refused; only Next on3010 was listening. Started the existing `bash scripts/dev_server.sh` (managed exec session46040); startup succeeded on8765/8766. Re-running the same HTTP checks returned200, overview7 sessions/20 metrics, list7 rows, collection healthok. Keep the restored server running; do not restart active voice sessions for unrelated tests. Actual cause confirmed is absence of the backend process; its earlier exit reason was not established.

Frontend: `loadDiagnosticsOverview` in src/lib/observability.ts owns the existing three independent fetches, preserves successful sources, and keeps safe failure details instead of dropping them to generic unavailable labels. AdminDashboard retains abort/old-result protection. Read proxy503 now explicitly asks to check the voice backend; application admin authentication remains unchanged. Regression: source failures first lost their explanations; four relevant assertions failed before the fix, then all19 related tests passed. TSC and scoped ESLint passed; existing code reviewer approved. This was HTTP/API and loader verification, not a browser UI run: computer-use runtime could not start because of the VoiceAgent symlink sandbox limitation. No Git commit this round.

## 2026-10-06 Session95a9b382 lost follow-up

Actual trace: Beijing-today reply playing; ASR recognized “明天天气怎么样？”. Two concurrent interruption candidates finished with effective UNCERTAIN confidence0.26/0.5 (below general0.8 threshold), no STOP. Slots did not queue and neither timed out. Original pre-threshold labels were not stored. Natural playback completed15:11:54; coordinator still awaited floor_claim_confirmed and recovery discarded input15:12:00. Captured301 events/42debug/4conversation items; zero summaryerrors did not detect this uncommitted lost input.

Fixed natural-completion input exit, late whole-snapshot result acceptance, and expired positive prefix after completion (independent review caught oldSTOP deleting latest question). Still-playing prefix quick STOP and already-issued lock stay intact; UNCERTAIN does not force interruption. Precise “哼哼” added to existing feedback rules; no length-based discards. Debug now keeps raw_label/threshold/downgrade, deferred commit has distinct reason. New17 actor replays exercise original words, result/completion orders, high-confidence stale STOP/CORRECTION/INTERRUPT and late negative suppression. Final fullPython1612 passed/62 skipped/3 subtests37.10s; related132passed, scopedRuff and2moduleMypy passed; both independent reviews approve. Report docs/reports/2026-10-06-session-95a9b382-lost-followup.md. Active-playback recovery discard, general noise oracle and fullADR0136—0138 remain open; AC11 onlypartial.

External JEV repeat with these conversation snippets was rejected by automatic approval review for lack of explicit authorization to resend conversation text externally; no request was executed. Model original output/accuracy diagnosis awaits that authorization. Existing trace plus local replay verifies state failure, not physical stop or real model improvement.

After verifying /sessions=[] twice, gracefully stopped prior backend exec46040 and restarted existing script with fix. New running backend exec3253, PID23883,8765/8766 ready. Health/overview/history allHTTP200,Next3010 preserved. Do not stop active voice sessions. No Git commit.

## 2026-10-06 authorized JEV weather retest

User explicitly answered“允许”to resend the Session95a9b382 weather snippet to the configuredJEV.18 real calls completed usingjev-1.13.0 and unchanged0.8 threshold. See docs/reports/2026-10-06-jev-weather-retest.md and matchingJSON (no credentials). Full-generated-answer context baseline selectedUNCERTAIN(.27/.29) for“明天天气怎么样？”; observed31-character playback-prefix context baseline selectedINTERRUPT(.39/.36), then downgraded. These are reconstructed contexts, not originalexactpayload or evidence of its originalrawlabel. Explicitcorrection baseline passed(.83/.81). Input-only/task-only/source-only changes did not pass; conciseprompt+primarytranscriptcumulative passedsameweatherquestion2/2(.83/.81). Officialconfidence formula differsfrom topclassprobability;6-wayconfidence0.8≈topprobability.8333. Do not lower threshold or claimgeneralaccuracy/P95.

Candidateprompt is stored in compact_candidate.prompt of reportJSON, NOT deployed; no productioncodechanged orrestartthisretest. Request/actor independentchunkcontracts stay proposedunchanged; potentialJEVpayload primarytext shift only. Wider syntheticfeedback/correction-tail/garble/retraction matrix combinedwithauthorizedweatherhistory was rejectedbyautomaticapprovalasnotexplicitlycovered. No matrixrequestexecuted; concrete4text approvalquestion is pending. Additionalauthorization must arrivebeforeexternalmatrixruns. Rejectedcommandmustnotbebypassed. No Gitcommit.

## 2026-10-06 sidecar control bar cleanup

User requested removal of session settings in the sidecar (并排) layout and review of redundant actions. SessionControlBar now hides settings/captions in sidecar: OpenRealtimeApp already disables sidecar live captions, so that toggle had no effect. Keyboard focus button also removed in sidecar/content because their composer is always visible; fullscreen keeps input expand/collapse, settings and captions. Sidecar retains microphone/layout/hangup plus composer/send. Removed only composerFocused UI state and redundant focus branch; recovery focusComposerRequest remains. Settings remain reachable by choosing content/fullscreen, no global settings behavior changed.

Regression first4failed, then19 componenttests pass; globalTSC andscopedESLint pass. Extended existing browser speech fallback E2E with content→sidecar,3actions/no redundant controls, draft entry/mic toggles→fullscreen restoration/draft retention→hangup. ActualChrome against isolatedNext3012:1passed32.5s (test11.4s), mockedvoice only; no external model call or user3010/backend restart. Existing code reviewer approved; independent9componentchecks passed. Files src/components/call/session-control-bar.tsx, its test, tests-e2e/voice-agent.spec.ts. No Gitcommit. Prior JEV extension authorization is still unanswered; this UI request did not authorize that matrix.

## 2026-10-06 remove session settings in every layout

User extended removal to fullscreen and content. This supersedes the preceding sidecar-only settings rule: all three layouts omit the session settings button. Deleted Settings2 import, onOpenSettings prop/destructure and parent callback argument. Non-sidecar captions and existing input/mic/layout/hangup behavior remain. Existing avatar open_config setup path remains unchanged; it only opens after requested avatar configuration loads, not on generic conversation URLs.

Regression first5failed, then49 componenttests (including28 ConfigDrawer checks) passed; globalTSC andscopedESLint passed. Chrome on isolatedNext3012: layout/speech fallback test passed8.5s; finalASR capture/reconnect test passed5.1s. ASR fixture now seeds existing persisted noiseSuppression=false before call instead of invoking the removed mid-call button; asserts effectivefalse/owner none, fresh reconnect epoch and preference retention. This no longer covers a live mid-call noise-setting UI toggle; no such button is retained. Two initial ASR test adaptations failed (generic open_config not supported; old device-owner assertion), then fixed to the actual contracts. Mockedvoice only, no externalmodel call, production3010/backend restart or Gitcommit. Existing code reviewer approved both the removal and final ASR fixture.


## 2026-10-06 HTML call controls interaction preview

User requested an HTML prototype before integrating redesigned input controls. Added standalone public/demos/call-controls-demo.html with embedded project theme tokens, nine themes (reads saved theme; preview selection does not persist), fullscreen/sidecar/content layouts. Collapsed mic/layout/hangup coordinates stay fixed across modes. Input toggle expands the glass dock, retires mic/layout into a keyboard-accessible More panel, keeps hangup accessible, and preserves drafts across collapse/mode switch. Fullscreen alone exposes captions; captions move above expanded input. Enter sends simulated text safely via textContent and collapses; Shift+Enter/newline, IME guard, Escape/focus restoration, reduced motion, mobile viewport and end/restart supported. No real microphone, backend or model call; production controls unchanged.

Chrome isolated3012: seven E2E checks passed20.9s after fixing delayed visibility/autofocus; final fullscreen caption placement check passed8.2s and end modal scope check passed13.5s. Reviewer caught incomplete modal inert scope, fixed topbar/footer along with stage content and regression checked attempted focus escape/restart restoration. Existing reviewer finally approved with no remaining findings. Scoped ESLint and inline JS syntax checks passed;3010 demo URL HTTP200, open_in_codex browser request queued. No production restart or Git commit. Tests live in tests-e2e/call-controls-demo.spec.ts; prototype default mode sidecar. Motion inspiration: Material3 expansion/collapse, retaining project visual style.


## 2026-10-06 revise HTML preview to original inline controls

User rejected the detached expanding panel and supplied an original horizontal control-bar screenshot. This supersedes the previous HTML preview design: sidecar and content use identical always-visible pill input/send + divider + circular mic/layout/hangup; they retain input after sending. Only fullscreen exposes keyboard/caption buttons, expands the same inline input, and contracts ALL three main call actions (including hangup) into a small More control. Contracted main-actions is inert and aria-hidden; More includes mic/captions/mode/hangup. Click collapse or Escape restores original icons, preserving drafts; mode changes cancel pending autofocus and restore correct persistent-input state. Production SessionControlBar remains unchanged; this is the user's HTML design review.

Updated eight Chrome prototype regressions passed21.9s after one prior red persistent-input check. Final geometry/fullscreen contraction/mobile-input checks3passed14.9s after removing duplicate assertion and reserving message space beside content avatar. ScopedESLint and embeddedJSsyntax passed; existing3010 revised URL /demos/call-controls-demo.html?v=2 HTTP200. Open-in-Codex browser request queued. No real audio/model calls, backend restart or Gitcommit. Independent reviewer approved final source; separately checked focus, inert/aria-hidden, keyboard mode changes, draft preservation, persistent send, end/restart and390px overflow.

## 2026-10-06 integrate approved call controls into the application

User approved HTML v2 and required hover-based page mode choices above the mode button. SessionControlBar now implements the accepted design with a scoped CSS module: sidecar/content share the original always-visible inline input and mic/mode/hangup; fullscreen adds keyboard/captions and collapses all main actions into a More panel while input is open. Drafts remain mounted, hidden forms/actions/menus are inert, and sending in persistent layouts keeps the input visible. Mode choices retain hover plus click/keyboard access, above their trigger, including inside the More panel. Captions render only in fullscreen. Escape closes layers and restores focus without propagating to the page's exit-fullscreen shortcut.

Menu placement accounts for ancestor scale and tracks the 440ms toolbar/260ms panel transitions for500ms, with resize refresh and frame/listener cleanup. Final review approved after fixing animation-time mobile clamp. Regression reproduces the parent transform with Web Animations (same260ms keyframes) so it does not depend on the initial paint being split across frames; a35ms pointer event bypasses Playwright's stability waiting. Initial fixture attempts sometimes had no native transition and were replaced with this deterministic simulation.

Related components22passed; final Chrome formal-page browser/control regression1passed22.4s, server-ASR fixture1passed3.8s in the preceding run. Browser tests use mocked speech/WebSocket/media, not real hardware or external model calls. GlobalTSC passed; finalscopedESLint andgitdiff--check passed. User3010/backend services were not restarted and noGitcommit was made. Changes: session-control-bar.tsx/module.css/test.tsx, open-realtime-app.tsx, andvoice-agent.spec.ts. This supersedes the preceding prototype-only status; the HTML demo remains available separately.

## 2026-10-06 continue phase1 long-input resource hardening

User asked whether the implementation plan was complete, then authorized continuation. This batch replaces SemanticChunk.prefix copies with semantic_end offsets and Buffer-owned validID mappings. Buffer caches current semantic text and preserves candidates only through adjacent-ASR longest common semantic prefix; erased/merged IDs cannot revive after text reversion or cross inputs. Original/cumulative model text, punctuation, feedback history and STOP arbitration stay intact. Current verdict_prefix remains one frozen snapshot, not one per history chunk. No new production module or actor.

Three red regressions reproduced staleID revival, crossBuffer same-text validity, and nonlinear retained memory (1000/4000chars266487/3468039B). After the representation fix, independent review found existing synchronous CPU scanning:8000chars~3666ms. Boundary cache now avoids repeating full-tail scans when there is no ASCII'.'; actual punctuation consumption invalidates cache. Suffix-sensitive'.' retains legacyURL/domain/decimal behavior. Units use islice(threshold orforce65), preserving<=64unit force seals. Added scan-count/URL tests; initialURL expectations were corrected for the existing rule that separators between revisions are skipped. Remaining remainder slicing still copies tails, so do not claim total asymptoticCPU linearity.

Final fullPython1617passed/62skipped/3subtests37.37s; scopedRuff and3productionMypy passed. Existing independent code/python reviewersApprove,102/115targetedchecks passed;10,000random multi-version comparisons match pre-scan-optimization behavior. Local1000/4000/8000char construction3-runmedians1.592/6.477/12.487ms; retained62729/272374/554502B. Synthetic pure-buffer evidence only, not model/voice/P95. Report docs/reports/2026-10-06-semantic-prefix-resource-hardening.md; implementationplan andADR0135updated. G0/G1 remainpartial: fullhistory/payload/CPUbudgets, persistedASRevidence/readback, realoracle/renderer andmulti-session/pairedlatency tests pending. Next integrate those budgets/evidence withADR0136input/replyledger; do not truncate unknown input or history before safe persistence. No realmodel/renderer calls, currentservicesrestart orGitcommit.


## 2026-10-06 continue input evidence and resource budgets (ADR0140)

User again requested continuation. Implemented bounded confirmed input evidence adapter in server/conversation_journal/input_evidence.py, reusing INTERNAL structured Conversation Journal items in a per-tenant/user/thread/voiceSession separate evidence thread; no new table/business actor. Writer limits pending32 includingactive, queue1MiB, record64KiB, write1s. Receipt checks item_id/digest and durable flag; Memory false, Postgres true. Actual turn/generation preserved on later observations with scope validation. ASR rewrites logged as LCP replace_from/suffix/previous id/hash; endpoint-only boundary changes logged; sealed chunks batched128, merges/invalidations/requests and accepted classifier labels recorded, including nonchunk modes. Capture point is TurnManager post echoprojection; not complete rawprovider/recording/stale-model oracle.

SemanticInputBudget defaults UTF8text16KiB, revisions2048, currenthistory2048, logicalduration120s, evidence2MiB, configurable .env fields; admission engineering limits not measuredSLO. Reject freezes input, cancels classifiers/prefetch and clears deferred observations; never classifies a truncated prefix. Terminal capture bounded16Kchars/32KiBUTF8, only complete durable receipt permits ASRdiscard. Missing/failed/memory/too-large capture explicitly reports not saved. Frozen oldfinal cannot commit; terminal accepted_revision/rejected_revision distinct. Asyncstoragefailure after normalfinal or exactbackchanneldiscard still emits sessionfailure, even _input=None. Spontaneously canceled storage also notifies and fails all queued receipts. Sessionclose bounded for uncooperativewrite; retaineddrafts/fullrejectedpayload release onclose, don't claim arbitraryprovider/network/allprocessmemory bounded.

Production voice_web_server wiring supplies runtime.journal and budgets. CLI/controlplane add paginated input-evidence reader; admin Next proxy retains applicationadmin gate. API /api/observability/sessions/{ID}/input-evidence?after_sequence=0&limit=100 returns status/records/cursors/durable; empty unknown versus available tail distinguished. Flush telemetry then ApplicationRuntime.session_history_scope resolves true server-recorded tenant/user/thread (publicticket/continuation covered), ambiguity fails; only old missingidentity local fallback. Sessiondeletion also deletes evidence scope in samePGtransaction with existing diagnostics. Found origin-session deletion would erase resumed thread; fixed SessionOwnedHistoryRetention: sameMemorylock or PGthread FORUPDATE usedby append, require allitemvoiceIDs selected before purge; process-local active/suspended threadrefs retain mainthread; customadapter missingnewprotocol retains. This isn't distributedactivity coordination or peritemsharedthread purge.

Engine maps rejection to semantic_input failure; WebSocket sends voice_session_failed dispositionclose and closestransport. Frontend close now stops public/private capture, speechSynthesis and existingplayback, clears3fallbacktimers and speaking state while preservingcaption/error. RecoveryNotice connectionerror shows specificsafe reason, toolbar paused/toggle follow actualmicActive. Chrome initially exposed genericbanner and stale micbutton; both fixed. Actualengine+ManagedRuntime+Endpoint regression starts blockedBrain/duplexTTS then blockedinterruption classifier, asserts allactive and pending_count>0 beforeoversize, verifies allcanceled/writer/actor/resourcesended. InitialEOTtest cancellation occurred atResponseStart and was corrected afterreview; no falsecoverageclaim.

Final fullPython1671passed/62skipped/3subtests38.07s, frontend66unitchecks + Chrome1failureexit16.2s, globalTSC/scopedESLint, core6module+registryMypy andscopedRuff pass. PGfile5TRY004 existingHEAD decodeValueErrors kept; no realPGfault/load/physicalrenderer/externalmodel tests. Existing Python/code reviewersApprove, reportedblockingbugs fixed. Final deletionrace hardening: registry thread_deletion_guard synchronously filters/reserves idle scopedthreads before awaits; register rejects matching newcontinuations through all deletion awaits; finally releases success/exception/cancellation, overlappingguards preserve ownership. Active+suspended refs preserved. Runtime interleaved success/failure regressions included in1671, independentreview4passed. ADR0140 Accepted forstorageresourceboundary; ADR0136 staysProposed. Report docs/reports/2026-10-06-input-evidence-and-resource-budgets.md andimplementationplanupdated. Input/replyledger/officialcorrection (0136), sentencehandoff (0137), recovery (0138), rawASR/audiooracle, machine readonlyidentity, realpairedlatency/renderer andspecialASCIIperiodCPU bound remain pending. User3010/backend8765/8766 not restarted; newbackendcapture activates afterdeployment/restart, not currentlyrunningoldservice. NoGitcommit at that batch; later commit recorded below.

## 2026-10-06 commit prior work and continue ADR0136 first batch

User authorized "commit, 继续未完成的". Prior completed changes committed as6b2228c (feat: harden voice coordination and session diagnostics),145files; no push. Restored generated Next env/E2E-portconfig noise beforecommit. New batch implements actor-driven pure synchronous ReplyRevisionController,current input/reply only (135lines), logicalroot/inputversion/replyversion/supersedes, revokedduplicatebinding cannotrestore. No newbusinessactor. FormalASR commits carry versions into publicevents/Journal; structuredlogical_input_id/nestedinput_revision preserve committedturn/generation separatelyfromASRobservationenvelope. Actor1592lines.

Same optional payloadpermission forwards through engine→Journaled→Tool→Delegation→Turn→Managed→bridge, rechecks dequeues/finalframe, terminalfacts visible. Managedqueuedorigin rejects replaceddelegateoutput. ExternalSpeech uses ownspeech_id even source responsecontext present. Cancel snapshots original task/admission beforeawait; preparingfailure cancelsandclearsmap beforeBrain. Naturalcompletionduringinvalidation sendsindependentstopwithoutsecondterminal, capturesoriginalcontext beforecleanup; directspeechusesreal response:delivery:<id> keytocancelrecord/clearunsettled. STOPsealdoesn'trejudge; subsequentnewbodyadmittedwithoutsecondstopverdict. Originalendpointdecision/source preserved separatelyfromadmission_reason. Unresolvedplayingoverlapdeadline explicitfailure/retainedtextinstead ofsilentdiscard. Sync versionevidenceofferfailure localstickyimmediatelyfreezesdelivery, thenexplicitfailure evenifrecorder.failure notyetset.

First3coordinator/2actualengine regressions red beforefix; finalreview two more rednaturalcompletion context/directrecordrace fixed. New4testfiles21passed; actualproductionwrapperthreeconfigs andfinalcachedbridge covered; placeholders don'tprove realtool/delegationsideeffectcancellation. FinalfullPython1692passed/62skipped/3subtests36.81s, core9Mypy/scoped18fileRuff/diffcheckpass. ExpandedMypy has12baselineerrors in tool/runtime/endpointbridge; notglobaltypepass. Existingcode/pythonreviewers independently21passedandapprove afterbusinessfixes; final importsort fixed. No frontendchanges/repeatbrowsertests, no realPG/model/physicalrenderer. 3010/8765/8766 untouched. Report docs/reports/2026-10-06-reply-version-delivery-isolation.md;ADR0136,plan,frameworkupdated. New batch tobecommittedunderuserauthorization; checkgitlogfor resultingcommit.

Remaining: complete semanticassociation (currentheuristics retained), crossSessionledgerrebuild/idempotence/G2; currentactualsentencepermit/heard_frontier/stoppedvsSTOP_UNKNOWN/0137; recoveryepoch/0138; raworacle/recording/machinereadonlyidentity/realpairedlatency/G0/G1 andresourceCPUcorner. Do notmarkfullstage2/3done; commandframe isn'tphysicalstopproof. Upperoutputqueues overallbounds notproven. Nextcontinueassociationcontracts andpersistentversionevidencebefore renderer-dependenthandoff; don'trestart useractiveservices without session context authorization.

## 2026-10-06 continue final input association after eed305c

User repeated "commit, 继续未完成的". Priorbatch committed eed305c, starting treeclean. Added86line pure injectable InputAssociationPolicy; no newbusinessactor/task/network. ActorfinalASR now revalidates explicitnewtopic/correction/limitedsupplement oraccepted reliablefullsnapshotCORRECTION. INTERRUPT/prefix/rewrite/fallback/lowconfidence don'tproveparent. Unknown retains independentfinaltext/root +relatedparent/sourceunresolved; publicevents/Journal carry relation metadata; TurnContent.model_text adds contextualindependentanswer-orclarify guidance (notrealmodelaccuracy/strongtoolpermission). ExplicitfinalnewtopicbeatsoldlockedCORRECTION; STOPnotrevoked. SameASRturn inputnewroot also getsnewcommittedturn/generation.

Finalrawbudget/evidencebeforepolicy; pluginexception/foreignparent/unsupportedresult fallbacksourceassociation_error withfinalretained, actorcontinues. Both speculativeBrain/Speech cachekeys compare new input_relation_unresolved, matchingmodel_text; actualtext/audio miss regressions redthenfixed. Asyncprefetchinvalidationalone wasn'tsufficient. Actorfailure readgatealsofreezesdelivery. Associationcommitted evidencepassesfinalsnapshot+revision; associated detailrevisionfinal. Last2redofferfailuretests provedoldpartial/revisionterminalcapture,nowcumulativefinal+rejectedrevision2captured.

Playedfacts independentofrevokedpermission; actorvalidates response/turn/gen onbothlate/currentbranches. engine lateprogress usesSpeechDeliveryRecord.context aftercancelmapgone, no extrahistorymap; zerooffset/no startedflagisn'tstartedproof. Latecancelreceipt usesstopped/positions,notcompletedsointerruptedstatusstays. _prior_model_items onlyremoves cumulativecoveredUSER; assistantcontentreusesexistingdelivery-awareprojection/refresh, emptyheardskipped. Commit-time supersedes_unplayed_reply isdiagnostichint,no proofphysicalunplayed andnotpermanenthistoryfilter. Lateplayedafternewcommit rebuilds futurecontext (doesn'tfixcurrentlyinflightgeneration;0137open). Actualsame-turnAheard/Bunplayed retainsA.

New46tests (policy22,actor16,production6,cache2), witholdcache6targeted52green; reviewersindependently52approve afterreportedHIGH/MEDIUM fixes. Production normalizedinput→actor→engine→Journal→automaticBrain withcontrolledASR/model/TTS/rendererreceipts,countsunchangedatfinalassociation (notclaimonlyoneexistingpartialcall). Scoped15Ruff/core9Mypy/diffcheckgreen; legacyturn_manager directMypy haspre-existing line594optionalassignment,notglobaltypepass. Full1736passed/62skipped/3subtests36.70s beforelastsnapshotfix; finalfullrerunrecordfollows. No frontendchanges/realmodel/PG/hardware/no service restart/push. ADR0136stillProposedpartial,frameworkactor1659lines. Report docs/reports/2026-10-06-final-input-association.md andplanupdated. Checkgitlogforauthorizednewcommit.

Remainingunchanged: fullsemanticassociation/oracle/G2, crossSessionledgerrebuild/persistentidempotence, actualcurrent-sentencepermission/heard_frontier/STOP_UNKNOWN/0137, recoveryepoch0138, recording/read-onlymachineidentity/realpairedlatency/resourceCPUcorner. Nextfocuspersistentversioncontracts+samples thenrendererhandoff; don'tclaimfullphase2/3completion orphysicalspeakerproof.

Finalsnapshotfix fullPython1738passed/62skipped/3subtests36.81s; finaltargeted52green/core9Mypy/scoped15Ruff/diffcheckpass, bothreviewersApprove. Prior1736wasbeforelast2regressions. Newbatchauthorizedlocalcommit, usegitlogforhash; user services untouched.

## 2026-10-07 speculative output budgets and shutdown ownership

User authorized local commit and continued remaining plan. Prior automatic repair commit75d81e2 remains separate. ADR0141 adds shared output-only SpeculativeOutputBudget/Buffer/CleanupOwner to existing Brain/Speech caches: UTF8text64KiB/1024chunks, PCM+subtitle8MiB/2048chunks/30audioSeconds, absolute unclaimed residency30s. Before-append protection, timer also clears completed candidates; terminal diagnostics detached/bounded and committed text uses hash/length. Formal consumers drain deques/backpressure without new provider/duplicate output; oversized single formal packet explicitly fails. Budget bypass only before claim and after actual old resources exit, original input/context kept. Full ordinary sentence-handoff pre-generation not integrated.

Unclaimed soft retirement clears caches and internal queue waits without cancelling unknown supplier __anext__, avoiding natural-finally interruption. TTL bounds cache residency, not generic supplier lifetime; pending owns single slot, new admission fails/awaits instead of reopening. Claimed formal responses retain existing Core deadlines/cancel contracts. Failed retiring/notdone candidate cannot be promoted to formal. Direct/hit Brain+TTS share lease, empty response releases nonexistentTTS lease. Supplier cleanup failure quarantines all new entry points, including miss/bypass. Response.prefetch observer now wired to optional speech path.

Actual controller->cache close forwarding (tool-chat forwards chat only), shared shield close tasks in caches/Core/Managed keep supplier/session/history ownership across cancelled/repeated waiters. Failed delegate shutdown leaves suspended registry/deletion guard and terminates event pump; no false unregister. No forceful generic supplier-exit guarantee. Red regressions included natural/exception finally cancellation, traceback-held8/16MiB packets, END queue deadlock, promotion race, direct lease mismatch, empty lease, and actualactor/Core/Managed shutdown (text/speech/tool-chat) with failure variants.

Final fullPython2237passed/69skipped/3subtests51.39s, 8productionMypy/13fileRuff/diffcheck green. Resource50/shutdown8 regressions include final actor independent evidence writer shutdown, Core event-stream terminal on failed close, and four post-await closed-admission races. Closing intention prevents new supplier admission; original shutdown errors and suspended deletion protection remain explicit. Two existing independent reviewers approved after fixes. Report docs/reports/2026-10-07-speculative-output-budgets.md, ADR0141, plan and ADR0137 updated. No realJEV/ASR/LLM/TTS/DB/browser orservice restart/push. Stage3/G3 remainsopen: integrate ordinary supplement preparation with old current-sentence wait and final heard_frontier validation, then ADR0138 recovery; manual/directrepair, persistentunknown actions, realrenderer/provideroracle/performance, horizontaldiagnostics/recording/machineidentity/globalresourcebudgets and G0–G5 remain full scope. Checkgitlog for authorized local commit.

## 2026-10-07 continue ordinary sentence-handoff candidate preparation

Prior speculative budget/closing batch committed f1359c0; no push. Existing actor/controller/Core locally admit ordinary supplement prefetch only after user stop + generation yield acknowledgment + still-valid exact current-sentence permit. Immutable candidate binds source ASR separately from cumulative text, parent turn, generation and permit. Each permit prepares at most once; late ASR growth invalidates without per-character calls. Actual stop still precedes ASR final commit; unknown terminal releases input but retires candidate. Final SUPPLEMENT/parent/text/gen must match before retaining cache, actual formal HF digest remains authoritative. Builder seam receives Candidate; Core hides covered prior USER while preserving contiguous source identities, same as formal projection. No new production module/actor/queue.

Independent constructor sentence_handoff_prefetch_enabled defaultsFalse and not wired/enabled in user product. Candidate uses confirmed heard only, never assumes permitted sentence heard. Thus normal current-sentence completion may invalidate/rebuild, and no latency gain is claimed. Conditional permitted-sentence projection, full mismatch/noncooperative provider matrix, product enablement, manual/DeliverItem repair, real renderer/provider G3 and ADR0138 remain open, alongside all G0–G5/horizontal requirements.

Initial six actualactor/cache red regressions failed supplier-start wait; fixed. New20cases include single-attempt growth, defaultoff, actual Managed/Core/Journal/Bridge text+speech stop600/1000: exact2suppliercalls (old+candidate hit) versus3 (old+candidate+actualHF rebuild), zero new frames before stop. Blocked noncooperative projector after resume/correction/unknown/close cannot start supplier; finalsame-text new_topic/unresolved/correction drops candidate. Review found UNKNOWN terminal cache retained; real red added, then invalidate before existing input release fixed. Final74targeted andfull2257passed/69skipped/3subtests50.53s,4productionMypy/7Ruff/diffcheckgreen, both independentreviewersApprove. No real models/ASR/TTS/DB/physicalaudio/browser, no service restart/push. Report docs/reports/2026-10-07-sentence-handoff-prefetch.md andADR0137/implementationplanupdated. Goal/stage3 remainactive/incomplete. Authorized local commit follows; check Gitlog.

## 2026-10-07 conditional permitted-sentence handoff continuation

Prior ordinary confirmed-only preparation committed bdbb161; no push. Existing immutable candidate now captures complete CurrentSentencePermit + original SentenceSpan. Core validates actual original delivery/source/scope/response/policies/text and prepares a private hypothetical prefix through existing projector. TurnContent retains actual confirmed context/digest separately from bounded64KiB ConditionalSentenceHandoff expected context/digest; explicit conditional model prompt, no predicted Journal/playback/ledger fact. Full and budgeted read-only hypothetical projection reuse only validated factual checkpoints, never invoke compressor/publish checkpoint/change in-flight factual task; overbudget/unsupported skips candidate preserving formal input. Async source stability3attempts and actor postawait authority retained. Exact terminal sentence-end sample+text match discharges condition, then formal actual context/digest+ASRrelation verifies cache. Normal1000sample uses2providers(old+candidate), early600uses3(old+candidate+actual rebuild), controlled24case matrix text/speech×finished/active generation×full/budgeted/sourcechanging projector. Candidate is not published before actual stop.

Eight originalsource/policy/frontier/model/TTS fault cases plus4checkpoint isolation cases added. Genuine red candidateTTSfailure previously drained bufferedtext then lostlease/fellback freshTTS; bothcache_follow now check knownerror beforebuffer. Pythonreview found second realrace TTSchild error beforeparent retired/done couldclaimformal and destructivelycancel privateBrain; red actualchild regression fixed by SpeculativeState.claim budget→retiredpending→knownerror&&!done raise originalbusinesserror→claimed. No falseclaim/new supplier beforeactualexit, privateBrainnotcancelled, originalinput retained. Realclosed supplier/deadlines/quarantine contracts unchanged; no universal forcefulsuppliercleanup claim. Independentcode/Pythonreview final results andfullverification follow.

No newproductionmodule/businessactor/playbackqueue. Constructorflag remainsdefaultFalse, not wired/enabled in userproduct, no3010/8765/8766restart/migration/realproviders/browser/push. Stage3/ADR0137/G3stillopen: complete mismatch/noncooperative supplierproductionmatrix, productwiring and realbrowser/digitalhuman physicalrenderer/latency, manual/DeliverItem repair. ADR0138 recovery newepoch/falseinterruption remainsunimplemented. FullG0–G5, durableunknownaction/idempotency/G2, realmarkedAudio/JEVfairness/globalwait/historybudgets, horizontaldiagnostics/errorcauses/defaultdualrecording/read-onlymachineAgentAPI remainoriginalscope. Report docs/reports/2026-10-07-conditional-sentence-handoff.md andADR0137/implementationplan updated. Authorizedlocalcommit follows; checkGitlog.

Finalafterpromotionwindowfix fullPython2290passed/69skipped/3subtests51.20s,132targeted,8productionMypy/12Ruff/diffcheckgreen. IndependentPython141tests+checksApprove; finalcodeincrementreviewApprove afterindependent51resourcetests/limitedchecks. Bothreviewers noblockers. Prior2289full wasbeforelastnewfaulttest. No production enablement/real latency claim, full plan goal remainsactive.

## 2026-10-07 product wiring / native WS Chrome handoff / admission error distinction

Prior batch committed a37f6fb; authorized local commit continues here. Added VOICEAGENT_SENTENCE_HANDOFF_PREFETCH_ENABLED default0 to actual server wiring, original response-prefetch master gate intact, text/speech unset/0/true regression red then green. Test-only ephemeral127.0.0.1 WS fixture uses actual Managed/Core/Journal/FrameBridge and original product conversation page/WebAudio; controlled ASR/final results/JEV/providers/synthetic silentPCM. No protocol/playback fake; browser supplies stop/sample receipts. Text/speech normal exact16000/16kHz sentence stop:2providers, no candidate frames/ASRcommit/predictedheardfact before actualstop, factualfirstsentence thennew source. Revoked pending candidate: formal failure retains importantinput, no privateprefix/PCM/newprovider, softretired notcancelled, actualrelease and fullBridge+Managed close checked; native overlapWS1013 and exact HTTPheaders/real directPythonSIGTERM close verified.

Browser red exposed real production bug: temporary supplier admission pending incorrectly OwnedStreamCleanupError poisoned permanent Brain/TTS cleanup ownership after realcandidateexit. ADR0142 adds sibling StreamAdmissionPendingError in existingcoreasync_stream, only2pendingguards+detachedcopy changed; genuineaclose failure remainssticky/quarantined. Three actualadapterred regressions nowgreen; cache unsolicted ownership remainsactor separately from formalBrain. No retryloop/newproductionmodule. Fixture itself latch/header/orphanprocess/diagnosticmasking issues fixed and failed beforepassingnative tests. Twoexisting independentreviewers limitedAPPROVE (161/134independentpytest). Final productionPython2298passed/69skipped/3subtests53.37s;151targeted,7Mypy/8Ruff/globalTSC/E2Eeslint/diffgreen. ServerMypy19existingHEADbaselineerrors unchanged; don'tclaimglobalserverMypy. ThreeChrome12passed42.3s; finalartifacterrorhandlingchange4passed18.6s. Oneearlier clientsideexception aftermicroclick beforetrigger was11green1red, no stackthen; preservedunresolvedfailure pluspageerror capture, subsequent12+4clean don'tprovefixed. Final archiveddocs/reports/evidence/2026-10-07-production-sentence-handoff.json syntheticPCMlength/hash only. Reportdocs/reports/2026-10-07-production-handoff-browser.md, ADR0142,0141,0137,plan updated.

Stage3/G3 stillopen: full ordinarysupplement/mismatch/noncooperativeproduction matrix/manual and DeliverItem repair; realmarkedAudio/provider/digitalhumanphysicalrenderer/pairedperformance; intermittentclientexception/Chromefirstfinishedunconfirmed. ADR0138 recoverynewoutputepoch/falseinterruption stillunimplemented. G0–G5/G1globalwait/historyfairness/G2durableunknownidempotency andhorizontaldiagnostics/defaultdualrecording/read-onlymachineAgentAPI originalfullscope remainactive. No new flag enablement/user3010/8765/8766restart/realprovider/DBmigration/push. Generatednext-env/tsconfig isolated3027noise restoredtoHEAD. This completes selectedincrement only, goalactive. Checkgitlogforauthorizedcommit. Nextcontinue scopedstage3 exceptions/repair and resolve browsererror with capturedstack beforeG3 closure; then0138.


## 2026-10-07 explicit/manual/model-delivery context repair

Continued the active full goal after b886827; no scope reset. ADR0143 accepted for current-session explicit reply admission/repair only. Existing actor/ReplyRevisionController admit completed model-visible same-scope/same-lease durable USER as manual root=item_id/version1, preserve existing ASR identity and subsequent pending voice supplement. New manual input records superseded unfinished voice text/input id/replacement id in input evidence before retiring it. Core takes user authority separately from tool/delegation trigger source; ResponseStarted.optional source_item_id preserves actual delivery parent, repairs retain original user and tool context, original absolute deadline/two-attempt budget, existing real cleanup/playback/permission and no-action-repeat rules. No new production module, actor or playback queue.

TurnController single repairable request covers auto/internal/public RequestResponse and MODEL delivery. Assignment revision fences new input/request/cancel; legal queued successors rebase when a delivery starts. Started facts retained so still-current failed admission can restore an original valid delivery that actually started during its wait. Public and internal send share original command/admission Future (shield duplicate waiters), successful replay cannot reauthorize old input, failed original may retry. Shared Request/MODEL delivery:<id> identity index rejects invalid new-key aliases before pending/output writes; errors only release original-command ownership. Non-MODEL errors never pop MODEL pending. Tables are current-session memory like existing Core idempotency; no cross-Session durable action claim or complete history budget claim.

27 new real Managed/Core/Journal/Bridge tests in tests/realtime/test_explicit_context_repair.py. Initial explicit4 red; reviewers reproduced manual+tool authority, CancelledError rollback, old Started takeover/clearing, legal queue, replay and rollback-started races. Actual red regressions also cover internal auto+repair replays, invalid delivery/Request aliases (original Journal item_id preserved), cross-mode DISPLAY_ONLY failure. Tools/delegations never execute from repairs. Final fullPython2325 passed/69 skipped/3 subtests53.42s; last targeted80 green. Six production Mypy/ten Ruff/diff green; base turn_manager.py628 sole type error independently confirmed same HEAD627 text, not introduced. Both reused reviewers final limitedApprove (Python105 plus cross-mode52; code80). Isolated3027 Chrome4 passed21.0s after shared identity index; last error-only filter/text changes covered by actual regressions/fullPython. Earlier browser4 runs green too; no real provider/marked audio/DB/physical renderer, no3010/8765/8766 restart or defaultoff flag enable/push. next-env/tsconfig generated noise restored exactly to HEAD.

Report docs/reports/2026-10-07-explicit-context-repair.md; ADR0136/0137/implementationplan updated without closing G2/G3. Goal remains active and full original scope G0–G5/horizontal tracks preserved. Next continue stage3 real manual transport/complete ordinary supplement mismatch and noncooperative resource matrix; review actual browser startup exception/first finished with captured stack; then implement ADR0138 false-interruption recovery with new version/epoch after prerequisites. Real provider/audio/digitalhuman paired perf, G1 global wait/history/fairness, G2 unknown-action durable idempotency, defaultdualrecording/diagnostics/errors/read-only machine Agent API remain unfinished. This is a completed increment, not whole-plan completion. Authorized local commit follows; inspect git log.


## 2026-10-07 canonical saved stop facts into the existing actor (ADR0144)

Continued the authorized commit/remaining-plan task after 4d8e58c. Actual manual UserTextFrame → Journal/Managed/Core/Bridge regression now covers legacy/precise stop receipts before context repair; manual rootID/version preserved, repairedreply increments only after actual stop projection. Precise evidence associates REQUEST/CONFIRMED with original input/reply and operation sequence. Tests use normalized controlled providers, not real voice performance.

Two new combination tests went red: Core saved stop but actor output_stop stayedNone. Rootcause Managed independently persisted RecordOutputStop and returned before Core's new observation branch. SpeechLifecycle returnscanonical fact; Managed now notifies captured original delegate through optionalasync wrapper observer aftersave, without anotherwrite or sendlock. Reconfigure clearsobserverdelegate before oldactor cancel/close; old/pendingwrites duringreplacement never notifyreplacement; closefencesnotification. Save+notify tracked underexistingstopwriteownership. Core fallbackwithoutsharedManagedstore independentlysavefirst. NewObserveAssistantOutputStop carriescontextproperty fornormalactor scopegate.

Bridge server ordinal len(live outputstops)+1, existing512limit, scopedtooutputepoch, optionalfactfield immutableidentity. Puretransition movedtoprotocolcommands withdeliverycompat reexport. Existingactor synchronouslydrives pureledger; onecurrentstopfact, scope/lease/response/speech/knownEpoch check, onlystrictlynewer orderedoperationcanreplace, firstterminal immutable, UNKNOWNcannotlaterconfirm. UTCreversal testproves noUTCordering. Observationdoesnotgrantdelivery/sentence/repairpermission orplaybackposition. Newbind/close fenceoldfact; evidenceJournal storesISOdates/originalinput/reply. PGJSONold/newrowcompatible, notnewtable/migration.

FinalPython2360passed/69skipped/3subtests54.79s; scoped19fileRuff,14productionMypy andgitdiffcheckpass. Legacyturn_manager pendingassignmentMypybaseline remainsline639, notintroducedhere. IndependentPythonreviewApprove/130tests. Chromeactualfourhandoffscenarios4passed18.5s with3027/loopbackcontrolledproviders andrealWebAudio; no3010/8765/8766restart, realproviders/PGcalls or productflag enable. Next actualADR0138 reliablefresh-evidence recoverypermit/newreply/epoch/reinterrupt/unknownstop exit. ADR0138/G4notcomplete, broaderG0/G1/G2/G3/G5 andhorizontalrequirementsremainactive. Report docs/reports/2026-10-07-canonical-output-stop-observation.md; ADR0144/0138/planupdated.

Code review also reproduced failedpre-reconfigure cancellation leavinglivehandle withobserverNone. Added4actualManaged red→green error/CancelledError cases canceloutput/oldclose. Reconfigure failurewithoutrestoredobserver synchronously starts ownedclose and marksclosed. Ifoldclosehasnotstarted, existingcleanup proceeds; ifstartednotconfirmed, explicitclosefailure cancelsManagedpump, retains suspendeddeleteguard, no wrapperclosed shortcircuit retry canclaimunderlyingcleanup. Awaitoldclose redcase initiallyhung and wasinterrupted; failureexit nowbounded. Shared_start_close helper avoidslockrecursion; 4tests/Mypyruntime pass; finalfull2360passed/69skipped/3subtests54.79s, Chrome4passed18.5s. Code-reviewrecheckApprove/106tests; Pythonrecheckidentified/fixed recoverycleanup below.

Python recheck found uncertainclose earlyraise skipped existingrecoverytask cancellation. ActualFactory/FakeDelegate.events emitsCapabilityFailed thenblockedRecovery; two oldcloseerror/cancel casesred2fail/2pass(recoverypending). Movedexistingrecoverycancel/gather beforeuncertainclosefailure;4pass0.18s/Ruff/Mypyruntimegreen. InitialtestfailureputInMemoryqueue hitadapter whitelist; correctFakeDelegate.events seamnowusesactualwrappedpump. BothreviewsApprove; independentcode58tests/Python4tests, staticchecksgreen; Finalfull2360passed/69skipped/3subtests53.00s afterallfixes.

## 2026-10-07 fresh revised evidence recovery planning (ADR0145)

After a048dee, original stopped reply/input/version and overlapping observation snapshot freeze before barge-in revoke. First absolute deadline never extended. Only higher ASR material rewrite/full ended reliable BACKCHANNEL/IGNORE and canonical STOP_CONFIRMED+matching terminal playback produce immutable ReplyRecoveryPlan; append/equivalent/old batch/partial/fallback/lowconf/question-answer rejected. Proposed fresh originalturn generation+response/epoch only, no actual bind/delivery/permit/Core/transport action. Unknown sample position truthful regenerate_continuation from confirmedheard; unknown stop never plans. New speech/input/reply/STOP/close/deadline supersede. One bounded anchor/text/plan; existingactor+ledger+evidence only. Actual actor local full sealed rules only; freshmodelbatch remainsnext. Factfirst/feedbackfirst × chunksFalse/True × concurrency1/2 actor tests. Reviewer found current full opposite model result leftplanlive, red4 reproduced; now valid current opposite clearsfeedback/cache,5old/partial/foreign/fallback/lowconf cases preserve. Both limitedApprove afterfix. New54tests; full2414passed/69skipped/3subtests53.23s; 3Mypy/4Ruff/diffgreen. No browser/provider/PG/service3010/8765/8766restart/flag/push. ADR0138/G4andfullremaininggoalactive; next fresh sealed JEV review then consumeplan/admission/newreply and physicalepoch/reset/againinterrupt/unknownexit. Reportdocs/reports/2026-10-07-misinterruption-recovery-planning.md. Authorized localcommit follows.

## 2026-10-07 independent sealed recovery model feedback

After83b44be, continued ADR0145 in existing actor/ledger/registry only. recovery_review_deadline validates original anchored reply/input/current material rewrite/first absolute stop deadline. Rules first; unmatched full new evidence after yield confirmed uses existing semanticclassifier/JEV/ClassificationExecutor via independent recovery_feedback token/recovery_model family. Frozen no-chunk snapshot, original verdict/stop never overwritten. ModelBACKCHANNEL/IGNORE canplan; actualquestionanswer/lowconf/failure/UNCERTAIN/INTERRUPT/CORRECTION retaininput forfinalcommit; newreliableSTOP purecontrol/discard withoutreply. Sharedslots retainnoncooperativechild untilrealexit. ResumeVAD/newASR/newreply/close/forcecommit cancelandfence. NoactualCoreconsume/permit/newreply/newepoch yet.

PythonreviewHIGH foundVADstopbeforetailASR partial eachreview incorrectlysentence_end. Formalactual4redcapacity1/2×endpoint/idle fixed: recovery_sealed_revision only currentrevision/acousticversion idleaccepted; newASR/VAD/replyclear. RequireactualTextBoundary.END orcurrentidlestability, otherwisewaitexistingidletimer; partialcancelsoldreviewwithoutstartingnewone. 36modelclassification/fault/questioncases+10noncooperativecancel/deadline/closecases+4sealingcases =50new; planningfile104passed. FullPython2464passed/69skipped/3subtests55.32s aftersealfix.3productionMypy/4Ruff/diffgreen. PythonfinalApprove109independentcases; codefinalsealApprove207independentcases. No browser/realJEV/PG/recording/service3010/8765/8766restart/flag/push. Nextactualrecoverypermit/Corecontinuationadmission/newreply andphysicalepoch/reinterrupt/UNKNOWNexit. Fullgoalstillactive, G4notcomplete; reportdocs/reports/2026-10-07-fresh-recovery-model-review.md and ADR0145/0138/planupdated. Authorizedlocalcommitfollows.


## 2026-10-07 actual misinterruption recovery execution (ADR0146)

Continued authorized commit/remaining-plan task after c2f9094. Existing actor/Core handshake consumes reliable recovery plan through existing ReplyRepairPermit. Durable original USER input_context is separate from new execution context; input_id/version retained, reply_version/supersedes/newgeneration preserved across repeated recoveries and Journal restoration. Core regenerates from confirmed heard history, retains original response deadline and tool/delegation execution prohibition. Existing modules/one actor/one queue reused.

Actual Bridge requires original confirmed stop + projection ready. Endpoint CAS rotates live outputepoch and send_output_epoch_started verifies epoch/attachment inside existing send lock and after send, never buffers control onto resumed attachment. Frontend ordered frame resets only outputGraph/playbackOutput/playbackText, preserves microphone/input epoch. Bridge advances future inputgeneration. Applied complete recovery plan retained in bounded stop record makes replay after completion idempotent. recovery_preparing is revocable by newer VAD until semantic publication; older VAD early-returns like ASR. First absolute recovery deadline bounds notification, cancellation by normal close is not a failure; every failure synchronously latches PCM before async notice.

Independent review red->green fixed futureinput rejection, completed replay failure, preparing VAD admission, failure scheduling PCM leakage, send-lock cross-attachment race, notification deadline overrun, normalclose falsefailure and staleVAD supersedingnewreply. 24 actual controlled production cases (fact order x actualEndpoint/simple x six behaviors), 12 output barriers and5 corruptsourcelease cases =41 newPython. Full2505passed/69skipped/3subtests56.89s; 10productionMypy,15file scopedRuff(E9/F63/F7/F82/I),TS noEmit and4Vitestfiles93pass. Actual isolated3027 Chrome text/speech normal/revoked_pending/recovery6pass24.9s; initialnewrecovery2pass14.9s. Autogeneratednext-env/tsconfigE2E changes restored from verifiedHEAD. No user3010/8765/8766restart/provider/PG/flag/push. G4 completefault/unknownstop/realprovider/audio/renderer remainsopen; G0/G1/G2/G3/G5 andhorizontal tracks unchanged. ADR0146/reportexecution and0138/0145/plan updated. Continue unknownstop/late receipt/noncooperative fault matrix, not claim fullplancomplete.


After43bb066 continued12 actualproduction unknown_stop/stale_stop/missing_receipt cases acrossfeedback orderandEndpoint/simple. CanonicalSTOP_UNKNOWN+boundedfailureexit retainoldrevoke/noBrain2/noepoch; latequeue_stopped cannotreopenfact/permission. Missingreceipt usesreal50msBridge timer andwait_forfact, notmanuallysetstate/fixedsleep. Productioncodeunchanged. Finalscoped planning/execution/barriers/stop/history204passed2.83s; scopedRuff/diffgreen. PythonlimitedApprove/36independentexecutiontests. G4terminalfailure subset nowcovered; completefault/realprovider/renderer andotherfullgoaltracksremainactive. Test/documentlocalcommitfollows.


## 2026-10-07 owned noncooperative output control IO (ADR0147)

After5eac78b continued G4 hard deadlines. Noncooperative epoch send in actual/simpleEndpoint swallowed all cancellation:50msdeadline yetcallerpending200ms,2formalred. ExistingBridge private _await_output_control_io nowowns Task+asyncio.wait boundedcallerwait; timeout/cancel requestschildcancel withoutfakeexit,8pendingtaskcap includesresiduals, actualdonecallbackcleansandlogs lateexceptions withVoiceSessionIDtaskname. Used for epochnotice, preciseandlegacy/targetNone stopcommands, failnotice andtransportclose. ExistingRecordOutputStop/playbackprojection ownershipunchanged.

Reviews foundlegacy wait_for fallbackstillunbounded; migrated. Then normalclose withoutcancellingcaller andnoncoop child causedtimeout falsefailure;4red legacy/precise×simple/actualEndpoint fixedclosed guard inbothsend Exception paths. begin_close cancelsIO, closeboundedjoin ofnotifications/controlIO/oldfactwrites preservesresidualowners. Endpointfailurefinallywakes evennoncoopnotice/close; actualVoiceSession cleanupbrain/tts/classifier tasksfinishbeforeIO exits. Adaptercannotbeforciblyterminated/alreadystartedsendcannotretracted; resourceexitnotclaimedbycallerreturn.

New14formalcases:epochsimple/actual×latesuccess/error4; stopslegacy/precise×simple/actual×normal/failure8; actualEndpointnoncoopnotice/close2. Finalscoped54passed3.71s; productionMypy/3fileRuff/diffgreen; fullPython2531passed69skipped3subtests60.69s; actual3027Chrome6pass28.0s. TwoindependentreviewsApprove/52cases and8capacity/ninthreject/callercancel/actualexitprobes. No user3010/8765/8766restart/PG/liveproviders/flag/push. E2Egeneratednext-env/tsconfigverifiedandrestored. ADR0147/report/0138/0146/planupdated. Wholegoalactive: G4 fullsupplier/disconnect/renderer matrix, G0oracle/G1fairness/performance/G2unknownactions/G3completehandoff/G5load andhorizontalrecording/diagnostics/AgentAPI stillopen. Authorizedlocalcommitfollows.

## 2026-10-07 Session-scoped Agent diagnostic access (ADR0148)

Continued after d03f726 with clean tree. Existing diagnostics GET gains independent exact-Session, named, 15-minute read bearer; admin same-Origin POST issues it. Separate OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET defaults empty/disabled, no service configuration changed. Invalid Authorization never falls back to cookie; machine cannot query global health or forward bearer to Control Plane. Existing telemetry/debug cursors and source completeness retained. Real Session detail adds same-theme credential JSON download; preview disabled, bounded request/duplicate-click/unmount fencing; no localStorage or token in ordinary diagnostic export.

Code review found dot-segment ID path normalization, 2 red tests; shared ID helper excludes standalone dots in issuer/verifier/GET. Then actual shared-thread A/B conversation leak (HIGH), 5 real ApplicationRuntime/Journal/Telemetry red cases. Production reader now resolves recorded tenant/user/thread via existing session_history_scope after telemetry flush, filters original context.voice_session_id and projects it. Machine GET independently checks every source/row provenance, including missing legacy identity. More than 1000 thread items probe+fail unavailable instead of falsely complete array. Conversation pagination remains unfinished. No new actor/queue, no production DB migration/provider call/user services restart/remote push.

Final fullPython2537passed69skipped3subtests58.56s; fullVitest1312passed7skipped18.49s; targeted29auth+93Python, TSC/scopedESLint/Ruff/diffgreen. Independent code review final APPROVE with92Python/30TS and UI lifecycle probes; actual admin download/externalAgent deployment acceptance remains open. ADR0148/report docs/reports/2026-10-07-agent-diagnostics-access.md and guide/requirements/plan updated. Secret rotation revokes all; no per-grant revocation/durable usage audit, removing admin does not revoke already issued 15min grants. Whole goal remains active: recording/storage/playback evidence, diagnostic completeness/conversation pagination/error cause dedup/coldwarm reconnect, G0–G5 original gates. Next audit AudioSink/ArtifactStore seams and default dual recording, preserve real experiment tracks. Authorized local commit follows; verify git log.

Python review also found first5000 telemetry scope page omitted conflicting5001st identity. Sixth actual Runtime/Journal/Telemetry red regression fixed via optional require_complete=False on existing resolver; only reader passesTrue and next_cursor fails incomplete without unbounded/repeated query. Otherhistory/deletion unchanged. Python final limitedAPPROVE/93tests. RuntimeMypy import-untyped asyncpg warning is HEAD baseline; disabled import-untyped internalcheck passes. Demo19Mypy errors identicalHEAD, no reader新增; not fullPythonTypesgreen. Remaining largeSession identity query and conversation pagination explicit, not confused with empty content.


## 2026-10-07 Journal-authoritative diagnostic conversation pagination (ADR0149)

After944362b, exact originalSession user.input/assistant.output Query inside existingJournalSeam; memoryscope/index/bisect+bothdeletepaths, PGsingleSQLsnapshot/3sstricterstmtbudgetrestore/4soperation/5sHTTPobserver,0035concurrentpartialindex controlledmigration. Querydoesnotusefirsttelemetryidentityorwholethreadlimit; CORRECTIONevidenceexcluded, multi-dialoguescopeconflictfails. Privateconversation-page→productionCLI/demo→unifiedGET200rows+thirddecimalstringbigintcursor→UI/Agentfile. Originalarrayreaderretainssafe1000/5000refusal. RowSession/monotonic/cursor/pagecapverified. Successfulsourcesadvanceindependentlywhilefailedsourcekeepsrows/cursor/status. Duplicateclick+switch/refresh/unmountlateignoreabort+15stimerfencing.

Pythonreviewfixedforcedrepeatable_readnestedoutertxn+SETLOCALleak; realPGouterreadcommittedand100msrestoretest. Concurrentinvalid/incorrectindexrefusedexplicitly, noautorepair; validationchecksvalid/ready/table/columnorder, notexactarbitrarypartialpredicate. 5newPGcases,fullJournalPG15passed1.82sonlocalexistingPG16.13/tmp randomizedtestschemasfinallycleaned; no productionmigration. FinalfullPython2547passed74skipped3subtests68.53s; fullVitest1331passed7skipped17.26s. RelatedPython122passed14.14s,8ESLint/TSC/5coreMypy/scopedRuff/diffgreen. KnownHEADdemo19/HTTP18Mypyerrorsnotclaimedgreen. ReusedindependentreviewersPythonlimitedAPPROVE/codeproductionandactualhookprobesnogatingissues; finalcodeapprovalcheckbeforecommit. Reportdocs/reports/2026-10-07-session-diagnostic-pagination.md, guide/requirements/plan/0148updated.

No user3010/8765/8766restart/liveprovider/secret/flag/push; deploymentactualadmin/externalAgent+0035remainopen. Fullgoalactive: defaultdualrecordingstorage/AudioSink+actualsentvsplayedmapping/7dayspin, inputevidenceaggregation/faultcausaldedup/coldwarmreconnect andallG0–G5originalscope. Nextcontinue recordingseamaudit/ADR andboundedproductionpathwithoutaddingbusinessactor/queue. Currentauthorizedlocalcommitfollows;inspectgitlog.

最终代码审查又复现合法空投影页带next_cursor被误报404：新增两页正式回归先红（404不等于200），修hasContent计入有效续游标后43项相关Vitest绿，TSC/路由ESLint绿；无游标真空仍404。此前1331项全量前端是在该最后小修前执行，不把43项定向验证称为再次全量。


## 2026-10-07 recording Artifact retention and actual upload ownership (ADR0150)

Afterauthorized7b3bb6d, continuedOBS03storageprerequisite. voice_session_recording requiresawaredeadline; existingPGcleanupintentcreatedsameartifacttransaction, pin cancels; Memory recordingonly expiry and retry underexistingphases. OptionalArtifactCleanup1..1000 strictint, fewerattemptsrotationavoidsrecordheadblocking. SharedprivateArtifactUploadOwnerbounded64 shieldedactualtasks throughSDKto_thread, caller cancelnotworkerexit. Memoryactive/orphanowners keepDELETINGuntilactualexit/cleanup, invalidreceiptkey remainsserver-owned, latefailedfinalizeCAScannotreviveDELETED,pinwinsnotfalsefailure.

Newcontrolled0036put_completedcolumn. Actualputreturn->DBmarkerbeforecrashhook; oldrevokedattemptrearmedcleanup_pending/tokenNULLnotpendingpublication. Unconfirmedwritecleanupkeepsdurableunknownpendingandperiodicretry; onlyconfirmedput+objectdelete+currenttokenUPDATE1countsclosed. Legacyoldcleanedrowsnotgivenfakehistory. Unknownmetadata mayretainindefinitely ifproviderexitunproven; noclaimnativeforcekill. PGdeletefailure/restart,pinbeforeafterclaim,lateputphysicalwrite/crash/orphandeletefail,SDKcaller cancel,64residualcapacity,tokenrevocation andfairnessformalregressions. Initialfeature7Memory3PGred, reviewedhigh/mediumactualred->greenfixes documented.

FinalfullPython2562passed84skipped3subtests59.20s; scoped48passed1skipped4.60s; actualexistinglocalPG16.13/tmp fixture-onlyrandomschemas36passed4.04s(Artifact21+Journal15),finallycleaned; no productionmigration/DBrestart.4coreMypy/7Ruff/diffgreen; Memory6_replace**objecterrorssameHEADshadowbaseline. ReusedPythonreviewfinallimitedAPPROVE28Memory21PG; codefinalAPPROVE29Memorypluscapacity/orphanprobes. ADR0150/reportdocs/reports/2026-10-07-recording-retention-foundation.md,requirements/planupdated. No realS3/provider/user3010/8765/8766restart/defaultrecording/flag/push.

NextOBS03 boundedsegmentedinput+actualsentcollector and seven-daypolicyapplication,RuntimeArtifactStore+ownedIOshutdown/maintenance,Sessionmanifest/audioquery+confirmedrendererplayback; recordingnotenablednorUIaudioavailable. OBS02inputevidenceaggregate/errorcausaldedup/coldwarmreconnect andallG0–G5originalscope remainopen;fullgoalactive. Authorizedlocalcommitfollows; inspectgitlog.

Finalcodeinspectionalsofoundorphanbranchstarvation:2actualLatePutorphansfirstpermanentsecondtemporaryfailure,limit1formalredsecondcleaned0expected1. Failedorphanlockpop/reinsertrotatesendwithoutnewqueue/ownershipchange; latestrelated48passed1skipped4.60s/Ruff/diffgreen. FinalfullPythonafterthissemanticfix2562passed84skipped3subtests59.20s; finalcodeAPPROVE29Memory/probes,4coreMypyrecheckgreen.
