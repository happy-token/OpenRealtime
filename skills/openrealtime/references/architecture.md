# Architecture

Condensed from `docs/ARCHITECTURE.md` and `CONTEXT.md` — read those in full for
the complete Seam map, Mermaid diagram, and Seam→Protocol→ADR table.

## Seam

The core organizing concept. A **Seam** is an extension point in the
framework's backbone with a defined contract (a `Protocol`) and a
deterministic, dependency-free default. A Seam's directory holds its
`Protocol` plus that default; a real, vendor-backed implementation lives
under that directory's own `plugins/` subfolder — e.g. `speech/asr.py`
defines `AsrEngine`, `speech/plugins/doubao_asr.py` implements it for real.

Backbone Seams: Conversation Kernel, Endpoint Session, Turn Policy,
Brain/Router, Response Scheduler, Event Ledger.

## Data flow for one turn

```
Transport Adapter → Conversation Kernel → EnergyVad → (EotClassifier, optional)
  → Turn Policy FSM → Router → DelegationPolicy
      → answers locally: ChatBrain/ToolCallingBrain (+ Tool Sources)
      → delegates: Agent Session Protocol (Driver)
  → BrainResponse → Response Scheduler (checks Generation Lease)
      → TtsEngine/StreamingTtsEngine → Transport Adapter sends frame
```

Every step also fans out read-only events to the Event Ledger's Observers —
logging/analytics never mutate the pipeline.

1. **Transport Adapter** turns a wire connection (WebSocket, UDP) into
   `Frame`s (`server/transport/frames.py`), handed to the
   **Conversation Kernel**.
2. The Kernel runs audio through `EnergyVad` and, if an `AsrEngine` is
   configured, through the **Speech Seam**'s `AsrSession`.
3. On `USER_EOT_CONFIRMED`, the Kernel optionally consults `EotClassifier`
   (gated at the Kernel, one layer *above* Turn Policy — not inside its FSM)
   before committing the end-of-turn signal.
4. **Turn Policy**'s 5-state/11-transition FSM (IDLE/LISTEN/SPEAK/WAIT/DUAL)
   evaluates the signal, consulting `AddresseeClassifier` and
   `DualIntentClassifier` as needed, and emits a committed user turn.
5. **Router** asks the registered `DelegationPolicy` whether to answer
   locally or delegate to an external Agent via the **Agent Session
   Protocol**.
6. The `BrainResponse` reaches the **Response Scheduler**, which re-checks
   the **Generation Lease** (a superseded turn's result is discarded, not
   spoken) before handing frames back to the Transport Adapter.

## Seam vs. plugin, at a glance

| Seam | Protocol file | Default | Real conformer |
|---|---|---|---|
| Transport Adapter | `transport/base.py` | — | `WebSocketTransportAdapter`, `UdpTransportAdapter` |
| Turn Policy | `turn_policy/policy.py` | full FSM (no plugin needed) | — |
| DualIntentClassifier | `turn_policy/dual_intent.py` | `DefaultDualIntentClassifier` (duration) | `LlmDualIntentClassifier` |
| EotClassifier | `turn_policy/eot_classifier.py` | unregistered = every signal passes | `LlmEotClassifier`, `EnsembleEotClassifier` |
| AsrEngine | `speech/asr.py` | `PreloadedAsrEngine` | `DoubaoAsrEngine`, `BellaAsrEngine` |
| TtsEngine / StreamingTtsEngine | `speech/tts.py` | `SilentTtsEngine` | `DoubaoTtsEngine` |
| Brain / LlmClient | `brain/base.py`, `brain/llm_clients.py` | `EchoLlmClient` | `OpenAiCompatibleLlmClient` |
| DelegationPolicy | `brain/delegation_policy.py` | `NeverDelegatePolicy` | `KeywordDelegationPolicy` (demo-grade) |
| Agent Session Protocol / Driver | `agent_session/` | `InMemoryDriver` | — |
| Knowledge Base / WebSearch | `knowledge_base/`, `web_search/` | `InMemoryKnowledgeBase`, `DeterministicWebSearch` | `ByteWebSearch` |

Full table with every Seam and its ADR: `docs/ARCHITECTURE.md`'s
"Seam → Protocol → ADR" section.

## Terms that are easy to get wrong

- **Brain**, not "Agent" — "Agent" is reserved for an *external* Brain
  reached via the Agent Session Protocol.
- **Barge-in** vs. **Backchannel** vs. **Third-party speech** — three
  distinct DUAL-state outcomes; "interruption" is not a term this project
  uses (conflating barge-in with backchannel is the survey's most-cited
  failure mode).
- **Generation** is a supersession counter, not a turn/session ID.
- **Observer** (async, read-only, Event Ledger) vs. **Hook Point**
  (synchronous, in-line, can transform/veto) — different mechanisms, not
  synonyms.

## L0 ceiling

This is an **L0** architecture (full-duplex survey §4): an external module
pipeline (VAD/EoT/turn-classifier feeding a text LLM), not an end-to-end
trained duplex model. DUAL-state discrimination is bolt-on classifier
plugins, not native architectural integration — a deliberate, accepted
trade-off, not a gap to close.
