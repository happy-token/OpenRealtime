# Voice Runtime 与 GPT Voice 行为对齐计划

本文记录 OpenRealtime 第一阶段 Voice Runtime 的技术边界、已确认决定、交付清单、延期项和验收计划。它以本机 GPT Voice 可验证证据与公开 Realtime 行为为参考，不推断或复刻未公开的云端内部实现。

**状态：Phase 1 scope frozen（2026-08-20）。** 冻结后的架构变更必须明确指出新增依据、影响的 M0–M6 批次和被替换的已确认决定，不能通过实现细节静默扩大范围。

**范围修订（2026-08-21）：** Phase 1 浏览器发布门禁收敛为 Desktop Chrome，Edge 不再是验收或删除前置条件。本修订影响 M5 浏览器 E2E/统计覆盖和 M6 replacement gate，替代本文此前要求 Chrome/Edge 双浏览器通过的决定；Edge 支持可以后续独立验证，但不得阻塞 Phase 1。真实 Cascaded Profile 的 200 attempted full turns、正确性与 SLO 门槛保持不变。

## 产品目标

第一阶段优先完成可支撑 Personal Voice Assistant 的传输无关 Voice Session Runtime。后续身份、长期记忆、Agent 编排和数字人展示都复用该 Runtime，而不是各自建立语音链路。RTC 接口与公网 RTC 基础设施排在这些产品能力之后。

Phase 1 固定交付 Cascaded Realtime Engine、Desktop Chrome、WebSocket v2、Device Audio Input/Output Runtime、Voice Session lifecycle/recovery、Context Policy/compression、控制面协调、单 Voice Runtime 实例、质量门禁和 Legacy 删除。Native Realtime 接入、RTC、Edge、移动端、ESP32 实现、Persona/长期 Memory/Avatar/多 Agent 产品能力以及多实例 live-session 热迁移不属于本阶段；后续只能消费本阶段稳定边界，不能反向阻塞或扩展 Phase 1。

## 系统边界

Voice Session Runtime 负责一场实时语音会话从打开、运行、恢复到关闭的一致性，范围包括：

- Voice Session 生命周期、Endpoint Session 与 Transport Bridge；
- Phase 1 Cascaded Realtime Engine 与未来 Engine 的稳定公共边界；
- Turn、打断、播放事实和取消传播；
- Journal 投影、上下文恢复、Tool/Confirmation/Delegation 控制请求协调；
- 故障恢复、遥测和资源清理。

Persona 与长期 Memory 的持久化模型、外部 Agent 内部执行、多 Agent 工作流、Avatar 渲染以及具体传输供应商不属于该边界。它们通过稳定的命令、事件、Journal Item 和控制面接口参与会话。

## 已确认决定

### 对齐行为与质量契约

“与 GPT Voice 对齐”表示对齐可验证的交互行为、协议语义和质量指标：

- 启动屏障、全双工对话、自然打断、工具续跑、重连恢复、播放事实、错误与资源清理；
- 命令与事件关联、正交状态、取消传播以及迟到结果抑制；
- 首音频、打断停止、入房、重连、长会话、弱网和工具延迟指标。

不把未公开的模型路由、容量调度或内部服务拓扑作为对齐目标。

### Phase 1 仅交付 Cascaded，Native 延后

- Cascaded Realtime Engine 是第一阶段唯一接入和验收的生产路径，以保留 VAD、ASR、Turn Manager、Brain、Speech Renderer 和 TTS 的替换能力。
- Phase 1 不接入 Native Realtime Provider，不安排真实凭据 A/B、样本门禁或 production-ready 声明；Native 不阻塞 Cascaded 发布。
- Stateful Realtime Engine 公共命令/事件边界继续保持 provider-neutral，Application Control Plane、Conversation Journal、工具、记忆和客户端不得依赖 Cascaded 内部拓扑。
- Native Realtime Engine 作为未来可选实现重新排期时，才要求通过同一 Contract Suite 和完整真实服务门禁；当前规划不为它投入集成工作。
- 仓库现有 Native 实现与单元/公共 Contract 测试保留但冻结，标记为 experimental/non-production，并从生产 Profile、默认装配、面向用户配置和 Phase 1 发布矩阵中移除。不补真实凭据、恢复、音质或供应商能力；Cascaded/Runtime 重构不得为兼容它而延期。只有其代码明确阻碍 Legacy 删除或公共接口演进时，才另行决定删除。

### RTC 延后到产品能力闭环之后

- Phase 1 使用现有 WebSocket 音频链路完成浏览器端到端验收。
- RTC Adapter、AI Media Gateway 和公网 RTC 基础设施不进入当前 Runtime Core 实现批次，也暂不选择声网、LiveKit 或其他供应商。
- Identity、Memory、Agent 编排和数字人产品闭环完成后，再根据真实部署、弱网、数字人视频轨与成本约束选择 RTC 方案。
- Realtime Engine 的公共命令、事件、音频格式和播放事实保持传输无关，未来接入 RTC 不应改变 Runtime Core 或产品领域模型。

### 中国大陆公网是首个地域基线

- Phase 1 的供应商可用性、网络质量、数据驻留、合规和成本均以中国大陆公网环境验收。
- 当前豆包、DeepSeek、Bella 等国内服务链路继续作为 Cascaded 默认候选。
- 全球部署通过后续地域 Profile 验证，不要求 Phase 1 同时优化两套网络与合规环境。

### 桌面 Web 是首个客户端门禁

- Phase 1 只以桌面 Chrome 的完整 WebSocket 音频会话作为端到端发布门禁。
- Web 客户端必须覆盖麦克风授权、设备切换、播放进度、打断、重连和页面生命周期清理。
- ESP32 保持协议兼容目标，但在真实 I2S 采集与播放完成前不阻塞 Voice Runtime 发布。
- 原生移动端的后台保活、音频焦点、蓝牙路由和系统来电打断属于下一阶段独立验收面。

### Device Audio Input Runtime 与 AudioWorklet

