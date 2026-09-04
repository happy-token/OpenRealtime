# Roadmap（中文版）

> 本文件是 [ROADMAP.md](../ROADMAP.md) 的中文翻译，随英文版手动同步更新；如有出入，以英文版为准。

要核对"某项需求是否已完成"，参见 [docs/COMPLETION_STATUS.md](COMPLETION_STATUS.md)；
本路线图所依据的逐项差距清单在 [docs/ISSUES.md](ISSUES.md)。本文件只面向未来规划。

## Phase 1 语音运行时（M0–M6）

**已于 2026-08-21 完成。** 桌面 Chrome 现在唯一的生产语音路径是 Voice Session Runtime、
WebSocket v2 与设备输入/输出运行时。已提交的真实供应商 200 轮门禁通过
（p50 635.7ms，p95 1035.8ms，异常率 0，正确性违规 0）；v1 的入站 `audio_chunk`、
其 worklet、旧运行时包以及旧的 React 会话 hook 均已删除。参见
[实盘报告](reports/2026-08-21-voice-runtime-phase1-live.md) 和
[替换矩阵](../docs/VOICE-RUNTIME-REPLACEMENT-MATRIX.md)。

RTC、Native Realtime Engine 与 Edge 依然明确延后，不阻塞这个里程碑。

## Now（当前）

**2026-08-09 修订**，依据 GPT-Voice 文档集与当前实盘运行时。本地 Voice Web Demo 现在
使用流式 Pipeline Conversation Engine、直连 Silero VAD、Generation 取消、Conversation
Journal，以及可选 PostgreSQL 的应用组合根。RTC 有意延后。

**Fast-tool 基线已于 2026-08-09 完成：** 实盘 Pipeline Engine 现在会产出带版本号的
`CallToolAction`，应用通过服务端权威的 Policy Gateway 与逐轮 Fast Tool Loop 来执行，
在执行前落 intent、在回注模型前落 result，并在 Generation 被取代时取消正在执行的
handler。同一个 Engine 响应会从关联反馈处恢复。低风险的 clock/search 工具在 Voice
Web Demo 里走这条路径；Brain 在那里不再直接执行它们的 handler。

**简单语音产品基线已于 2026-08-09 完成：** WebSocket 握手现在会声明 ASR/TTS 与文本
流式能力。已配置的部署使用供应商直连 ASR 配合直连 Silero VAD；浏览器语音识别只在
服务端 ASR 不可用时作为最后手段的 conformer，而助手文本始终随 Engine delta 到达
以累积方式渲染。空的 ASR 输出会在 Kernel 边界被拒绝，而不是变成一个无效的用户轮次。
一个确定性的浏览器语音流程和一个双说话人、双轮次的实盘流程覆盖了产品路径；
说话人分离仍是后续的多方能力，这个顺序化模拟并不声称做到这一点。

**实时接地基线已于 2026-08-10 完成：** 普通的推测式 ChatBrain 路径现在会为每个
SentenceEnd 候选冻结一个权威时钟，通过可替换接口规划 respond/clock/lookup，并把
有边界、有类型的网络证据作为不可信数据注入。日期偏移使用目标时区的日历语义；
缺失搜索凭据会在网络访问前失败。稳定的 EOT 接受复用同一个
planner/search/主响应生成器，而新的 VAD/ASR 活动会取消它，避免一次修订产生
重复工作。参见 [Realtime Grounding](../docs/REALTIME-GROUNDING.md)。

按顺序：

1. **完成交互式确认与多次调用的工具轮次。** 当前策略会创建并持久化一个绑定确认，
   返回一句安全的口播提示，但不会执行副作用。需要增加经认证的客户端决策帧、
   精确摘要（digest）的批准/拒绝处理，以及响应恢复；然后把当前的单工具 Brain
   适配器推广为有边界的顺序多工具调用，且不削弱每轮预算。
2. **通过持久化的 v2 Supervisor 执行规范化的委派任务动作。** 把 `DelegateTaskAction`
   路由进 Transactional Outbox 和 `AgentSupervisorRuntime`，按 `worker_id` 暴露
   进度/状态/结果，并复用现有的去重/Backend Commit Point 保护，避免一次语义请求
   派生出重复的 Claude/Codex/Hermes 工作。
