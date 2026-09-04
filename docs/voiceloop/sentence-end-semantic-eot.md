# 语义完整度（Semantic EoT）判断逻辑

日期：2026-08-10
状态：现网实现，本文档为补充说明（代码 `server/processors/semantic_eot.py` 顶部注释引用此文档）

## 1. 背景与目标

声学 VAD（`VADUserStoppedSpeakingFrame`）只知道"用户不再出声"，不知道"用户话说完了没有"。
中文口语大量存在"我想订一张……"这种声学停顿但语义未完成的情况；反过来也存在声学一直不停但语义
早已完整的情况（背景噪声、口头禅拖尾）。`SemanticEoTProcessor` 的职责是在声学 VAD 之上叠加一层
**语义完整度判断**，回答"这段话，现在能不能提交给 Brain"，从而替代或补强"VAD 判停即结束话轮"
的旧策略。

语义打断（[`docs/design/semantic-interruption.md`](semantic-interruption.md)）判断"助手现在要不要
停声"；本文档的语义完整度判断是"用户什么时候说完"的唯一权威，两者职责不重叠（见该文档第 9 节）。

## 2. 核心概念

| 术语 | 含义 |
|---|---|
| `active` | 构造参数。`False` 时完全不调用分类器，VAD 判停即视为话轮结束（等价于旧的 `eot_strategy=vad`）。由 `voice_session` 按会话的 `eot_strategy` 决定。 |
| `candidate`（`_EotCandidate`） | 一次待判定的"当前轮累积文本"快照，带单调 `generation`、来源 `source_kind`（`sentence`/`partial`）。 |
| `generation` | candidate 版本号，每次作废/替换 +1。`_is_current()` 用它判断某次异步推理结果是否仍对应当前 candidate。 |
| `sentence revision` | 每个 ASR `TranscriptionFrame`（SentenceEnd）到达时预先起算的一次语义判断，编号单调递增，独立于 `generation`。 |
| `transcript revision`（`SemanticTranscriptRevisionFrame`） | 对外/下游（语义打断等）广播的文本版本，携带 `partial`/`sentence_end` 边界，与判定逻辑本身无关，仅做转写分发。 |
| `EotDecision.status` | 语义判定的三态结果：`complete`（说完了）/ `incomplete`（没说完，继续等语音）/ `uncertain`（证据不足，短暂等待后重判）。 |
| `stale` | 某次推理结果对应的 candidate/revision 已被更新的语音作废；只记录诊断，绝不能触发收尾。 |

## 3. 两类触发源：SentenceEnd 预计算 与 VAD Stop 消费/重判

这是整个状态机的设计核心，直接影响响应延迟：

- **SentenceEnd 预计算**：每次 ASR 给出 `TranscriptionFrame`（意味着一句话结束）时，
  `_start_sentence_revision` 立刻用"当前轮累积文本"发起一次语义判断（FireRed + 可选 LLM），
  **不等待 VAD 判停**。这样当用户真正停止说话时，语义结果往往已经算完，可以直接消费，省掉推理
  耗时。
- **VAD Stop 消费或重判**：真实 VAD 判停（`source=acoustic`）或 ASR 空闲合成判停
  （`source=asr_idle`）到来时：
  - 若最新一次 sentence revision 覆盖的文本恰好等于当前累积文本，直接**消费**该 revision 的结果；
  - 否则说明 VAD 判停后还有一段 partial 没有被任何 SentenceEnd 覆盖，**重新**对"当前累积文本"发起
    一次判断（`_evaluate_candidate`／`_evaluate_with_llm`）。

只有被 VAD 判停"消费"或"重判"接受的结果，才能调用 `on_turn_confirmed` 真正结束话轮；
SentenceEnd 预计算本身从不直接结束话轮。

## 4. 判定器：FireRed 与 LLM，以及双判交叉校验

