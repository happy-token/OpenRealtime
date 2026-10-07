# Agent 按 Session ID 排查

管理员进入设置 → 会话诊断 → 对应会话详情，在“交给 Agent 排查”区域点击“生成 Agent 只读凭据”。下载文件只授权当前 Session，15 分钟后失效；将该文件和问题描述交给排查 Agent。普通“导出诊断 JSON”不包含授权凭据。

部署者先在 Next.js 服务端配置独立随机 `OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET`（至少 32 字符），不要复用其他密钥或配置为公开环境变量。未配置时页面明确提示授权尚未配置，不自动生成共享密钥。配置示例文件留空；本次实现没有修改运行中服务的秘密或重启服务。

Agent 从文件读取 `endpoint` 和 `authorization_header`，以 `GET` 和 `Authorization` 请求头查询，不要将凭据写入链接、日志或错误报告。请求必须在凭据有效期内，生产环境使用 HTTPS；Session ID 与凭据必须匹配。Agent 无法列出其他会话、查询全局总览、修改账户或自行刷新权限。

响应 `schema_version: 1`：

- `telemetry`：该会话的事件、指标和 `next_cursor`。
- `conversation`：当前页的已提交对话记录；`conversation_next_cursor` 表示后续页。每条记录的 `journal_sequence` 是十进制字符串，不能转成 JavaScript Number。
- `debug_log`：决策日志和独立的 `next_cursor`。
- `input_evidence`：原始 Session 的已提交输入证据，包含 ASR 改写、语义判断与纠正记录；`next_cursor` 和 `sequence` 为十进制字符串，保持原样使用。`not_collected` 不表示用户没有输入，`durable: false` 表示临时存储。
- `sources`：每个来源的可用性和截断状态。缺失数据不代表事件未发生。
- `audio.status: not-queried` 与 `audio.catalog_url`：录音目录是独立来源，使用同一请求头查询；该状态不表示录音一定存在或已回放。旧部署可能仍返回 `not-configured`。
- `collection_health: null`：机器凭据不提供全局采集健康状态。

如 `telemetry.next_cursor` 非空，下次传 `telemetry_cursor`；如 `debug_log.next_cursor` 非空，下次传 `debug_cursor`；如 `conversation_next_cursor` 非空，下次传 `conversation_cursor`；如 `input_evidence.next_cursor` 非空，下次传 `input_cursor`。四路分别推进，日志按 `event_id`、对话和输入证据按 `item_id` 合并去重；没有请求续页的来源不要重复累加。某一路不可用时保留其旧游标和已读记录，成功来源可以继续推进；页面会显示部分失败并允许重试。根据 `sources.*.truncated` 和游标判断是否仍有后续，不能把单页当完整记录。

HTTP 403 表示授权无效/过期/Session 不匹配；重新联系管理员授权，不使用管理员浏览器 Cookie 补救。404 表示该会话没有记录。503 表示所需服务不可用；200 仍可能是部分来源可用，应读取 `sources`。有效凭据不证明 Session 一定存在。

[ADR0149](../adr/0149-session-journal-diagnostic-pagination.md)接通 Journal 原始 Session 查询：只回读该 Session 的 `user.input` / `assistant.output`，验证其唯一 tenant/user/thread，不依赖遥测第一页推断身份。共享线程中的其他 Session 不混入；独立输入证据记录不充当对话身份。多对话 scope 冲突明确不可用。私有来源按序列分页，一页最多200条；游标根据扫描记录推进，空文本页也可有后续。

部署须同时更新 Next.js 与后台，并由部署者在维护流程中执行新增0035并发索引迁移。自动服务启动不执行迁移；迁移加载器拒绝无效/不兼容索引，详细恢复说明见ADR0149。旧后台没有 `/conversation-page` 时，对话来源明确不可用，不回退未经验证的整线程记录。传统 `/conversation` 数组接口仍保留1000条线程与遥测5000条身份页的保守拒绝策略；统一诊断GET不再使用该旧路径。

管理员授权服务：同源、已登录管理员可以 `POST /api/observability/sessions/{sessionId}/diagnostics/access?agent_id={name}`。响应 201 返回凭据；匿名、非管理员、机器单独调用或来源不匹配返回 403；独立密钥未配置返回 503。凭据绝对有效期 15 分钟，管理员移除权限不立即撤销已签发凭据；轮换独立密钥可以一次撤销全部凭据。当前没有单凭据提前撤销或持久签发审计。


[ADR0153](../adr/0153-authorized-session-recording-api-and-player.md)补充当前 Session 录音访问。使用下载文件的 `recordings_endpoint` 或统一响应的 `audio.catalog_url`：

- `GET /api/observability/sessions/{sessionId}/recordings?limit=200&after_sequence=0`，以 `next_cursor` 原样推进 `after_sequence`。序列保持字符串；失败保留游标，不把单页当完整目录。
- 每条记录包含 `direction`（input/sent）、epoch/speech/stream、sample范围、原轮次/响应、保留期限、临时/持久状态、摘要及保护的 `audio_url`。仅转发白名单字段，不返回对象存储地址。
- 用相同 Authorization 请求头 GET `audio_url`。到期/删除返回410，缺少原始引用返回404，存储/完整性错误返回503。目录的available表示metadata验证通过，物理对象仍可能读取失败。
- sent表示物理发送完成，`playback_confirmation=not-inferred`；不能以播放器能播放推断用户当时已听到。客户端确认映射仍待补齐。

管理员详情页的“查看录音”独立加载，可分页、选择一个片段播放；普通Agent凭据无保留/删除能力。Memory存储不跨重启，PG缺对象配置时目录/播放明确不可用。新录音仅适用于更新装配后的新Session，旧Session不回填。部署者需受控执行0035–0037并发索引/保留迁移并同时更新后台与Next；自动启动不执行。真实S3、实际管理员/外部Agent和浏览器音频验收仍待部署验证。

[ADR0156](../adr/0156-admin-session-recording-preservation.md)新增目录 `preservation` 状态与管理员“长期保留”按钮。GET仍使用同一只读凭据，状态不可用不表示未标记或没有录音；等待完成的数量不证明物理上传结束。只有现有录音目录核实为unmarked时按钮可用，确认标记后自动刷新；结果未确认时先刷新核查，不能当作操作失败或已保留。临时存储会明确提示重启后不保留。

管理员同源可空体 `POST /api/observability/sessions/{sessionId}/recordings/preservation`，不接受客户端actor/source/query。Agent Authorization即使有效且同时有管理员Cookie也会403。Next完成管理员校验后向私有后台发送限定Session/原始body/60秒窗口的签名证明；部署须让两服务使用相同既有32字节 `VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY`，没有或不匹配则拒绝，不自动生成。受控部署需补0038，长期保留政策及历史删除保护在原来源上执行；已过期/删除的片段不恢复。新签名采用独立领域派生，不能用Agent只读密钥代替。私有接口仍须保持内部可达；本批未改变生产密钥或迁移。

隔离管理员/无Cookie机器凭据/WAV浏览器链路已验收；真实S3、生产部署、录音完整性和原交互confirmed renderer映射仍待验收。浏览器回放完成不能证明原通话中已播放。

[ADR0161](../adr/0161-session-authoritative-input-evidence.md)将输入证据改为 Journal 原始身份查询，不依赖遥测第一页或本地账号猜测。私有 `/input-evidence` 使用同一来源，一页最多100条；真实空尾页保留已采集状态，不存在的来源不因请求游标变成已采集。部署者需在维护流程中受控执行0041并发部分索引，并同时更新两服务；本次仅隔离测试库执行，没有修改运行中服务。
