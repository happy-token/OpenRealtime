# 为自己的 Chat Agent 加上语音

**保留你的对话能力，让用户直接说话、追问和打断。**

已有文字对话产品可以通过兼容 API 或适配器连接到 OpenRealtime：语音输入转换为文本交给你的 Agent，返回内容再转换成声音，并可连接数字人呈现。你的业务回答逻辑仍由自己的 Agent 提供。

## 选择接入方式

| 已有能力 | 接入路径 | 需要适配什么 |
| --- | --- | --- |
| 兼容 OpenAI 的 Chat Completions 或 Responses 接口 | 复用现有模型客户端 | 接口地址、认证、模型名、流式事件与取消行为 |
| 自己的 HTTP、SDK 或其他文本对话接口 | 实现对话客户端适配器 | 输入映射、文本／流式输出、异常与取消 |
| 编码或办事 Agent 后端 | 现有 ACP、Codex、Claude、Hermes 适配基础 | 后端安装、权限与任务流程；统一体验仍待补齐 |

## 兼容接口的本地配置

本地默认回答路径可通过 `.env.local` 指向自己的兼容接口：

```dotenv
VOICEAGENT_LLM_API_KEY=your-chat-agent-key
VOICEAGENT_LLM_BASE_URL=https://your-chat-agent.example.com/v1
VOICEAGENT_LLM_MODEL=your-agent-model
VOICEAGENT_LLM_API_STYLE=chat_completions
```

这是接口形状的配置示例；服务需要实际支持对应协议与模型标识。若服务实现 Responses，可将 API style 改为 `responses`。角色的供应商覆盖、公开准入配置和工具回答路径各有作用域，须同时核对，不能假设修改默认值会覆盖全部路径。

## 自定义接口的适配边界

- [LlmClient](../../server/brain/llm_clients.py) 的 `complete(system_prompt, user_text)` 返回回答文本。
- 实现 `stream` 可逐段返回文本；已有 [ChatBrain](../../server/brain/chat_brain.py)会使用流式接口。
- 工具路径使用独立的 `ToolCallingLlmClient` 合约；普通文字接口不能自动视作完整工具调用接口。
- 适配器负责自己的认证、会话关联、超时与取消；按用户隔离 Agent 上下文。

从[现有兼容客户端](../../server/brain/plugins/openai_compatible_llm_client.py)和[语音 Pipeline 接口](../VOICE-PIPELINE.md)开始。自定义适配器需要开发与装配，当前没有通用的一键接入任意 Chat Agent 的页面。

## 接入后验证

确认文字回复、流式语音、追问、停止、纠正、超时与重连。工具、知识和记忆可以由自己的 Agent 提供，也可与 OpenRealtime 的能力结合；明确各自的数据与权限边界。

停止声音播放与取消后台工作是不同操作。现有文本对话接口的接入方式，不等于编码／办事 Agent 的统一安装、进度反馈和完整任务协作已全部交付。具体后端按能力逐项验收。

[模型服务配置](../getting-started/CLOUD-SERVICES.md) · [角色设置](ROLE-CONFIGURATION.md) · [架构](../ARCHITECTURE.md)