- **FireRed**（`_predict`，本地小模型 `/predict`）：返回 `(score, is_end_of_turn, inference_ms)`。
  `score >= threshold` 时 `is_end_of_turn=true`。请求失败/超时/返回体不合法时，`_predict` **降级为
  `(1.0, True, 0.0)`**——即认为已经说完（透传优先，不阻塞对话）。
- **LLM judge**（`semantic_vad.py` 的 `LlmSemanticVAD.judge`，可选）：输出严格三态 JSON
  `{"status": "complete|incomplete|uncertain", "confidence": ..., "wait_ms": ...}`。
- 两者可以同时配置（`llm_judge` 非空时）：**LLM 结果为准，FireRed 并行跑作为独立观察/交叉校验**：
  - LLM 超时或异常 → 直接采用 FireRed 结果（`source="firered_fallback"`）；FireRed 也失败则保持
    话轮敞开（推 `transcript.incomplete`，不结束）。
  - LLM 正常返回 `complete`/`incomplete` 时，等待 FireRed 完成后交叉校验：**两者的"是否完整"结论
    不一致，则把 LLM 结果强制降级为 `uncertain`**，附带一次短等待（`wait_ms` 取 LLM 给出的值，缺省
    用 `min_eot_ms`）。
  - LLM 本身返回 `uncertain` 不受交叉校验影响。

  交叉校验双向生效（LLM 说完但 FireRed 说没完 / LLM 说没完但 FireRed 说完，都会被拉回
  `uncertain`）。这是为修复一次线上事故新增的：某次 `asr_idle` 触发的 VAD 判停时，累积文本仍是
  4 个字的残句"贝壳找房"，FireRed 打分 0.000（incomplete），但 LLM judge 以 0.950 置信度判定
  `complete`，若只信任 LLM，话轮会带着截断的问题提交给 Brain，导致答非所问。修复前的代码只在
  "FireRed 完整但 LLM 不完整"方向做降级，是非对称的漏洞。

- 未配置 `llm_judge` 时，只用 FireRed：`is_end_of_turn=true` → `complete`；否则 → `incomplete`，
  等待时长用 `_linear_wait_ms(score, threshold, min_eot_ms, max_eot_ms)` 兜底计算（score 越接近
  threshold，等待越短；越接近 0，等待越长，在 `[min_eot_ms, max_eot_ms]` 之间线性插值）。

## 5. 状态机：逐场景处理流程

以下按帧类型和触发条件列出实际代码路径。

### 5.1 `active=False`（`eot_strategy=vad`，纯声学策略）

不调用任何分类器。`VADUserStoppedSpeakingFrame` 到达即 `_schedule_candidate` →
`_evaluate_candidate` 直接 `_finish_turn`，等价于旧行为。SentenceEnd 到达也只做转写累积与广播，
不发起 sentence revision。

### 5.2 ASR SentenceEnd 到达（`TranscriptionFrame`，正文）

1. 把新文本并入 `_confirmed_parts`，清空 `_last_interim_text`。
2. 判断是否"仅标点确认"（`punctuation_only_confirmation`）：清洗标点空格后，新累积文本与当前
   candidate 文本相同——说明这次 SentenceEnd 只是给上一个 partial 补了句末标点，语义没有新增内容。
   - 是：**保留**现有 candidate，不作废、不重新发起判断（避免"江苏。"这种只补标点的
     SentenceEnd 白白多打一次模型请求）。
   - 否：作废当前 candidate（`_invalidate_candidate`），因为文本已经变化。
3. 广播一次 `sentence_end` 边界的 transcript revision。
4. `active=True` 且当前没有正在收尾的候选且不是"仅标点确认"：调用 `_start_sentence_revision`，
   对**当前轮累积文本**并行发起一次新的 sentence revision（FireRed + 可选 LLM），**替换**掉上一个
   还没被消费的 sentence revision（旧的记入 `_superseded_sentence_revisions`，仅用于日志，不再
   影响判定）。
