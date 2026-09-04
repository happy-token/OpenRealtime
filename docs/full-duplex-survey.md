# Full-Duplex Spoken Dialogue Systems Survey — Reference Doc

Internal reference extraction of the academic survey that this project's Turn Policy Seam (dialogue-state management) is modeled on. This is factual extraction for citation purposes, not commentary on the paper.

## 1. Citation and Summary

**Title:** "A Survey of Full-Duplex Spoken Dialogue Systems: Architectural Hierarchy, Interaction Ontology, and Decision State Machine"
(The paper's companion GitHub repo currently self-describes under the working title "Speaking While Listening: A Survey and Empirical Audit of Full-Duplex Spoken Dialogue Systems" — same paper, same arXiv ID; the PDF's own title page is used here as the canonical title.)

**Authors:** Jingyu Lu, Yuhan Wang, Jianming Luo, Yifu Chen, Tianle Liang, Shengpeng Ji, Ziyue Jiang, Xiaoda Yang, Yu Zhang, Xize Cheng, Chenyuhao Wen, Changhao Pan, Haoxiao Wang, Chen Ye, Jian Wu, Xiaoxi Jiang, Guanjun Jiang, Zhou Zhao.

**Affiliations:** Zhejiang University; Qwen Business Unit, Alibaba; HunYuan Team, Tencent; ByteDance.

**arXiv:** 2606.19453v1 [eess.AS] — https://arxiv.org/abs/2606.19453

**Official repo:** https://github.com/DuplexLM/DuplexSurvey (linked directly under the paper's own title block; contains a demo site, timeline/architecture/ontology/state-machine figures, and appendix tables of public full-duplex models, datasets, and benchmarks).

**Summary:** The survey argues that "full-duplex" has become an overloaded label applied to systems with substantially different behavior, and that most of the ambiguity is taxonomical rather than empirical. It introduces three complementary, orthogonal frameworks — an **L0–L3 Architectural Hierarchy** locating *where* in the model stack the duplex decision is made; a **T×I×R Interaction Ontology** specifying *which* interaction (temporal relation, user intent, required system response) a full-duplex moment represents; and a five-state **Decision State Machine** (IDLE/LISTEN/SPEAK/WAIT/DUAL) describing *what the system is doing* moment-to-moment — then uses all three to run cross-system, training-data, and evaluation audits of published full-duplex systems (Moshi, MinMo, Freeze-Omni, OmniFlatten, SyncLLM, FireRedChat, and others). Its central empirical finding is a **realization gap**: architecture determines which interaction cells a system can *in principle* reach, but training-data coverage (a documented "data bottleneck," especially for sustained concurrent speech and third-party speech) determines which cells it actually realizes in practice — and L0 (external module pipelines) remains competitive against more deeply integrated architectures rather than being an obsolete stage.

## 2. L0–L3 Architectural Hierarchy (§4)

The hierarchy answers one question: *where in the stack does the system decide to LISTEN / SPEAK / WAIT / handle DUAL overlap?* It is explicitly **not a progress ladder** — the paper's own audit finding is that "L0 remains competitive," "L1 has become an industrial attractor," "L2 is the largest and most Dual-capable family but remains internally heterogeneous," and "L3 is still open."

**L0 — Module-level.** The duplex decision is made by one or more lightweight external modules (VAD, end-of-turn/EoT classifier, dialogue manager) that run continuously alongside an LLM-based or template-based generator; the LLM itself has no duplex awareness. This is the direct descendant of the pre-LLM industrial pipeline (Google Duplex, Ant Group 2021, Alibaba DAMO 2022). Paper's examples: **FireRedChat** (serial pVAD → EoT classifier → dialogue manager), **FlexDuo** (adds an explicit inter-turn IDLE buffer state), **X-Talk** (a position paper arguing L0 is competitive on latency/interpretability/engineering cost, not merely transitional), **SoulX-Duplug** (plug-and-play streaming state-prediction module attached to a frozen LLM), and 2026 turn-detector modules **Easy Turn** and **FastTurn**. The paper notes a structural "L0 ceiling": even a ~100ms decision module plus downstream LLM forward pass and first-chunk TTS decoding pushes response latency to roughly 500ms — the physical motivation for the L1 step.