- 设备侧只有一个麦克风输入边界：Device Audio Input Runtime。桌面 Web 使用以 AudioWorklet 为核心的 conformer；原生移动端和 ESP32 后续以平台音频 API 实现同一行为契约，而不是依赖浏览器类型。
- Web conformer 统一管理 `getUserMedia` capture graph、重采样/声道转换、固定时长 Audio Frame、`input_epoch`、frame sequence/timestamp、有界 Ring Buffer、静音裁剪、pre-roll、`release/reset/mute` 和采集健康遥测。
- AudioWorklet 不拥有服务端 VAD/EOT、ASR、网络重连或授权；本地能量判断只服务于静音裁剪、pre-roll 和 UI/诊断，不成为 Turn 决策。
- `STARTING` 和 `RECONNECTING` 为当前新 `input_epoch` 进入 `buffering`。只有服务端启动或 Recovery Barrier 完成并发布匹配 epoch 的 release 后，才按 `buffering → replaying → live` 输出；旧 epoch 在断线、超时、Session 替换和 overflow 时 reset，永不补发。
- 预缓冲保护连接就绪边界处的首字，不等同于 ADR-0068 禁止的旧网络帧、旧媒体输出或跨 epoch 重放。长语音或 overflow 不发送残缺尾部，而是作废该输入并提示用户重说。
- 首版 Device Capture Profile 使用本机 GPT Voice 可观察基线：30 秒最大 Ring Buffer、`0.003` 前导静音能量阈值、100ms pre-roll 和 32ms 输出 Audio Frame。它们是版本化默认值，不是协议常量；真实设备的首字丢失、误触发、overflow 和恢复延迟遥测可推动后续 Profile 版本调整。
- Prebuffer 与 replay 期间新采集 PCM 保持一条有序 sample timeline；实现不得照搬参考 Worklet 在 replay 时静默丢弃并发输入的行为。WebSocket conformer 在下游声明支持 accelerated ingest 时以最大 `2x` 的受控速率追赶，并受 `InputAudioAck` 与发送队列高水位约束，禁止一次性 burst。
- Replay 可以跳过确定的静音，但不得静默丢 voiced samples；只有追赶到 live boundary 后才能进入 `live`。下游不支持加速或在 buffer/deadline 内无法追上时，Runtime reset 当前 epoch、发布明确 overflow/Audio Gap，并提示用户重说。
- `max_replay_rate`、catch-up deadline 和 queue watermarks 属于 Device Capture Profile。`2x` 仅是 Phase 1 WebSocket 初始值，必须通过 Cascaded ASR 路径的顺序、稳定性、endpointing 和延迟测试后才能保留；未来 RTC conformer 可以采用不同媒体实现，但遵守“不静默丢 voiced samples”的行为契约。
- 30 秒 PCM Ring Buffer 只存在于 AudioWorklet/页面进程内存；不得写入 IndexedDB、LocalStorage、文件、应用日志或默认崩溃报告。未收到匹配 epoch 的 release 前，PCM 不离开设备。
- `reset`、Voice Session 关闭、权限撤销、页面隐藏超时、设备切换或 epoch 终止必须清空并覆盖可复用缓冲。普通遥测仅包含容量/时长、能量统计、overflow、drop/gap 和状态转换，不包含原始 PCM。
- 原始音频诊断是默认关闭的独立能力，只能通过明确、限时授权开启，并声明保留期、访问审计和删除策略。UI 在 buffering/replaying/live 全程显示麦克风正在采集，不把“尚未发送”伪装为“未录音”。
- 音频增强采用设备优先和单一生效所有者：Desktop Web 首选浏览器 `getUserMedia` 的 AEC、noise suppression 与 AGC，并上报 requested/effective constraints。AudioWorklet 首版不重复实现重型 DSP；Phase 1 不提供缺少时间对齐播放参考的服务端 AEC。服务端 Audio Graph 只有在客户端明确声明某项未处理且策略要求时，才补充可选降噪或增益 Processor，绝不重复应用同一种效果。
- 设备切换、浏览器 constraint fallback 或 AudioContext 重建会重新协商 effective Device Capture Profile；遥测必须记录实际设备能力和每种效果的 owner，而不是只记录请求值。
- 麦克风切换或 capture graph 重建总是创建新 `input_epoch`。旧 Worklet 立即 reset，旧 epoch PCM 不得与新设备音频拼接；切换中的用户输入结算为 `aborted_by_device_change`，不得形成跨设备 Turn。
- 设备切换不改变网络或服务端 Session，因此 Voice Session 保持 `ACTIVE`，只临时关闭 input admission。新设备完成 effective profile 协商并收到匹配 epoch 的 release 后恢复输入；Assistant 播放与 durable Agent Task 继续，客户端显示明确的切换状态。
- 不建立基于 `device_id` 的跨标签页 Device Media Lease。每个标签页可以独立创建 Input/Output Runtime、申请浏览器权限和运行 Voice Session；浏览器/操作系统决定物理设备能否被并发打开，服务端不因同一 device 上已有另一个 Voice Session 而拒绝 `InputEpochStarted`。
- 每个标签页始终使用独立 `voice_session_id`、Input/Output Epoch 和 Generation。默认新 Voice 使用独立 `thread_id`，只共享后续 Persona 与长期 Memory；只有用户明确打开同一会话时，多个 Voice Session 才共享 Thread。
- 共享 Thread 的 Journal sequence 由服务端全局排序。每个 Response 在开始时冻结自己的 Context Visibility Barrier；其他 Session 稍后提交的 Item 从下一轮开始可见，不在生成途中热插入。Barge-in、Response/Speech cancel 与客户端 clear 只作用于来源 Voice Session，不能跨标签页传播。
- 上行协议以 `InputEpochStarted` 声明 `input_epoch`、requested/effective Device Capture Profile、不可变 `format_id` 与时间线起点；后续 `InputAudioFrame` 携带 epoch、单调 sequence、相对 `start_sample`、`sample_count`、`capture_mode=prebuffer|live` 和 payload。
- 服务端周期性发送最高连续 sequence 的 `InputAudioAck`，不为每个 32ms Frame 往返确认。重复 sequence 幂等忽略，错误或已关闭 epoch 拒绝，sample timeline 缺口形成显式 `AudioGap`；任何格式变化必须开启新 epoch。
- Endpoint 连接已授权并绑定 Voice Session，普通 Audio Frame 不重复携带 Session ID。无 sequence/timestamp/epoch 的 v1 `audio_chunk` 已在 M6 删除。
- Endpoint wire protocol 通过 `SessionHello.supported_protocol_versions` 与 `SessionAck.protocol_version` 协商唯一版本。v2 只接受 `InputEpochStarted`、`InputAudioFrame`、`InputAudioAck` 等 epoch-aware 消息；禁止按单帧形状猜测版本或静默降级。
- v1 `audio_chunk` parser/bridge/client type 已删除。版本无交集时服务端返回结构化 upgrade-required 并关闭连接；ESP32 不阻塞删除，后续直接实现 v2。
- v2 WebSocket 在处理 SessionHello 前先从可信登录 Session/Bearer Credential 解析 tenant/user/device identity；客户端 Hello 自报的身份字段没有授权力。Production Profile 缺失身份时拒绝连接，显式 localhost development profile 可以使用不安全固定身份但必须输出显著告警。
- 新 Voice Session 返回 256-bit 随机 Resume Token；owner Registry 只存哈希，并绑定 identity、`voice_session_id`、protocol version 和 grace。恢复必须提交 Session ID + token 且与当前认证身份全部匹配，token 只在 Session detached 时可用，成功 attach 后立即轮换。
- 一个 Voice Session 同时最多一个 Endpoint attachment。active Session 的第二次 resume、错误/过期 token 和身份不匹配均不透露 Session 存在性，返回统一 `resume_rejected` 或 `continuation_required`。浏览器 token 只进入标签页内存或 sessionStorage，不进入 URL、日志或普通遥测。
- 新 Session 只接受可选 `requested_thread_id`。缺省时服务端为当前认证 tenant/user 创建 Thread；指定时必须验证其所有权与当前可访问状态。并发标签页共享 Thread 仍逐 Session 授权。
- Continuation 的 `thread_id` 从旧 Session/Journal 权威关系推导，客户端给出不一致值时拒绝。Resume Token 本身不授予 Thread 访问权；Thread 授权失败同样返回不枚举资源存在性的统一错误。
- `public/voice-input-worklet.js` 已实现 v2 Worklet 状态机、有界 Ring Buffer、epoch 控制与新的输入帧元数据；v1 `public/pcm-worklet.js` 已删除。

