# 语义判停与打断插件合约

2026-10-01：这些模型接口已由 Web Demo 的模块化协调器消费，协调策略和 provider 替换方式见《模块化话轮协调器》（`turn-coordination`）。

Jev 已提供 `JevEotClassifier` 与 `JevSemanticInterruptionClassifier`，两者实现本页的 rich/legacy 接口。配置、独立 Demo 与超时说明见《模块化话轮协调器》的“尝试 Jev 判停与打断”章节。

标签的设计评估、主流方案对照与下一版建议见文档页面《判停与打断标签评估》（`semantic-label-assessment`）。该评估中的新增维度属于建议，现行合约以本页为准。

判停和打断可以替换为独立模型插件。两者使用不同输出，不共用一个含糊的「是否结束」布尔值。运行时负责超时、文本修订、generation 校验、取消及真正的轮次提交，模型负责提供语义判断。

## 统一输入

新插件推荐实现 `classify_request(request)`。输入为不可变的数据记录，当前合约版本为 `1`。

| 字段 | 判停 `EotRequest` | 打断 `InterruptionRequest` |
| --- | --- | --- |
| 当前文本 | `text`：本轮累计用户文本 | `transcript`：插话的累计用户文本 |
| 历史 | `context.history`：有序已提交 user/assistant 消息 | `history`：有序已提交 user/assistant 消息 |
| 当前助手内容 | 从历史读取上一轮助手消息 | `assistant_text`：当前播放相关的助手文本 |
| 本轮标识 | `generation` | `generation` |
| 文本/音频观察 | `input_state` | `input_state` |
| 语言 | `language`，未知时 `None` | `language`，未知时 `None` |
| 身份与关联 | 可选 `interaction` | 可选 `interaction` |
| 合约版本 | `contract_version=1` | `contract_version=1` |

历史是不可变 tuple，按发生顺序排列。首轮没有历史时传空 tuple，模型不能因此报错或编造历史。当前 TurnManager 默认历史预算为最近 8 条、4,000 字符，按预算截断时标记 `truncated=True`。默认配置会优先保留最近两条消息，避免长助手回答挤掉前面的用户问题；内容不保证全文保留。若显式配置仅一条消息或不足两字符的预算，就无法保留双方。支持上下文的模型可使用最近 user/assistant 交换，文本模型可只使用当前文本。不会额外调用模型生成一条假历史。

`SemanticInputState` 支持：

- `transcript_revision`：当前识别文本修订号。
- `boundary`：`partial`、`sentence_end` 或 `final`。ASR 句尾与最终提交是不同状态。
- `dialogue_state`：当前 `idle/listen/speak/wait/dual`。
- `speech_active`：已知的说话活动；未知传 `None`。
- `silence_duration_ms`：已观察到的音频静音时长；未知传 `None`。
- `audio_timestamp_us`：音频时间线观察位置；未知传 `None`。

字段为可选观察，运行时只填已知值。ASR 文本无增量不能被伪装成确定的音频静音。判停在 ASR 句尾触发时标记 `sentence_end`，在 partial 的静音/idle 路径触发时仍标记 `partial`；打断请求携带实际提交边界和对应 revision。请求为某次判断的快照，后续活动由 Gate 单独校验，不能把快照当成永久有效状态。

`interaction` 用于日志关联与隔离校验，不是语言模型的推理材料。现有 LLM 适配器不会把用户身份或会话凭据序列化进模型输入。接口暂不直接传音频片段或声学特征；未来需要音频模型时，应定义明确的音频合约与数据授权，不能把任意字节塞进文本字段。

## 统一输出

### 判停

返回 `EotClassification`：

```python
EotClassification(
    decision=EotDecision.COMPLETE,  # COMPLETE / INCOMPLETE / UNCERTAIN
    confidence=0.92,               # 对该标签的置信度，不等同于完整性概率
    wait_ms=0,                     # 等待建议；真正的时序策略由运行时决定
    source="my-model:v1",
)
```

可选 `evidence` 保留模型证据。`EotEvidence` 支持完整性 `probability`、阈值、推理耗时与来源，适用于二分类概率模型和组合判断。适配器负责把原始 logits、概率或厂商标签映射到规范输出。置信度与概率限制在 `[0,1]`，时长必须有限且非负。

`COMPLETE` 只表示语义完整，不直接提交轮次。Gate 还要确认当前文本没有过期且停说条件满足。失败进入现有有界等待策略，不无限阻塞会话。

### 打断

返回 `InterruptionClassification(label, confidence)`：

- `stop`：只要求停播。
- `correction`：纠正当前回答所依据的信息。
- `interrupt`：新任务或补充信息，需要取得话轮。
- `backchannel`：附和，通常继续播放。
- `ignore`：不采取动作。
- `uncertain`：判断证据不足。

