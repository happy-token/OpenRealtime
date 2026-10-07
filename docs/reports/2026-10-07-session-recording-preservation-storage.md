# Session 录音长期保留：存储基础

本批继续“commit，继续未完成的”，落实[ADR0154](../adr/0154-session-recording-preservation-storage.md)。按原 tenant/owner/Session 保存首次标记时间与操作人，覆盖已保存片段与后续片段；上传中的片段不改变修订号，验证完成才转为不可变。已过期、正在删除或已删除片段不恢复；标记恰好到期也不恢复。Memory 明确临时，PG 重建 adapter 后政策仍存在。

独立 review 发现受保护 pending 上传占满清理前缀，导致其他孤儿永久无法清理。正式真实 PG 回归先阻塞首上传，再让另一 Session 实际写入后崩溃；`limit=1` 连续三轮仍未删除，复现红。现扫描先排除精确政策下受保护 pending，再限批次；锁内重验保留，失败和撤权任务照常清理。修复后孤儿删除，原上传仍持有许可并可最终验证保留。失败 finalize 会恢复到期清理意图。

验证：全量 Python **2624 passed、96 skipped、3 subtests passed，62.61s**；独立隔离真实 PG **27 passed，3.31s**；5 个生产模块 Mypy、限定 Ruff、diff 检查通过。两名既有 reviewer 对存储基础限定 APPROVE，清理饥饿 HIGH 已关闭。未修改前端，因此本批没有新增浏览器验收。

0038 仅在随机隔离测试 schema 应用并清理；未生产迁移、重启用户服务、调用真实供应商/S3 或 push。当前只有内部能力，页面还看不到标记操作。下一步接管理员授权、原 Session 来源在删除竞争中的重验、历史/manifest 删除保护与同主题按钮。真实回放、confirmed renderer 映射、录音完整性与 OBS02/OBS03、G0–G5 全量验收仍开放。