跨客户端公共契约见 [ADR-0070](./adr/0070-device-audio-input-runtime-and-web-audioworklet.md)，恢复语义见 [ADR-0068](./adr/0068-semantic-session-resume-without-media-replay.md)。

### Device Audio Output Runtime 与播放事实

- 设备侧播放统一进入独立的 Device Audio Output Runtime；它与 Input Runtime 由 Client Voice Session Controller 协调，但保持各自的 epoch、队列和状态，不合并为客户端巨型媒体状态机。
- Output Runtime 负责音频解码/重采样、播放时钟、有界队列、输出设备与音量、`speech_id/generation` 关联、立即 cancel/clear，以及按 Audio Frame sequence/sample position 产生 Playback Progress。
- Phase 1 WebSocket 可以使用 AudioWorklet 播放 conformer 或现有 AudioBufferSourceNode 调度的增强实现；未来 RTC Remote Track 必须适配同一取消、清队列和播放事实契约，不能让 Transport 类型改变 Speech/Delivery 语义。
- Barge-in 先以 generation-aware cancel/clear 使旧输出在设备端立即失效，再向服务端报告最后可信 `played_position`。发送、接收、排队或解码完成均不等于已播放。
- 输出设备切换若能在同一 AudioContext、播放时钟和队列上通过 `setSinkId` 完成，则保留当前 `output_epoch` 与 Speech，只记录设备边界和短暂 glitch。若平台必须重建播放图，则创建新 `output_epoch`、清空旧队列，并把当前 Speech 结算为 `interrupted_by_device_change`；状态不确定的旧缓冲不得迁移或重播。
- 输出设备重建不改变 Voice Session Phase，输入与 durable Agent Task 继续。新设备 ready 后可用新的 Speech 告知切换完成，用户可以要求继续内容，但系统不静默重放旧 Speech。
- Client Voice Session Controller 执行服务端关联后的本地命令并投影 UI，但 Voice Session Phase、Generation、Journal、策略与持久化 Delivery Record 仍由服务端权威组件拥有。
- Output Runtime 同样不采用跨标签页排他 lease；每个标签页只管理自己 Voice Session 内的 output epoch、队列和播放事实，不发送 BroadcastChannel/Web Locks 接管命令。

决策记录见 [ADR-0071](./adr/0071-device-audio-output-runtime-and-playback-truth.md)。

### 删除 Legacy Runtime Path

- Voice Session Runtime 行为迁移完成后删除 `VOICEAGENT_REALTIME_RUNTIME=legacy` 选择分支以及 `_build_kernel()` / `_finish_build_kernel()` 可运行组装路径。
- `ConversationKernel`、`PipelineConversationEngine.respond()`、`VoiceEvent` 和 `ConversationAction` 不再作为公共或生产编排边界。
- 旧路径覆盖的重要场景先迁入 Realtime Engine Contract Suite 或专项测试，再删除对应旧测试；不以降低行为覆盖率换取代码清理。
- 现有 VAD、ASR、Brain、TTS 实现继续保留。当前 `Legacy*CapabilityAdapter` 是这些能力进入新 Runtime 的迁移桥，不等同于 Legacy Runtime Path；它们在原生 Capability Binding 就绪后逐个替换。
- `server/gpt_voice_reference` 继续作为可执行行为规范，不成为第二套生产 Runtime。

### 服务端权威的 Voice Session Phase

- Voice Session Runtime 实现 `INACTIVE → STARTING → ACTIVE → RECONNECTING → STOPPING → CLOSED` 权威状态机；它与 Dialogue State、Realtime Conversation 生命周期和物理连接状态正交。
- `ACTIVE` 必须等待 Endpoint hello/resume、Realtime Profile 解析与 Conversation 打开、Event Pump 与控制器启动、客户端音频准备四类屏障全部通过。
- 断线进入 `RECONNECTING`；恢复继续使用同一 `voice_session_id` 和 `thread_id`。启动失败、恢复超时或主动结束通过 `STOPPING → CLOSED` 结算。
- 进入 `ACTIVE` 前不接受普通用户输入或触发模型回答；关闭必须结算活动 Response、Speech、Tool、Delivery Record 与资源句柄。
- 决策记录见 [ADR-0067](./adr/0067-server-authoritative-voice-session-phase.md)。

`VoiceSessionEvent` 是独立于 `RealtimeEvent` 的 Runtime 事件族，至少包含 Phase Changed、Ready、Recovery Started/Completed/Failed 和 Closed。两类事件可以复用同一个 WebSocket 控制通道，但必须保留各自的所有权、schema version、事件身份和顺序；Voice Session Event 使用服务端单调递增的 `session_sequence`。

Voice Session 关闭使用有界结算顺序：

1. 进入 `STOPPING` 并拒绝新输入；客户端 reset Input Runtime、clear Output Runtime；
2. 推进 Generation，取消活动 Response、Speech、Brain/TTS 和 Fast Tool Loop；
3. 以最后可信 Playback Progress 结算 Delivery Record，无确认时标记 `uncertain`；
4. 使 Session-bound Pending Confirmation 失效，durable Agent Task 继续并保留持久化投递；
5. 在 deadline 内提交 Journal/Outbox 终态与 close reason；
6. 关闭 Event Pump、Cascaded Conversation、Capability Sessions、Endpoint，释放 Admission 并从 Registry 移除；
7. 发布 `CLOSED`。清理超时记录具体资源与 degraded close，不无限阻塞退出。

正常 Session close deadline 为 5 秒；进程收到终止信号后的全部 Voice Runtime drain deadline 为 15 秒。超过 deadline 的外部调用被取消或遗弃为明确未知状态，不能报告 clean close。

v2 使用统一 Voice Session Failure Envelope：`error_id`、稳定 `code`、当前 `phase`、`retryable`、可选 `retry_after_ms`、`session_disposition`（`keep_reconnecting | close | continuation_required`）和 `safe_message`。客户端只按结构化字段决策，不解析文案。

