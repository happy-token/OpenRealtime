# 播放期字幕同步、日志系统与乱码修复方案

日期：2026-10-02。状态：方案已通过 grilling 会话确认，待实现。

本文是 [VOICE-PLAYBACK-TURN-REQUIREMENTS.md](VOICE-PLAYBACK-TURN-REQUIREMENTS.md) 风险修复的具体设计方案，由一次结构化访谈（/grilling）产出。背景、Case A/B/C 的轮次竞态需求见该文；本文只覆盖这次访谈确认要修的四项，以及明确排除在外的项。

## 范围边界

**这次要修的：**
1. 字幕显示整段而非实时同步的根因修复（Doubao TTS2.0 协议参数误用）
2. 日志系统补齐（文件落盘 + 关联 ID），支撑后续排障
3. 后端日志乱码诊断与防御
4. `voice_session_failed` 无条件覆盖已显示文本的小修复

**明确排除、留给后续独立任务：**
- 输出侧（服务端→客户端 TTS 音频）背压水位机制——当前只有输入侧（麦克风采集）实现了 `queue_high_watermark`/`queue_low_watermark`/`buffered_duration_ms`（`server/voice_session/protocol.py`），输出侧完全没有对应逻辑。这是真实存在的不对称缺口，但涉及服务端合成调度和客户端上报协议的改动，工作量和设计决策都独立于本次主题，值得单开一轮 grilling。
- 验收场景 4/5/7/9/12（`VOICE-PLAYBACK-TURN-REQUIREMENTS.md` 验收场景一节）当前无自动化测试覆盖——这些覆盖的是 Case A/B/C 的轮次竞态逻辑，不在本次改动的代码路径上，混进来会让改动失焦。
- 误打断率测试、正式的追加/修订/替换/独立/停止关系分类器（当前仍是时间窗启发式）、WebRTC 传输适配器、真正的播放中途暂停/恢复命令——文档本身已标注为"后续需求"，本次不动。

## 一、字幕同步根因与修复

### 根因

当前实现（`server/speech/plugins/doubao_tts_direct.py`）请求 `enable_timestamp: true`，依赖 `TTSSentenceEnd`（事件 351）附带的 `words` 数组做词级对齐。

火山引擎官方文档明确：**`enable_timestamp` 只在 TTS1.0/ICL1.0 生效**。当前代码 `DEFAULT_RESOURCE_ID = "seed-tts-2.0"`（`doubao_tts_direct.py:48`）用的是 TTS2.0——这个参数对服务端完全无效，`words` 永远不会被填充。这不是解析 bug，是协议版本与参数不匹配，且这个不匹配从代码第一次提交时就存在，没有任何 ADR 或讨论记录发现过。

降级路径：`_alignment_chunks`（`doubao_tts_direct.py:174-205`）在 `words` 为空时退化为"整句一个 chunk，起止时间为 None"→ `websocket.py:246-247` 整句 `audio_start_us` 退到 0 →客户端 `playback-text.ts` 的可见性判断 `position_us >= audio_start_us + 20ms` → 整句话播放开始 20ms 左右就全部显示。这正是用户实测到的"显示的是 TTS 整段文本，不是跟音频实时显示"。

TTS2.0/ICL2.0 的字幕机制是另一套：
- 请求参数是 `enable_subtitle`（在 `audio_params` 下），不是 `enable_timestamp`
- 触发全新事件 `TTSSubtitle`，当前代码的 `_EVENT_*` 常量表（350/351/352，以及一个来源不明的 `364`）里没有正式定义这个事件
- 字幕**基于原文打轴**（TTS1.0 是基于 tn/文本规范化后的 token），`words[].word` 直接是原文片段，不需要额外做 tn→原文映射
- 字幕返回**非阻塞**：合成进度不被字幕识别阻塞，可能某句的字幕在更晚的音频帧已经发出之后才到达——这与 TTS1.0"一句的时间戳返回之后才返回下一句音频"的阻塞语义不同
- 整次合成只返回一次 `TTSSentenceStart`/`TTSSentenceEnd`（不论有多少子句），字幕通过多次独立的 `TTSSubtitle` 事件补上——`_alignment_chunks` 当前挂在 `_EVENT_TTS_SENTENCE_END` 上触发解析的结构性假设在 2.0 下不成立

### 关于 `364`

