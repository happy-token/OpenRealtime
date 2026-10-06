# 2026-10-07：精确停播诊断与正常关闭清理

本批承接 `3a10515`，将 live 精确停播操作接入现有 SessionTelemetry 写入队列、PostgreSQL JSONB 适配层和 Session ID 统一诊断接口。不是 actor 持久恢复账本，不能关闭 ADR0137/G3。

## 行为与计时口径

- 记录 requested、receipt、handoff_ready、handoff_failed，关联被停止的原 generation/turn/response、epoch、speech、stop_command_id 和已播放样本位置。
- 三项成功指标：发送命令至匹配本地队列回执、回执至服务端播放事实投影与放行、请求至交接总等待。使用服务端同一单调时钟，包含回执传输；不能推断物理扬声器停止。总等待与子阶段重叠，不重复相加。
- 未知、过期、回执超时、投影超时和取消的经过时间保留在 observed_wait_ms 元数据中，不填入成功 duration。一次操作只产生一次交接失败统计；重复/错配回执不增加成功样本。事件不是用户轮次终态，不增加 turn_count。
- 收到有效 queue_stopped 后保留 STOP_CONFIRMED，即使投影失败，handoff 仍 denied，禁止新音频放行。投影截止独立记录 playback_projection_deadline/TIMEOUT。
- 诊断组件沿用项目主题，显示三项数字及悬停说明；打断详情和回放时间线保留操作事件，导出/统一 API 保留原字段。

## 关闭与日志隔离修复

真实 Endpoint 取消运行且入站泵正在等待投影时，先取消泵曾导致正常挂断被误报为投影取消异常。新增同步 begin_close 在取消泵前结算 session_closed，随后完成原有异步清理；已确认停止事实不撤销。

同步诊断观察器的普通异常与 CancelledError 均在观察边界隔离，不能阻止停播发送、音频放行或关闭。业务任务在异步 transport/projection 边界的取消仍正常传播。日志队列满时沿用 collection_health 的丢弃统计，不阻塞实时控制链。

## 验证

先失败再修复：正常 Endpoint 关闭原因、投影超时误计普通错误、观察器 CancelledError 泄漏、前端指标名称/停播事件过滤。

最终 Python：1826 passed、62 skipped、3 subtests passed（37.48秒）。前端：1273 passed、7 skipped。独立审查：后端111项定向通过，前端与API30项通过。限定8文件Ruff、3源文件Mypy、TypeScript、ESLint和diff检查通过。

Chrome 独立3012服务：真实诊断组件开发预览1项通过，验证100/40/140ms、悬停说明和操作/样本/轮次详情。首次测试因把已有格式100ms写为100 ms失败，修正断言后通过，没有修改产品数字格式或增加等待时间。预览数据是合成样例，不是真实语音或模型测量。

存储验证是实际 PostgresTelemetryStore 的 append/session_detail 适配层测试，执行器模拟数据库；统一 Next API 使用模拟上游验证透传。没有据此宣称已验证真实 PostgreSQL 或真实模型。现有实时服务未重启。

## 仍未完成

诊断使用既有异步队列，可能丢弃或写入失败，健康状态需一并检查；不承诺 actor 恢复所需的写入确认。持久停止事实、actor 当前句许可、未来句清理、heard_frontier 重验、误打断恢复、真实renderer/G3和其余计划继续开放。前批 Chrome 首轮音频完成间歇缺失尚未定位，数字人 void 取消仍不构成实际停播确认。
