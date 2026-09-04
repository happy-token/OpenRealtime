---
status: accepted
---

# Rules-first stop-phrase check and confidence-threshold demotion in LlmDualIntentClassifier

ISSUE-0005 (see `docs/ISSUES.md`) and ADR-0015 both previously claimed that
`LlmDualIntentClassifier`'s "fall back rather than guess a fixed direction"
discipline "mirrors voiceloop's own `apply_interruption_threshold`, which
downgrades low-confidence stop-labels to 'uncertain'." An exhaustive grep of
`tmp/voiceloop-modular-runtime` (the in-repo checkout of `../realtime`) found
no `apply_interruption_threshold` method and no confidence-threshold
classifier anywhere in that codebase. Voiceloop's actual interruption
mechanism is a **static `interrupt_strategy` config choice** (`"transcript"`
vs `"vad"`, composing pipecat's built-in strategy classes) plus an unused,
never-invoked `backchannel_classifier` stub — there is nothing dynamic or
confidence-scored to port. The only real "cheap rules check before ever
calling the LLM" precedent in voiceloop is in its unrelated filler-gate
module (`RuleMatcher`), which short-circuits filler-word insertion, not
interruption classification. ADR-0015 is corrected in place (see its
2026-08-03 correction note) rather than left standing on a false claim, and
this ADR records the real design that replaces it.

Two additions to `LlmDualIntentClassifier`
(`voiceagent/turn_policy/plugins/llm_dual_intent_classifier.py`), both ahead
of or around the existing LLM round-trip, both new design work loosely
inspired by voiceloop's filler-gate `RuleMatcher` *shape* rather than a port
of anything voiceloop's interruption path runs:

**Rules-first stop-phrase check.** A new `stop_phrases: tuple[str, ...] =
DEFAULT_STOP_PHRASES` constructor param (`"stop"`, `"wait"`, `"hold on"`,
`"hang on"`, `"停"`, `"等等"`, `"打断一下"`, `"不是不是"`) is checked as a
case-insensitive substring match against `text`, before ever calling the
LLM. A match returns `FLOOR_CLAIM` immediately, skipping the network
round-trip entirely for the obvious case — the same motivation as
voiceloop's filler `RuleMatcher`: don't pay for a model call when a cheap
deterministic check already has the answer. Passing `stop_phrases=()` opts
out and restores the previous all-LLM behavior.

**Confidence-threshold demotion.** `DEFAULT_SYSTEM_PROMPT` now asks for two
space-separated tokens — a label and a confidence, e.g. `"stop 0.92"` —
instead of one. A new `confidence_threshold: float = 0.8` constructor param
gates the `stop`/`correction`/`interrupt` labels specifically: if the
confidence token is missing, unparseable, or below the threshold, the
classifier delegates to `self._fallback` exactly like the existing
empty-text/unparseable-reply path, rather than manufacturing a `FLOOR_CLAIM`
from an unsure judge. `backchannel` is deliberately **not**
confidence-gated: a false backchannel only means the assistant keeps
talking, which carries no false-interruption risk, so there is nothing to
guard against by demoting it.

Both additions are backward compatible by construction: the defaults only
add a new immediate `FLOOR_CLAIM` path for obvious stop-phrases (a case that
previously required a full LLM round-trip to reach the same answer), and
demote low-confidence `stop`/`correction`/`interrupt` replies to a path
(`self._fallback`) that was already the destination for unparseable output.
No change to the `DualIntentClassifier` Protocol or the `DualIntent` enum;
unregistered behavior (no classifier configured at all) is unchanged.
