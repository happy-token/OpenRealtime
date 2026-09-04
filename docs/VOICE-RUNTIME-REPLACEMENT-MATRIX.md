# Voice Runtime Replacement Matrix

本表是 Phase 1 M0–M6 的删除门禁。`new evidence` 必须在 M6 前全部为绿色；状态为 `blocked` 的旧模块不得删除。

## 行为覆盖

| 行为 | 旧证据 | 新边界 / 新证据 | 决定 | 当前状态 |
| --- | --- | --- | --- | --- |
| 启动屏障与结构化失败 | `ConversationKernel.run` 随连接直接运行 | `VoiceSessionRuntime`; `tests/voice_session/test_runtime.py`; `test_endpoint_bridge.py` | intentionally replace | covered |
| 普通音频 Turn | v1 `audio_chunk` → Kernel | `InputEpochStarted/InputAudioFrame` → Cascaded Conversation | preserve | covered: v2 bridge/E2E |
| Barge-in 与迟到音频抑制 | Kernel generation + Web Hook | Realtime Turn Controller + Device Output Runtime generation | preserve | covered |
| Fast Tool 取消与续跑 | Application coordinator / legacy adapter | `RealtimeToolController` + frozen-prefix recovery; transport detach cancellation | preserve | covered |
| Agent Task | legacy event mapping | Brain proposal → `RealtimeDelegationController` → durable Agent Task Supervisor → Journal projection; Task Store → rebuildable Work Registry | preserve | covered: authoritative commit, duplicate suppression, recovery, offline result queue |
| Bound Confirmation | legacy event mapping | authoritative Tool Handler item → exact digest decision transport; Journal + Authorization recovery restatement | preserve | covered: stale pre-reconnect decision is rejected |
| 模型请求结束会话 | `EndSessionAction` → `EndSessionRequested` | 无；显式客户端/服务端命令驱动 `VoiceSessionRuntime.stop()` | delete | deleted: model output cannot directly terminate a Voice Session |
| 断线恢复 | Endpoint outbound frame replay | semantic Voice Session runtime; connected registry suspend/resume; no v2 raw-frame replay | intentionally replace | covered |
| 模型历史恢复 | unbounded Journal replay | Context Policy/Budgeter/Projector/Compressor barrier | intentionally replace | covered |
| 播放结算 | v1 `playback_progress` | output epoch + speech/generation Playback Progress | preserve | covered |
| 关闭与资源回收 | Kernel/session close | bounded `VoiceSessionRuntime.stop` + `Closed` event | intentionally replace | covered: runtime contract |
| Native Realtime | experimental adapter | no Phase 1 production replacement | delete from production profile only | removed from production selector |
| RTC/UDP | Kernel UDP demo | deferred v2 conformer | delete UDP demo; defer RTC | UDP demo deleted; RTC deferred |

## 模块门禁

| 旧模块 / 路径 | 可复用能力迁移目标 | 删除前必须满足 | 当前判断 |
| --- | --- | --- | --- |
| `VOICEAGENT_REALTIME_RUNTIME=legacy` | 无 | production 默认与 E2E 仅使用 Voice Session + v2 | deleted |
| `demos/voice_web_server.py::_build_kernel/_finish_build_kernel` | VAD/ASR/Brain/TTS 构造移入 Realtime capability composition | production imports=0；Voice Web E2E green | deleted |
| `server/kernel/` | 无领域编排保留 | 行为矩阵全部有新 Contract/E2E | deleted；旧专项测试随路径删除，新 Voice Session/Realtime 契约保留 |
| `server/conversation_engine/` | Brain streaming/speculative/tool-result/latency 已迁入 Realtime/Observability | production imports=0 | deleted；可复用能力已迁入 `server/realtime/capabilities/` 与 `server/observability/` |
| `server/realtime/legacy.py` | Delegation/Confirmation 映射移入控制面 | 新映射与恢复门禁 green | deleted |
| `RealtimeWebSocketSession` 兼容壳 | `VoiceSessionWebSocketSession` | production imports=0；v2 startup/recovery/Chrome E2E green | deleted |
| 旧 Application turn/tool-action coordinator | 必要 policy 移入 Realtime control plane | production imports=0 | deleted |
| `server/scheduler/` 与 `SpeakingClock` | TTS/播放生命周期移入 Realtime Speech capability 与 Device Output Runtime | production imports=0；播放真值/取消契约 green | deleted |
| v1 `audio_chunk` adapter | 无 | Desktop Chrome v2 E2E、恢复与设备切换、真实 Profile 质量门禁 green | deleted: parser/bridge/client type 与 `public/pcm-worklet.js` 已删除；负向协议测试保留 |
| `src/hooks/use-conversation-engine.ts` 兼容实现 | `src/voice/session/controller.ts`、`src/voice/session/transport.ts`、`src/voice/audio/*`、`src/voice/protocol/v2.ts` 与 `use-voice-session.ts` React binding | 重连/媒体图装配迁出；Chrome v2 E2E 与真实 Profile 质量门禁 green | deleted: 网络重连、输入 Worklet graph 与输出 Web Audio graph 已迁出并有独立契约测试 |
| `demos/basic_ws_server.py` Kernel 装配 | 最小 v2 Voice Session demo | demo smoke green | migrated |
| `demos/udp_server.py` | 无；ESP32 后续直接实现 v2 | 无 production/import 引用 | deleted |

## M6 判定规则

单个模块只有同时满足以下条件才能从仓库删除：

1. production import 与装配引用为零；
2. 对应 preserve 行为已有新 Contract 或 Chrome E2E；
3. Cascaded correctness 与资源清理门禁通过；
4. 可复用 capability 已迁移到正确包，且不存在从新 Runtime 回指旧 Runtime 的依赖；
5. 文档、示例和发布 Profile 不再宣传旧路径。
