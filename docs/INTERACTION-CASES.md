# Interaction cases — audit

One row per interaction the system must handle, from the survey's T×I×R ontology
([full-duplex-survey.md](full-duplex-survey.md) §3) plus the cases the survey
does not model but a production runtime meets anyway. Each case records what
*should* happen, what the code *does*, the τ path, and — the point of this
document — **what the existing test asserts versus what it misses**.

Companion documents: [ASSESSMENT.md](ASSESSMENT.md), [LATENCY.md](LATENCY.md).

## How to read the columns

- **τ path** — from `full-duplex-survey.md` §6.4's cell-to-transition mapping.
- **Test asserts** — what the shipped test actually checks.
- **Test misses** — the observable outcome no test checks. This column is the
  reason four P0 defects survived 425 passing tests.
- **Fixed now?** — whether this round's P0 work closes it.

---

## Part 1 — The six acid-test cells

### Cell 1 · Standard turn (T1, I1, R6)

|  |  |
|---|---|
| **Expected** | Clean sequential handoff at a transition-relevance place. |
| **Actual** | Works. |
| **τ path** | τ3, then τ7. |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:73` `test_standard_turn_completes_via_tau3_then_tau7` |
| **Test asserts** | `["τ1","τ3","τ7"]`, `end_state is IDLE`, and the exact `AssistantTextFrame` sent. |
| **Test misses** | Nothing material. This is the one cell whose test checks an output frame, not just the edge list. |
| **Fixed now?** | n/a — already correct. |

### Cell 2 · Latched zero-gap (T2, I1, R6)

|  |  |
|---|---|
| **Expected** | Near-zero-gap handoff: the assistant must begin generating *before* the user finishes. Requires semantic VAD plus speculative TTS. |
| **Actual** | **Implemented for the default Chat Brain.** Doubao/Bella sentence-final revisions start semantic confirmation and one speculative main-LLM stream concurrently. A stable complete verdict commits the turn and the Conversation Engine consumes the buffered/live response without a duplicate request. VAD speech or an ASR revision invalidates both candidate and speculation. Tool-calling remains non-speculative because external side effects need a separate commit protocol. |
| **τ path** | Should be τ3 at near-zero latency; is τ3 at 1.5–4.5s (see [LATENCY.md](LATENCY.md)). |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:108` `test_latched_zero_gap_handoff_is_still_tau3` |
| **Test asserts** | `["τ1","τ3"]`, `end_state is SPEAK`. |
| **Test misses** | Everything that makes latching *latching*. The test name and body **encode "zero-gap is not implemented" as the expected value** — it is a pin on current behaviour, not a check of the cell. Nothing anywhere asserts a latency bound. |
| **Fixed now?** | **Core path yes.** `AsrSnapshot`, `SemanticEndpointGate`, `SpeculativeStreamingBrain`, the streaming Conversation Engine, and segmented streaming TTS are wired in the live demo ([ADR-0057](adr/0057-sentence-end-semantic-race-and-speculative-response.md)). The vendor TTS first-audio delay remains the dominant measured tail. |

### Cell 3 · Cooperative barge-in (T3, I4, R2) — **the headline defect**