首批稳定 code 为 `authentication_failed`、`protocol_incompatible`、`capacity_exhausted`、`invalid_command`、`provider_unavailable`、`context_restore_failed`、`recovery_deadline_exceeded`、`continuation_required` 和 `internal_error`。Provider 名称、异常堆栈、凭据、资源存在性等细节只通过 `error_id` 关联服务端日志/Event Ledger；terminal failure 不得伪装成 retryable。

### 语义恢复，不重放原始媒体帧

- `SessionHello` 恢复请求携带授权后的 Session 身份、客户端最后应用的 `session_sequence`、最后可见的 Journal sequence 和最新播放位置。
- Runtime 在保留窗口内返回增量事件尾；游标不可用或存在缺口时返回 Voice Session Snapshot，再从新的序列边界继续。
- Voice Session Snapshot 投影 Phase、可见 Conversation 状态、活动 Work 与 Playback Facts，但不冒充 Conversation Journal 或持久化数据库。
- `AudioDelta`、部分 Transcript delta 和过期 UI delta 永不重放。断线时活动 Speech 结算为 interrupted 或 uncertain，恢复后默认不自动重播。
- Snapshot、Engine 上下文、控制器和客户端播放端重新同步后，Runtime 才发布 Recovery Completed 并回到 `ACTIVE`。
- ADR-0068 取代 ADR-0019 的原始 `OutboundFrame` 缓冲回放语义；Endpoint attach/detach、恢复握手与 bounded grace period 保留。

Semantic Session Resume 只适用于进程仍存活且未超过 grace period 的 Voice Session。进程崩溃、部署重启或 grace 超时后创建新的 `voice_session_id`，通过 `previous_voice_session_id` 关联旧 Session，并继续同一个 `thread_id`；Conversation Journal、Agent Task Store 和 Delivery Store 分别恢复语义上下文、后台任务和播放事实。

恢复使用服务端原子 Recovery Barrier。Runtime 保持 `RECONNECTING`，直至以下条件使用同一个恢复目标全部成立：

1. 身份、Voice Session 归属、设备权限与恢复游标已验证；
2. Conversation Journal 和当前 Engine 的 Model Context 已恢复到冻结的目标 sequence；
3. Agent Task、Tool Request/Result 与 Pending Confirmation 已从各自权威存储重建；
4. 断线前 Speech 的 Playback/Delivery Facts 已结算，客户端不会继续旧音频；
5. Voice Session Snapshot 与增量事件尾建立了无缺口的新 `session_sequence` 边界。

客户端可在此期间渲染 reconnecting UI，但普通用户输入不得进入 Turn/Engine，也不得触发模型回答。必需屏障失败时 Runtime 保持 `RECONNECTING` 并发布可诊断的失败原因；超过恢复策略的 deadline 后，旧 Session 通过 `STOPPING → CLOSED` 结算，并返回 Continuation Required，使客户端以新 `voice_session_id`、原 `thread_id` 和 `previous_voice_session_id` 打开 Voice Session Continuation。任何子步骤完成都不能单独把 Session 标记为已恢复。

### Model Context Restoration Barrier

重连或新会话连续性不仅恢复 UI 状态，还必须确保历史已经进入当前大模型上下文：

1. Recovery 开始时冻结目标 `target_thread_sequence`。
2. 从 Conversation Journal 按序读取模型可见 Item；Assistant Item 先结合 Speech Delivery Record 应用 Interrupted Context Policy，默认只保留用户实际听到的内容。
3. Phase 1 Cascaded Engine 将投影交给 Turn Manager 与 Brain Context Projection；未来其他 Engine conformer 必须证明等价的可见性。
4. Engine 确认 `projected_through >= target_thread_sequence` 后，Runtime 才发布 Context Restored、Recovery Completed，并进入 `ACTIVE`。
5. 投影缺口、摘要失败或 Provider 拒绝时保持 `STARTING/RECONNECTING`，不得在缺历史的情况下静默回答。

触发屏障的场景包括：进程重启后的 Voice Session Continuation、Provider/Engine 重建、Profile Reconfiguration 和故障迁移。仅物理 WebSocket 断开且原 Engine 健康存活时不重复导入，但仍需核验 Engine 的 projected sequence。

当前代码基础：

- `RealtimeRuntimeFactory._replay_journal()` 已在 Engine 打开后顺序发送 `ProjectCommittedItem`；
- 仓库已有 Native adapter 的 Provider item 投影代码，但它不属于 Phase 1 接入或发布证据；
- Cascaded Engine 已保存 projected items，并在下一轮构造 Brain conversation context；
- `minimum_thread_sequence` 已阻止回答越过未投影的 Journal Item；
- Delivery-aware projection 已按 completed/interrupted/uncertain 的实际送达事实修正 Assistant 历史。

用户语音只在 Turn Manager 接受 EOT 且 ASR 形成稳定最终转写后，以 `USER_INPUT` Item 进入 Conversation Journal。Partial/revision delta 仅存在于 bounded live event/UI；Journal commit 成功并通过 Context Visibility Barrier 前不得请求模型回复。Reconnect、设备切换、overflow 或用户取消导致的中止输入不进入模型上下文，只记录不含原文的原因与音频时间范围。

后续 ASR/用户修正通过引用原 `item_id` 的 `CORRECTION` Item 追加，不能原地改写历史；它同时使覆盖该范围的 Summary Checkpoint 失效。空或策略判定为低可信的 final 不提交空 Turn，系统明确请求用户重说。原始用户音频默认不持久化，录音/回放/训练数据是独立显式授权能力。

当前实现已经把 Journal/Engine 投影核验、控制状态恢复和新 input epoch 放入同一个 Voice Session Recovery Barrier，并发布目标、完成/失败事件与 projection digest。Cascaded 使用版本化 Context Policy、预算、Checkpoint 校验和混合压缩器；固定最近 8 条/4000 字符路径不再参与生产回答。恢复目标在开始时冻结，后续 Journal 写入留给下一次投影，不能让模型历史和控制状态使用不同游标。

### Context Budget 与压缩机制

Phase 1 的 Cascaded Engine 使用一个版本化 Context Policy；未来 Engine conformer 必须复用同一策略语义，而不能另建隐式截断。每次投影先读取目标模型声明的 context window，再依次预留：

1. 最大输出 token；
2. Tool schema 与可能的 Tool Result；
3. 系统规则以及后续 Persona/Identity/Memory 注入；
4. 当前用户输入与活动 Work/Confirmation；
5. tokenizer 误差和 Provider 包装开销的安全余量。

剩余空间才分配给 Conversation Summary Checkpoint 和最近原文。模型原生 tokenizer 可用时按目标模型精确计数；不可用时使用偏保守估算，绝不依赖字符数冒充 token 数。