5. 若此时 `_vad_stopped` 已经是 `True`（VAD 先停、SentenceEnd 后到），立刻安排消费这个新
   revision（见 5.8），不必等待下一次 VAD 事件。
6. `active=False` 且 VAD 已停、当前无候选：直接 `_schedule_candidate`（等价于声学策略下 SentenceEnd
   触发一次收尾判断）。

### 5.3 声学 VAD 判停（`VADUserStoppedSpeakingFrame`，`source="acoustic"`）

统一入口 `_handle_vad_stop`：

1. 若已经处于 `vad_stopped` 状态（重复停止帧，或此前已经被 `asr_idle` 合成停止占用）：
   - 若当前状态是 `asr_idle` 合成停止，**采纳**为真实声学停止（`_vad_stop_source = "acoustic"`），
     其余状态不变，只补一条诊断日志；
   - 否则视为重复帧，忽略。
2. 首次进入 `vad_stopped=True`，记录 `vad_stop_ts`。按三种情况分流（仅 `active=True` 时区分）：
   - **rearm_consumed_revision**：存在一个"曾经被 `VADUserStartedSpeakingFrame` 打断、但语音又
     很快停止、文本没有变化"的 revision（见 5.5），且它就是当前 candidate 所在的 revision——直接
     复用该 revision 已有的（或仍在进行的）判断结果，不重新发起请求；
   - **最新 sentence revision 覆盖当前文本**（`_latest_revision_covers_current_text()`
     为真）：直接安排**消费**该 revision 的结果（见 5.8）；
   - **否则**（VAD 判停时手上还有一段没被任何 SentenceEnd 覆盖的 partial）：对"当前累积文本"
     重新发起一次判断（`_schedule_candidate` → `_evaluate_candidate`）。
3. `active=False`：只要没有候选正在收尾，直接 `_schedule_candidate`（进入 5.1 的直通路径）。

### 5.4 ASR 空闲合成停顿（`source="asr_idle"`）

声学 VAD 可能因为背景噪声迟迟不判停，导致语义判断被无限拖后。`asr_idle_stop_ms`（默认
1000ms，配置项 `turn_taking.semantic.asr_idle_stop_ms`）提供一个"文本层兜底"：

- 仅在 `active=True`、声学 VAD 仍处于 speaking、当前累积文本非空、且没有候选正在收尾时武装
  （`_arm_asr_idle_timer`），每次语义相关的文本变化（`semantic_changed`）都会重新武装计时器。
- 计时器到期时，若快照文本（清洗后）与武装时刻完全一致（既没有新字，也没有被回撤/改写），才
  触发一次合成 `VADUserStoppedSpeakingFrame` 等价物：`_handle_vad_stop(source="asr_idle")`，
  走 5.3 的判定分支。
- 合成停顿期间若真实声学 VAD 后来也判停，两者去重合并为 `acoustic`（见 5.3 第 1 点）。
- 合成停顿期间若又有**语义变化**的新文本到达（`semantic_changed=True`）：`_resume_after_synthetic_stop`
  撤销这次合成停顿——取消尚未消费的 sentence revision 消费任务、作废当前 candidate、清空
  `_vad_stopped` 等状态、下推 `TurnCancelFrame(reason="asr_increment_after_idle_stop")`，让状态机
  回到"仍在说话"，等待新的静默窗口重新判断（不会立即重新请求模型，见 5.6）。
- 只有非空文本才会武装计时器；标点符号变化（长度未增长的重写、纯标点追加）不算"新语音"，不会
  重新武装或提前触发。

### 5.5 用户又开始说话（`VADUserStartedSpeakingFrame`）

