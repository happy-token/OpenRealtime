---
status: accepted
---

# Keep Conversation Kernel thin over independent capability Seams

Conversation Kernel will be reduced to the coordinator of one live voice interaction: lifecycle, event ordering, correlation IDs, supersession, cancellation propagation, and dispatch across replaceable Seams. Conversation Engine, fast-tool execution, background-task execution, media I/O, output scheduling, persistence, and observability remain independent capabilities behind contracts. This follows the locally observable GPT Voice boundary between continuous Realtime media/generation, app-server/Sideband control and tool bridging, and delegated background threads, without claiming that these project modules reproduce OpenAI's private cloud topology.

## Consequences

- Kernel may depend on capability contracts, never vendor SDKs or concrete tool/task backends.
- Capability implementations can be replaced independently and tested with deterministic conformers.
- Cross-cutting IDs and cancellation semantics are coordinated centrally instead of reimplemented by every capability.
- Existing Kernel behavior may move behind new Seams even when that requires breaking internal interfaces.