压缩流程：

- 当投影预计达到可用预算约 70% 时，后台异步生成或扩展 Summary Checkpoint，不阻塞实时回答；
- Checkpoint 是 `CONTEXT_SUMMARY` 派生 Item，记录精确 `source_sequence_start/end`、source digest、compressor model/version、prompt/policy version、输入/输出 token 与生成时间；
- 恢复时选择最新有效 Checkpoint，加上其覆盖范围之后的未压缩 Item 和最近原文；
- Correction、Redaction、源 digest 不匹配或策略不兼容会使 Checkpoint 失效并触发重建；
- 压缩不能丢弃当前输入、活动 Tool/Agent/Confirmation、未解决事项、关键决定和实际送达修正；
- 新摘要暂时不可用时，可使用上一有效 Checkpoint 和更小的最近原文窗口，并发布 `context_projection_degraded`；若必需内容仍无法装入，则 Context Restoration 失败，不静默截断；
- Provider 调用前再次计算最终 payload token，并记录各分区预算、projection digest、covered sequence 和 omitted-by-summary 范围。

Conversation Summary Checkpoint 使用结构化内容加自然语言摘要：

```text
narrative
decisions[]
open_questions[]
commitments[]
active_work_refs[]
artifact_refs[]
source_sequence_start / source_sequence_end
source_digest
compressor_model / compressor_version
compression_policy_version
input_tokens / output_tokens
```

所有引用 ID 必须能解析到来源范围内的 Journal、Task 或 Artifact 权威记录。Checkpoint 不提取或持久化长期用户 Memory；后续 Memory 系统可以消费授权后的 Journal，但不能把 Context Compression 当作 Memory 写入旁路。

Context Compressor 采用混合实现：

- 代码确定性提取 Tool、Agent Task、Confirmation、Artifact、Item ID、生命周期和因果关系；
- 模型只压缩 narrative、决定背景和未解决问题，不得生成权威任务状态；
- 输出必须通过 JSON Schema、引用解析、source range/digest、token budget 和敏感数据校验；
- 校验失败的 Checkpoint 不可见，不覆盖上一有效版本，也不触发任何任务或工具副作用。

Context Policy 与 Compressor 归 Application Control Plane 管理，不进入 Realtime Profile 或 Engine plugin slot。配置显式包含 `compressor_id`、model/schema/prompt/policy version、token/cost budget、queue、timeout 和 concurrency。部署可以复用聊天模型的供应商凭据，但不能隐式继承当前聊天模型；切换 Engine、ASR 或 TTS 不改变压缩策略。

初始实现应提供 `ContextPolicy`、`ContextBudgeter`、`ContextCompressor`、`SummaryCheckpointStore/Validator` 与统一 `ConversationProjector`，替换 Cascaded 的固定 8 条/4000 字符逻辑。决策记录见 [ADR-0069](./adr/0069-budgeted-context-projection-and-summary-checkpoints.md)。

### Barge-in 的取消传播边界

- Turn Manager 确认 Barge-in 后立即推进 Generation，停止客户端旧音频播放，并取消当前 Response、Brain/Provider 生成、TTS/Speech Output 和属于该 Response 的 Fast Tool Loop。
- Generation lease 是最终输出防线：外部系统无法及时取消时，旧 Response 的迟到文本、音频和 Tool Result 仍不得影响用户或续跑旧回复。
- 已提交的 Tool 副作用不回滚；其结果和真实状态继续写入 Conversation Journal。是否需要在新 Generation 中告知用户，由后续投递策略决定。
- Barge-in 不自动取消 durable Agent Task，新话题也不隐式取消无关任务。Agent Task 继续运行，结果进入持久化投递队列，不得抢占当前语音；只有明确且无歧义地解析到 `worker_id` 的取消请求，才由 Agent Task Supervisor 发起幂等取消。
- Context Compressor 等独立派生工作不绑定 Response cancellation；若完成时 source range、digest 或 Context Policy 已失效，则丢弃该输出。

该边界组合并沿用 [ADR-0048](./adr/0048-end-to-end-streaming-conversation-engine-and-output-contract.md) 的 Response cancellation 与 Generation lease，以及 [ADR-0052](./adr/0052-durable-agent-task-supervisor-deduplication-and-result-delivery.md) 的 Agent Task cancellation 语义，不另建重复 ADR。

### Barge-in 与 Bound Confirmation

- Barge-in 只停止 Confirmation Prompt 的当前语音输出，不删除或默认为批准/拒绝对应 `PendingConfirmation`。
- 一个 Voice Session 同时最多暴露一个前台 Confirmation；底层即使存在其他待定记录，也不得让一句自由形式的“是”在多个候选之间猜测授权目标。
- 后续语音只有在意图明确、主体匹配、未过期且能唯一绑定 `confirmation_id` 与 exact action digest 时，才成为批准或拒绝决定。
- 新话题、含糊回答、背景语音或 Prompt 播放中的打断均不构成批准。记录保持待定直至 TTL 过期、明确拒绝或策略安排安全的再次提示；系统不存在默认同意。
- 同一 Voice Session 的 Semantic Session Resume 可以恢复尚未过期的待定状态，但必须先重新陈述操作、目标和重要后果，再接受新的决定。脱离重新陈述上下文的一句“是”没有授权力。
- 创建新 `voice_session_id` 的 Voice Session Continuation 不复用旧 Voice Session 绑定的批准；若操作仍需执行，必须重新过策略并生成新的 Bound Confirmation。

这些规则细化 [ADR-0051](./adr/0051-server-authoritative-tool-policy-gateway-and-bound-confirmation.md) 的 Bound Confirmation 协议，不改变 Tool Policy Gateway 的权威边界。

### Phase 1 两层发布门禁

第一层是零容忍的 correctness gate。以下不变量在 deterministic Contract Suite、故障注入和浏览器 E2E 中必须保持零违规：

- 不产生跨 Voice Session 的音频、Generation、cancel/clear 或 Confirmation 决定；
- 未认证、伪造身份、猜测 Session ID、重放/窃取旧 Resume Token 均不能 attach 或观察 Session；
- Barge-in 后 stale Generation 不再产生可观察文本、音频或 Tool continuation；
- reconnect、retry 与 replay 不重复执行 Tool、Agent Task、Confirmation 或结果投递；
- Voice Session Recovery 和 Model Context Restoration Barrier 未完成时不触发新模型回复；
- 客户端 prebuffer PCM 不进入持久存储、普通日志、默认崩溃报告或未 release 的网络发送；
- 启动/reconnect、replay-to-live、device change 与 overflow 测试中不存在 voiced sample 的静默丢弃。

第二层是真实服务 statistical gate。每个被验收的 Engine/Profile 至少记录 200 个 attempted full turns，失败尝试同样进入分母，之后才能评价：

