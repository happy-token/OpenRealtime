# Documentation / 文档导航

Start with the [English README](../README.md) or [中文 README](../README.zh-CN.md). Guides currently include English and Chinese documents; navigation language does not imply that every provider/language combination is validated.

## Get started / 开始使用

| Goal | Read |
| --- | --- |
| Run the application locally | [Local development](getting-started/LOCAL-DEVELOPMENT.md) |
| Connect real hosted services | [Cloud services](getting-started/CLOUD-SERVICES.md) |
| Use the Web application | [首页使用指南](QUICK-START.md) |
| Configure a role | [角色配置](guides/ROLE-CONFIGURATION.md) |

## Build your assistant / 配置助手

- [Knowledge library / 知识库](KNOWLEDGE-BASE-GUIDE.md), [integration choices](KNOWLEDGE-INTEGRATION.md).
- [Tool permissions / 工具权限](TOOL-PERMISSIONS.md).
- [Memory and conversation history / 记忆与续聊](MEMORY-AND-HISTORY-GUIDE.md).
- [Avatar presentation / 数字人驱动](DIGITAL-HUMAN-DRIVING.md), [motion orchestration / 动作编排](MOTION-ORCHESTRATION-GUIDE.md).
- [Data management / 数据管理](DATA-MANAGEMENT-GUIDE.md).

## Deploy and operate / 部署与运维

- [Hosted deployment](deployment/public-trial.md): includes the public site's topology; adapt domains, providers and credentials to your deployment.
- [Reliability operations](RELIABILITY-OPERATIONS.md).
- [Service configuration examples](reference/WEB-DEMO-CONFIGURATION.md), [environment reference](../.env.example).
- [Agent session diagnostics](guides/agent-session-diagnostics.md).

## Understand and extend / 架构与扩展

- [Project structure](PROJECT_STRUCTURE.md), [architecture](ARCHITECTURE.md), [glossary](../CONTEXT.md).
- [Turn coordination](TURN-COORDINATION.md), [semantic decision contracts](SEMANTIC-DECISION-PLUGINS.md), [end-of-turn](SEMANTIC-EOT.md), [interruption](SEMANTIC-INTERRUPTION.md).
- [Voice pipeline](VOICE-PIPELINE.md), [grounding](REALTIME-GROUNDING.md), [protocol](asyncapi.json).
- [Observability](OBSERVABILITY.md), [runtime quality](VOICE-RUNTIME-QUALITY.md).

## Contribute and follow the project / 贡献与项目状态

- [Contributing](../CONTRIBUTING.md), [security](../SECURITY.md), [license](../LICENSE), [third-party notices](../THIRD_PARTY_NOTICES.md).
- [Roadmap](../ROADMAP.md), [changelog](../CHANGELOG.md), [versioning](VERSIONING.md).
- [Positioning, comparisons and evidence](product/README.md).
- [Architecture decisions](adr/), [validation reports](reports/): historical evidence, interpreted with their dates and configurations.
- [Requirements status audit](COMPLETION_STATUS.md), [gap register](ISSUES.md), [improvement audit](PROJECT-IMPROVEMENT-AUDIT.md): detailed/historical planning; verify current implementation before treating an old entry as current status.

Existing `/docs/<slug>` routes and source directories are unchanged. Research reports and ADRs are not the first-time user path. Local ignored/untracked research material is not necessarily included in the public repository.
