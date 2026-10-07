# 管理员录音保留与真实浏览器验收

承接提交 `eacde41` 和 [ADR0156](../adr/0156-admin-session-recording-preservation.md)，接通管理员 POST、私有签名证明、目录保留状态及现有主题按钮。Agent 只能读，任何 Authorization 都不回退管理员 Cookie。标记沿用 Runtime 原始 Journal 来源，不按管理员生成录音 owner；响应隐藏 actor/owner/对象地址。

Review 发现 optional getter 挂起会拖住整个录音目录。正式回归先出现 `recording_source_timeout`，修复后有效 rows 返回、保留状态 unavailable，真实 late task 仍受相同容量、删除和关闭保护；增加迟到失败与容量占满回归。没有新增任务队列或运行时状态机。

隔离 Chrome 首轮播 WAV 返回合法206，测试断言已改为核验 Range 和实际媒体完成。随后真实管理员 POST 返回403；正式单测复现 Next 将127.0.0.1规范化为localhost导致同源误拒绝。修复为按实际 Host 严格校验 Origin；不信 Forwarded、不允许 malformed Host 回退。另一503由本次夹具手工误输35字节测试密钥造成，接口正确拒绝，改用规范32字节测试密钥并重建夹具后通过。未修改实际服务密钥。

最终 Chrome **2 passed，16.2s**：真实 PG 管理员、真实 Runtime/Journal/Memory Artifact/WAV、Next→私有HTTP→保留政策、目录真实刷新、手机390宽度、无Cookie Agent目录/音频/摘要校验、Agent/匿名/跨站拒写，以及预览无录音请求。测试仅使用100ms合成输入PCM，没有真实麦克风、供应商、S3或用户已听到的证明。Python夹具原子CREATE认领随机测试schema，启动早期捕获SIGTERM并分层清理；独立启动期SIGTERM探针退出0且schema已删除。该spec需要外部显式启动夹具，不是日常E2E自动准备。

全量 Python **2637 passed、99 skipped、3 subtests passed，70.49s**；之后仅 POST 错误响应 no-store 与无语义差异格式调整，最终 HTTP/保留/CLI 回归 **42 passed，14.23s**。真实隔离 PG 录音+Artifact **102 passed，6.90s**。最终前端全量 **1414 passed、7 skipped，17.16s**。四个相关源码/夹具 Mypy、限定 Ruff/ESLint 和 TSC 通过；HTTP已有18条Mypy诊断，与HEAD消息完全相同，无新增，不能称全仓Mypy通过。两名既有 reviewer 限定 APPROVE。

隔离夹具和浏览器Next均已退出，实际查询确认拥有的测试schema已清理。可按[重复执行说明](../guides/recording-browser-integration.md)重建测试环境。

本批不执行生产迁移/部署、重启用户服务、真实供应商/S3或push。仍继续 confirmed renderer 映射、完整录音证据、OBS02故障因果去重/冷暖连接，以及全部原G0–G5，不将本次局部验收视为整体完成。