Gate 决定是否停播、是否创建新用户轮次。模型不能直接取消播放器或修改状态机。LLM 原始输出继续要求严格的 label/confidence JSON；返回错误类型、NaN 或无穷数不会作为有效判断使用。

## 当前文本模型和上下文模型怎样兼容

```python
class TextOnlyDetector:
    async def classify_request(self, request: EotRequest) -> EotClassification:
        # 只用本轮文本；history 可以存在也可以为空。
        score = await self.model.predict(request.text)
        return EotClassification(
            decision=EotDecision.COMPLETE if score >= 0.8 else EotDecision.INCOMPLETE,
            source="text-detector:v1",
        )

class ContextDetector:
    async def classify_request(self, request: EotRequest) -> EotClassification:
        # 将有序历史、当前文本与支持的状态字段转换成模型自己的输入。
        return await self.adapter.predict(
            history=request.context.history,
            text=request.text,
            input_state=request.input_state,
        )
```

这是接口示意，需实现 model/adapter，不能直接运行。阈值只是示例，应按真实模型输出定义与评测结果设置。项目已有 `FireRedChatEotProvider.evaluate(EotRequest)`，只取当前文本进行推理，不要求历史。该 provider 可作为 Hybrid/FastFallback 的一个组件使用。

## 注入与兼容

```python
turn_manager = LegacyTurnManagerCapabilityAdapter(
    policy_factory=TurnPolicy,
    eot_classifier=my_eot_plugin,
    semantic_interruption_classifier=my_interruption_plugin,
)
```

新接口优先调用 `classify_request`；旧的判停 `classify(text, generation)`、`classify_with_context(...)` 和打断关键字参数 `classify(...)` 继续兼容。Hybrid 与 FastFallback 已支持将整个请求传给内部 provider，避免中间组合丢失 revision、边界、历史或状态字段。

现有 LLM 判停适配器会接收历史和结构化状态；LLM 打断适配器会接收历史、当前助手内容和插话状态。更换模型时无需改 pipeline 的音频、播放和取消逻辑。服务端仍需显式构造并注册插件，不自动执行网页提供的代码。

## 验证与边界

新增 `tests/turn_policy/test_semantic_request_contract.py` 验证：上下文模型收到上一轮、无历史/纯文本兼容、组合模型完整转发、打断请求 revision 和边界、LLM 序列化，以及非法数值和合约版本拒绝。现有 Gate 测试继续覆盖过期结果、取消和超时。

本次未下载新模型权重，也未验证某个外部新模型的判断准确率。新增服务商还需要确认模型全名、输入模态、标签/概率含义与延迟，再写薄适配器及真实语音评测。

## 规则优先的打断插件

实时协调器通过 `RuleFirstInterruptionClassifier` 统一执行本地规则与模型回退。它位于 `server/turn_policy/plugins/rule_first_interruption_classifier.py`；默认 `ExactInterruptionRules` 的附和词、立即停播词、需要稳定边界的短停播词，以及提问/跨 chunk 前文的保护均在同一插件内。未命中或存在歧义时才调用注入的模型，生产配置可以使用 JEV。

`server/turn_policy/interruption_rules.py` 只定义不依赖供应商的规则输入、返回值和 `InterruptionRuleProvider` 接口。自定义规则实现 `match(context)`，明确命中返回分类，无法可靠判断返回 `None`。插件返回 `source=rule/model`；超时与异常由运行时记录为 fallback，不伪装成规则命中。

协调器负责 chunk 队列、版本有效性、超时、遥测和停播动作，不维护规则词表。规则插件没有播放、ASR、Session、网络连接生命周期的副作用；JEV 的传输、并发和共享连接仍属于模型插件。

规则可在装配时替换或扩展，例如保留默认附和词并增加“收到”：

```python
from server.turn_policy.plugins.rule_first_interruption_classifier import ExactInterruptionRules

rules = ExactInterruptionRules(
    backchannels=ExactInterruptionRules().backchannels | {"收到"},
)
turn_manager = CoordinatedTurnManagerCapabilityAdapter(
    semantic_chunks_enabled=True,
    interruption_rules=rules,
    semantic_interruption_classifier=my_jev_classifier,
)
```

旧 `match_interruption_rule` 入口保留兼容，只转发到规则插件的精确词面匹配；新协调器使用带完整上下文保护的插件接口。精确附和在 partial/助手提问等有歧义场景不会直接吞掉用户回答；已有前块时的停止词需要模型结合前文判断。

回归覆盖：规则命中不调用模型、未命中仅调用一次模型且完整转发请求、提问/partial/跨块否定交给模型、规则替换生效、输入与规则上下文不匹配被拒绝，以及注入自定义停播规则后协调器直接停播。
