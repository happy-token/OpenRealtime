# 阶段 0：播放能力与回放证据基线

日期：2026-10-06。范围：语音输出 renderer、身份字段、播放时钟、回执来源及现有回放 seam。

本报告初稿来自当前代码的静态审计和已有 WAV 文件头读取；初稿没有运行测试。后续本轮已运行现有mock回归，结果见第7节；没有调用真实模型或连接真实renderer。本报告中的“已接入”表示主运行路径实际调用该实现，不代表已验证实体设备发声、停播或恢复效果。

## 1. 总体结论

当前能力足以支持按回答取消、拒绝迟到音频，以及部分路径的已播放位置记录。尚不足以承诺“当前实际播放句结束后切换纠正回答”，或“误打断后从准确位置恢复旧回答”。这些功能需要补充句段身份、播放证据精度、停止确认及输出版本隔离。

`AvatarAudioSink` 已提供 enqueue、completeGeneration、cancelGeneration、isActive 和可选 playbackPosition，但没有保留当前句、清除未来句、按句停播或恢复接口。`PlaybackOutputController` 当前取消整 generation，并同时取消 browser/avatar 输出；取消后的 generation 拒绝再入队。见 [AvatarAudioSink](../../src/voice/audio/avatar-output.ts#L16)、[PlaybackOutputController](../../src/voice/audio/playback-output-controller.ts#L13)。

## 2. 实际 renderer 能力表

| 路径 | 主入口是否使用 | started / finished 来源 | 位置证据 | 停止、队列、恢复现状 | 安全降级 |
| --- | --- | --- | --- | --- | --- |
| WebAudio PCM | 已接入主语音链 | started 在调用 `source.start(startAt)` 前同步回调；finished 依赖末包 source 的 ended | AudioContext.currentTime 累计安排播放的 PCM 区间；排除区间间网络空隙；每 100 ms 报告 | 整 generation 停止所有安排的 source，清队列，拒绝该 generation 迟到音频；无句级保留或恢复接口 | 使用样本位置与已有文本对齐作段级证据；首播锚点标注为安排播放，不能声称 DAC 发声确认 |
| 浏览器 speechSynthesis | 无服务器 TTS 时的实际备用路径 | SpeechSynthesisUtterance start/end 事件 | 无词级或样本位置回报 | 全局 speechSynthesis.cancel；未接入句级切换或 pause/resume 恢复 | 仅确认完整 utterance，或将部分播放位置标为未知；基于已确认内容重新生成衔接 |
| Anam | 已接入 hosted 主入口 | started 为首次 chunk 后固定 800 ms 定时器；finished 为此延迟加上传 PCM 总时长的定时器 | video.currentTime 减估算 start 锚点，限幅至上传音频总时长 | interruptPersona + endSequence 后立即清本地记录；没有 SDK stopped 确认；没有按句清队列或恢复接口 | 将位置、首播、完成标为估算；不能以定时 finished 证明用户已听完某句 |
| LiveTalking/Wav2Lip 实时 | 已接入实际 segmented runtime | 每 120 ms 轮询服务端 audio_status；playing/completed/cancelled 映射本地回调 | video.currentTime 减收到 playing 状态时的锚点，限幅至上传音频总时长 | 按 generation 请求 interrupt_talk，客户端不等待设备停播确认；服务端可保留较新 generation 队列，无当前句保留界限 | 服务端发送状态与客户端媒体时间均属有边界的估计；先校准语音与媒体时间映射 |
| HeyGen/LiveAvatar | 主入口未接入，配置后使用普通音频；LiveAvatarAudioBridge 代码/单测存在 | 桥中 started 为 repeatAudio 返回后立即回调；ended 依赖外部 handleAvatarSpeechEnded | 桥中仍用 video.currentTime 估算；未保留 repeatAudio 返回的供应商 utterance ID | 整回答缓冲后一次 repeatAudio；全局 interrupt；无按句保留或恢复 | 当前按 WebAudio 实际路径验收，不能列为 LiveAvatar 已验证支持 |
| OpenTalking、动作底片、预制分段视频 | 视觉预览/动作路径，没有独立 AvatarAudioSink；启用实际 segmented runtime 时才进入 LiveTalking 桥 | 预览视频事件不代表语音播放事件；底片循环且静音 | 预览视频 currentTime 不代表 TTS 位置 | 普通语音由 WebAudio 处理 | 听觉指标沿用实际 WebAudio 路径，不以底片完成事件认定语音完成 |

### WebAudio 与浏览器语音

- [BrowserAudioOutput 调度](../../src/voice/audio/browser-output.ts#L159)：started 回调在 source.start 之前，不能等同于最终设备听见声音。AudioContext 挂起、恢复和设备输出缓冲仍可能造成误差。
- [样本位置计算](../../src/voice/audio/browser-output.ts#L289)：累计每个已安排区间实际经过的 AudioContext 时间；不是累计墙钟时间，也不是设备反馈的 DAC 样本计数。
- [取消](../../src/voice/audio/browser-output.ts#L207)：整 generation 取消并停止已安排 source。现有接口不能保留当前句而只取消后续句。
- [主 hook 的进度接入](../../src/hooks/use-voice-session.ts#L478)：每 100 ms 发送 WebAudio V2 播放位置；末包 ended 经 [音频帧回调](../../src/hooks/use-voice-session.ts#L866) 进入 finished。
- [speechSynthesis 备用路径](../../src/hooks/use-voice-session.ts#L1054)：使用 utterance start/end，不报告 charIndex 边界或真实样本位置。

### Anam

- [主入口接入](../../src/components/digital-human/digital-human-stage.tsx#L354)：创建 agent audio input stream 并设置 AvatarAudioSink。
- [固定启动估算](../../src/components/digital-human/anam-audio-bridge.ts#L143)：800 ms 定时器触发 started、建立媒体时钟锚点。
- [完成估算](../../src/components/digital-human/anam-audio-bridge.ts#L80)：首次 chunk 时间 + 800 ms + 所上传音频时长，触发 ended。
- [停止实现](../../src/components/digital-human/anam-audio-bridge.ts#L91)：清本地 generation，再调用 interruptPersona/endSequence。调用返回及本地状态清空，不证明远端缓冲已停止。
- 主入口仅接入 CONNECTION_CLOSED 和 SERVER_WARNING 等 SDK 事件，当前桥未使用供应商的逐语句或设备播放回执。见 [SDK 接入](../../src/components/digital-human/digital-human-stage.tsx#L341)。

### LiveTalking/Wav2Lip

- [主入口接入](../../src/components/digital-human/digital-human-stage.tsx#L215)：WebRTC 接收 session、LiveTalkingAudioBridge 和 AvatarAudioSink 已连接。
- [上传协议](../../src/components/digital-human/livetalking-audio-bridge.ts#L90)：连续 PCM 重采样后上传 generation、sequence、final；此 sequence 是上传包顺序，不是句子身份。
- [状态轮询](../../src/components/digital-human/livetalking-audio-bridge.ts#L116)：playing/completed/cancelled 转成回调。cancelled 也进入通用 onEnded，因此该回调不能独立作为自然完成证据。
- [服务端状态来源](../../server/avatar_compositing/service.py#L87)：started_at 在音频 OutputTrack.recv 返回 frame 给 WebRTC 的阶段设置；末 frame 设置 completed_at。见 [speech_status](../../server/avatar_compositing/service.py#L333)。这证明服务端发送进度，不证明客户端完成抖动缓冲、解码和设备播放。
- [取消](../../src/components/digital-human/livetalking-audio-bridge.ts#L145)：清本地状态后异步请求 interrupt_talk，未等待 stopped 回执。[服务端按 generation 清队列](../../server/avatar_compositing/service.py#L290) 可保留较新 generation，但没有“保留当前实际播放句”的稳定句界。
- [异步失败回放](../../src/components/digital-human/livetalking-audio-bridge.ts#L172)：断开 renderer 后回放缓冲 chunks 到浏览器；它是失败后的整段音频回放 seam，不是精确位置恢复能力。不能据此承诺零重复或零重叠。

### 未接入的 renderer 与视觉预览

- [HeyGen/custom 主入口](../../src/components/digital-human/digital-human-stage.tsx#L294) 明确进入待接入预览，保留普通音频。
- [LiveAvatarAudioBridge](../../src/components/digital-human/liveavatar-audio-bridge.ts#L57) 虽有缓冲、repeatAudio 和 interrupt 实现，但主入口不实例化该桥；供应商返回 utterance ID 未被保存，ended 使用 FIFO active.shift。
- [segmented 预览](../../src/components/digital-human/digital-human-stage.tsx#L155) 与 [动作底片视频](../../src/components/digital-human/digital-human-stage.tsx#L504) 不能替代语音播放真值；视觉配置名称也不能作为 renderer 已接入的证据。

## 3. 身份、句段与时钟链

### 3.1 接口字段存在，不表示所有实际路径已采用

[PlaybackProgressV2](../../src/voice/protocol/v2.ts#L91) 包含 output_epoch、speech_id、generation、phase 和 played_position_samples。WebAudio 实际发送该协议；Avatar 的位置实际发送 [旧版 playback_progress](../../src/hooks/use-voice-session.ts#L1001)，仅含 generation、finished、played_audio_end_us，没有 output_epoch 或 speech_id。

因此不能将 V2 接口存在解释为所有 renderer 已具备同等身份隔离或样本精度。Avatar 停止时也可能同时发送旧版位置与浏览器 V2 返回值，需要按实际 renderer 和证据来源解读。见 [取消回执发送](../../src/hooks/use-voice-session.ts#L935)。

### 3.2 speech_id 不等于 sentence_id

[音频帧](../../src/lib/frames.ts#L131) 有 generation、可选 speech_id、音频 sequence 和 is_final；[文本对齐帧](../../src/lib/frames.ts#L115) 有 speech_id、音频起止时间和累计文本。当前未提供稳定 sentence_id、句段完成事件或 reply_version。

音频 sequence、上传 sequence、标点位置均不能直接冒充稳定句子 ID。一次回答可以包含多句话，同一句话也可跨多个 TTS/audio 包。播放纠正需要区分正在播放的句段、已确认完成的句段、未来已排队音频与尚未生成的文本。

### 3.3 output_epoch 尚未成为服务端隔离屏障

前端收到 session_ack 后 [创建随机 output epoch](../../src/hooks/use-voice-session.ts#L628)。服务端 [V2 接收分支](../../server/realtime/transport/websocket.py#L571) 校验 generation/speech_id，output_epoch 只进入命令幂等键，没有检查它是否等于活动输出 epoch。

[恢复 hello 的 playback](../../src/voice/protocol/v2.ts#L100) 仅含 generation 与 played_position_samples，没有 speech_id/output_epoch。controller 提供 observePlayback，但主 hook 的持续位置发送未同步调用它；[snapshot 应用路径](../../src/voice/session/controller.ts#L105) 才会更新其保存位置。不能声称 hello 必然携带最新本地播放位置。

下一阶段应明确哪些字段隔离跨 session、重连、renderer 切换、reply 修订和 stop/handoff 操作。当前代码尚未具备这些全部契约。

### 3.4 媒体时间估算与实际设备时间不同

[AvatarPlaybackClock](../../src/voice/audio/avatar-playback-clock.ts#L28) 使用 video.currentTime 与启动锚点之差，限幅至上传 PCM 时长，并在 paused/readyState 不足时冻结。它没有映射 idle frame、句间静音、远端音频缓冲或网络 gap 的独立证据；Anam 定时锚点和 LiveTalking 轮询锚点还带入额外误差。

[输入 V2](../../src/voice/protocol/v2.ts#L39) 虽有 input_epoch、timeline_origin_ms、start_sample，但当前整体响应/打断延迟依然按 [服务器 VAD 到收到播放回执](../../server/realtime/observability.py#L214) 计算，包含回传网络，且标记 estimated。不能把该值标为客户端同一时钟的精确物理发声/停声延迟。

### 3.5 服务端取消完成不等于实际 stopped

当前 [engine 的 assistant_yielded](../../server/realtime/cascaded/engine.py#L1714) 在服务端响应取消分支执行后发送，并不等待客户端 stopped 回执。它可以确认服务端让出控制权，不能确认旧音频已从 WebAudio、SDK、远端缓冲和实体设备中停止。

此事实适用于“误打断后恢复”和“纠正回答接替旧回答”：仅凭服务端取消完成启动新声音，不能证明旧新声音无重叠。

## 4. 可复用回放输入和测试 seam

### 4.1 已有 WAV 候选

以下文件均位于 `tmp/voice-runtime-campaign/`，文件头读取确认：单声道、16 kHz、PCM16。它们没有本次验证过的文本、停说时刻、语义标签或预期动作 manifest。

| 文件 | 时长 | 可复用价值 | 当前证据限制 |
| --- | --- | --- | --- |
| chrome-microphone-turn.wav | 34.593 s | 长一些的固定麦克风输入 | 无有效逐句标注，不能据文件名推定语义 |
| chrome-microphone-short-turn.wav | 14.981 s | 固定短轮次输入 | 无经验证 oracle |
| chrome-microphone-short-turn-long-silence.wav | 74.981 s | 固定输入和较长静音窗口 | 无经验证停说采样边界和预期判定 |
| chrome-microphone-nihao.wav | 61.775 s | 已有固定麦克风素材 | 不能因文件名而断言完整内容仅为“你好” |

复用前需要补充：sample ID、内容 hash、格式、来源、标注版本、文本、语音区间、重要补充/附和/噪声/显式停止标签、预期动作和可容忍边界误差。未标注文件只能做输入稳定性 smoke，不应作为正确性或误判率的分母。

### 4.2 无模型测试 seam

- [WebAudio fakeContext](../../src/voice/audio/browser-output.test.ts#L6)：注入 createContext，控制 currentTime，手动触发 source ended，可检查安排队列、取消、迟到音频与位置。已有 [网络 gap 位置测试](../../src/voice/audio/browser-output.test.ts#L221) 可复用。
- [Avatar 媒体时钟测试](../../src/voice/audio/avatar-playback-clock.test.ts#L5)：直接推进 currentTime、paused、readyState；可检查估算冻结，但不能证明供应商流与 PCM 的真实对齐。
- [Anam fake session/input 和 fake timers](../../src/components/digital-human/anam-audio-bridge.test.tsx#L23)：验证固定 800 ms 估算、完成时钟及取消清理。
- [LiveTalking 注入 fetcher](../../src/components/digital-human/livetalking-audio-bridge.test.tsx#L184)：驱动 buffering→playing→completed/cancelled、失败和延迟；无需调用真实 renderer。
- [LiveAvatar 桥单测](../../src/components/digital-human/liveavatar-audio-bridge.test.tsx#L22)：用于代码接口验证，不能证明主入口已接入。
- [Chrome 文件麦克风配置](../../playwright.config.ts#L8)：通过 VOICEAGENT_E2E_AUDIO_FILE 和 use-file-for-fake-audio-capture 注入固定 WAV。现有 [live 用例](../../tests-e2e/voice-runtime-live.spec.ts#L8) 依赖真实 runtime；离线实验应借该 seam 配固定 ASR/分类/LLM/TTS stub，而不是直接运行 live 用例后称无模型回放。
- [record_avatar_realtime.py](../../scripts/record_avatar_realtime.py#L61)：有按 chunk_ms 拆 WAV、按音频时长 pace 推送、指定时间 interrupt 的 seam。该脚本实际连接 renderer，本阶段未运行；可复用拆包/时间表逻辑生成离线 fixture。

## 5. 下一阶段最小协议缺口

以下为待设计/实现项，不代表已经支持。

1. **句段和输出版本身份。** 为可播放语句提供稳定 sentence/segment ID，并关联 reply version、speech ID、generation、output epoch；明确 TTS 包 sequence 与句段身份的差别。允许在同一句跨包时可靠识别句尾。
2. **播放证据等级。** 每种 renderer 显式声明位置精度与回执来源，例如音频样本时钟、段级确认、媒体时间估算、定时估算、未知。估算 finished 不能被提升为已确认整句完成。
3. **停止确认。** 区分 stop requested、server cancellation completed、renderer/local queue stopped、client stop observed；定义操作 ID、deadline、重复/迟到处理及缺失回执的安全退出。
4. **切换屏障。** 为“保留正在播放句、清除未来队列、切换到纠正回答”定义请求和确认。renderer 不支持选择性清队列时必须显式降级，不能把整 generation cancel 伪装为按句切换。
5. **跨 epoch/version 隔离。** 服务端验证活动输出 epoch；拒绝旧停止/完成回执污染新回复。恢复 hello 应携带可解释的 renderer、speech/version 身份和最新已确认位置，避免只凭 generation 重建真值。
6. **已听上下文与恢复。** 保存最后确认完成的句段及对应音频/文本；位置未知时从确认的已听内容重新生成衔接。没有缓冲音频或供应商恢复 API 时不承诺原音频位置恢复。
7. **最低回归矩阵。** 停止回执缺失/重复/迟到，旧 generation cancel 到达新 generation 播放期间，renderer 切换/断连，末包 completed 与 stopped 竞争，估算时钟遭遇停顿，以及旧新输出不重叠。

优先复用现有输出运行时、PlaybackOutputController、文本对齐与交付记录，先补必要字段和事件，不为每个供应商新建一套独立状态决策系统。

## 6. 安全降级与本阶段边界

- **无法确认当前句界：** 不承诺等待实际当前句结束；对重要纠正执行整回答停止，等待可信停止条件，依据最后确认已听内容重新生成。一般补充可先保留输入，但必须设定有界退出，不得静默丢失。
- **只有估算播放位置：** 记录估算及来源；不将未确认部分写入“用户已听到”的模型历史。恢复允许轻微重复的条件应明确，不能编造已播放文本。
- **物理 stopped 不可确认：** 禁止以服务端取消完成作为无重叠播放证明；应使用有界等待、媒体输出断开/关闭或其它实际可验证的停播措施。可靠条件仍不存在时进入恢复失败/明确降级，不以超时等同 stopped。
- **供应商恢复接口缺失：** 重新生成衔接，不尝试重放已取消 generation；避免迟到音频重新入队。
- **仅接口/代码存在：** 标记未接入或未实测，不显示为生产支持。HeyGen/LiveAvatar 本阶段沿实际普通音频路径评估。
- **样本未标注：** 仅作 smoke；不输出误判率、准确率或因果性能结论。

本阶段交付是能力边界、证据精度和后续协议前置条件。句尾纠正切换、误打断精确恢复、所有 renderer 的物理停播确认仍待实现和验证。

## 7. 本轮无模型基线执行

2026-10-06运行现有WebAudio、PlaybackOutputController、AvatarPlaybackClock、Anam、LiveTalking、LiveAvatar六个测试文件，共31 passed。注入故障用例按预期产生LiveTalking失败日志并验证fallback；无真实renderer连接。

该结果证明现有测试seam可执行、既有取消/迟到音频/媒体估算契约通过，不提升本报告能力等级：定时结束仍是估算，LiveAvatar仍未接入主入口，句级保留与物理stopped仍未支持。固定ASR事件回放及运行时实施记录见[实施报告](2026-10-06-parallel-hardening-implementation.md)。
