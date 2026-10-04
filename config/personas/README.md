# Avatar Persona 配置

这里保存可独立于 Avatar 复用、按风格命名的 Persona。`../avatar-persona-links.json` 只负责把一个 Avatar ID 和显示名关联到默认 Persona ID。

当前 Persona：

- `intellectual-warmth`：阅读顾问 · 知性温柔
- `sweet-sunshine`：生活伙伴 · 活泼元气
- `fresh-pastoral`：自然向导 · 清新平和
- `romantic-french`：生活美学 · 浪漫优雅
- `soft-luminous`：日常陪伴 · 温柔安心
- `cool-urban-night`：创意顾问 · 理性直接
- `melancholic-mist`：文字倾听 · 安静共情

Persona 文件不固定人物姓名。同一 Persona 可以同时关联昭宁、Shuchang 或未来创建的其他 Avatar；人物姓名统一写成 `{{role_name}}`，会话通过服务端角色目录中的 `display_name` 填充；未选择角色的旧形象链路回退到 `avatarDisplayName`。模板标题只表示用途与性格，不是人物姓名。

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

内置 Avatar 已提供默认关联：托管形象 `default-anam` 和分段式 `shuchang` 使用“阅读顾问 · 知性温柔”，`companion` 使用“日常陪伴 · 温柔安心”。

## 如何设计人设

- 角色名称：具体人物姓名，例如“若水”，在角色设置中修改。
- 人设名称：用途与性格，例如“阅读顾问 · 知性温柔”，方便多角色复用。
- IDENTITY：填写 `人物姓名：{{role_name}}`、交流范围和虚构背景；不把模板标题当姓名。
- SOUL：描述性格、说话方式、情绪表达和边界。职业/用途决定擅长什么，性格决定怎么交流。
- AGENTS：写清回答长度、事实查询和工具使用等可执行规则；性格不能影响查询事实或履行用户请求。

职业只是交流定位，不能因此虚构专业资质或保证回答正确。风格分类不使用形象审美词作为能力名称；已有模板 ID 保持稳定，角色关联继续有效。
