# Avatar Persona 配置

这里保存可独立于 Avatar 复用、按风格命名的 Persona。`../avatar-persona-links.json` 只负责把一个 Avatar ID 和显示名关联到默认 Persona ID。

当前 Persona：

- `intellectual-warmth`：知性温柔
- `sweet-sunshine`：甜美元气
- `fresh-pastoral`：清新田园
- `romantic-french`：浪漫法式
- `soft-luminous`：柔光纯欲
- `cool-urban-night`：冷艳都市
- `melancholic-mist`：忧郁薄雾

Persona 文件不固定人物姓名。同一 Persona 可以同时关联昭宁、Shuchang 或未来创建的其他 Avatar；自我介绍所用姓名来自关联目录中的 `avatarDisplayName`。

运行时按 OpenClaw 的相对顺序读取本项目采用的角色文件：

| 文件 | 是否需要 | 用途 |
| --- | --- | --- |
| `IDENTITY.md` | 必需 | 名称、身份背景、擅长领域和自我定位，回答“她是谁”。 |
| `SOUL.md` | 必需 | 人格、语气、价值观和关系边界，决定“她如何表达和相处”。 |
| `AGENTS.md` | 推荐、可省略 | 语音回答长度、交互规则、安全边界等可执行约束，决定“她具体如何行动”。 |

为了与 OpenClaw 的上下文优先级保持一致，实际拼接顺序为 `AGENTS.md` → `SOUL.md` → `IDENTITY.md`；缺少可选的 `AGENTS.md` 时，只加载另外两个必需文件。

以下文件不绑定到数字人资产：

- `USER.md`：当前用户资料与偏好，属于用户，不应因切换 Avatar 而改变。
- `MEMORY.md`：长期记忆及会话沉淀，属于用户或会话。
- `TOOLS.md`：工具说明与本地环境备注，属于运行环境。
- `HEARTBEAT.md`：周期性检查清单，属于后台任务调度。
- `BOOT.md`：服务启动时执行的任务，属于网关生命周期。
- `BOOTSTRAP.md`：首次初始化引导，完成后通常移除。

这些 Markdown 是服务端可信配置。浏览器只提交 `avatar_id`，不能直接提交或覆盖 system prompt。

内置 Avatar 已提供默认关联：托管形象 `default-anam` 和分段式 `shuchang` 使用“知性温柔”，`companion` 使用“柔光纯欲”。
