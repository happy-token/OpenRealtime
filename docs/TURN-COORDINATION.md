# 模块化话轮协调器使用说明

2026-10-01：Web Demo 的 Cascaded Pipeline 默认使用 `CoordinatedTurnManagerCapabilityAdapter`。Jev 已支持分别替换判停和打断；暂停/恢复、多头语义输出仍属于后续工作。

## 三个替换接口

| 接口 | 职责 | 当前实现 |
| --- | --- | --- |
| TurnManager provider：`open → send/events → close` | 会话协调、候选输入、响应归属、模型调度及等待期限 | `server/realtime/capabilities/coordinated_turn_manager.py` |
| `classify_request(EotRequest)` | 语义完整性；兼容原有 text/context classifier | `server/turn_policy/eot_classifier.py` |
| `classify_request(InterruptionRequest)` | 语义打断；兼容原有 classifier | `server/turn_policy/semantic_interruption.py` |

模型提供证据，协调器负责动作。替换整个算法时，在 `CascadedPipelineBindings.turn_manager` 或部署注册的 TURN_MANAGER 插件槽绑定新 provider。

只调整等待和准入策略时，使用 `TurnCoordinationPolicy`：

```python
from server.realtime.capabilities.coordinated_turn_manager import (
    CoordinatedTurnManagerCapabilityAdapter,
)
from server.turn_policy.coordination import DefaultTurnCoordinationPolicy

provider = CoordinatedTurnManagerCapabilityAdapter(
    eot_classifier=my_eot_model,
    semantic_interruption_classifier=my_interruption_model,
    coordination_policy_factory=lambda: DefaultTurnCoordinationPolicy(
        incomplete_wait_ms=3000,
        uncertain_wait_ms=300,
    ),
    recovery_timeout_ms=10000,
)

# 将 provider 绑定到 Pipeline 的 turn_manager 槽位。
# 每次 open 创建独立的协调策略、输入记录与事件队列。
```

自定义策略实现同步、快速的 `endpoint_wait_ms(result)` 与 `interruption(verdict)`。后者返回 `InterruptionDisposition(stop_response, admit_input)`；不要在策略内调用播放器或修改 Journal。完整语义合约参见《判停与打断插件合约》。

## 状态与事件

`session.snapshot()` 提供两个上层话轮：`user/assistant`，以及候选输入 ID、文本修订号、响应 ID、是否等待 ASR final。

内部输入和助手响应分别记录，允许助手持有话轮时收集用户插话。兼容现有 UI、Engine 的 `idle/listen/speak/dual` 事件只是投影；没有额外构造一个负责所有逻辑的五状态 FSM。

会话 actor 串行修改记录。语义模型在后台运行，带输入 ID、revision 和请求 token 的结果回流；VAD/ASR routing 不等待模型推理。新内容使旧证据过期；同文本的 VAD restart 撤销旧 stop，但保持输入 ID。

普通用户输入等待语义完整性与停止条件；助手响应期间的插话候选不调用语义判停，按打断结果、VAD/ASR 停止条件和让出确认请求 ASR final。旧回复停止后，该候选仍保持插话归属直到最终提交。最终提交使用 ASR final 的权威文本，不用较早的 partial 覆盖它。最终提交等待期间保存后继 VAD/ASR 观察，旧轮次的 final 或让出确认不能完成新轮次。

## 默认策略

- complete：停止条件满足后推进；incomplete/uncertain：有界等待，可替换等待策略。
- correction/interrupt：停止旧响应，保留输入。
- stop：停止旧响应，不创建新请求；如果随后文本变成“别说了，查上海”，最终修订会重新判断。
- 精确附和规则：稳定边界确认后可抑制；当前助手文本含问号时不直接用附和白名单吞短回答。
- 模型 backchannel：稳定边界且置信度达到 `backchannel_confidence`（默认 0.95）时保持助手输出；阈值可通过策略替换。
- 模型 ignore/uncertain、低置信附和及模型故障：保留最终输入；完成后准入并让出话轮。
- 输入由唯一内部 ID 跟踪；取消绑定目标 response_id。旧响应的完成事件不会关闭新响应。

以上优先避免丢用户请求，可能带来额外误打断。它不是经过真实语音评测后的最优阈值；后续可用新策略与场景集调整。

## 等待与恢复

`VOICEAGENT_TURN_RECOVERY_TIMEOUT_MS` 默认 `10000`：从最新 ASR 内容修订起计时，纯 VAD 振荡不重置。普通静音/完整性等待、取消确认和 ASR final 等待分别管理。