- EOT accepted → client playback started：p50 `< 800ms`，p95 `< 1500ms`；
- Barge-in confirmed → old audio stopped：p95 `< 200ms`；
- network available → same-process Voice Session returned to `ACTIVE`：p95 `< 1000ms`；
- no-response/abnormal-terminal rate：`< 0.5%`；
- first-word preservation 专项中 voiced-sample silent loss 为 0。

样本不足的构建只能标记 Preview，不能宣称达到 GPT Voice alignment gate。所有分位数必须按 Engine、Provider、Device Capture Profile、浏览器版本、网络档位和结果类型分组，不能用混合平均值掩盖失败路径。

### Telemetry 与 correlation

- Phase 1 复用现有 `RuntimeTelemetry/SessionTelemetry` 与 Event Ledger，不在实时关键路径强制引入 OpenTelemetry SDK。未来 OTel 只能作为异步 exporter，不能改变核心事件、关联或失败语义。
- `voice_session_id` 贯穿 Session，但不创建覆盖整场长会话的单一 Span。启动、connection attempt、Recovery、Turn、Response、Speech、Tool 和 Agent Task 分别拥有独立 `trace_id/operation_id`，再通过 Session 与因果 ID 关联。
- 关联字段至少包含 `connection_attempt_id`、`input_epoch`、`turn_id`、`response_id`、`speech_id`、`call_id`、`worker_id`、`confirmation_id` 和 `error_id`；不存在的关联不得用空字符串伪造。
- 客户端与服务端分别用本地 monotonic clock 计算 duration；跨设备只交换具名 milestone 与各自时间基准，不能直接相减未同步的 wall clock。
- 普通 telemetry 不记录原始 PCM、完整 transcript、Prompt、模型 Token 内容或 Tool secret。Writer/Exporter 使用有界非阻塞队列；诊断存储或 Event Ledger 故障不阻塞音频、Generation cancellation 或 Session close。
- Preview 与 200 Turn 验收期对 milestone、terminal、failure 和 stage span 采集 100%。GA 后 milestone/terminal/failure 仍为 100%，成功 Turn 的详细 stage span 默认 10%，error/timeout/degraded 保持 100%；failure 不得因成本被无声明丢弃。
- 详细 Session/Turn telemetry 默认保留 30 天，去内容后的聚合 SLO 指标默认保留 90 天。Tenant 删除或更严格合规策略可以提前清除，并覆盖索引、诊断视图和异步 exporter；Profile 只能缩短默认保留，延长需单独数据政策。

## 实施批次与依赖顺序

### M0：行为基线

- 把 Legacy Runtime 的启动、普通 Turn、Barge-in、Fast Tool、后台 Agent、Confirmation、重连、播放结算与关闭行为迁移为新的 Engine Contract、Voice Session Contract 和浏览器 E2E 用例。
- 对旧行为分类为 preserve、intentionally replace 或 delete；任何待删除测试必须先有新边界下的等价覆盖或明确淘汰理由。

### M1：服务端 Runtime 与 v2 协议骨架

- 实现 Voice Session Phase、Voice Session Event、`session_sequence`、启动/恢复 barrier 框架和结构化失败原因。
- 实现 v2 Endpoint 版本协商、`InputEpochStarted/InputAudioFrame/InputAudioAck`、epoch/timeline 验证、Audio Gap 与 v1 显式适配器。
- 当前实现：v2 Endpoint 只接受 Transport Authenticator 产生的可信 tenant/user/device identity；Client Hello 自报字段被忽略。缺少可信身份返回统一 `authentication_failed`，Resume Token 绑定可信身份且只在 detached 状态可用，成功后轮换，active Session 的竞争 attach 被拒绝。localhost development 显式注入固定身份并告警；production-shaped `static_bearer` 支持可信代理 Header 或安全 Cookie。指定 Thread 必须经过服务端 Journal authority 校验，Resume Token 本身不授予 Thread 权限。
- 当前实现：进程级 `LocalVoiceSessionAdmissionController` 在 AudioWorklet release 前共同限制活跃 Session、ASR/TTS 租约、事件循环延迟、进程内存与音频队列预算，拒绝时发布 `capacity_exhausted`/`retry_after`；不按 `device_id` 排他。断线后的 5 秒 fast-resume 保留实时资源，超窗后 quiesce Provider Conversation 与 Admission；60 秒 grace 内恢复会重新 Admission、重开 Conversation，并仍须通过同一个原子 Recovery Barrier。

### M2：Desktop Web 媒体闭环

- 实现 Device Audio Input Runtime、AudioWorklet Ring Buffer、release/reset、受控 catch-up、Device Capture Profile 和设备生命周期。
- 实现 Device Audio Output Runtime、generation-aware queue/clear、output epoch、Playback Progress 与 Client Voice Session Controller。
- 打通第一个 Cascaded + WebSocket v2 端到端启动、普通对话、Barge-in 与设备切换链路。
- 当前实现：Desktop Web 的 AudioWorklet 以 30 秒上限、`0.003` 能量阈值、100ms pre-roll 和 32ms Frame 运行 `buffering → replaying → live`；并发采集的 voiced PCM 始终排在旧 prebuffer 之后，不在 replay 时丢弃。页面 Runtime 为同一 epoch 分配连续 sequence/sample timeline，按最多 `2x` 令牌节流发送，以服务端累计 `InputAudioAck` 和 8/32 Frame 低/高水位驱动 Worklet pause/resume；无法在 deadline 内追上或任一缓冲溢出时整 epoch 失效并提示重说。
- 当前实现：每个 `InputEpochStarted` 都携带单调 timeline origin、requested/effective Capture Profile、浏览器实际 AEC/NS/AGC constraints 与逐效果 owner。服务端把这些无内容元数据写入 `client.input_epoch_started`；overflow、catch-up deadline 和 Worklet/AudioContext/device failure 只上报 epoch、缓冲时长/容量与聚合能量，不上报 PCM。reset、断线、停止、设备结束、Worklet failure、AudioContext suspension 和页面隐藏 30 秒都会覆盖并清空缓存；capture graph 重建生成新 epoch。

### M3：语义恢复与模型上下文

- 实现 Voice Session Snapshot/event tail、Semantic Session Resume 与 Continuation Required。
- 把 Journal replay 接入 Model Context Restoration Barrier；实现 Context Policy、Budgeter、Conversation Projector、Context Compressor 和 Summary Checkpoint validation。
- 当前实现：`VoiceSessionRuntime` 保留连续、bounded 的语义事件尾；v2 重连在 Model Context 与控制状态完成同一原子恢复后、`RecoveryCompleted` 前返回增量 lifecycle tail，游标缺口则返回包含 Phase、Journal sequence、Work、Pending Confirmation 与最近客户端播放位置的 Snapshot。原始音频和过期 delta 从不回放。恢复总 deadline 超时会发布 `recovery_deadline_exceeded`、关闭旧 Session，并由浏览器以 `previous_voice_session_id` 和经过重新授权的原 `thread_id` 建立新 Session Continuation；模型启动时从同一 Journal Thread 重投影历史。客户端在 Continuation 中保留可见对话，但清除旧媒体 epoch、token、播放与 Session sequence。