代码里 `event in {_EVENT_TTS_SENTENCE_END, 364}`（`doubao_tts_direct.py:535,605`）把 364 当作 351 的等价事件处理，但没有任何注释或 git 历史说明这个数字的来源。查了协议本身来源的开源参考实现（TEN-framework 的 `bytedance_tts_duplex`）确认：该参考实现的事件表与官方文档完全一致（仅 350/351/352），**不包含** 364 或任何字幕专属事件；它默认使用 `resource_id = volc.service_type.10029` + `moon_bigtts` 音色族系（对应 TTS1.0 路径），而当前 OpenRealtime 用的是 `seed-tts-2.0` + `uranus_bigtts`/`saturn_` 音色族系——两套命名体系不同，无法直接类比验证。`364` 的真实来源无法仅靠静态分析确认。

### 决策（见 [ADR-0132](adr/0132-doubao-tts-subtitle-not-timestamp-for-seed-tts-2-0.md)）

- 保留 `seed-tts-2.0`（音色列表已在使用，切回 1.0 需要重新验证音色兼容性，未独立核实，视为工作假设而非确认事实）
- 把 364 当作"大概率是 `TTSSubtitle`"直接写进处理逻辑，同时加诊断日志交叉验证——不等真实数据回来再动手，但日志能立刻暴露猜测是否成立
- 不改用 `seed-tts-1.0`：那条路径虽然"已验证可行"，但 1.0 的 `words` 是 tn（文本规范化）形式而非原文字面，当前代码从未处理这层映射，本质是把一个未知问题换成另一个已知但同样没做的问题

### 实现要点

1. 请求参数新增 `enable_subtitle: true`（`audio_params` 下），与现有 `enable_timestamp: true` 并存（保留给 TTS1.0 场景，若未来切换 resource_id 不必再改请求构造）
2. 新增事件常量 `_EVENT_TTS_SUBTITLE`，暂定映射到 `364`，并保留对未知事件号的诊断日志（见下）
3. `TTSSubtitle` 的处理与 `TTSSentenceEnd` 解耦为独立分支：按原文直接打轴（不做 tn 映射），按非阻塞到达处理（允许字幕滞后于已发出的音频帧，`PlaybackTextTimeline` 现有的"迟到对齐追上播放位置"机制已经支持这个语义，不需要新协议字段）
4. 核实后发现：`words` 缺失时的整句兜底实际已经正确实现，不需要新代码。`_alignment_chunks` 的最后一个分支（`doubao_tts_direct.py:202-205`）在没有词级数据时，产出一个 `spoken_start_us`/`spoken_end_us` 均为 `None` 的整句 chunk；`tts.py:_emit_audio`（361-376 行）处理这种 chunk 时，仍按整句文本做一次性匹配，`audio_end_us` 取当前累计音频字节位置换算出的真实时长（`timestamp_us`），不是按字数比例臆测——这正是文档要求的"以真实累计音频时长提供整段显示，不按字数估算词速"。所以这个兜底路径本身是对的，问题只在于：由于 `enable_timestamp` 对 2.0 版本从未生效，这个本该是"罕见兜底"的路径变成了"每次都走"的常态路径。修复 `TTSSubtitle` 接线后，词级数据能真正到达，这个兜底自然回归到真正的兜底角色，不需要额外改动。`PlaybackPrecision` 枚举是 `ReportPlaybackProgress`（客户端→服务端回报播放进度）专用的概念，和这里的文本对齐帧（服务端→客户端）是两个不同方向、不同目的的字段，不应该混用——之前设计稿里"复用 `ESTIMATED` 枚举"这个说法不准确，予以纠正，避免凭空给对齐帧新增一个和现有用法不一致的字段
5. 诊断日志：在收到任何未被已知事件常量覆盖的 `event` 数值时记录原始数字 + payload 的 top-level key 列表（不记录文本内容本身，避免和日志系统的敏感信息策略冲突）；在 `_alignment_chunks` 内记录每次解析成功/退化为估算的分支选择

## 二、日志系统补齐

### 现状缺口

当前日志配置只在 `server/cli/harness.py:203-213` 做了一次 `logging.basicConfig`，输出到 stderr：
- 没有文件落盘，没有轮转——终端关闭或崩溃后，当次会话的日志完全丢失（这也是本次字幕 bug 排查一度卡住、需要去翻 VoiceLoop 参考实现而非直接看日志的原因）
- 没有关联 ID——日志记录不会自动带上 `voice_session_id`/`generation`，排查某次会话的问题只能在混杂的全局日志里肉眼搜字符串
- 日志级别硬编码（dev=DEBUG，其他=INFO），不能按模块单独调整

