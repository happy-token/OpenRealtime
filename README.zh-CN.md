# OpenRealtime

**让你的 AI Agent 通过实时语音和数字人与人交流。**

可组合的实时语音与数字人 Agent 运行时，附带 Next.js 参考应用，提供对话、角色配置、资源管理与服务设置。话轮决策、回答模型、声音和数字人呈现可分别选型。

[公开体验](https://realtime.happy-token.cn) · [文档导航](docs/README.md) · [English](README.md) · [参与贡献](CONTRIBUTING.md)

## 为什么选择 OpenRealtime？

- **自然交流。** 语义话轮协调支持停顿、附和、停止、插话与纠正的判断和处理；决策模型提供证据，运行时协调取消与新请求准入。[话轮说明](docs/TURN-COORDINATION.md)
- **为 Agent 加上形象。** 将自己的回答和音频连接到云数字人或受支持的本地呈现。不同路线的流式、口型与打断能力不同。[数字人指南](docs/DIGITAL-HUMAN-DRIVING.md)
- **每层自主选择。** 按应用需要配置决策模型、回答模型、声音、知识、工具和形象；各适配器有明确的配置与能力边界。[架构](docs/ARCHITECTURE.md)
- **轻松启动，按需组合。** 通过托管语音、模型和数字人 API 起步。云服务路线无需自建模型 GPU 推理，仍需应用后端、凭据和服务费用。[部署](docs/deployment/public-trial.md)

### Jev 判断话轮，LLM 负责回答

Jev 可选用于结构化判停与打断分类；运行时处理时序、置信度阈值和取消策略，回答模型负责生成内容。[.env.example](.env.example) 中两类决策默认均为 `llm`。模型调用耗时不能当作整链语音响应延迟。[实现与证据](docs/product/CLAIMS-AND-EVIDENCE.md)

## 能做什么

- 使用产品资料的语音或数字人导览助手。
- 自定义声音、人设、知识与工具的角色助手。
- 面向已支持外部 Agent 后端的实时交流入口。

Web 页面已有角色配置、资源库、对话记录、供应商及模型服务设置。[使用指南](docs/QUICK-START.md)

## 当前能力与边界

| 领域 | 当前范围 | 边界 |
| --- | --- | --- |
| 语音交互 | 级联 ASR → 话轮协调 → Brain/工具 → TTS，流式输出与取消 | 真实质量取决于供应商、语言、网络和配置 |
| 语义决策 | 判停和打断可分别配置 LLM/Jev | 分类与执行策略独立，不承诺所有场景正确 |
| 数字人 | Anam 云集成、HeyGen LiveAvatar 对照路线、可选本地/视频呈现 | 循环视频、口型对齐与实时云渲染是不同模式 |
| 知识与工具 | 资料导入、角色绑定、检索、工具及权限 | 需用实际资料和任务验证效果 |
| 记忆与历史 | 用户/角色范围的记忆、历史和续聊 | 依赖存储、保留及恢复配置 |
| 外部 Agent | ACP、Codex app-server、Claude stream-JSON、Hermes 适配基础 | 后端能力不同；统一接入与语音任务流程仍为 TODO |
| 传输与设备 | 浏览器 WebSocket v2、UDP/ESP32 参考客户端 | 不等于 RTC 或生产设备支持已完成 |

**规划亮点（TODO）：连接已有 Agent，用对话驱动任务。** 用语音发起任务、追问进度、补充与修改要求。统一接入体验及端到端任务流程仍需补齐与验收。[清单](docs/product/POSITIONING.md)

产品面向全球开发者。英文 ASR/TTS 配置、可复现英文示例与真实英文对话验收仍需补齐；文档语言不能代表多语言交互质量。[路线图](ROADMAP.md)

## 快速开始

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 22、pnpm 10（与当前 CI 对齐）。语音输入需要浏览器麦克风权限，通常要求 HTTPS 或 localhost。

```bash
git clone https://github.com/happy-token/OpenRealtime.git
cd OpenRealtime
uv sync
pnpm install
pnpm dev
```

打开 `http://localhost:3000`。启动器同时启动 Next.js 与 Python WebSocket/控制面服务（8765/8766）；本地 GPU 渲染默认关闭。[详细启动与排错](docs/getting-started/LOCAL-DEVELOPMENT.md)

未配置服务凭据时，后端使用确定性演示适配器；支持的浏览器可提供显式语音回退。这用于检查页面与演示路径，不等于真实云模型对话。浏览器语音不可用时仍可使用文字入口。

## 配置与部署

以 [.env.example](.env.example) 为配置参考，将凭据保存在本地环境文件。真实语音需要受支持的语音/模型服务；云数字人需要单独的授权与配置。平台服务凭据与个人供应商凭据各有作用域。

[云 API 配置路径](docs/getting-started/CLOUD-SERVICES.md) · [详细配置示例](docs/reference/WEB-DEMO-CONFIGURATION.md)

完整托管部署包含 Next.js、Python 语音/控制面服务与 PostgreSQL。持久媒体存储和可选渲染按功能配置。云推理路线无需自建模型 GPU；可选本地神经渲染另有算力要求。公开站提供运营方配置的受限额度，自托管需自行配置服务、认证、存储与配额。

[部署指南](docs/deployment/public-trial.md) · [可靠性与运维](docs/RELIABILITY-OPERATIONS.md)

VoiceAgent 更名后，已有 `VOICEAGENT_*` 环境变量与旧存储/协议标识继续兼容；修改持久标识前应核对升级说明。

## 项目结构

```text
server/       Python 运行时、服务合约、适配与持久化
demos/        服务启动器与控制台演示
src/          Next.js 应用、组件、浏览器语音运行时与库
clients/      设备/传输参考客户端
config/       配置与人设资源
scripts/      开发、检查与运维脚本
deploy/       部署配置与可选服务
docs/         用户/开发者指南、架构、ADR 与验证证据
```

[详细结构](docs/PROJECT_STRUCTURE.md) · [架构](docs/ARCHITECTURE.md) · [术语](CONTEXT.md) · [协议](docs/asyncapi.json)

## 开发与贡献

```bash
uv run pytest
uv run python scripts/check_mypy.py
pnpm lint
pnpm exec tsc --noEmit
pnpm test
```

浏览器测试需先运行 `pnpm exec playwright install chromium`。`pnpm test:voice` 为确定性语音回归；`pnpm test:voice:live` 调用已配置的外部服务，可能产生费用。本地媒体测试需相应服务和素材。[贡献指南](CONTRIBUTING.md)

## 文档与项目状态

- [文档总导航](docs/README.md)：启动、角色配置、部署与扩展路径。
- [路线图](ROADMAP.md)、[更新记录](CHANGELOG.md)：后续工作与已记录变更。
- [定位与竞品研究](docs/product/README.md)：采用理由及证据边界。
- [质量验证](docs/VOICE-RUNTIME-QUALITY.md)：报告仅证明记录的版本与配置。
- [架构决策](docs/adr/)、[历史状态审计](docs/COMPLETION_STATUS.md)：工程背景。

## 许可

运行时与集成代码采用 [Apache-2.0](LICENSE)。托管模型、数字人服务和第三方素材保留各自条款。参见[第三方说明](THIRD_PARTY_NOTICES.md)、[安全报告](SECURITY.md)与[行为准则](CODE_OF_CONDUCT.md)。
