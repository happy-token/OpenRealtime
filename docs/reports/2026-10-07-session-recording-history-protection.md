# Session 保留：来源和历史删除保护

在存储提交 `9dbd15d` 后继续[ADR0155](../adr/0155-session-preservation-source-and-history-protection.md)。内部 Runtime 标记接口从 Journal 核实原用户/线程，锁内再次确认来源；有录音时用录音权威页，没有录音时用对话权威页。未知来源拒绝，不按管理员推算。后续录音继续采用 Session 政策。

历史清理在任何修改前检查整批 Session；有保留项则整批拒绝。PG 使用排序的原来源事务锁，持久标记在重启且 S3 未配置时仍保护 manifest、输入证据、对话、停播事实和日志。Memory 使用共享 Store 的元数据协调锁，跨 Runtime 的标记/删除同样重验。只复用既有模块，不增状态机或队列。

原回归先红：标记后仍能删除历史。新增实际两 Runtime 的先标记/先删除交错均通过，晚到标记不会在已删除来源上创建政策。标记超时后实际任务仍占预算、阻止资源关闭，真实完成才结算。Review 又发现可插拔适配器标记失败被误报为“已保留”；正式红回归后修为只转译 deletion guard 准入冲突，操作体保留原异常。

验证：修复最后异常分类之前全量 Python **2630 passed、99 skipped、3 subtests passed，61.12s**；随后受影响最终回归 **33 passed，0.29s**。真实 PG 录音与 Artifact 合计 **95 passed，6.33s**（含新增三个竞争/重启用例）。两名既有 reviewer 限定 APPROVE。5 个相关生产模块 Mypy（忽略缺失第三方类型包）及限定 Ruff、diff 检查通过。

现有全仓 Mypy baseline gate 仍失败，不能报告为全仓类型检查通过。用临时目录归档同一提交 HEAD、相同 Python/mypy 全 server 对比：HEAD 97 条诊断，当前 96 条，没有新增；未扩 baseline。临时目录已清理。未运行新前端测试，本批没有修改前端。

未生产迁移、调用真实供应商/S3、重启用户服务或 push。当前是内部入口，页面仍未显示标记按钮。下一步接管理员专用 HTTP、目录保留状态和同主题按钮；Agent 仍仅有读取权限。完整 OBS02/OBS03、confirmed renderer、真实回放/录音完整性及 G0–G5 仍开放。
