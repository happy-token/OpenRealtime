# 认识 OpenRealtime

**一个开源、可自定义、可打断的实时语音交互 Agent 产品。接入你的 Agent，用语音聊天和工作。**

直接说话、追问，在回答时补充要求或纠正问题。自由选择声音、TTS、LLM、人设与工具，打造符合自己需求的助手；数字人作为可选的呈现能力。

**[体验实时语音](https://realtime.happy-token.cn/conversation?role_mode=conversation&experience=voice)** · [快速指南](../QUICK-START.md) · [定制语音 Agent](../guides/ROLE-CONFIGURATION.md) · [接入你的 Agent](../guides/CHAT-AGENT-INTEGRATION.md)

## 能干什么

- **实时语音交互。** 直接开口交流、连续追问，在回答时随时打断、补充或纠正，让 Agent 跟上你的对话节奏。
- **接入你的 Agent。** 为已有 Chat Agent 加上语音输入与输出，通过兼容 API 或适配器连接，保留自己的模型与业务回答逻辑。
- **用语音聊天和工作。** 聊天、查询资料、讨论问题，或调用已接入的工具辅助工作。把需求说出来，并在交流中继续补充与确认。

产品讲解、资料问答与互动角色都可以在这些能力之上配置。[产品资料问答上手示例](PRODUCT-ASSISTANT.md)

## 核心亮点

### 自由组合，打造你的语音 Agent

灵活选择 TTS、LLM 与语音识别服务，搭配喜欢的声音、人设和工具，定制助手的表达方式与实际能力。已有 Chat Agent 可以继续提供回答。[角色配置](../guides/ROLE-CONFIGURATION.md) · [Agent 接入](../guides/CHAT-AGENT-INTEGRATION.md)

### 智能判停，给思考留时间

结合语义与说话状态判断你是否说完，减少把思考中的停顿当作结束，让助手在合适的时机接话。话轮决策服务可以独立选型。[判停机制](../SEMANTIC-EOT.md)

### 智能打断，听懂你的意图

区分真正的打断与简单附和，减少环境噪声引起的误打断；识别到叫停、纠正或新问题时，及时停止旧回答，响应新的输入。具体效果取决于语言、服务配置与实际环境。[打断机制](../SEMANTIC-INTERRUPTION.md)

## 你可以怎样定制

| 想要的体验 | 可以选择什么 |
| --- | --- |
| 喜欢的声音与风格 | TTS、音色、人设与回答方式 |
| 适合自己的服务组合 | 语音识别、LLM、语音合成与话轮决策 |
| 保留已有 Agent 的能力 | 兼容文字对话 API 或自定义适配器 |
| 懂自己业务的助手 | 产品资料、知识检索与选定的工具 |
| 持续交流 | 长期记忆、对话历史与续聊 |
| 有形象的交流对象 | 可选云数字人、本地口型或已有动作与口型素材 |

识别、回答与声音服务分别选型，可以按预算组合更经济的方案。合适的组合可比 GPT-Realtime 这类端到端方案更便宜；云 API 路线无需自建模型 GPU。[成本与服务选型](../product/COST-AND-FLEXIBILITY.md)

## 工作方式

你说话，OpenRealtime 识别内容并协调话轮；回答模型或你的 Chat Agent 生成回复，再由声音服务播出来。知识、工具和记忆按需参与，数字人负责可选的视觉呈现。

兼容的文字对话 API 可以复用已有客户端，自定义服务通过适配器连接。你可以保留业务逻辑，单独调整声音、模型与交互策略。[接入方式](../guides/CHAT-AGENT-INTEGRATION.md)

## 从哪里开始

| 目标 | 下一步 |
| --- | --- |
| 先体验一次语音对话 | [进入对话](https://realtime.happy-token.cn/conversation?role_mode=conversation&experience=voice) · [快速指南](../QUICK-START.md) |
| 定制角色、声音和服务 | [角色配置](../guides/ROLE-CONFIGURATION.md) · [云服务配置](CLOUD-SERVICES.md) |
| 接入自己的 Chat Agent | [接入指南](../guides/CHAT-AGENT-INTEGRATION.md) |
| 使用产品资料完成问答 | [完整上手示例](PRODUCT-ASSISTANT.md) |
| 在自己的环境运行 | [本地启动](LOCAL-DEVELOPMENT.md) · [自行部署](../deployment/public-trial.md) |
| 添加数字人 | [数字人方案](../DIGITAL-HUMAN-DRIVING.md) |

公开体验位于 [realtime.happy-token.cn](https://realtime.happy-token.cn)。可用角色、权限与额度由运营方配置，自行部署可以配置自己的服务与数据。

## 当前范围

知识库默认使用文本与关键词片段检索。导入资料不会训练模型，也不保证每轮都检索或每个问题都正确。使用自己的资料时，请核对事实、条件和资料未覆盖的问题。[知识库说明](../KNOWLEDGE-BASE-GUIDE.md)

未配置服务凭据时，本地后端提供确定性演示适配器，用于检查界面和应用链路。真实资料问答和云语音需要配置兼容服务。[服务配置](CLOUD-SERVICES.md)

现有 Chat Agent 的文本接口可通过兼容 API 或适配器连接；编码和办事 Agent 的统一接入与完整语音任务协作仍为 TODO。英文语音配置与完整交流验收也仍需补齐。[支持与范围](../reference/SUPPORT-AND-SCOPE.md) · [路线图](../../ROADMAP.md)
