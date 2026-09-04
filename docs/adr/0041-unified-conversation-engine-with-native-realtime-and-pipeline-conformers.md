---
status: superseded by ADR-0063
---

# Unify native realtime and composed speech pipelines behind Conversation Engine

The production runtime will depend on one vendor-neutral `ConversationEngine` contract that advances conversation context into canonical `ConversationAction`s. Native end-to-end realtime model sessions and composed ASR → Brain → TTS pipelines are equally supported conformers; neither leaks provider events or its internal pipeline shape into orchestration. We rejected making either form the only core because a GPT Voice-style native session is the latency target, while the existing replaceable speech and Brain capabilities remain necessary for vendor choice, local deployment, and incremental migration.

## Consequences

- The canonical action vocabulary is speak, fast tool call, background delegation, confirmation, and session end.
- The existing Brain remains a capability used by the Pipeline Engine rather than the whole runtime's top-level contract.
- `RealtimeSession` is not adopted as the shared name because it conflicts with the existing Endpoint Session concept and incorrectly privileges one conformer.
- New conformers live behind explicit Seams and must be replaceable without changing the session coordinator or tool/task orchestration.
