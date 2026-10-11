> 2026-10-11：四个亮点与 TODO 状态已合入[英文 README](../../README.md)及[中文 README](../../README.zh-CN.md)。下文保留为文案设计记录；当前对外入口以根 README 为准。

# README 英文定位与亮点草案

更新：2026-10-09。面向全球开源开发者。依据[定位](POSITIONING.md)、[竞品研究](COMPETITIVE-ANALYSIS.md)与[证据矩阵](CLAIMS-AND-EVIDENCE.md)。下面是可用于 README 首屏的建议文案；英文 API 路线仍需补齐和验收。

## Suggested hero

# OpenRealtime

**Bring your AI agents to life with real-time voice and avatars.**

Build interactive agents with configurable turn decisions, answer models, voices, and avatar presentation. Start with cloud APIs, with no self-hosted model GPUs required for the cloud path.

[Try the demo](https://realtime.happy-token.cn) · [Source code](https://github.com/happy-token/OpenRealtime)

## Why OpenRealtime?

- **Talk naturally.** Explore semantic turn-taking for pauses, backchannels, interruptions, and corrections. Turn decisions and reply cancellation are coordinated by the runtime. [Turn decisions](../SEMANTIC-DECISION-PLUGINS.md)
- **Give your agent a face.** Connect your agent's answers and audio to avatar presentation, including cloud avatar integrations. Streaming and interruption capabilities vary by provider. [Avatar integration](../DIGITAL-HUMAN-DRIVING.md)
- **Choose each layer.** Configure turn-decision providers, answer models, voices, and avatar services separately. Supported adapters let you tailor the combination to your application. [Architecture](../PROJECT_STRUCTURE.md)
- **Start simply. Build your way.** Get started with cloud APIs for speech, model inference, and avatar rendering. The cloud path requires no self-hosted model GPUs; choose supported services to fit your application. Application hosting, service credentials, and usage fees apply. [Deployment](../deployment/public-trial.md)

## Planned highlight — TODO

**Bring your own agent. Talk through the task.**

Connect an existing agent and use voice to start tasks, ask for progress, and refine instructions. Keep the agent's tools and execution capabilities while OpenRealtime provides the real-time conversation and optional avatar interface.

**Status: TODO.** Existing adapters provide a starting point. A consistent setup experience, backend capability documentation, and end-to-end task interaction still need to be completed and validated. [Delivery checklist](POSITIONING.md)

## Jev for turn decisions. Your LLM for answers.

Jev is an optional provider for structured end-of-turn and interruption decisions. The runtime applies timing, confidence thresholds, and cancellation policy; your answer model handles response generation. The repository defaults to the LLM decision provider. [Implementation and validation](CLAIMS-AND-EVIDENCE.md)

## Current scope

English-facing ASR/TTS API configurations, reproducible English examples, and end-to-end English conversation acceptance still need to be completed. Existing reports cover specific configurations and test sets; they do not establish general multilingual quality or comparative latency leadership.

Pipecat, LiveKit, TEN, and Qwen Audio Agent are strong alternatives. Evaluate OpenRealtime for its existing Web experience, configurable semantic turn coordination, and integrated voice/avatar combinations. [Comparison and selection guide](COMPETITIVE-ANALYSIS.md)

## 合入前需要补齐的首屏素材

- 当前版本真实英文 Demo：展示一次请求、一次纠正及一次停止，保留可核对的版本与供应商配置。
- 纯语音 CPU+API 与云数字人两条 quickstart，完成英文 API 与声音配置验收。
- 支持表明确每个 adapter 的流式、取消与外部 Agent 能力；与 README 旧实现说明同步。

短版传播文案：**Your agent. Your voice. Your avatar.** 用于封面或片尾；正文使用完整主张说明它是什么。