### 方案

- 用标准库 `logging.handlers.RotatingFileHandler`：单文件上限 20MB，保留 5 份滚动备份
- 用 `contextvars` 在进入每个语音会话的处理协程时设置 `voice_session_id`/`generation`，配合一个 `logging.Filter` 自动把这两个值注入每条日志记录（不需要每条 `logger.info(...)` 调用手动传参）
- 保持现有的人类可读文本格式（`harness.py` 的 `_DEFAULT_LOG_FORMAT`），不切换为 JSON——这次诉求是"方便排查"，不是"接入日志平台"，JSON 结构化是更大的独立决策，不夹带在这次修复里
- `websockets.client/server`、`boto3/botocore` 的 INFO 级别钳制（避免泄露 ASR/TTS 凭据和签名 URL）保持不变，这是有意为之，不是缺口

## 三、乱码诊断与防御

### 现状

三处用 `errors="replace"` 解码火山引擎二进制协议按 `size` 字段切出的字节片段：`doubao_tts_direct.py:151,158`、`doubao_asr.py:86`（`code`/`session_id`/错误 `message` 字段）。最可能的机制：服务端返回帧的压缩标志与客户端请求时声明的不一致（代码只验证了"我们请求时没开压缩"，从未验证"对方确实按无压缩格式回复"），导致切片边界落在 UTF-8 字符中间，`errors="replace"` 静默把损坏字节换成 `�` 而不报错——这与"大量乱码但服务不崩溃"的现象吻合，但未经真实抓包确认。

已排除的候选：Doubao 二进制帧的 gzip/压缩标志处理本身内部一致（编码器声明无压缩，解码器也不尝试解压，不是字节偏移错位）；本机 macOS 环境无 locale/终端编码问题；没有发现把 `bytes` 对象直接做字符串格式化打日志的情况（不是"看起来像乱码但其实只是 bytes repr"这种假阳性）。

### 方案（分两步，不同时做）

1. **先加诊断**：在三处 `errors="replace"` 解码触发时，记录原始帧的压缩标志位数值和声明长度字段，积累一段真实运行样本
2. **坐实根因后再加防御**：校验服务端返回帧的压缩标志是否与请求一致，不一致时拒绝解码并记录告警，而不是继续静默 replace

直接把 `errors="replace"` 换成别的处理方式而不先确认根因，可能把真正的异常掩盖成另一种静默失败——这正是字幕 bug 已经踩过的坑，不重复。

## 四、`voice_session_failed` 覆盖已显示文本

### 现状

`use-voice-session.ts:666-667` 收到 `voice_session_failed` 帧时无条件执行 `setCaption(frame.safe_message)`，把屏幕上已经显示的 ASR 识别文本或助手部分回复文本直接覆盖成通用错误文案（额度不足/鉴权失败/限流/供应商不可用之一，来自 `server/voice_session/speech_failure.py`）。`session_disposition === "close"` 紧接着把 `connection` 置为 `"error"`，触发 `SessionRecoveryNotice` 显示"连接未恢复"。

用户实测复现：说话后先看到识别文本正常显示，随后被"连接未恢复"吞掉——助手侧没有机会生成任何回复，服务端在某个能力（ASR/Brain/TTS）失败后直接关闭会话。

### 修复

只在当前没有任何已显示的助手/用户文本时才用 `safe_message` 覆盖 `caption`；否则保留已显示内容不动，`safe_message` 仍然写入 `sessionError`（已有的独立字段）。`SessionRecoveryNotice` 本来就读 `sessionError`/`connection` 展示错误横幅，不依赖 `caption`，所以这个修复不影响错误提示本身的可见性，只是不再抹掉用户已经看到的识别文本。

这个修复点小、独立于前三项，不需要等日志系统或协议问题解决就能验证。

**实现**：`use-voice-session.ts` 的 `voice_session_failed` 分支改用 `setCaption((current) => current || frame.safe_message)`——React 状态更新函数的函数式写法读取的是真正最新的 state，不会有闭包捕获旧值的问题，不需要额外引入 ref。

