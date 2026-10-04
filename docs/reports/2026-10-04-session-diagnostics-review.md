# Session 日志与交互延迟审查及设计

日期：2026-10-04。范围：主侧边栏、/admin、决策日志、后台诊断接口、Realtime 事件观测、PostgreSQL 日志存储。

## 已修复的入口问题

管理员应用账号登录后，仅设置侧边栏显示「数据日志后台」，点击 /admin 直接进入。
后台统一使用应用账号 session 和 app_admin_accounts 权限，不再显示独立管理员密码登录表单。
总览、单会话详情、决策日志和管理员账号管理使用相同权限边界。普通账号访问显示权限提示，未登录访问使用应用的登录入口。
后台仅提供返回应用入口，账号退出统一在应用账户菜单完成。

## 审查结论

现有系统有可复用的基础：PostgreSQL telemetry、独立的 debug log、对话 journal、ASR/LLM/TTS 计时、客户端播放回执、Session ID 查询和指标聚合。
但尚不能承诺「给 Agent 一个 Session ID，就能完整排查」。下述缺口需要继续实现，本文定义的接口及指标均为设计，尚未上线。

| 优先级 | 缺口与证据 | 影响与修复方向 |
|---|---|---|
| P1 | `server/realtime/observability.py` 把 `SpeechPlaybackProgress.completed == false` 当作停播；`transport/websocket.py` 对 started/progress/stopped 都可能产生 completed=false；事件类型没有 stopped 字段 | 普通进度可能被当成确认停播。必须透传 phase 和 interruption_id，仅明确 stopped 回执关闭对应打断测量 |
| P1 | 同名 `turn.endpoint_to_client_playback` 在 `telemetry.py` 使用 endpoint_candidate 锚点，`realtime/observability.py` 使用 InputTranscriptCompleted 观测时间 | 不同执行路径的样本口径不一致，不能混算百分位。统一指标定义，记录 schema_version 和测量来源 |
| P1 | `barge_in.time_to_client_stop` 从 barge_in_confirmed / AssistantYieldRequested 开始 | 没有包含用户开始打断后的检测和语义判定时间；现有指标只能描述确认打断后的执行部分 |
| P1 | session detail、debug-log、conversation 是独立接口；debug log 上限 2000，telemetry detail 上限 5000，缺少分页与截断标识 | Agent 可能拿到早期片段却误以为日志完整。增加统一诊断接口、游标、采集完整性与截断元数据 |
| P2 | 决策日志页只加载最近 24 小时的 100 个 Session，没有输入 Session ID 的入口；timeline 最多取 500 条；日志和指标通过 Promise.all 加载 | 已知 Session ID 可能找不到；单个数据源失败会遮蔽另一个。增加直接查询、刷新、分页和各数据源独立错误展示 |
| P2 | `admin-diagnostics.ts` 以候选指标替代阶段指标，例如 ASR 尾包可退化为首 partial，TTS 首音可退化为连接耗时 | 展示标题与实际含义不符。缺少对应样本时显示未采集，不能用不同定义的指标补空 |
| P2 | 日志查询主要依赖浏览器管理员 cookie | Agent 缺少正式机器访问方式。提供受限制的只读凭据，明确授权范围、过期、审计和敏感字段处理 |

## 统一的 Agent 诊断接口

拟新增 `GET /api/observability/sessions/{session_id}/diagnostics`。
浏览器继续使用管理员会话；Agent 使用只读诊断凭据。Session ID 是查找键，不是访问凭据。机器接口应具有明确权限边界，并复用同一查询服务。

返回版本化 JSON，包括：

- session：Session ID、运行实例、引擎/供应商、开始结束时间、断连/恢复记录、有效配置版本、关联 thread_id。
- turns：每轮 turn_id、generation、response_id、状态、关键里程碑及延迟。
- interruptions：每次 interruption_id、被打断的 speech_id/output_epoch、判定、执行、停播回执及缺失信息。
- timeline：决策事件、telemetry、错误、取消与重连，保留原始事件身份、来源和因果关联。
- conversation：按授权范围提供对话文本；内容与凭据分开处理，错误信息和配置快照必须脱敏。
- completeness：各数据源 available/unavailable、采集起止、writer 丢弃计数、待写状态、truncated、next_cursor、协议版本、缺失里程碑。

每个数据源独立报告可用性：日志不可用时仍返回指标，并明确部分结果。所有数据源均无记录时返回 404；授权失败与基础设施故障分别返回 401/403 和 503。
分页使用稳定游标及查询快照，不以 debug log 的 sequence 作为全局唯一排序键：多个绑定/恢复可能产生相同序号。排序保留 event_id、实例 ID、来源序号和因果关系。
Agent 工具可封装为 `get_session_diagnostics(session_id, cursor)`。输出事实、缺失信息和可定位的事件 ID，原因推断须与事实分开。

