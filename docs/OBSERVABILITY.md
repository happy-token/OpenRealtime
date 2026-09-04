# OpenRealtime 运行观测与诊断

本文说明当前语音链路的耗时、超时、异常与无响应如何采集、存储和查询。目标是让一次 Session 可以从用户开口一路追到客户端真正开始播放，而不是只保留若干无法关联的日志行。

## 1. 分层结构

```mermaid
flowchart LR
    K[Conversation Kernel] --> S[SessionTelemetry]
    E[Conversation Engine] --> S
    P[Provider Adapters] --> S
    T[Tool Orchestration] --> S
    S --> Q[非阻塞内存队列]
    Q --> W[后台批量写入器]
    W --> M[InMemoryTelemetryStore]
    W --> PG[PostgresTelemetryStore]
    M --> D[DiagnosticsQuery]
    PG --> D
    D --> API[Control Plane API]
    API --> UI[/admin 运行诊断]
```

- 业务模块只依赖 `SessionTelemetry`，不依赖 PostgreSQL、HTTP 或前端类型。
- 实时链路只执行内存入队，不等待数据库写入。后台写入器默认最多聚合 64 条，或每 250ms 刷新一次；队列上限为 10,000 条，存储长期阻塞时丢弃新的诊断记录并输出分级计数错误，避免诊断系统拖垮语音进程。
- `TelemetryWriter` 和 `DiagnosticsQuery` 是独立接口；本地内存实现与 PostgreSQL 实现可以替换。
- 文本、转写、提示词只记录长度；API Key、Authorization、token、PCM 与音频属性不会写入遥测。
- 当前不保存原始音频。后续若增加音频或大产物诊断，应只在 PostgreSQL 保存元数据和 S3 对象引用。

## 2. 已观测链路

| 类别 | 主要指标 | 含义 |
|---|---|---|
| 端点检测 | `vad.silence_window`、`endpoint.commit_wait` | VAD 静音窗与语义端点确认等待 |
| ASR | `asr.start_session`、`asr.time_to_first_partial`、`asr.final_tail` | 建连、首批文字、最后一批识别尾延迟 |
| 语义判断 | `turn_policy.eot_classify`、`semantic_interruption.classify` | 表达完整度与语义打断判断 |
| LLM | `provider.<provider>.chat.stream` | 首 token 写入 `ttfb_ms`，记录流式调用总耗时与状态 |
| TTS | `provider.doubao.tts.synthesize_duplex`、`tts.time_to_first_audio` | 整轮双流式合成、首音频与连接状态 |
| 工具 | `tool.policy.evaluate`、`tool.execute`、`provider.byte.web_search` | 权限策略、工具执行和联网搜索 |
| 服务端交付 | `turn.time_to_first_text_sent`、`turn.time_to_first_audio_sent` | 首文本/首音频真正交给传输层 |
| 设备采集 | `client.input_epoch_started`、`client.input_capture_failed` | requested/effective Capture Profile、实际浏览器增强能力、缓冲容量/时长、聚合能量与失败原因；不含 PCM |
| 容量准入 | `voice_session.admission` | accept/reject/release、拒绝维度、活跃/预计 Session、event-loop lag、进程内存与音频队列预算 |
| 客户端播放 | `turn.endpoint_to_client_playback`、`client.playback_duration` | 从端点候选到浏览器首播及播放时长 |
| 打断 | `barge_in.time_to_cancel_sent`、`barge_in.time_to_client_stop` | 服务端取消与客户端实际停播 |
| Turn 终态 | `turn.total` | `ok`、`timeout`、`error`、`cancelled`、`superseded` 或 `no_response` |

时间线使用 `voice_session_id`、`generation`、`turn_id`、`response_id` 和 `call_id` 关联。供应商调用还记录 provider、model、operation、attempt，但不记录请求正文。

## 3. 超时边界

