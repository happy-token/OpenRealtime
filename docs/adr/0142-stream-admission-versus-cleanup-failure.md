# ADR 0142：区分流准入等待与资源清理失败

日期：2026-10-07。状态：Accepted，限既有预生成缓存的错误契约。

## 背景

ADR0141 规定未消费候选软退休，供应商实际退出前不准入新请求。真实 Chrome → WebSocket → Managed/Core 句末交接测试发现：缓存把「仍在等待旧供应商退出」报告为 `OwnedStreamCleanupError`，Brain/TTS 适配器因此保存永久清理故障。候选后来正常退出，会话仍无法关闭，连接与历史归属被持续隔离。

## 决策

在现有 `core/async_stream.py` 增加 `StreamAdmissionPendingError(RuntimeError)`，与 `OwnedStreamCleanupError` 同级。仅在退休候选尚未完成的接管检查和退休供应商的有界准入等待中使用。存储诊断的错误复制保留此类型。

准入等待表示本次请求没有开始，不证明任何供应商已释放，也不属于物理清理失败。正式请求报告失败；原输入、旧供应商归属和准入屏障继续保留。适配器确认自己未准入的请求迭代器已经退出；会话的预生成控制器仍负责 join 旧供应商。关闭等待者取消不改变该归属。

真正的迭代器 `aclose`、provider 退出或关闭失败继续使用 `OwnedStreamCleanupError` 并保持原有永久隔离和历史删除保护。没有新增业务 actor、播放队列或重试循环，也没有承诺任意供应商可被强制释放。

## 验证

三个真实适配器回归先失败后通过：文本缓存 → Brain、语音缓存 → Brain、语音缓存 → NativeTTS。新请求不启动供应商，旧候选不被取消，旧供应商未退出时组合所有者关闭仍等待，退出后关闭成功。真正清理失败的既有反例继续通过。完整浏览器证据与范围见[本批报告](../reports/2026-10-07-production-handoff-browser.md)。本 ADR 不关闭 G3 或 ADR0138。