## 用户说完后的响应延迟

主指标定义为「用户最后一个有效语音采样 → 客户端实际开始播放回复」。VAD 宣告结束时间晚于最后语音采样，必须单独记录，不能把 VAD 等待隐藏掉。

建议里程碑：

1. speech_end：输入音频采样轴上的最后有效语音采样，附 VAD 版本、置信度及时间精度。
2. vad_end_detected：VAD 检测/上报结束。
3. asr_final：最终识别文本可用。
4. endpoint_committed：语义完整度判定完成，提交用户轮次。
5. model_request / first_text：模型请求与首段可用文本。
6. tts_input / first_audio：合成首文本与首音频。
7. audio_sent / audio_received：服务端发包和客户端收包。
8. playback_started：客户端音频调度到实际播放的起点。

展示三个不同的总量：speech_end→playback_started（用户体验）、endpoint_committed→playback_started（响应执行）、speech_end→first_audio_sent（服务端可观测近似）。不具备客户端回执时，用户体验总量标记缺失。
模块统计覆盖 VAD 等待、ASR 首文本/尾部、语义判定、知识检索/记忆/工具、模型首文本和完成、TTS 建连/首音、下行与播放缓冲。分阶段保留请求开始结束和错误/超时状态。
预取、流式模型与 TTS 可并行，模块耗时不能直接求和得到端到端耗时；用每轮瀑布图呈现重叠。

## 打断延迟设计

主指标定义为「用户开始有效打断语音 → 客户端旧输出实际停止」。对 backchannel/ignore 不计为有效打断，但记录判定结果，支持复核误打断和漏打断。

每次候选打断分配 interruption_id，贯穿检测、语义判定、取消发送及客户端回执，并绑定旧输出 generation、speech_id、output_epoch。不能仅用 generation 配对：取消和新轮次可能导致 generation 推进。

| 里程碑 | 含义 |
|---|---|
| interruption_speech_started | 客户端输入采样轴上的打断起点 |
| server_overlap_detected | 服务端观测到用户与助手重叠 |
| interruption_confirmed | 规则/语义判定为有效打断，记录标签、来源、置信度及等待时间 |
| cancellation_sent | 取消旧输出命令发出；模型/合成取消独立记录 |
| cancellation_received | 客户端收到取消命令 |
| playback_stopped | 已停止旧音频调度并清空对应队列，记录停止位置及设备估计误差 |
| stop_ack_received | 服务端收到该 interruption_id 的 stopped 回执 |

分别展示：检测耗时、判定耗时、确认到取消发送、客户端收到取消到停止、本地总打断耗时、服务端确认到收到停止 ACK。
最后一项包含回传网络延迟，是服务端代理测量，不应标注为用户听感停播时间。
普通 started/progress、自然播放完成、旧 output_epoch 回执均不能结束打断计时。重复 ACK 不重复采样，停止事件丢失显示缺失/超时，不能填 0。
补充统计取消命令成功率、停止 ACK 覆盖率、已标注场景的误打断/漏打断率，以及停止后旧输出残留播放时长。

## 时钟与质量约束

服务端内部使用同一进程单调时钟；客户端内部使用同一客户端单调时钟和音频采样轴。
不能直接相减浏览器 performance.now 与服务端 monotonic_ns。客户端总打断耗时可以在本地测量后上报；端到端用户体验耗时也优先使用客户端输入/输出同一时钟。
跨端拆分采用多次往返校准，返回 offset、RTT、误差范围；未校准时保留各端局部耗时与服务端 ACK 代理值，不输出虚假精确值。
客户端播放开始/停止的回执是调度器确认，并不保证扬声器物理出声精确到毫秒；设备输出延迟有估计值时明确展示。
所有指标保留单位、定义版本、测量来源、时间精度、样本数及覆盖率。区分正常回复、主动取消、有效打断、超时、无回复，不能将取消样本混入普通回复平均值。

## 页面与验收

后台应以「总览 → 输入 Session ID → 单会话时间线 → 单轮/单次打断详情」为主流程。
总览分两张主卡：说完后的响应延迟、有效打断停播延迟，显示 P50/P95/P99、覆盖率和异常样本；下方为模块统计。
单会话页支持精确 Session ID 查询、分页、JSON 导出与统一 Agent 接口说明；每轮展示并行瀑布图、用户/助手文本、判定原因及可定位事件。

实施顺序：先统一播放回执 phase 和计时定义，再补统一诊断查询与分页，随后完善采样里程碑与页面瀑布图，最后加入机器访问和运行质量告警。
验收必须包括：长会话完整分页、单数据源故障、无首音、语义等待、工具等待、客户端缓冲、普通进度不冒充 stopped、重复/迟到 ACK、generation 推进、回连、网络延迟、backchannel，以及跨时钟偏差。