### M4：控制面恢复

- 完成 Fast Tool cancellation、Bound Confirmation 前台恢复、Agent Task/Work Registry 重建、Delivery queue 与迟到结果处理。
- 验证 reconnect/replay 不产生重复 side effect、任务、确认或用户通知。
- 当前实现：物理断线先 suspend `ActiveRealtimeConversations` 并取消活动 Response，使 Speech/Playback/Fast Tool 进入既有结算链；Agent Result Outbox 在恢复完成前保持 pending。恢复从冻结 Journal 前缀重建 Tool/Delegation/Confirmation 身份，从 Agent Task Store 重建非终态 Work Registry，并以 Tool Authorization Store 核验仍有效的 exact action digest。浏览器断线立即撤销旧确认入口，Runtime 回到 `ACTIVE` 后才重新下发确认；同一次恢复幂等，而每次新的物理重连都必须重新陈述。
- 当前实现：共享 Admission 的 accepted/rejected/released 决策、拒绝原因、活动/投影 Session 数、event-loop、进程内存和音频队列压力进入去内容的 Session diagnostics；观测写入失败不改变 Admission 决策或阻塞音频关键路径。

### M5：质量门禁

- 运行故障注入、Chrome E2E、长会话、设备变化、弱网/断线和资源清理测试。
- 为 Phase 1 Cascaded release profile 累积至少 200 个 attempted full turns，生成 correctness 与 SLO 分组报告。
- 当前实现：`VoiceRuntimeQualityGate` 严格区分 live/synthetic 证据，对每个 Engine/Provider/Capture Profile 独立应用 200 turns 门槛，并按 Chrome 版本、网络档位和结果类型分组；deterministic 样本只能得到 Preview。`scripts/collect_voice_runtime_quality_evidence.py` 从 Control Plane 的 content-free diagnostics 导出逐 Turn 严格 JSONL，并要求 capture epoch；标为 live 时还要求 Provider Call 证据，同时保留相邻 invocation manifest。`scripts/generate_voice_runtime_quality_report.py` 原子生成 JSON/Markdown，`scripts/test_voice_runtime.sh` 将全量 Python、前端单测、TypeScript、production build、Chrome E2E 与统计报告串成发布门禁。
- 当前实现：Chrome E2E 已覆盖同一 Voice Session 内 capture graph/device constraint 重建（只更换 `input_epoch`）、累计 Audio ACK、物理断线 resume，以及只有收到恢复后的匹配 `VoiceSessionReady`、真正回到 `ACTIVE` 才上报 reconnect duration。2026-08-21 的真实 Doubao ASR → DeepSeek → Doubao TTS Profile 已完成 200 attempted full turns，p50 635.7 ms、p95 1035.8 ms、异常率 0、正确性违规 0，M5 状态为 Passed。证据见 [VOICE-RUNTIME-QUALITY.md](./VOICE-RUNTIME-QUALITY.md) 与 [正式报告](./reports/2026-08-21-voice-runtime-phase1-live.md)。

### M6：生产收口与删除

- 将新 Voice Session Runtime + v2 Desktop Web 设为唯一生产路径。
- 删除遵循 replacement gate，而不是按计划日期直接执行。每个旧模块必须同时满足：生产 import/装配引用为 0；对应行为已有新 Contract/E2E；新路径通过 correctness gate；可复用能力已迁入正确包且没有反向依赖。
- 当前状态：Cascaded 主链路、Voice Session Runtime、WebSocket v2 media、Context Compressor、Fast Tool/Confirmation 控制面与播放事实已进入新边界；Agent Delegation 由 Brain 提议、Realtime 控制器、唯一 Supervisor 权威提交和 Journal 投影组成，重复提议不会重复启动任务。控制恢复、Work Registry 重建、连接 suspend/resume 与待确认重新陈述已进入生产 endpoint。`server/kernel/`、`server/conversation_engine/`、`server/scheduler/`、`server/realtime/legacy.py`、旧 Application coordinator、旧 Demo 装配和对应专项测试均已按 replacement gate 删除。
- v1 `audio_chunk` parser/bridge/client type 与 `public/pcm-worklet.js` 已在真实 Profile 门禁通过后删除；服务端只接受 epoch-aware v2 输入。
- React 入口使用 `useVoiceSession`；旧 `use-conversation-engine.ts` 已删除。协议解析和重连归属 `src/voice/session/transport.ts`，设备输入图归属 `src/voice/audio/browser-input.ts`，输出播放图归属 `src/voice/audio/browser-output.ts`；Hook 不再创建物理媒体图。
- VAD/ASR/TTS 等现有能力实现及仍被新 Cascaded Engine 使用的 `Legacy*CapabilityAdapter` 不属于 Legacy Runtime Path，暂时保留；Brain adapter/speculative implementation 先迁入 Realtime Capability/observability/control 正确归属，再删除原包。
- `demos/basic_ws_server.py` 迁成最小 v2 Voice Session 示例；仅依赖 Kernel 的 `demos/udp_server.py` 删除，未来 UDP/ESP32 直接实现 v2。`server/gpt_voice_reference` 继续保留为不参与生产装配的行为规范。

## 代码归属与迁移目标

服务端新增独立 `server/voice_session/` 包，避免继续把完整 live-session orchestration 塞入 Engine 或 Endpoint：

```text
server/voice_session/
  models.py          # Voice Session Phase、Snapshot、VoiceSessionEvent
  runtime.py         # VoiceSessionRuntime
  recovery.py        # Recovery Barrier、Semantic Resume、Continuation
  registry.py        # 活跃 Voice Session 定位与生命周期
  endpoint_bridge.py # Endpoint 命令/事件与 Runtime 的桥
```

- `server/realtime/` 只拥有 Realtime Engine、Realtime Conversation、Capability、Speech 与其公共命令/事件。
- `server/endpoint_session/` 只拥有物理连接 hello/attach/detach、transport continuity 与 grace period，不恢复 Journal、Work 或模型上下文。
- 当前 `RealtimeRuntimeFactory` 迁移并收窄为 `RealtimeConversationFactory`：解析 Realtime Profile、打开 Phase 1 Cascaded Conversation、执行受 Context Barrier 约束的 Journal projection。完整 Session 生命周期由 `VoiceSessionRuntime` 负责。
- 当前 WebSocket Realtime Session orchestration 迁入 `voice_session.endpoint_bridge`；Transport Adapter 不持有领域状态。