- `eot_pending`：VAD 已经判停但还没有候选进入真正收尾（`_finalizing_candidate is None`）。
  - 若存在一个"最新 sentence revision 编号 ≤ 已消费编号"的历史 revision
    （`_vad_rearm_revision`）：说明这段"又开始说话"只是噪声抖动，文本没有实质变化，标记为可
    **重新武装**（rearm），供下一次真正停止时（见 5.3）直接复用，不重新请求模型；否则彻底作废
    当前 candidate；
  - 取消尚未消费的 revision 消费任务、取消宽限期/超时等待中的 pending task；
  - 下推 `TurnCancelFrame(reason="vad_start_during_eot")`，通知下游（如 filler）本轮暂不会结束；
  - 清空 `vad_stopped`／`stop_source`／`svad_interval_response_ts` 等一次性状态。
- 非 `eot_pending`（比如已经在收尾中）且 `active=False`：也会作废候选（声学策略下"又说话了"
  直接取消上一次判停）。
- 重新武装 `asr_idle` 计时器（若声学 VAD 是从静止到说话，或本次是从 `eot_pending` 恢复）。

### 5.6 Partial 增长 / 改写（`InterimTranscriptionFrame`）

- **`active=True`**：把 `_confirmed_parts + text` 与"上一次已生效的累积文本"比较得到
  `semantic_changed`（内容层面，不只是长度）。变化时：
  - 若最新 sentence revision 对应的候选文本与新文本不一致，标记该 revision 为
    `superseded`（仅供后续判定结果打日志用，不影响正在跑的推理）；
  - 通知语义打断侧丢弃对应的"投机"候选（`_discard_candidate_speculation`）；
  - 尝试撤销合成 `asr_idle` 停顿（见 5.4）；
  - 重新武装 `asr_idle` 计时器。
  - **不会**在这里立即发起新的语义判断请求——请求只在 SentenceEnd（5.2）或 VAD Stop（5.3/5.4）
    时发起，partial 增长本身只负责让旧结果失效和刷新展示文本。
  - 例外：若此刻已经处于"声学 VAD 判停但还没选定候选"的窗口（`_vad_stopped and
    source==acoustic and not _stop_semantic_selected`），说明 VAD 判停后才等到第一段迟到的
    partial，这时才补一次 `_schedule_candidate`（对应测试
    `test_real_vad_stop_with_empty_text_uses_first_late_partial_once`：真实 Stop 先到、
    文本后到，只在第一段非空迟到文本上补判断一次，后续 partial 增长不重试）。
- **`active=False`**：仅当 partial "有效增长"（`sentence` 来源候选下任何非空文本，或
  `partial` 来源候选下严格变长）时作废候选并下推 `TurnCancelFrame(reason="asr_increment_detected")`；
  若此刻 VAD 已停且当前无候选，直接 `_schedule_candidate`。

### 5.7 三态决策后的动作（消费 sentence revision 或直接评估 candidate 之后）

无论结果来自"消费预计算的 sentence revision"（`_consume_sentence_revision`）还是"VAD 停后
直接评估"（`_evaluate_candidate` / `_evaluate_with_llm`），三态的后续动作一致：

| 决策 | 处理 |
|---|---|
| `complete` | 立即 `_finish_turn`（短文本）或先过一次长文本宽限期（见 5.9）。 |
| `incomplete` | 下推 `TurnCancelFrame(reason="semantic_eot_rejected")`，通过 `ws_send` 广播 `transcript.incomplete`，安排一个**强制超时兜底**（见 5.10），话轮保持敞开等待新语音。 |
| `uncertain`（仅 LLM 路径） | 若 `wait_ms > 0`：广播 `transcript.incomplete` 附带 `wait_ms`，`sleep` 该时长后**仅当**这段时间内 VAD 仍处于停止状态、且没有更新的 revision 出现，才补一次 `_finish_turn`；否则视为被新语音取代，什么都不做（消费路径）。评估路径（`_evaluate_with_llm`）里 `uncertain` 直接走同一套"等待后强制推送"的 `_fallback_push`。 |

### 5.8 长文本宽限期（`_handle_eot_true`）

`is_end_of_turn=true`（或三态 `complete`）不代表可以无条件立刻透传：

