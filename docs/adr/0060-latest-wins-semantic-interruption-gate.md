# ADR-0060: latest-wins Semantic Interruption Gate

日期：2026-08-10
状态：Accepted

## Context

OpenRealtime 已有 DUAL 状态与 `DualIntentClassifier`，但只在重叠语音结束后读取一次 ASR 文本。异步 ASR
monitor 在 `SPEAK/DUAL` 跳过 provider revision，导致 partial 无法提前停播，也无法区分纯 stop 与会创建
新 Turn 的 correction/interrupt。

VoiceLoop 的现网语义打断实现证明了六标签、规则优先、revision 调度、latest-wins 和 generation 防护的
必要性；其 Pipecat FrameProcessor 不能直接成为本项目依赖。

## Decision

1. 新增 provider-neutral `SemanticInterruptionClassifier` 和深模块 `SemanticInterruptionGate`。
2. Gate 只负责播放期停播意图和 EOT 后 Turn 准入；`SemanticEndpointGate` 继续独占 EOT。
3. 播放期同步 snapshot 与异步 ASR update 都进入 Gate。
4. 本地精确规则优先；模型按 5 字、100ms idle 或 SentenceEnd 调度。
5. 同一 Gate 只保留一个当前模型任务，新 revision latest-wins；应用结果时再校验 candidate 和播放 generation。
6. 停播仍使用现有 `τ9`、Generation Lease 和 `AssistantSpeechCancelledFrame`。
7. `stop/backchannel/ignore/uncertain` 在 EOT 后通过辅助 `semantic_suppress` 转换关闭 LISTEN，不调用 Brain/Agent；
   `correction/interrupt` 走原 EOT 提交流程。
8. 模型通过统一 `LlmClient` 接入，Demo 使用现有 DeepSeek 配置；不引入 Pipecat 或新厂商 SDK。
9. `OpenAiCompatibleLlmClient.complete()` 复用其 cancellation-aware SSE 实现，使 supersede/timeout 会关闭底层 HTTP response。

## Consequences

- “别说了”可在 ASR partial 到达时停播，不再等待 300ms VAD silence 后才判断。
- 停播与创建 Agent Turn 被明确分离。
- 旧 revision 和旧 generation 无法取消新播放，避免重复或陈旧任务副作用。
- 增加一次可选小模型调用；规则快路径、字符/idle 防抖和 800ms 硬超时约束其成本与尾延迟。
- 当前助手播放上下文是完整回复文本，不是精确播放游标；未来可由 `PlaybackProjection` 增强而不改变契约。

## Rejected alternatives

- 扩大 `DualIntentClassifier` 的二分类返回值：会把实时 revision 调度、EOT 准入和旧的静音后兼容接口混在一起。
- 把逻辑放进 ASR adapter：会让厂商协议层拥有对话状态和 generation 副作用。
- 把语义打断合入 Semantic EOT Prompt：两个判断的时点、降级方向和动作不同，合并会破坏职责边界。
- 引入 VoiceLoop 的 Pipecat processor：与本项目已移除 Pipecat、使用自有 Frame/Kernel 的架构决策冲突。

## Verification

见 [`../SEMANTIC-INTERRUPTION.md`](../SEMANTIC-INTERRUPTION.md) 第 11 节和对应测试文件。
