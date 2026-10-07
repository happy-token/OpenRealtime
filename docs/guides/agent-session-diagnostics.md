# Agent 按 Session ID 排查

管理员进入设置 → 会话诊断 → 对应会话详情，在“交给 Agent 排查”区域点击“生成 Agent 只读凭据”。下载文件只授权当前 Session，15 分钟后失效；将该文件和问题描述交给排查 Agent。普通“导出诊断 JSON”不包含授权凭据。

部署者先在 Next.js 服务端配置独立随机 `OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET`（至少 32 字符），不要复用其他密钥或配置为公开环境变量。未配置时页面明确提示授权尚未配置，不自动生成共享密钥。配置示例文件留空；本次实现没有修改运行中服务的秘密或重启服务。

Agent 从文件读取 `endpoint` 和 `authorization_header`，以 `GET` 和 `Authorization` 请求头查询，不要将凭据写入链接、日志或错误报告。请求必须在凭据有效期内，生产环境使用 HTTPS；Session ID 与凭据必须匹配。Agent 无法列出其他会话、查询全局总览、修改账户或自行刷新权限。

响应 `schema_version: 1`：

- `telemetry`：该会话的事件、指标和 `next_cursor`。
- `conversation`：当前页的已提交对话记录；`conversation_next_cursor` 表示后续页。每条记录的 `journal_sequence` 是十进制字符串，不能转成 JavaScript Number。
- `debug_log`：决策日志和独立的 `next_cursor`。
- `sources`：每个来源的可用性和截断状态。缺失数据不代表事件未发生。
- `audio.status: not-configured`：录音存储尚未接入，不能声称已回放实际语音。
- `collection_health: null`：机器凭据不提供全局采集健康状态。

如 `telemetry.next_cursor` 非空，下次传 `telemetry_cursor`；如 `debug_log.next_cursor` 非空，下次传 `debug_cursor`；如 `conversation_next_cursor` 非空，下次传 `conversation_cursor`。三路分别推进，日志按 `event_id`、对话按 `item_id` 合并去重；没有请求续页的来源不要重复累加。某一路不可用时保留其旧游标和已读记录，成功来源可以继续推进；页面会显示部分失败并允许重试。根据 `sources.*.truncated` 和游标判断是否仍有后续，不能把单页当完整记录。

HTTP 403 表示授权无效/过期/Session 不匹配；重新联系管理员授权，不使用管理员浏览器 Cookie 补救。404 表示该会话没有记录。503 表示所需服务不可用；200 仍可能是部分来源可用，应读取 `sources`。有效凭据不证明 Session 一定存在。

[ADR0149](../adr/0149-session-journal-diagnostic-pagination.md)接通 Journal 原始 Session 查询：只回读该 Session 的 `user.input` / `assistant.output`，验证其唯一 tenant/user/thread，不依赖遥测第一页推断身份。共享线程中的其他 Session 不混入；独立输入证据记录不充当对话身份。多对话 scope 冲突明确不可用。私有来源按序列分页，一页最多200条；游标根据扫描记录推进，空文本页也可有后续。

部署须同时更新 Next.js 与后台，并由部署者在维护流程中执行新增0035并发索引迁移。自动服务启动不执行迁移；迁移加载器拒绝无效/不兼容索引，详细恢复说明见ADR0149。旧后台没有 `/conversation-page` 时，对话来源明确不可用，不回退未经验证的整线程记录。传统 `/conversation` 数组接口仍保留1000条线程与遥测5000条身份页的保守拒绝策略；统一诊断GET不再使用该旧路径。

管理员授权服务：同源、已登录管理员可以 `POST /api/observability/sessions/{sessionId}/diagnostics/access?agent_id={name}`。响应 201 返回凭据；匿名、非管理员、机器单独调用或来源不匹配返回 403；独立密钥未配置返回 503。凭据绝对有效期 15 分钟，管理员移除权限不立即撤销已签发凭据；轮换独立密钥可以一次撤销全部凭据。当前没有单凭据提前撤销或持久签发审计。
