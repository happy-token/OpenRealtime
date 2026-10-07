# Realtime 投影与恢复类型契约修正

日期：2026-10-07，前置提交 `ab2c7cc`。这是一批后续接口补强，不是公开后自动回复纠正或 G3 验收。

## 改动

扩大最终输出许可的类型检查时，runtime、tool_controller、endpoint_bridge 有12项已确认来自前置提交的诊断。本批修复这些诊断，并把确认消息的 Journal 恢复解析纳入同一检查范围。

- 新增结构协议 `CommittedItemProjection`，仅声明 `send(ProjectCommittedItem)`。工具与委派控制器使用这个已有能力；共享 JournalCommittedProjector 不承担会话事件流和关闭职责。既有 RealtimeConversation 的宽命令入口仍结构兼容，不需要强制转换或实现虚假的 lifecycle 方法。
- 确认消息与恢复解析逐字段验证字符串，确认通道使用 `Literal["voice", "strong"]`。Journal构造边界的类型转换仍由原 `__post_init__` 实际校验；保留无效字段、时间、身份、摘要、未知通道的既有 ValueError/TypeError 契约与错误优先级。
- endpoint 的槽位标注为实际 `_ReconnectableConversation`；命名条件函数仍通过默认参数冻结原 generation。恢复事件尾列表精确声明为 phase/ready 两类，不扩大 wire 契约。
- 异步故障恢复使用已核对的局部 recovery 引用；不存在恢复策略时有明确返回。

没有新增业务 actor、输出队列、重连机制、数据库迁移或供应商调用。

## 验证

- 全量 Python：2155 passed、69 skipped、3 subtests passed，47.06秒。
- 工具/委派/装配/endpoint/控制恢复及最终输出许可定向69项通过；新增4项真实Journal回读负例，确认身份/摘要/通道/时间同时出错时的失败优先级。
- 10个生产模块 Mypy 通过：Core、协议、Bridge、Journal、TurnController、工具、委派、Managed runtime、endpoint 与控制恢复。
- 7个修改Python文件（含测试）Ruff、diff检查通过。
- 两位独立审查批准；代码审查复跑34项并在最后校验修正后复跑控制恢复7项，Python审查最终复跑27项。组合错误的优先级变更在审查中发现并恢复原契约，负例检查通过。

此处的类型通过仅覆盖列出的10个模块，不代表整个仓库类型检查。用户服务未重启，未执行真实模型/物理音频验收。

## 下一项

公开后上下文失效目前能撤销旧输出并记录失败；自动新版本衔接仍未实现。后续应使用显式原因和身份驱动已有 actor/版本账本，避免解析错误字符串触发重试：新 response_id 绑定相同有效 input_id/input_version、supersedes 和最新已听依据；准备、停止、真实资源清理与新输入竞争分别验证。已执行工具/委派的结果及未决状态必须先纳入衔接，不因更换 response_id 重放副作用；请求次数、绝对截止与关闭所有权必须有界。

阶段3/G3、G0–G5其余未验收项与诊断/双路录音/Agent接口横向轨道保持开放。