| 边界 | 默认值 | 配置 |
|---|---:|---|
| 整轮回复 | 30s | `VOICEAGENT_TURN_RESPONSE_TIMEOUT_S` |
| TTS 双流式会话相邻音频包空闲 | 10s | `VOICEAGENT_TTS_SEGMENT_TIMEOUT_S`（兼容旧配置名） |
| 豆包 ASR WebSocket 建连和首个配置包 | 5s | 构造参数 `connect_timeout_s` |
| 实时搜索 | 3s | `VOICEAGENT_GROUNDING_SEARCH_TIMEOUT_S` / Byte 搜索适配器配置 |
| 语义完整度模型 | 5000ms | `VOICEAGENT_EOT_LLM_TIMEOUT_MS` |
| 语义打断模型 | 800ms | `VOICEAGENT_SEMANTIC_INTERRUPTION_TIMEOUT_MS` |

供应商超时会保留 `timeout_ms` 和实际 `duration_ms`。整轮超时且没有任何文本交付时，Turn 终态记为 `no_response`，同时保留 `turn.response_timeout`，以区分“失败但已部分回复”和“完全没有响应”。级联 Realtime 另有 `VOICEAGENT_RESPONSE_FIRST_TEXT_TIMEOUT_S`（默认 5 秒）：提交用户轮次后若 Brain 一直没有产出首段文本，会记录 `response_first_text_deadline`、取消悬挂的 Brain/TTS，并由浏览器桥显示可重试提示；已交付部分文本的响应不会被提示覆盖。

播放中打断时，逻辑话权切换不再无限等待供应商清理。`VOICEAGENT_TTS_CANCEL_TIMEOUT_MS` 默认 300ms；超过后旧 TTS 任务与 WebSocket 会被隔离并强制关闭，新用户轮次继续提交。该降级记录为 `realtime.capability.tts_cancel_cleanup`，用于统计豆包 TTS 取消不稳定和定位“打断后无响应”。

## 4. 看板和接口

启动 Demo 后访问：

- 语音产品页：`http://localhost:3000/`
- 运行诊断：`http://localhost:3000/admin`
- Control Plane：`http://127.0.0.1:8766`

诊断接口：

- `GET /observability/overview?minutes=60`
- `GET /observability/sessions?minutes=60&limit=50`
- `GET /observability/sessions/{voice_session_id}`

看板每 5 秒刷新，展示成功率、无响应、超时、错误、P50/P95/P99、最近 Session 和完整时间线。时间线的“查看上下文”只展示服务端已脱敏的结构化属性。

## 5. 存储模式

默认 `VOICEAGENT_STATE_BACKEND=memory`，适合本地调试；数据只存在于当前服务进程，重启后清空。

生产或需要跨重启分析时使用 PostgreSQL：

```bash
export VOICEAGENT_STATE_BACKEND=postgres
export VOICEAGENT_POSTGRES_DSN='postgresql://user:password@host/database'
export VOICEAGENT_POSTGRES_SCHEMA=voiceagent
```

必须在部署阶段显式执行版本化 migration；应用启动不会自动建表。运行遥测表由 `0007_runtime_telemetry.sql` 创建，按时间、Session、异常结果和供应商调用建立索引。百分位数在 PostgreSQL 内使用 `percentile_cont` 聚合，不把整个时间窗加载进应用内存。

## 6. 排障顺序

1. 先找 `turn.total`：确认是 `no_response`、`timeout`、`error` 还是正常完成。
2. 查看 `endpoint.commit_wait`：判断等待发生在 VAD/ASR/语义完整度阶段。
3. 对比 LLM `ttfb_ms` 与总耗时：区分首 token 慢和生成过程慢。
4. 对比 `tts.time_to_first_audio`、服务端首音频和客户端首播：定位 TTS、传输或浏览器播放延迟。
5. 若有工具调用，依次查看策略判断、工具执行、搜索供应商和 LLM follow-up。
6. 查看同一 generation 的 cancelled/superseded 事件，排除打断或新 Turn 使旧任务失效。

日志与聚合使用同一事件词汇，但 PostgreSQL 遥测是结构化诊断依据；普通日志仍用于进程启动、连接生命周期和遥测写入器自身故障。
