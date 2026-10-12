# OpenRealtime 文档

**实时语音交互，接入你的 Agent，用语音聊天和工作。**

OpenRealtime 是一个开源、可自定义、可打断的语音交互 Agent 产品。自由选择声音、TTS 和 LLM，配置人设、知识与工具，让助手在合适的时机接话，并响应你的打断和纠正。数字人作为可选能力。

**[体验实时语音](https://realtime.happy-token.cn/conversation?role_mode=conversation&experience=voice)** · [快速指南](QUICK-START.md) · [定制语音 Agent](guides/ROLE-CONFIGURATION.md) · [接入你的 Agent](guides/CHAT-AGENT-INTEGRATION.md)

[前端文档](https://realtime.happy-token.cn/docs) · [中文 README](../README.zh-CN.md) · [English README](../README.md)

## 1. 认识产品与开始使用

先了解它是什么、能干什么，再按需要体验或运行。

| 目标 | 文档 |
| --- | --- |
| 认识定位与核心亮点 | [产品概览](getting-started/OVERVIEW.md) · [English overview](getting-started/OVERVIEW.en.md) |
| 开始对话、追问与打断 | [快速指南](QUICK-START.md) |
| 在本机运行 | [本地启动与排错](getting-started/LOCAL-DEVELOPMENT.md)（English） |

## 2. 定制你的语音 Agent

选择服务、声音与人设，按体验和预算组合助手的能力。

- [角色配置](guides/ROLE-CONFIGURATION.md)：名称、人设、声音、供应商覆盖与角色能力。
- [连接真实语音与模型服务](getting-started/CLOUD-SERVICES.md)（English）：识别、回答与声音服务的本地配置。
- [成本与服务选型](product/COST-AND-FLEXIBILITY.md) · [English](product/COST-AND-FLEXIBILITY.en.md)：选择经济的服务组合，比较总费用。

未配置凭据的演示模式用于浏览界面与检查应用链路；真实语音和问答需配置兼容服务。

## 3. 接入你的 Agent

保留已有模型和业务回答逻辑，为自己的 Chat Agent 增加语音输入、输出与交互。

- [兼容 API 与自定义适配](guides/CHAT-AGENT-INTEGRATION.md) · [English integration guide](guides/CHAT-AGENT-INTEGRATION.en.md)：配置 Chat Completions / Responses 接口，或实现自己的适配器。
- [语音 Pipeline 与插件接口](VOICE-PIPELINE.md)：了解流式回答、输入归属与取消合约。

具体接入后验证追问、打断、取消和工具行为；编码、办事 Agent 的统一接入与完整语音任务协作仍有路线图工作。

## 4. 知识、工具与记忆

在语音交互基础上，为助手增加业务资料、可调用的工具和持续交流能力。

| 能力 | 文档 |
| --- | --- |
| 导入与检索自己的资料 | [知识库](KNOWLEDGE-BASE-GUIDE.md) |
| 跑通一个资料问答示例 | [产品资料语音讲解与问答](getting-started/PRODUCT-ASSISTANT.md) · [English walkthrough](getting-started/PRODUCT-ASSISTANT.en.md) |
| 选择工具并配置权限 | [工具权限](TOOL-PERMISSIONS.md) |
| 管理记忆、历史与续聊 | [记忆与会话历史](MEMORY-AND-HISTORY-GUIDE.md) |
| 更新、删除、备份与恢复数据 | [数据管理](DATA-MANAGEMENT-GUIDE.md) |

产品资料问答是一个上手示例。先测试引用片段，再在真实对话中核对回答；默认知识检索采用关键词片段。

## 5. 可选：添加数字人

语音交互跑通后，再按需要选择形象、素材与驱动方式。

- [数字人方案](DIGITAL-HUMAN-DRIVING.md)：已接入的云服务、本地口型与其他选型方向。
- [动作编排](MOTION-ORCHESTRATION-GUIDE.md)：准备和管理配对动作素材。

各方式有独立的服务、素材与算力要求，可用模式以实际配置为准。

## 6. 部署与维护

- [本地启动](getting-started/LOCAL-DEVELOPMENT.md)（English）、[自行部署](deployment/public-trial.md)：运行应用，配置认证、存储、服务与额度。
- [服务配置参考](reference/WEB-DEMO-CONFIGURATION.md)（English）、[环境变量示例](../.env.example)。
- [可靠性与运维](RELIABILITY-OPERATIONS.md)（English）、[会话诊断](guides/agent-session-diagnostics.md)。
- [支持与范围](reference/SUPPORT-AND-SCOPE.md)（English）：当前能力、验证前提与部署边界。

## 7. 开发与扩展

面向需要修改运行时、接入新服务或开发适配器的读者。

- [项目结构](PROJECT_STRUCTURE.md)、[架构](ARCHITECTURE.md)、[术语](../CONTEXT.md)、[协议](asyncapi.json)。
- [语音 Pipeline](VOICE-PIPELINE.md)、[话轮协调器](TURN-COORDINATION.md)、[判停与打断插件合约](SEMANTIC-DECISION-PLUGINS.md)。
- [智能判停](SEMANTIC-EOT.md)、[智能打断](SEMANTIC-INTERRUPTION.md)、[Grounding](REALTIME-GROUNDING.md)。
- [知识服务选型与接入](KNOWLEDGE-INTEGRATION.md)、[可观测性](OBSERVABILITY.md)、[运行时质量](VOICE-RUNTIME-QUALITY.md)。
- [贡献指南](../CONTRIBUTING.md)、[安全报告](../SECURITY.md)、[许可](../LICENSE)、[第三方说明](../THIRD_PARTY_NOTICES.md)。

## 8. 研究、规划与历史记录

以下资料用于理解设计依据和演进过程；首次使用从产品概览或快速指南开始。

- [路线图](../ROADMAP.md)、[更新记录](../CHANGELOG.md)、[版本说明](VERSIONING.md)。
- [产品定位、受众与竞品研究](product/README.md)。
- [架构决策](adr/)、[验证报告](reports/)：结合记录的日期、版本和配置阅读。
- [需求状态审计](COMPLETION_STATUS.md)、[缺口登记](ISSUES.md)、[项目完善审查](PROJECT-IMPROVEMENT-AUDIT.md)：历史规划需对照当前实现。

产品概览、资料问答示例和 Agent 接入等基础文档提供中英文版本；其他指南保留其正文语言。英文文档不代表所有英文语音组合已通过验收。