- 有文本且当前已停说：到恢复期限可以有界推进，不持续依赖被 VAD 重置的普通计时器。
- 声学持续显示说话但 ASR 不进展：明确发布 capability failure，交给现有 Runtime 恢复；不伪造静音或无条件截断用户。
- 缺少 ASR final 或取消确认：有界失败，不永久挂起。
- 关闭最多等待后台任务 100ms；不响应取消的插件记录警告，插件仍需自行释放资源。

这些失败会进入现有诊断/恢复机制，不能承诺未提交的输入在 provider 重启后自动重放；持久化未决音频与输入恢复是后续范围。默认协调器暂不执行旧 `response_prefetcher` 的推测准备，避免未经协调的预取生命周期影响准入；Brain 的正常响应路径保持可用。Legacy Adapter 保留供兼容使用。

## 验证与后续

Jev 分类 API 已于 2026-10-01 复测，结果及重跑命令参见 [Jev 复测报告](reports/2026-10-01-jev-retest.md)；尚未切换默认运行模型。

回归覆盖普通提交、恢复说话、连续 VAD 振荡、慢模型迟到、负面模型结果、纯附和、问答短回复、stop 后纠正、三次连续打断、缺 final、仅 ASR hint、以及现有 Engine/Journal/音频与播放后打断契约。

已用真实 Jev API 跑通模拟 ASR/VAD 的协调器 Demo，没有开展模型训练或真实麦克风/浏览器音频 A/B。暂停/恢复、结束会话控制、多头标签、系统附和保持 TODO；替换模型无需改当前 Pipeline 或输入归属合约。

## 尝试 Jev 判停与打断

服务端 `.env` 中配置以下字段；密钥不得使用 `NEXT_PUBLIC_` 前缀。两个 provider 可独立选择 `llm` 或 `jev`。

```dotenv
JEV_API_KEY=你的服务端密钥
VOICEAGENT_EOT_PROVIDER=jev
VOICEAGENT_INTERRUPTION_PROVIDER=jev
VOICEAGENT_JEV_MODEL=jev-1.13.0
VOICEAGENT_JEV_TIMEOUT_MS=2000
VOICEAGENT_JEV_MAX_CONCURRENCY=2
VOICEAGENT_JEV_EOT_MIN_CONFIDENCE=0.8
VOICEAGENT_BACKCHANNEL_CONFIDENCE=0.95
```

安装并运行独立 Demo：

```bash
uv sync --extra jev
uv run --extra jev --env-file .env python -m demos.jev_turn_demo
```

Demo 调用真实 Jev，模拟 VAD、ASR final 和停播确认，分别输出普通请求、纠正和附和的实际准入动作。
检查 `eot_model_result_observed` 与 `interruption_model_result_observed`；只有 `committed` 而没有模型结果时，不能当作 Jev 成功。
它没有连接真实麦克风或播放器。启动或重启 `pnpm dev:server` 后，Web Demo 也会读取这些配置；开发启动脚本已包含 Jev 依赖。

Jev 适配器使用 `classify_request`，输入包含历史、当前文本与观察状态；打断另包含助手文本。
未知的声源明确标为 unknown，不编造声学识别结果。会话身份不发送给模型。
判停低于 `VOICEAGENT_JEV_EOT_MIN_CONFIDENCE` 时转为 uncertain，等待仍由协调器控制。
打断置信度先经过 `VOICEAGENT_SEMANTIC_INTERRUPTION_THRESHOLD`（默认 0.8）；稳定附和再经过 `VOICEAGENT_BACKCHANNEL_CONFIDENCE`。
降低附和阈值可能减少误打断，也可能吞掉误判成附和的新请求，需用真实场景验证。

Jev 不重试实时请求，超时／故障交给现有保留输入与恢复策略。Jev 模式的打断超时默认继承 Jev 超时；若显式配置 `VOICEAGENT_SEMANTIC_INTERRUPTION_TIMEOUT_MS`，则以该值为准。
当前实现每次请求创建并关闭异步客户端，因此连接无法复用。本机实测协调器 Demo 约 1.1–1.6 秒，不能沿用旧评测脚本复用连接时约 300ms 的耗时结论。

实现：`server/turn_policy/plugins/jev_classifier.py`。实测与限制见 [Jev 运行时接入报告](reports/2026-10-01-jev-runtime.md)。


2026-10-02：首音前的续说候选等待回复 preparing 后取消并组合上一输入，以 continuation_of_turn_id 保留 Journal 修订关系；播放开始后则创建独立插话轮次。打断模型的 assistant_text 固定为开口时客户端进度已确认的完整句段，不使用 BrainTextDelta。缺少 TTS 对齐的未播放完部分保持未知，不以生成全文补齐。详见 VOICE-PLAYBACK-TURN-REQUIREMENTS.md 的实现记录。