- 清洗后文本长度 `< long_text_chars`（默认 60）：立即 `_finish_turn`。
- `>= long_text_chars`：进入 `long_text_grace_ms`（默认 200ms）宽限期
  （`_grace_push`）——给可能紧跟着到达的下一句 SentenceEnd 一个机会：宽限期内只要 candidate 被
  作废（新语音、VAD 又开始说话等），`_grace_push` 直接 `return`，不会误收尾；宽限期结束时
  candidate 仍是当前版本才真正 `_finish_turn`。这是因为长句在 FireRed/LLM 眼里更容易被误判为
  "完整"（长句本身信息量大，模型倾向给高分),需要多等一小段时间验证。

### 5.9 `incomplete` 的强制超时兜底（`_schedule_incomplete_timeout` → `_fallback_push`）

语义模型判定"没说完"不能让话轮无限期敞开——用户可能已经放弃继续说，或者模型持续误判。
`incomplete_timeout_ms`（默认 5000ms）到期后，即使模型仍未点头，也强制 `_finish_turn`，把当前
累积文本连同 `FillerArmFrame` 一起推给下游，交由 LLM 兜底应答（"没听清"类回复由 Brain 侧处理，
不是本处理器的职责）。这个兜底任务在新的 SentenceEnd 到达（会重新发起 revision 并作废旧
candidate）或 VAD 又开始说话（5.5）时会被取消。

### 5.10 竞态与失效结果的防御

判定链路里同时存在多个异步任务（FireRed 请求、LLM 请求、sentence revision 推理、宽限期/超时
sleep），必须保证过期结果永远不能影响状态机：

- `generation` 单调递增：`_is_current(candidate)` 要求候选对象**同一个实例**且版本号匹配，任何
  作废操作（新文本、VAD 重新开始说话）都会 `+1`，让旧任务的后续判断在 `_is_current` 处直接短路。
- sentence revision 单调递增，处理器生命周期内不重复；`_superseded_sentence_revisions` /
  `_discarded_speculation_revisions` 只用于日志和对下游"投机执行"的撤销通知，从不参与是否收尾
  的判定。
- `_consume_sentence_revision` 在拿到结果后重新检查 `_vad_stopped` 与
  `revision == _latest_sentence_revision`（非 rearm 情形还要求 `revision >
  _last_consumed_revision`），确认这次消费仍然对应"当前"状态才会真正调用 `_finish_turn`。
- `_finish_turn` 本身在入口处再检查一次 `_is_current(candidate)` 且
  `_finalizing_candidate is None`，防止同一 candidate 被并发路径重复收尾。
- 所有 stale 结果只上报 `metrics_observer`（打点 `stale=True`），不产生任何用户可见效果。

### 5.11 话轮收尾与 ASR finalization 协调（`_finish_turn`）

语义判断"可以收尾"之后，还需要问权威 ASR 服务要一次 `overall final`（`on_turn_confirmed`，对应
`bridges/bella_stt.py` 的 `finalize_turn`，会真正给 ASR 发 `StopTranscription`）。两种模式：

- **阻塞模式**（`wait_for_asr_finalization=True`）：先 `await on_turn_confirmed(...)` 拿到权威
  `overall_final` 结果，再下推最终 `TranscriptionFrame`。转写延迟更高，但下游拿到的文本一定是
  ASR 侧认为的最终版本。
- **后台模式**（默认）：立即用"语义判断时刻的累积文本"下推最终帧、解除 filler/下游阻塞，
  `on_turn_confirmed` 放到后台任务里跑；结果回来后：
  - 与已提交文本相同：只打日志，不改变已发生的对话；
  - 不同（ASR 侧修正了尾部）：通过 `ws_send` 发一条 `transcript.corrected` 事件做**展示层纠错**，
    不撤回已经发给 Brain 的内容；
  - 超时/发送失败：记结构化 `diagnostic.error` 日志，`error_code` 标注 `text_kind` 是
    `partial` 还是 `sentence`，供排障。