|  |  |
|---|---|
| **Expected** | User asserts the floor mid-reply; the assistant stops within ~200ms and the interrupting utterance becomes the next turn. |
| **Actual (before)** | Three separate failures stacked. (a) `run()` is a single sequential loop (`kernel/conversation_kernel.py:161-163`), so during `router.decide()` and TTS streaming **no audio frames are read at all** — the overlap is not even observed until the loop frees up. (b) The intent is only classified when the overlap *ends* (`_resolve_dual_overlap` runs on a quiet chunk), so the earliest possible yield is after the user stops talking, not 200ms in. (c) On YIELD the kernel only sets `_speaking_ms_remaining = 0.0` (`:528-529`); it never advances the generation, so the lease stays current and `streaming_spoken_response_scheduler.py:60-62` keeps streaming. The transcript is `peek`ed, never consumed, and τ9 lands in LISTEN with the VAD tracker still `_speaking = False`, so **no EOT can ever close that utterance** — the user's words are discarded and they must repeat themselves. |
| **τ path** | τ8 then τ9. Both transitions fire correctly; the *actions* attached to them do nothing. |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:119` `test_cooperative_barge_in_sustained_overlap_yields_via_tau9`, and `tests/test_conversation_kernel.py:467` |
| **Test asserts** | `[("τ1",None),("τ3","RESPOND"),("τ8",None),("τ9","YIELD")]` and `end_state is LISTEN`. |
| **Test misses** | That audio actually stopped. That the interrupting utterance was answered. That the superseded reply was *not* spoken. How long the yield took. The smoking gun: `tests/scheduler/test_streaming_spoken_response_scheduler.py:123` simulates barge-in with `on_yield=counter.advance` — the test **manually advances the generation because the kernel never does**, which is precisely the bug, encoded as a fixture. |
| **Fixed now?** | **Core logic yes.** `_yield_floor_to_user` advances Generation, sends `AssistantSpeechCancelledFrame`, and re-arms VAD. `SemanticInterruptionGate` now consumes playback-time ASR partials, so exact stop phrases and current model verdicts can yield before overlap silence; `stop` is control-only while correction/interrupt wait for EOT before becoming a Turn. The full ~200ms p95 is still unmeasured because it includes provider first-text and browser buffer drain. See [Semantic Interruption](SEMANTIC-INTERRUPTION.md). |

### Cell 4 · Backchannel during system speech (T3, I2, R1)

|  |  |
|---|---|
| **Expected** | Short listener-support signals ("嗯", "uh-huh") must **not** be treated as a floor claim. The survey calls misclassifying this the field's single most-cited failure mode. |
| **Actual** | `SemanticInterruptionGate` recognizes exact backchannels on partial ASR and keeps the assistant speaking; ambiguous text uses the same six-label LLM seam with latest-wins revision control. `DualIntentClassifier` remains only the disabled/empty-ASR compatibility fallback. |
| **τ path** | τ8 then τ10. |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:135` `test_backchannel_during_system_speech_continues_via_tau10` |
| **Test asserts** | `[…,("τ8",None),("τ10","CONTINUE")]`, `end_state is SPEAK`. |
| **Test misses** | That the assistant's audio kept flowing uninterrupted across the backchannel. No test feeds realistic backchannel *content* through the real classifier end to end. |
| **Fixed now?** | **No change needed** for the classification itself. The DUAL-escape work does touch this path: a backchannel arriving after the speaking budget is spent now resolves the overlap instead of self-looping (see Cell 8). |

### Cell 5 · Third-party / noise (T3, I7, R5)

