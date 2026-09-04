# 大模型上下文配置

此目录只保存可以进入版本控制、由项目维护者审核的共享配置。运行时把不同所有权的数据分开存放，避免切换 Avatar 时错误地切换用户资料、记忆或工具能力。

## 目录建议

| 配置 | 建议位置 | 是否入库 | 所有权与用途 |
| --- | --- | --- | --- |
| Persona `IDENTITY.md` / `SOUL.md` / `AGENTS.md` | `config/personas/<style-id>/` | 是 | 可复用的风格 Persona 资产。 |
| Avatar 默认 Persona 关联 | `config/avatar-persona-links.json` | 是 | 保存 Avatar ID、显示名与默认 Persona ID，不把 Persona 内嵌进 Avatar。 |
| `USER.md` | 本地 `.openrealtime/users/<user-id>/USER.md`；生产环境用户资料库 | 否 | 单个用户明确授权保存的资料和偏好。 |
| `MEMORY.md` | 本地 `.openrealtime/memory/<user-id>/MEMORY.md`；生产环境记忆库 | 否 | 经筛选的长期记忆与会话沉淀，需要访问控制和删除能力。 |
| `TOOLS.md` | `config/runtime/TOOLS.md`，需要时再创建 | 是，但不能包含密钥 | 当前部署可用工具、限制和操作备注；工具能力仍由服务端注册表决定。 |
| `HEARTBEAT.md` | `config/lifecycle/HEARTBEAT.md`，启用定时任务时再创建 | 是 | 后台周期检查清单。 |
| `BOOT.md` | `config/lifecycle/BOOT.md`，需要启动任务时再创建 | 是 | 服务或网关启动后执行的任务。 |
| `BOOTSTRAP.md` | `.openrealtime/bootstrap/<workspace-id>/BOOTSTRAP.md` | 否 | 一次性初始化引导，完成后删除，不作为长期配置。 |

`.openrealtime/` 已在 `.gitignore` 中，适合本地开发数据。生产环境的 `USER.md` 与 `MEMORY.md` 不建议直接落在共享文件系统，应进入带用户隔离、审计和删除能力的数据存储。

目前运行时只加载 Avatar 默认关联的 Persona 文件。其他文件的存放位置已经预留，但在对应的用户记忆、工具说明或生命周期模块接入前不会自动注入模型上下文。