**L1 — Hidden-state-level.** An external predictor (sidecar) reads the LLM's hidden state at each step to make the duplex decision, reusing the language model's semantic competence without an LLM-external module pipeline. Paper's examples: **MinMo** (a single-layer Transformer "Full-Duplex Predictor" reading the LLM hidden state, discriminating "respond now" vs. "keep waiting" when silent, and barge-in vs. backchannel when speaking) and **Freeze-Omni** (three-stage protocol around a frozen LLM). The paper highlights L1 as a *structural attractor* independently converged on by different product goals: **MinMo** and **Qwen2.5-Omni's Thinker–Talker** (and its successor Qwen3.5-Omni) arrived at architecturally identical designs — a text LLM ("Thinker") whose hidden state feeds a downstream module ("Talker"/predictor) — despite the latter not claiming full-duplex behavior at all (it targets concurrent text+speech generation, not overlapping user/assistant audio). **Step-Audio R1.1**'s dual-brain articulation-reasoning split shares the same L1 shape without claiming full-duplex behavior either.

**L2 — Token-level.** The duplex decision is encoded directly in the token-level generative process itself — there is no separate decision module; turn-taking is "wired into" how tokens are produced. This is the largest, most heterogeneous, and most DUAL-capable family. Paper's examples: **Moshi** (parallel-stream RQ-Transformer over the Mimi codec with an "Inner Monologue" text track — the always-on user-audio-prediction stream naturally absorbs turn-taking), **LSLM** (the first published LLM-era dual-channel duplex system), **OmniFlatten** (flattens four streams into one sequence with a `silent_speech_token`), **SyncLLM** (fixed-size chunk alternation with `[S0]`/`[S1]` synchronization markers — the paper's canonical example of an L2-shaped but only *apparent*, not *substantive*, full-duplex system, since it cannot causally respond within a chunk), **Mini-Omni2** (keyword-triggered command-mode interruption), **Fun-Audio-Chat** and **Covo-Audio** (industrial parallel-stream / token-exposed variants), **DuplexMamba** (L2 pattern on a Mamba/state-space backbone, showing the pattern is backbone-agnostic), and **SALMONN-omni** (codec-free — duplex decision is still token-level even though the tokens are continuous-valued embeddings rather than discrete codec output). GLM-4-Voice shares the L2 architectural shape but does not claim full-duplex behavior.

**L3 — Representation-level.** A hypothetical layer where user and assistant streams share one continuous latent representation rather than negotiating turn-taking through discrete tokens — dissolving the token-level boundary between perception and generation so that DUAL becomes *native* to the representation rather than a separately-computed mechanism. **No published system realizes L3**; the paper lists three obstacles (the discrete-tokenizer ecosystem is now a deep substrate that's costly to displace; continuous-latent/flow-matching generative models aren't yet real-time at current L2 latencies; no agreed formulation of what an L3 dialogue latent should encode exists) and, in its Frontiers section (§9), proposes three candidate L3 architectural hypotheses as live options rather than realized designs: (i) continuous-latent autoregressive streaming (MAR-style, removing the K-tokens-per-frame bottleneck), (ii) JEPA-style dual-stream prediction (assistant latent predicted from joint user+assistant context, natively integrating overlap), and (iii) world-model-conditioned dialogue (a latent encoding "who holds the floor" as controllable world state, with IDLE/LISTEN/SPEAK/WAIT/DUAL corresponding to latent regions rather than external state variables).

## 3. T×I×R Interaction Ontology (§5)

Where L0–L3 asks *where* the duplex decision is made, the ontology asks *which interaction* it must handle. Every full-duplex moment is characterized as a triple **(T, I, R)** over three deliberately orthogonal axes:

