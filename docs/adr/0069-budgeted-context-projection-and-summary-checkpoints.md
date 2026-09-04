---
status: accepted
---

# Use one budgeted context policy with traceable summary checkpoints

Native and Cascaded Realtime Engines rebuild model context from the same versioned Context Policy rather than applying provider-specific implicit truncation. The policy reserves output, tool-schema, governing-instruction, current-input, and safety capacity first, then assembles active work and delivery-corrected recent turns with the latest valid Conversation Summary Checkpoint covering older Journal sequences.

Phase 1 implements and gates this policy only on the Cascaded Realtime Engine. Native provider integration is deferred and does not block Cascaded release; any future Native conformer must adopt this same policy semantics before it can become production-ready.

Compression is asynchronous and produces a derived `CONTEXT_SUMMARY` Item containing its exact source range and digest, compressor model/version and policy version, token counts, and invalidation metadata; original Journal Items remain authoritative. A projection may continue with a prior valid checkpoint plus a smaller recent window when new compression is unavailable, but it must emit an observable degradation and must fail the Model Context Restoration Barrier if required instructions, active work, current input, or a coherent recent history cannot fit without silent loss.

Each checkpoint uses structured content plus a natural-language narrative. The structured payload contains decisions, open questions, commitments, active work/artifact references, source range and digest, and compression-policy identity; model adapters render that canonical structure for their own context format, while long-term user Memory remains a separate domain rather than an accidental side effect of conversation compression.

Context Compressor is hybrid: code deterministically derives typed Tool, Agent Task, Confirmation, Artifact, item identity, lifecycle, and causal fields, while a model compresses only the conversational narrative and source-grounded decisions or unresolved questions. Schema validation, reference resolution, source-range checks, token limits, and sensitive-data policy reject invalid output; rejection leaves the previous valid checkpoint in force and never updates an authority from model-generated state.

Context Policy and Compressor selection belong to Application Control Plane, not Realtime Profile or an Engine plugin slot. A deployment may reuse the same provider credentials as its chat model, but compressor identity, model/schema/prompt version, budget, queue, timeout, concurrency, and checkpoint compatibility are explicit and independently observable; changing speech or Engine bindings does not silently change context compression.