无论哪种模式，`_carry_over_late_speech` 都保证：`_finish_turn` 等待期间新到达的 ASR 增量文本
（属于下一段语音）不会被随缓冲区一起清空——按"是否是本轮已提交 transcript 的严格后缀"判断，是
则保留为下一轮的起始文本，否则（ASR 回修了已提交文本导致语义错位）宁可丢弃也不重复/错序带入
下一轮。

## 6. 相关配置（`TurnTakingConfig` / `SemanticConfig`，`server/app_config.py`）

| 配置项 | 默认值 | 作用 |
|---|---|---|
| `turn_taking.strategy` | `semantic` | `vad`（对应 `active=False`）或 `semantic`。 |
| `turn_taking.semantic.backend` | `llm` | `llm` 启用 `LlmSemanticVAD`，与 FireRed 并行交叉校验；`firered` 只用本地模型。 |
| `turn_taking.semantic.threshold` | `0.5` | FireRed `score >= threshold → complete`，同时是兜底等待公式的上界 `y`。 |
| `turn_taking.semantic.timeout_ms` | `300` | FireRed HTTP 超时；超时按"已完成"降级透传。 |
| `turn_taking.semantic.llm_timeout_ms` | `1000` | LLM judge 超时；超时按 FireRed 结果兜底。 |
| `turn_taking.semantic.min_ms` / `max_ms` | `100` / `400` | 纯 FireRed 路径的线性兜底等待区间。 |
| `turn_taking.semantic.incomplete_timeout_ms` | `5000` | `incomplete` 判定后强制收尾的超时上限。 |
| `turn_taking.semantic.asr_idle_stop_ms` | `1000` | 声学 VAD 未判停但正文 ASR 静默多久后补一次合成停顿；`0` 禁用。 |
| `turn_taking.semantic.long_text_chars` | `60` | 触发长文本宽限期的清洗后文本长度阈值。 |
| `turn_taking.semantic.long_text_grace_ms` | `200` | 长文本宽限期时长。 |
| `turn_taking.wait_for_asr_finalization` | `False` | 是否阻塞等待 ASR `overall_final` 才下推最终帧。 |

## 7. 失败降级

- FireRed 服务不可达/返回非法数据：`_predict` 返回 `(1.0, True, 0.0)`，即按"已完整"透传，并通过
  `check_health` / `_report_predict_unavailable` 上报 `semantic_vad_unavailable` 诊断（含
  outage 计次、恢复时的一次性 `diagnostic.recovery` 日志），同时通过 `ws_send` 给客户端发一次
  降级告警（同一次故障期间只发一次，不刷屏）。
- LLM judge 超时/异常：见第 4 节，退回 FireRed 单判；FireRed 也失败时保持话轮敞开而不是硬提交。
- ASR finalization 失败或超时：见 5.11，记 `diagnostic.error`，用当前已有转写兜底，不阻塞对话。

失败降级的统一取向是"宁可提前透传或用旧文本兜底，也不让对话卡死"——语义完整度判断只做加分项，
从不成为对话的单点故障。

## 8. 相关代码与测试

- 实现：`server/processors/semantic_eot.py`、`server/semantic_vad.py`
- 共享文本规则：`server/transcript_text.py`（`normalize_turn_text`，判断"是否仅标点差异"的基准）
- ASR finalization 契约：`server/asr_finalization.py`
- 单元测试：`server/tests/unit/test_semantic_eot_processor.py`（约 130 个用例，覆盖本文列出的
  全部分支，包含 rearm/asr_idle/长文本宽限期/双判交叉校验/迟到语音 carry-over 等）
- 装配位置：`server/voice_session.py`（`SemanticEoTProcessor(...)` 构造处）

## 9. 相关文档

- [语义打断设计](semantic-interruption.md)（"助手是否该停声"，与本处理器职责互补）
- [语义表达完整度评测报告](../research/semantic-completeness-benchmark-20260715.md)
- [Semantic VAD / EoT 技术调研](../research/semantic-vad-eot-survey.md)