|  |  |
|---|---|
| **Expected** | Overlapping audio not from the addressed user (another person, a TV) must be filtered and ignored. |
| **Actual** | The *mechanism* is real and elegantly unified: one `AddresseeClassifier` gates both τ1 and τ11 (ADR-0004), since both answer "is this addressed to the assistant?". But **the only shipped conformer is `DefaultAddresseeClassifier`, which always returns `True`** (`turn_policy/addressee.py:18-20`) — so out of the box, τ11 can never fire and third-party speech is treated as the user. PRD 需求 point 11 ("排除第三方对话") is satisfied at the seam and unsatisfied in behaviour. Related: voiceprint exists as real embedding/matching (ADR-0022) but is deliberately informational and gates nothing (ADR-0005). |
| **τ path** | τ8 then τ11. |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:151` `test_third_party_speech_is_ignored_via_tau11` |
| **Test asserts** | The τ sequence — using `OnsetOnlyAddressedClassifier`, a test double built for the purpose. |
| **Test misses** | That the shipped default cannot reach this cell at all. The test proves the wiring works *given* a classifier; nothing flags that no such classifier ships. |
| **Fixed now?** | **No.** Needs a real `AddresseeClassifier` conformer (speaker-conditioned VAD, or the voiceprint matcher promoted from informational to gating). Tracked as a gap. |

### Cell 6 · Hesitation with long silence (T5, I6, R3)

|  |  |
|---|---|
| **Expected** | Acoustic silence that does *not* mean end-of-turn — "我想要那个…" trailing off. A fixed-threshold VAD fires prematurely where semantic EOT should wait. |
| **Actual** | `hesitation_silence_ms` remains a purely acoustic WAIT transition, but committed endpoint selection is now semantic. SentenceEnd freezes a revision and starts LLM-only completeness plus main-response prefetch; VAD stop or 1000ms ASR-idle supplies a separate stop latch. `INCOMPLETE` holds the same candidate for new activity up to 5000ms, while VAD speech/ASR increment cancels it immediately. |
| **τ path** | τ4 then τ5 (or τ6). |
| **Test** | `tests/bench/test_full_duplex_scenarios.py:169` `test_hesitation_with_long_silence_then_resume_via_tau4_tau6` |
| **Test asserts** | `["τ1","τ4","τ6"]` from `loud 200ms → quiet 350ms → loud 100ms`. |
| **Test misses** | The old acoustic benchmark still cannot prove semantic accuracy by itself. Semantic behavior is instead pinned in `tests/turn_policy/test_semantic_endpoint_gate.py`, `tests/kernel/test_semantic_endpoint_flow.py`, and the opt-in DeepSeek live smoke test. |
| **Fixed now?** | **Yes for endpoint coordination.** `AsrSnapshot` exposes partial revisions/SentenceEnd; `SemanticEndpointGate` requires both semantic and stop latches, cancels on activity, and uses bounded incomplete/uncertain holds. See [Semantic EoT](SEMANTIC-EOT.md). The separate WAIT state remains an acoustic FSM state by design. |

---

## Part 2 · Sustained concurrent speech (T4, I1, R1)

|  |  |
|---|---|
| **Expected** | A DUAL self-loop. The survey omits it from the eleven named transitions because no audited system stably enters it. |
| **Actual** | Modelled: 3000ms of uninterrupted overlap (`_SUSTAINED_OVERLAP_CEILING_MS`) fires `CONCURRENT_SPEECH`. But it was reachable only *because* the speaking budget never decremented in DUAL — the same bug as P0-4. |
| **Test** | `tests/test_conversation_kernel.py` `test_sustained_dual_overlap_without_silence_fires_concurrent_speech_self_loop` |
| **Test misses** | It implicitly depended on the DUAL budget bug. After the fix its 600ms budget would be exhausted first, so the fixture's clock is raised to preserve the test's actual intent (the self-loop). |
| **Fixed now?** | Intent preserved; the dependency on a bug is removed. |

---

## Part 3 — Cases the survey does not model, and the framework did not handle

### Cell 8 · Noisy environment during assistant speech

|  |  |
|---|---|
| **Expected** | Ambient noise above the VAD threshold must not prevent the assistant from finishing its turn or the user from starting a new one. |
| **Actual (before)** | **Session-bricking.** `_speaking_ms_remaining` decremented only on *quiet* chunks in SPEAK (`:461-463`) and never in DUAL. Sustained noise → the budget never drains → `SYSTEM_EOT` never fires → the FSM ping-pongs SPEAK ↔ DUAL forever. Since τ1 only has a rule from IDLE, **the user can never start another turn.** Compounding it, `_TABLE` has no `(DUAL, SYSTEM_EOT)` rule, so even a correct decrement could not exit DUAL. |
| **Test** | None existed. |
| **Fixed now?** | **Yes.** The budget now ticks on every chunk in both SPEAK and DUAL, and an exhausted budget in DUAL resolves the overlap through the existing τ9/τ10/τ11 classification — τ9 → LISTEN (VAD re-armed, so the noise ends in a normal EOT), τ10/τ11 → SPEAK with a spent budget, so the next chunk fires SYSTEM_EOT → IDLE. **Every branch leaves DUAL, and the survey's eleven-transition table is not extended.** New tests: `test_sustained_loud_noise_during_speak_does_not_trap_the_kernel_in_dual` and `test_a_new_user_turn_is_still_answered_after_sustained_noise_during_speak` (the latter asserts the outcome that matters — the escape lands in LISTEN, which already unblocks τ3; IDLE only arrives once the noise stops). |

### Cell 9 · Playback timing is estimated, not observed

|  |  |
|---|---|
| **Expected** | The assistant leaves SPEAK when its audio actually finishes playing. |
| **Actual (before)** | `SpeakingClock.estimate_ms` is `len(text) * ms_per_char` — a linear guess explicitly decoupled from real TTS timing, and `ms_per_char=180.0` in the web demo (`demos/voice_web_server.py:157-158`) is ~3× too long for English. Turn-taking decisions were made on a fiction. |
| **Fixed now?** | **Yes, for reporting clients.** New inbound `PlaybackProgressFrame` lets the client report real playback completion from the audio source's `ended` event; the kernel fires `SYSTEM_EOT` on it (and resolves DUAL if that is where it lands, so a web client escapes DUAL without needing another audio frame). Stale or forged generations are rejected. `SpeakingClock` is retained as a **watchdog ceiling** rather than switched off — otherwise a client that reports once then vanishes (tab backgrounded, socket dropped mid-playback) would hold SPEAK forever, trading one liveness hole for another. Non-reporting clients (ESP32, tests) keep byte-identical behaviour, as ADR-0007 requires. |

### Cell 10 · User goes silent and never speaks again

|  |  |
|---|---|
| **Expected** | Either a proactive prompt, or a graceful timeout. |
| **Actual** | Neither. τ2 (`PROACTIVE_TIMER`) has exactly one producer in the codebase — `_await_delegation:335`, used to speak a delegation result — so **there is no idle or proactive timer at all**. And there is no session- or turn-level timeout anywhere in `server/`: per-vendor socket timeouts exist, but nothing bounds a turn. |
| **Fixed now?** | **No.** Note this contradicts `COMPLETION_STATUS.md`'s "需求 8 timeout handling = Done"; ADR-0006 reasons about *fillers*, not deadlines. Corrected to Partial in this pass. |

### Cell 11 · Delegated backend hangs

|  |  |
|---|---|
| **Expected** | A deadline, then a spoken failure. |
| **Actual** | `await session.result()` (`kernel/conversation_kernel.py:314`) has no deadline. `AcpDriver` does not handle `fs/*` or `terminal/*` peer requests, and its own docstring notes a backend needing those "will hang". So the user hears the single ack (ADR-0006, deliberately no fillers) and then **permanent silence**. `AcpAgentSession.cancel` is also fire-and-forget: it sends `session/cancel` without confirming, killing the subprocess, or tracking the in-flight task. |
| **Fixed now?** | **Partly.** A barge-in during a pending delegation now supersedes it explicitly, closing a related hole where the *next* user turn would answer "Still working on it." against a dead delegation. The missing deadline itself is not fixed. |

### Cell 12 · ASR emits no punctuation

|  |  |
|---|---|
| **Expected** | Semantic completeness scoring should not silently degrade based on a vendor's formatting choices. |
| **Actual** | `PunctuationEotScorer` (`turn_policy/eot_classifier.py:56-71`) treats sentence-final punctuation as COMPLETE — the fast half of the ensemble. If the configured ASR does not emit punctuation, that branch is dead and every utterance falls through to UNCERTAIN, silently halving the ensemble. No test exercises the scorer against real ASR output from either shipped conformer. |
| **Fixed now?** | **No.** Tracked as a gap; needs a conformance test per ASR conformer. |

### Cell 13 · Disconnect mid-playback

|  |  |
|---|---|
| **Expected** | The reply survives the reconnect. |
| **Actual** | `EndpointSession` genuinely handles this: hello/resume, a 60s grace period, and a bounded 256-frame outbound buffer that drops oldest while detached (ADR-0019). This is the best-engineered part of the transport tier. Two caveats: it is entirely in-process (nothing survives a restart or a second replica), and `clients/esp32` / `clients/udp` do not use resume on reconnect (ISSUE-0011). |
| **Fixed now?** | **Improved.** `run()` now drains an in-flight turn before returning, so a turn that was mid-flight when the socket dropped completes and buffers for replay instead of being lost. `InMemoryEndpointSession.send` also gains a lock, because `_flush_buffer` on reattach could previously race a live `send` and reorder buffered frames ahead of live ones — a race that only became reachable now that two coroutines can send concurrently. |

### Cell 14 · Text frame arrives while the assistant is speaking

|  |  |
|---|---|
| **Expected** | Treated as a barge-in. |
| **Actual** | Silently dropped. `_TABLE` has no `(SPEAK, USER_EOT_CONFIRMED)` rule, so `_evaluate_and_record` returns `None` at `:196` and the turn vanishes with no ledger event. Nearly unreachable before; with the turn task plus a nonzero speaking clock, **typing twice quickly in the web demo loses the second message.** |
| **Fixed now?** | **No — deliberately deferred.** The fix routes τ8 → τ9 → τ3, reusing only existing transitions and inheriting the whole barge-in path, but it changes ledger sequences and so ships in its own commit. Tracked in `ISSUES.md`. |

---

## Summary

## Part 4 — Realtime interruption and follow-up matrix

The stateful Realtime runtime treats "the user spoke while output exists" as an
overlap episode first, not automatically as a new turn.  The final ASR revision
then determines the semantic outcome.  This mirrors the OpenAI Realtime split
between stopping/truncating output and committing the next user item.

| User behaviour | Immediate media action | Conversation action | Regression coverage |
|---|---|---|---|
| Exact backchannel: “嗯 / 好的 / 继续” | Keep playing | Discard overlap transcript; no Brain call | `test_backchannel_transcript_is_discarded_before_the_next_user_turn` |
| Playback-only stop: “停 / 别说了” | Stop and clear queued audio | No user item unless the final revision adds a request | `test_final_revision_can_promote_an_early_stop_into_a_user_turn` |
| Correction: “不是北京，是上海” | Stop immediately | Commit the complete final revision as a new turn | `test_semantic_correction_stops_now_but_routes_only_after_eot` |
| Clarification slot fill: “北京的” | Stop the assistant question if still playing | New user item retains prior question/context | `test_slot_fill_during_assistant_playback_yields_and_commits_a_new_turn` |
| Supplement: “还有明天的” | Cancel current response/tool presentation | New generation; late old results remain history-only | `test_user_follow_up_projects_an_inflight_tool_request_before_itself` |
| Stop prefix plus a task: “别说了，查北京天气” | Early stop on the prefix | Final revision promotes it to a normal user turn | `test_final_revision_can_promote_an_early_stop_into_a_user_turn` |
| Speech after generation completed but audio is buffered | Clear browser playback immediately | Interrupt delivery without emitting a second response terminal | `test_barge_in_stops_playback_even_after_response_generation_completed` |
| Client reports its final playhead after cancellation | Playback is already stopped | Refine the interrupted delivery prefix; never reopen it | `test_client_can_report_the_exact_played_prefix_after_cancel_arrives` |
| Follow-up after partial assistant playback | Stop remaining audio | Brain sees only the assistant prefix actually heard | `test_follow_up_context_contains_only_the_interrupted_assistant_prefix_heard` |
| Model mislabels a real question as backchannel | May stop later at EoT | Fail open and preserve the completed user turn | `test_model_backchannel_verdict_cannot_discard_a_non_rule_user_question` |

Two invariants apply to every row:

1. ASR partial revisions update one candidate; only the final admitted revision
   creates a durable user item, so partials do not become duplicate bubbles or
   duplicate LLM requests.
2. Response generation and playback delivery are separate lifecycles. A
   `ResponseCompleted` does not mean the browser has played all audio, and a
   later barge-in truncates model context to the confirmed delivered prefix.

| Case | Before | After this round |
|---|---|---|
| 1 Standard turn | ✅ | ✅ |
| 2 Latched zero-gap | ❌ not implemented | ❌ needs partial-ASR + streaming TTS |
| 3 Cooperative barge-in | ❌ does not interrupt | ✅ early semantic/rule cancellation; ~200ms p95 still unmeasured |
| 4 Backchannel | ✅ mechanism real | ✅ |
| 5 Third-party | ⚠️ seam only, no conformer ships | ⚠️ unchanged |
| 6 Hesitation | ❌ acoustic only, could deadlock | ⚠️ deadlock fixed; still acoustic |
| 7 Concurrent speech | ⚠️ reachable via a bug | ✅ reachable legitimately |
| 8 Noisy environment | ❌ bricks the session | ✅ |
| 9 Playback timing | ❌ fiction | ✅ real for reporting clients |
| 10 User goes silent | ❌ no timeout, no proactive turn | ❌ |
| 11 Backend hangs | ❌ no deadline | ⚠️ supersede hole closed |
| 12 ASR without punctuation | ❌ silent degradation | ❌ |
| 13 Disconnect mid-playback | ✅ resume works | ✅ + turn drain, send lock |
| 14 Text frame during SPEAK | ❌ silently dropped | ❌ deferred to its own commit |

**The meta-finding.** Before this round, cases 1–7 all had tests and all passed;
cases 8–14 had no tests at all. Every passing test asserted a τ-transition list.
Not one asserted that audio stopped, that a specific utterance was answered, or
that any operation completed within a time bound. That is how four P0 defects
survived a 425-test suite — and it is why every fix in this round ships with a
test that fails on the parent commit for a behavioural reason.