| Axis | Values |
|---|---|
| **T — Temporal relation** | T1 Sequential · T2 Latched · T3 Overlap · T4 Concurrent · T5 Silence |
| **I — User intent** | I1 Information · I2 Backchannel · I3 Repair · I4 Floor-claim · I5 Floor-yield · I6 Disfluency · I7 Third-party |
| **R — System response** | R1 Continue · R2 Stop · R3 Wait · R4 Backchannel · R5 Ignore · R6 Initiate |

The Cartesian product yields 210 nominal cells, most physically impossible or pragmatically redundant. The paper singles out **six acid-test cells** — a compact stress suite exercising every axis and exposing the field's main recurring failure modes:

1. **Standard Turn** (T1, I1, R6) — clean sequential handoff at a transition-relevance place; the cascaded-SDS baseline.
2. **Latched Zero-Gap** (T2, I1, R6) — near-zero-gap handoff; the assistant must begin generating before the user finishes (requires semantic VAD + speculative TTS).
3. **Cooperative Barge-In** (T3, I4, R2) — the user asserts the floor while the assistant is still talking; the assistant must stop within ~200ms.
4. **Backchannel During System Speech** (T3, I2, R1) — short listener-support signals ("uh-huh", "mm") that must NOT be treated as a floor claim; the single most-cited failure mode is misclassifying this as barge-in.
5. **Third-Party/Noise** (T3, I7, R5) — overlapping audio not from the addressed user (another person, TV, environmental speech) that must be filtered and ignored, typically via personal/speaker-conditioned VAD or an LLM-level relevance gate.
6. **Hesitation with Long Silence** (T5, I6, R3) — acoustic silence that does not mean end-of-turn (e.g. "I want to..." trailing off); a fixed-threshold VAD fires prematurely where semantic end-of-turn prediction should instead wait.

## 4. The Decision State Machine (§6)

The FSM names *what the system is doing right now* at every instant, closing the loop after L0–L3 (*where* the decision lives) and the ontology (*what interaction* it must handle).

### 4.1 The Five States

| State | Definition |
|---|---|
| **IDLE** | Neither user nor system is producing speech; no active stream. |
| **LISTEN** | Only the user is speaking; the system is silently encoding. |
| **SPEAK** | Only the system is speaking; user audio is silent or below a noise floor. |
| **WAIT** | The system has paused inside its own turn (after a hesitation or an unfinished user utterance) and is monitoring before resuming — not equivalent to IDLE. |
| **DUAL** | Both speakers are producing audio with active mutual integration (a sustained backchannel during system speech, a third-party voice being filtered out, or true concurrent speech) — not merely simultaneous audio. |

### 4.2 The Eleven Transitions

Each transition is written `s --(Ti,Ij)/Rk--> s'`: in state `s`, given input of temporal class `Ti` and intent class `Ij`, the system takes response `Rk` and moves to `s'`. A transition with no `R` component is *perceptual* (state updates from input without producing an output action). This is the paper's Table 4, reproduced exactly since τ1 and τ11 are already cited by number elsewhere in this codebase:

| # | From → To | Trigger (T, I) | Action (R) | Notes |
|---|---|---|---|---|
| **τ1** | IDLE → LISTEN | (T1, I1) user onset | — | Front-end VAD or speaker-conditioned VAD detects user speech. |
| **τ2** | IDLE → SPEAK | (T1, I5) proactive timer | R6 respond | System initiates a turn after a silence threshold. |
| **τ3** | LISTEN → SPEAK | (T1, I1) EoT confirmed | R6 respond | End-of-turn predictor fires; standard handoff. |
| **τ4** | LISTEN → WAIT | (T5, I6) user hesitation | R3 wait | Semantic EoT says the user has not finished. |
| **τ5** | WAIT → SPEAK | (T1, I1) EoT re-confirmed | R6 respond | User completes their utterance. |
| **τ6** | WAIT → LISTEN | (T3, I1) user resumes | — | User keeps talking after the pause. |
| **τ7** | SPEAK → IDLE | (T1, I1) system EoT | — | System finishes its turn cleanly. |
| **τ8** | SPEAK → DUAL | (T3, I*) overlap detected | — | User audio onset while system is speaking; intent `I` is disambiguated once in DUAL. |
| **τ9** | DUAL → LISTEN | (T3, I4) floor-claim | R2 yield | System stops speaking and listens. |
| **τ10** | DUAL → SPEAK | (T3, I2) backchannel | R1 continue | System keeps speaking; brief listener-acknowledgment absorbed. |
| **τ11** | DUAL → SPEAK | (T3, I7) third-party / noise | R5 ignore | System keeps speaking; filters out non-addressee audio. |