Desktop Web 将当前巨型 React Hook 拆成：

```text
src/voice/session/controller.ts
src/voice/session/transport.ts
src/voice/audio/input-runtime.ts
src/voice/audio/output-runtime.ts
src/voice/audio/browser-input.ts
src/voice/audio/browser-output.ts
src/voice/protocol/v2.ts
src/hooks/use-voice-session.ts
public/voice-input-worklet.js
```

`use-voice-session.ts` 把 Client Voice Session Controller 的状态和命令绑定到 React；协议解析、重连、输入/输出 epoch、Worklet、播放队列和 Playback Progress 不再由 UI Hook 自己实现。旧兼容 Hook 已在 M6 删除。

## Live Session 存储边界

- 活跃 `VoiceSessionRuntime`、Voice Session Registry、Snapshot cache 与 bounded `session_sequence` event tail 只存在于拥有 Session 的进程内存；同一 Session 的 Semantic Resume 必须在 grace period 内通过 sticky routing 回到该进程。
- Voice Session Snapshot 是从当前 live state 与 Conversation Journal、Agent Task Store、Confirmation Store、Delivery Store 等权威来源生成的临时投影，不作为新的数据库权威或可执行备份。
- Session opened/resumed/closed 等语义边界进入 Conversation Journal；详细运行事件异步进入 Event Ledger 供审计和诊断，但 replay Event Ledger 不得恢复执行或重建同一 live Session。
- 进程丢失、部署重启、owner 不可达或 grace 超时后不从 Redis/PostgreSQL 复活原 `voice_session_id`，而是按 ADR-0068 创建 Voice Session Continuation。
- Phase 1 不引入 Redis Session directory。只有未来多副本/RTC Gateway 的真实路由与可用性需求证明进程内 Registry 不足时，才单独设计外部 Session directory；它也不能取代 Journal、Task 或 Delivery authority。

## Phase 1 部署拓扑

- `/voice/ws` 只进入一个 Voice Runtime 进程；Phase 1 禁止对该入口启动多个不共享 Registry 的 Uvicorn/Gunicorn worker。Web UI、普通 HTTP API、管理后台与持久化服务可以独立扩容。
- 单进程承载多个并发 Voice Session，并对 Session、ASR/TTS、队列、内存和外部调用设置显式容量；并发标签页只是独立 Session，不要求独占进程。
- Phase 1 明确不提供 live Session 热故障转移。健康检查和进程管理负责快速重启；进程丢失后的客户端恢复是 Voice Session Continuation，不是假装同一 Session resume。
- CPU、事件循环延迟、内存、活跃 Session、音频队列、ASR/TTS 并发和 restart/continuation 比率必须可观测。只有容量证据表明单实例成为瓶颈时，才设计基于 Session 的一致性路由或外部 directory。
- Voice Session Admission 是 `STARTING → ACTIVE` 的必需屏障，并发生在 AudioWorklet release 之前。它综合活跃 Session、event-loop lag、内存、ASR/TTS Provider 并发和音频队列预算；容量不足返回结构化 `capacity_exhausted` 与 `retry_after`，客户端 reset 当前 input epoch，服务端不先收语音再无限排队。
- 已激活 Session 不因新请求被强制驱逐。实时音频容量优先于 Context Compressor、后台 Agent 通知和可选 Analyzer/Sink；这些低优先级工作必须有独立 queue/concurrency budget。
- 不按 `device_id` 排他。部署可以配置 tenant/user 并发和速率配额防滥用，但必须允许合法多标签页；具体默认并发不在设计阶段拍定，由 M5 负载测试写入部署 Profile。
- 断线进入 `RECONNECTING` 时立即停止 input admission，取消/结算当前 Response、Speech、Fast Tool Loop 与 Playback Facts。前 5 秒为 fast-resume window：保留 Cascaded Conversation、Provider 连接和实时容量，以支持亚秒恢复。
- 5 秒后进入 quiesced resume：关闭 ASR/TTS/音频队列并释放实时 Admission 资源，只保留 Session 身份、bounded event tail、Snapshot 所需 live metadata。60 秒总 grace 内重连仍可复用 `voice_session_id`，但必须重新 Admission、重建 Conversation 并通过 Model Context Restoration Barrier。
- quiesced resume 暂时无法重新取得容量时保持 `RECONNECTING` 并返回 `retry_after`；超过 60 秒关闭旧 Session并走 Continuation。Durable Agent Task 和 Context Compressor 不因实时资源 quiesce 而取消。

## 当前实现判断

- Stateful Realtime Engine、Cascaded conformer、公共命令/事件、播放事实、Journal-first 投影、工具续跑和 Agent 结果回注主链路已经存在。
- 当前 Voice Session Runtime 以真实 WebSocket Transport conformer 作为主入口；RTC 与 AI Media Gateway 明确延后。
- 仓库现有 Native adapter 冻结为 experimental，不进入生产注册、Phase 1 接入、A/B、弱网或长会话验收范围。
- 旧 Conversation Kernel、Conversation Engine、Scheduler、迁移期 Application coordinator、v1 `audio_chunk` adapter 与 `use-conversation-engine.ts` 均已按 replacement gate 删除；Desktop Web 的 v2 transport 和物理输入/输出图具有独立契约测试。
- Identity、Memory 和 Avatar 尚未进入 Voice Session Runtime 的产品集成；它们将在 Runtime 验收边界稳定后接入，并先于 RTC 产品化。

## 冻结后的交付清单与延期项

1. 交付：将已确认的 correctness/SLO 门禁展开为完整 GPT Voice 行为用例矩阵与自动化报告。
2. 交付：维护逐模块 Legacy replacement matrix，按 M0–M6 证据执行删除。
3. 交付：实现 Voice Session/Engine/Device Runtime Contract Suite、真实场景 E2E 与发布报告。
4. 延期：产品能力完成后的 RTC Adapter、AI Media Gateway 与供应商选型。
5. 延期：Native Realtime Engine 的重启条件、供应商与真实服务验收计划。
6. 延期：移动端、ESP32、Persona/长期 Memory、Avatar、多 Agent 产品能力与多实例热迁移。

## 参考

- [GPT Voice 当前产品对照与目标架构](./GPT-Voice/06-当前产品对照与目标架构.md)
- [GPT Voice 状态机、优化与验收指标](./GPT-Voice/07-状态机、优化与验收指标.md)
- [Realtime Engine 统一接口与插件架构](./GPT-Voice/13-Realtime-Engine统一接口与插件架构.md)
- [ADR-0040：GPT Voice 参考作为行为规范](./adr/0040-single-production-runtime-with-gpt-voice-reference-as-behavior-spec.md)
- [ADR-0063：Stateful Realtime Engine](./adr/0063-stateful-realtime-engine-command-event-contract.md)