3. **从 Conversation Journal 投影多轮上下文。** 构建有边界、按供应商定制的投影，
   而不是把供应商会话或浏览器转录本当作历史。工具/Agent 结果要通过引用和明确的
   可见性规则纳入；永远不要把 Journal 记录当命令重放。
4. **补齐已测得的延迟差距。** 增加强制的 EoT-到首字、EoT-到首音频、取消-到停止
   基准；然后实现 TTS 连接复用、HTTP 连接池，以及慢查询确认事件。语义分类器与
   实时 Grounder 已经有边界化的截止时间，流式 LLM → 分句器 → TTS 基础已经实盘，
   优化现在应该由测量驱动。
5. **加固非 RTC 部署。** 在宣称生产就绪之前，补齐认证/租户推导、就绪检查、限流、
   指标导出、PostgreSQL 迁移运维，以及 S3 回收/垃圾回收。容器化打包和首个 CI
   流水线已作为 2026-09-04 开源就绪整改的一部分上线
   （[ISSUE-0024](ISSUES.md#issue-0024-no-ci-and-pytyped-promises-what-nothing-verifies)）；
   剩下的是数据面认证/限流/多实例路由的工作。

**2026-09-03 新增，来自与 Pipecat 和 Qwen-Audio-Agent 的竞品对比调研**
（完整对比见 `openrealtime-improvement-todo.md`，该文件不放在本仓库内——其中的
差异化战略方向章节是另一个独立、尚未并入的产品决策）。按优先级顺序：

6. **补齐断言交互结果的行为级测试，而不只是断言状态迁移。** ISSUE-0021 记录过
   425 个测试全部通过，却漏掉了一个 P0 级打断（barge-in）回归，因为测试断言的是
   Turn Policy FSM 的迁移路径，而不是真实的交互结果。需要参照 Pipecat 的
   `pipecat.evals` 补一层端到端评测（真实/模拟音频输入，断言打断和最终输出是否
   真的发生）。此项被
   [ISSUE-0025](ISSUES.md#issue-0025-the-live-demos-barge-in-path-cannot-be-exercised-without-real-speech-audio)
   阻塞（合成音频无法触发 Silero VAD）——要先解决测试音频的真实性问题，否则
   打断路径永远测不出来。
7. **把工具接入生产组合根，而不只是 demo。** `server/application/runtime.py`
   目前对 `Brain`/`ToolRegistry` 零引用；唯一真正构造它们的地方是
   `demos/voice_web_server.py::_build_brain`，靠 `VOICEAGENT_DEMO_TOOLS` 门控，
   工具列表是硬编码的 Python list。这是同一个"建了但没接线"失败模式的第三次
   出现，前两次是
   [ADR-0030](../docs/adr/0030-chat-brain-datetime-grounding.md) 和
   [ADR-0035](../docs/adr/0035-silero-vad-and-live-demo-eot-interruption-wiring.md)，
   而
   [ADR-0032](../docs/adr/0032-wire-web-search-tool-calling-into-live-demo.md)
   曾经修过一次，但只修在了 demo 层。完整证据见
   [ISSUE-0027](ISSUES.md#issue-0027-toolsbrain-have-never-been-wired-into-the-production-composition-root)。
   需要一个 demo 和生产共用的、稳定的、配置/清单驱动的 `build_tool_registry()`，
   外加一条集成测试断言"配置好的工具在真实会话里确实能被 LLM 调用"——不能再是
   一次性的 demo 层修复。
8. **写一篇前后端边界的 ADR。** Brain/ToolCallingBrain 的职责划分（实时层保持
   轻量；多步编排应该被委派，而不是内联在实时层）目前还不是一份文档化、强制
   执行的契约——可参照 Qwen-Audio-Agent 的 `spawn_thinking` 边界。需要新增一篇
   ADR，明确 Brain 允许做什么、不允许做什么，并评估是否需要一个显式的异步任务
   派发原语，把耗时工作挪出主 Turn Policy 循环。
9. **用真正的 MCP client 替换现有适配器。**
   [ISSUE-0014](ISSUES.md#issue-0014-mcp-and-rag-are-named-seams-without-implementations)
   已经把这个记录为"有名字但没实现"的 seam；`mcp_source.py` 目前只是个 schema
   适配器，没有真正的 stdio/SSE/HTTP transport 或握手。要把它的验收标准和上面
   第 7 项绑定："零代码加工具"必须验证到端到端（配置里加一条 MCP server →
   该工具在真实会话里确实能被 LLM 调用），不能只验证到"client 能连上 server"。
10. **引入二进制/编解码的传输层抽象。** 音频目前是 base64 塞进 JSON（约 33% 带宽
    损耗），没有二进制帧或编解码协商能力，记录在
    [ISSUE-0019](ISSUES.md#issue-0019-transport-is-not-deployable-over-a-real-network)。
    需要设计一个类似 `FrameSerializer` 的抽象（Pipecat 的电信协议
    serializer 在编解码细节上是有用的参照），再决定电话运营商相关的传输是否
    在范围内。
11. **补齐单次调用级的工具取消与中间态结果更新。** 目前取消是 response 级联的
    （`realtime/tool_controller.py` 的 `ToolCancellation`），`ToolResultChannel`
    对每个 `call_id` 只能单次投递——没有办法只取消一个仍在跑的后台工具而不
    影响整个 response，也没有办法让一个长耗时工具在给出最终结果前先汇报进度。
    需要评估单次调用级取消和支持多次提交的结果通道；应在第 8 项的边界 ADR
    落地之后再做，以先把异步契约定下来。同时应重新审视
    [ADR-0061](../docs/adr/0061-two-speed-voice-tool-runtime.md)，它低估了
    `LatencyClass` 本来就是每个工具自己声明的字段这一事实。

## Later（稍后）

以下条目之间没有承诺的顺序——每一项都被 [docs/ISSUES.md](ISSUES.md) 里写明的
前提条件阻塞，而不是已排期：

- **RTC / MQTT / 直连 LiveKit 传输 conformer**
  （[ISSUE-0001](ISSUES.md#issue-0001-rtcmqttdirect-livekit-transport-remain-contract-only)）
  ——满足 PRD 第 1 点的剩余部分。需要先对每种协议分别做 SDK/供应商决策。
- **一个真正的 `VisionSource` conformer**
  （[ISSUE-0002](ISSUES.md#issue-0002-no-real-visionsource-conformer)）
  ——完成 PRD 第 6 点的多模态集成。
- **针对 GPT-live 和 Grok voice 的真正 `Driver`**——`AcpDriver`
  （[ADR-0017](../docs/adr/0017-acp-driver-real-agent-backend-conformer.md)）
  已经为任意 ACP-stdio 后端补齐了 PRD 第 3 点里 Qwen-audio-agent 风格的那一部分；
  GPT-live 和 Grok voice 都不说 ACP，如果再次被点名，各自都需要针对自己真实
  API 的专属 `Driver`
  （[ISSUE-0003](ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)）。
- **实盘的 GitHub issue 跟踪**
  （[ISSUE-0007](ISSUES.md#issue-0007-no-live-github-issue-tracker-yet)）
  ——已完成：私有远程仓库托管在 `happy-token/OpenRealtime`。
- **规范化委派上线后的多 Agent 后端广度。** 保持一份 `AgentDriver` 契约，
  按每个后端的真实协议为 Claude、Codex、Hermes 增加已验证的配置/适配器。
  Agent 选择保持显式；一个不可用的具名后端必须显式失败，绝不能悄悄回退
  或派生另一个后端。非 ACP 供应商仍需要各自专属的 conformer，见
  [ISSUE-0003](ISSUES.md#issue-0003-no-real-driver-for-a-named-external-agent-backend)。
- **ESP32/UDP 设备端弱网重连恢复**
  （[ISSUE-0011](ISSUES.md#issue-0011-esp32udp-device-clients-dont-use-session-resume-on-reconnect)）
  ——把 ADR-0019 的 resume 机制和 web 客户端的退避模式移植进
  `clients/esp32`/`clients/udp`。已延后：按 ADR-0025，这些保持参考/demo 级别，
  直到真的有意愿推进为止。
- **插件落地（Increment 3 候选形态）。** 挑一个当前只是占位 Protocol 的插件——
  例如 `VisionSource`
  （[ISSUE-0002](ISSUES.md#issue-0002-no-real-visionsource-conformer)）
  或 `AddresseeClassifier`/唤醒词——在未来独立的一轮 plan-mode 里做出真正的
  conformer。目前尚未纳入具体计划。
- **传输层加固**
  （[ISSUE-0019](ISSUES.md#issue-0019-transport-is-not-deployable-over-a-real-network)）
  ——和 ISSUE-0001"存在哪些协议"是两件事。音频目前是塞进 JSON 的 base64 PCM，
  没有编解码、没有序列号、没有抗抖动缓冲、没有心跳、也没有协议版本字段。
  无法在蜂窝网络上部署。
- **经认证的身份推导与分布式会话映射**
  （[ISSUE-0016](ISSUES.md#issue-0016-no-identity-or-tenancy-model-across-the-three-session-abstractions)）
  ——规范化的 `InteractionContext` 和持久化租户键现在已经存在，但实盘 demo
  仍然从受信任的环境变量默认值推导租户/用户/设备，而不是来自一个经认证的连接。
  这是数据面认证的前提
  （[ISSUE-0020](ISSUES.md#issue-0020-the-data-plane-has-no-authentication)），
  也是数据/运维层一切工作的前提。
- **一个真正的 `AddresseeClassifier` conformer**
  （[ISSUE-0023](ISSUES.md#issue-0023-no-addresseeclassifier-conformer-ships-so-third-party-filtering-is-unreachable)）
  ——这个 seam 设计得很优雅，但唯一随附的 conformer 永远返回 `True`，导致 τ11
  永远不会触发，PRD 第 11 条要求（排除第三方对话）在结构上满足了，行为上
  却没有满足。
- **一份录制语音的 fixture 语料库**
  （[ISSUE-0025](ISSUES.md#issue-0025-the-live-demos-barge-in-path-cannot-be-exercised-without-real-speech-audio)）
  ——`SileroVad` 正确地拒绝了合成音调，导致已上线接线的打断路径完全无法被
  脚本化客户端触发。这也是 ISSUE-0013 存活这么久的一个诱因。
- **真正的 MCP 与真正的 RAG**
  （[ISSUE-0014](ISSUES.md#issue-0014-mcp-and-rag-are-named-seams-without-implementations)）
  ——两者目前都只是以能力命名、却没有实现的 seam。**前提：** 先选定一个 MCP
  client 库和一个向量存储。
- **一个轮次级超时**
  （[ISSUE-0015](ISSUES.md#issue-0015-no-session-or-turn-level-timeout-anywhere)）
  ——目前没有任何东西给一个轮次设边界；一次挂起的委派会让用户收到一个 ack
  之后就永久沉默。需要单独的 ADR，因为一个挂钟计时器和 ADR-0007 的
  帧驱动确定性规则之间存在张力。
- **分布式实盘会话路由与运维能力补齐**
  （[ISSUE-0018](ISSUES.md#issue-0018-the-data-and-operations-tier-does-not-exist)）。
  权威的语义/工作状态现在已经有 PostgreSQL conformer，但活跃的媒体/对话会话
  仍然是进程本地的；多副本路由、录制策略、仪表盘和运维层对账仍未解决。
- **CI，以及一个真正为 `py.typed` 背书的类型检查器**
  （[ISSUE-0024](ISSUES.md#issue-0024-no-ci-and-pytyped-promises-what-nothing-verifies)），
  外加一个有强制 SLO 的延迟基准，让打断边界和上面的延迟工作不会悄悄回归。

## 明确不在本路线图上

- `EotClassifier`/`DualIntentClassifier` 对齐 voiceloop 的双模型/规则优先/
  置信度阈值设计——用户审阅过这个分歧，选择维持当前实现不变
  （[ISSUE-0005](ISSUES.md#issue-0005-eotinterruption-design-intentionally-diverges-from-voiceloop)）。
  这是一个已关闭的决定，不是延后的决定。
- 一个填充词/延迟隐藏子系统（voiceloop 那套约 5,400 行的"垫词"系统），以及
  voiceloop 里"谁拥有 agent/工具逻辑"的划分（把一切都推给外部客户 Brain，
  不做原生工具调用）——两者都是刻意的、已经决定的分歧，不是待补的差距
  （[ISSUE-0012](ISSUES.md#issue-0012-broader-comparison-against-voiceloop-2026-08-05--production-infra-fillers-tool-calling-philosophy-vad)）。