**测试缺口（如实记录，不假装已覆盖）**：`handleFrame` 是 `use-voice-session.ts` 内部 `useEffect` 闭包里的私有函数，不是导出的纯函数；现有 `use-voice-session.test.ts` 只测试文件导出的纯函数（`mergeAssistantTranscript`/`updateAssistantCaption` 等），项目里也没有 `renderHook` 渲染整个 hook 来测 WebSocket 消息处理的先例。为这一个小改动引入这类集成测试基础设施，改动面和工作量都超出这次任务比例，故未补充自动化测试，留给手动验收（见"验收方式"一节）。

## 实现后用真实请求验证发现的问题（2026-10-02）

实现完成后，直接用真实 `DOUBAO_API_KEY` 跑了一次 `DoubaoDirectTtsEngine.synthesize_stream`（绕过完整浏览器会话，直连验证这一层），而不是等用户复现后才排查。真实数据证实：

- `364` 确实是 `TTSSubtitle`，`enable_subtitle` 生效，拿到了 23 个真实词级时间戳
- 但同时暴露了修复本身引入的新 bug：`TTSSentenceEnd`（351）总是先到达且 `words` 总是空的，真正的词级数据由随后的 `TTSSubtitle`（364）单独送达。`_alignment_chunks` 当时在 `words` 为空时会立即吐出一条整句兜底 chunk——这个决定本不该由它做，因为这条兜底在 364 的真实数据到达*之前*就抢先执行了。客户端 `PlaybackTextTimeline` 取"已到达可见位置的 cue 中文本最长的一条"，整句兜底 cue 几乎立即可见且文本最长，于是视觉上把随后到达的真实逐词字幕全部盖掉——这正是用户复现的"TTS文本跟音频不是同步出现的"（文本先于对应音频出现）

**修复**：把整句兜底逻辑完全从 `_alignment_chunks` 中移除——它现在只在真有逐词数据时才产出，没有数据时只记录日志，不再猜测。"整个回复都没有任何词级数据"这种情况的兜底，继续交给已经存在、时机正确的 `ResponseCompleted` 路径（`websocket.py:273-282`，只在确认整个回复结束后才触发，不会抢跑）。修复后重新用真实请求验证：23 条真实逐词数据，时间戳连续递增，不再出现抢跑的整句 chunk。

这一条印证了 grilling 过程本身的教训：协议参数（`enable_subtitle`/364 事件号）判断是对的，但消费侧的时序假设（"收到事件就该决定是否兜底"）没有一起核实，只有拿真实数据跑一次才能看出来。

## 关键纠正：线上实际用的是 Bailian，不是 Doubao（2026-10-02）

上面整段 Doubao TTS2.0 分析——协议文档、ADR-0132、`enable_subtitle`/`TTSSubtitle`(364) 的事件接线和真实验证——全部成立，但针对的是一个**当前环境实际没有在用**的引擎。本机 `.env` 配置了 `VOICEAGENT_TTS_BACKEND=bailian`，`demos/voice_web_server.py:_build_tts_engine()` 据此选择了 `BailianTtsEngine`（阿里云百炼 CosyVoice），完全绕开了 `DoubaoDirectTtsEngine`。这是本次排查中我犯的一个本可以更早避免的错误：一开始就该先确认当前环境实际配置的后端是哪个，而不是从文档里提到的"Doubao TTS 流式协议"链接直接假设是 Doubao。

**排查过程**：用真实请求跑完整 WS v2 会话后发现只收到一条整句 `assistant_text_alignment`（走 `ResponseCompleted` 兜底）；而 Doubao 直连探针明明验证过逐词数据正常。交叉检查发现 `doubao_tts_direct` 这个 logger 在真实会话的日志里完全没有任何记录——证明 TTS 请求根本没有经过这个模块。追到 `VOICEAGENT_TTS_BACKEND=bailian` 才找到真正原因。

**Bailian CosyVoice 的真实协议**（官方文档 help.aliyun.com/zh/model-studio/cosyvoice-client-events 和 cosyvoice-server-events 原文确认）：
- 请求参数需要显式开启 `word_timestamp_enabled: true`（默认 `false`，仅流式模式下可用，仅部分模型/音色支持：`cosyvoice-v3.5-plus`、`v3.5-flash`、`v3-flash`、`v3-plus`、`v2` 的复刻音色及部分系统音色——当前配置的 `cosyvoice-v3-flash` 在支持范围内）
- 词级时间戳在 `result-generated` 事件的 `payload.output.sentence.words` 数组里，仅当 `payload.output.type === "sentence-end"` 时才有效数据；`sentence-begin`/`sentence-synthesis` 阶段 `words` 恒为空
- `words[].text` 直接是原文字面（不是 tn 规范化形式），`begin_time`/`end_time` 单位是毫秒
- 对不支持的音色请求这个参数是**静默无效**（返回空 `words` 数组），不是报错——所以绝不能假设"参数发了就一定有数据"

