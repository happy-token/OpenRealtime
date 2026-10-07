# Agent 按 Session ID 排查

管理员进入设置 → 会话诊断 → 对应会话详情，在“交给 Agent 排查”区域点击“生成 Agent 只读凭据”。下载文件只授权当前 Session，15 分钟后失效；将该文件和问题描述交给排查 Agent。普通“导出诊断 JSON”不包含授权凭据。

部署者先在 Next.js 服务端配置独立随机 `OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET`（至少 32 字符），不要复用其他密钥或配置为公开环境变量。未配置时页面明确提示授权尚未配置，不自动生成共享密钥。配置示例文件留空；本次实现没有修改运行中服务的秘密或重启服务。

Agent 从文件读取 `endpoint` 和 `authorization_header`，以 `GET` 和 `Authorization` 请求头查询，不要将凭据写入链接、日志或错误报告。请求必须在凭据有效期内，生产环境使用 HTTPS；Session ID 与凭据必须匹配。Agent 无法列出其他会话、查询全局总览、修改账户或自行刷新权限。

响应 `schema_version: 1`：

- `telemetry`：该会话的事件、指标和 `next_cursor`。
- `conversation`：已提交的对话记录。
- `debug_log`：决策日志和独立的 `next_cursor`。
- `sources`：每个来源的可用性和截断状态。缺失数据不代表事件未发生。
- `audio.status: not-configured`：录音存储尚未接入，不能声称已回放实际语音。
- `collection_health: null`：机器凭据不提供全局采集健康状态。

如 `telemetry.next_cursor` 非空，下次传 `telemetry_cursor`；如 `debug_log.next_cursor` 非空，下次传 `debug_cursor`。两个来源分别推进，以 `event_id` 合并去重；没有推进的来源不要重复累加。根据 `sources.*.truncated` 和游标判断是否仍有后续，不能把单页当完整记录。

HTTP 403 表示授权无效/过期/Session 不匹配；重新联系管理员授权，不使用管理员浏览器 Cookie 补救。404 表示该会话没有记录。503 表示所需服务不可用；200 仍可能是部分来源可用，应读取 `sources`。有效凭据不证明 Session 一定存在。

后端对话来源按记录的 tenant/user/thread 定位，再按每条记录的原始 `voice_session_id` 过滤，同线程续接会话不会混入。Agent 接口额外拒绝缺失/不匹配的来源身份。旧后端尚未部署时，对话来源可能显示不可用；不要绕过身份检查。当前对话数组接口最多扫描1000条线程记录，超过上限明确不可用，分页尚未接通，不能将这种情况理解为没有对话。

身份依据的遥测页若还有后续（目前单页上限5000条），本次对话读取也会明确不可用，避免后续页存在冲突身份却被遗漏。大Session的独立身份查询和对话分页仍需补齐。

管理员授权服务：同源、已登录管理员可以 `POST /api/observability/sessions/{sessionId}/diagnostics/access?agent_id={name}`。响应 201 返回凭据；匿名、非管理员、机器单独调用或来源不匹配返回 403；独立密钥未配置返回 503。凭据绝对有效期 15 分钟，管理员移除权限不立即撤销已签发凭据；轮换独立密钥可以一次撤销全部凭据。当前没有单凭据提前撤销或持久签发审计。