Three transition families: **onset** (τ1, τ2 — bring the system out of IDLE), **turn-handoff** (τ3–τ7 — move between single-speaker states), and **overlap** (τ8–τ11 — the duplex-specific transitions distinguishing a true full-duplex system from a half-duplex one; a half-duplex system implements τ8 as an unconditional fast handoff to LISTEN and cannot distinguish τ9 from τ10 or τ11).

Note: sustained **T4 concurrent speech** is modeled as a DUAL self-loop (`DUAL --(T4,I1)/R1--> DUAL`) rather than a twelfth named transition — the paper explicitly omits it from the eleven-transition count because no audited system in the paper's cross-system audit stably enters it.

**Cell-to-transition mapping** (from §6.4): Standard turn = τ3; Latched = τ3 at near-zero latency; Cooperative barge-in = τ8 followed by τ9; Backchannel = τ8 followed by τ10; Third-party = τ8 followed by τ11; Hesitation = τ4 followed by τ5 (or τ6); Concurrent = τ8 followed by a sustained DUAL self-loop.

## 5. Where This Project Departs From or Extends the Survey

This project's Turn Policy Seam adopts the survey's Dialogue State FSM and L0–L3 hierarchy directly (see [CONTEXT.md](../CONTEXT.md)), with one explicit positioning choice and two plugin extensions:

- **Turn Policy is L0 by construction.** Per [CONTEXT.md — L0/L1/L2/L3](../CONTEXT.md), this project is a pluggable-module framework (VAD / EoT / turn-classifier feeding a text LLM Brain), not an end-to-end trained duplex model — so it sits at L0, not L1/L2/L3, and the project accepts the survey's own "L0 ceiling" finding (§4.3: L0's structural latency floor is the physical motivation for L1) rather than treating L0 as a stage to be escaped. This is consistent with the survey's own audit conclusion that "L0 remains competitive" (§4.1) — the project does not read L0 as legacy.
- **Dialogue State** ([CONTEXT.md](../CONTEXT.md)) is this project's own name for the survey's five-state FSM (§6 above), unchanged in structure.
- **Backchannel** ([CONTEXT.md](../CONTEXT.md)) = ontology cell (T3, I2, R1), realized as τ8 followed by τ10 (§4 above) — the assistant must not stop.
- **Barge-in** ([CONTEXT.md](../CONTEXT.md)) = ontology cell (T3, I4, R2), realized as τ8 followed by τ9 — the assistant must yield within ~200ms.
- **Third-party speech** ([CONTEXT.md](../CONTEXT.md)) = ontology cell (T3, I7, R5), realized as τ8 followed by τ11 — same DUAL→SPEAK destination as backchannel, but reached via a different intent classification.
- **τ1 and τ11 were extended with bolt-on classifier plugins**, since the survey's FSM specifies *what* transitions exist but is explicit (§6.6, "What the State Machine Is Not") that it is silent on *how* any given system computes them. [ADR-0004](adr/0004-unified-addressee-classifier.md) unifies τ1 (IDLE→LISTEN onset) and τ11 (DUAL→SPEAK, third-party ignore) behind one `AddresseeClassifier` plugin interface, since both are instances of the same underlying question ("is this speech addressed to the assistant?"). [ADR-0005](adr/0005-voiceprint-informational-wakeword-gating.md) further gates τ1 with an optional Wake Word plugin (hard gate: no wake event keeps the system in IDLE) while treating Voiceprint as informational metadata attached to Turn Content rather than a gate on any transition — an asymmetry the ADR records explicitly because both plugins are nominally "optional identity-adjacent" but behave differently with respect to the FSM.