**修复**（`server/speech/plugins/bailian_tts.py`）：
1. 请求参数加 `word_timestamp_enabled: true`
2. `_parse_event` 从只返回事件名改为返回 `(event, message)` 元组，不再丢弃消息体
3. 新增 `_alignment_chunks` 纯函数，只在 `result-generated`/`sentence-end` 且 `words` 非空时产出真实对齐数据；`words` 为空时只记录诊断日志，不猜测、不吐出整句兜底——这个决定权同样完全交给上一层已存在的 `ResponseCompleted` 路径，和 Doubao 修复用的是同一个架构原则
4. `_stream_task`/`_run_duplex_task`（真实对话走的是后者）两个事件分发点都接上 `result-generated` 分支

**真实验证**：直连 `BailianTtsEngine.synthesize_duplex` 产出 25 个真实逐字时间戳；完整端到端 WS v2 会话验证收到多条逐步累积的 `assistant_text_alignment` 帧（"你"→"你好"→"你好，"→……），不再是单条整句帧。日志关联也在同一次真实会话里确认生效（`session=<真实session_id>`）。

## 第三次纠正：用时间比例取代文字比对（2026-10-02）

真实使用中又发现一个现象：字幕"一开始对齐，后面渐渐就不出字，最后一下子蹦出所有文字"。用含数字/英文的句子直接探测两个供应商后确认：**供应商返回的"这个词"本身是朗读形式，不是原文字面**——"123"会被读成"一百二十三"返回，"Hello World"中间的空格会被吞掉变成"HelloWorld"，货币符号会被展开读音。而原来的对齐逻辑（`server/realtime/capabilities/tts.py` 的 `_emit_audio`）是拿供应商返回的词字面去匹配原文字面，一旦某个词因为朗读规范化而和原文不同，匹配从那一刻起永久失败——字幕从此卡死，直到播放结束才被整段兜底逻辑一次性放出全文。

一开始考虑过直接显示供应商朗读出来的文字（跳过比对问题），但代码里 `server/realtime/speech/delivery.py:55` 有一条硬性约束："已交付给听众的文本必须是模型原文的前缀"，这是为了保证用户打断后，模型的后续上下文只收窄到真正播出去的那部分原文，不能被污染成朗读形式的文字。所以显示的内容必须始终锚定在原文上，不能直接用供应商的朗读文字。

**最终方案**：两个供应商在"句子结束"事件里，都额外带着一个**句级原文字段**（Doubao 的 `text`、Bailian 的 `original_text`），经真实请求验证这两个字段永远和模型原文完全一致，不会被规范化。于是改成：不比较"这个词写的是什么字"，而是用"这个词的真实结束时间 ÷ 这句话总时长"算出一个播放进度比例，再按这个比例从**句级原文**里换算出对应的截止位置。这样显示的内容始终是原文的一部分，不依赖供应商返回的词字面是否和原文相同，详见 [ADR-0134](adr/0134-time-ratio-caption-alignment-instead-of-text-matching.md)。

**真实验证**：用同时包含"Hello World"（英文空格会被吞）和"第1句有数字123"（数字会被读成中文）的句子，通过真实的生产引擎（本机实际配置的 Bailian）跑一次完整对话——字幕从头到尾持续推进，没有在这两个历史上会卡死的位置停住，播放结束前没有出现整段突然跳出的情况。

## 验收方式

- 字幕同步：真实对话一次，确认诊断日志里出现的事件号与假设的 `TTSSubtitle`/364 是否吻合；字幕应随音频播放逐步显示而非整段跳出
- 日志：杀掉/重启服务进程后，确认日志文件仍保留最近记录；同一会话的多条日志能通过 `voice_session_id` 过滤出来
- 乱码：观察一段时间后，诊断日志中压缩标志位的分布，确认是否存在非预期的压缩标志值
- 覆盖修复：模拟一次助手已输出部分文本后服务端失败关闭的场景，确认字幕保留原文本，错误提示仍正常弹出
