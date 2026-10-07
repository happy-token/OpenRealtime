# 长会话播放回执定向查询

日期：2026-10-07。对应 [ADR0158](../adr/0158-targeted-recording-playback-lookups.md)，继续 OBS03。完整计划仍未完成。

## 问题与修复

实际 Runtime 的长会话回归先写入5001条通用遥测，再查精确播放回执。Memory 和 PostgreSQL 都返回 unknown，因为 ADR0157 只读通用诊断的第一页。另一个回归禁止迭代 Memory 的通用遥测列表，目录返回 unavailable。三条正式红证据分别为2 failed/.28s 和1 failed/.74s。

现在现有遥测 seam 增加可选 `PlaybackReceiptQuery`，每次最多200个完整原始附件身份键。Memory 在 append 时维护最大有效前缀的派生索引，读取只做附件字典查找，删除 Session 同时清理；较小迟到前缀不覆盖已有正证据，删除后重新写入零回执可正确显示零。PostgreSQL 查询既有不可变遥测日志，使用0039的严格采样位置/附件摘要函数及0040的并发部分表达式索引；单次SQL快照、每个请求附件最多一个最大前缀。摘要仅帮助索引，查询仍独立重验全部十个原始字段及nullable turn/response，不把摘要当授权。

录音 Reader 在同一实际任务归属、最多250ms可选等待及原目录剩余预算内使用定向能力。外层取消/超时不丢弃实际IO，迟到任务继续保护关闭和删除；坏返回值、错误或缺少索引只令播放证据 unavailable，已验证音频继续可读取。旧适配器仍走明确带截断状态的5000条诊断页；内置 Memory/PG 不再依赖该通用页。公共白名单、数字界面、Session读授权、管理员保留和 `playback_confirmation=not-inferred` 保持原合同。

## 审查发现并闭环

- 返回键中的 bool/float 与 int 在 Python 比较中相等，三条真实 Runtime 回归先红/.23s；现在先严格验证返回键，再检查请求成员与安全前缀计数。
- 合法 schema 在 `search_path` 可见时，PG反编译表达式省略schema，误拒合法索引。真实PG先红/.44s；索引验证使用独立 SAVEPOINT 规范化到pg_catalog，成功后显式还原原设置，失败则回滚。
- 未固定内置函数搜索路径的 IMMUTABLE 摘要函数会受同名 sha256 影响；所属测试schema中的影子函数回归先红/.44s。两个新函数都固定 `search_path=pg_catalog`。迁移尚未部署，不修改已经生产部署的不可变函数语义。
- 同形状 UNIQUE 索引可能破坏合法重复回执日志写入。仅改变唯一性的真实PG回归先红/.44s；校验明确拒绝 UNIQUE/排他索引，同时检查表、表达式、predicate、函数依赖、方向及ready/valid。

两个新增测试夹具曾构造超过安全微秒上限的样本，以及非法NULL turn的 InteractionContext；已修正为同时满足sample/micro边界，以及真实Observer生成的 TelemetryRecord 经公共存储 seam 写入nullable字段。Context准备在Runtime创建前，实际Runtime关闭覆盖finally；没有降低断言或修改业务上下文合同。

## 验证

- 全量 Python：2695 passed、111 skipped、3 subtests，61.66s。
- 本机现有 PostgreSQL `/tmp`、随机所属schema：65项相关录音、Artifact、Journal、Telemetry测试通过，7.84s；其中本批播放定向测试12项通过，2.42s。Objects仍是Memory客户端，非真实S3。
- 76项本地查找/关联/history/telemetry回归通过/.47s；完整键/计数、零/迟到最大前缀、删除重建、旧适配器fallback截断、可选慢/自身取消/迟到失败均验证。
- 真实PG样本函数与Python规范校验对比29个畸形属性案例，以及零、两个ties-to-even和最大安全微秒对应的样本位置。真实 `EXPLAIN (ANALYZE, FORMAT JSON)` 在5001条无关事件后使用 `runtime_playback_attachment_idx`，该索引节点Actual Rows=1且过滤丢弃行数为0。外层100ms statement_timeout和自定义search_path成功后保持原值。
- 本批无前端源码改动，相关路由/UI真实处理函数hook/SSR 43项通过，1.44s；TSC通过。隔离3029 Chrome 2项通过，16.5s，真实管理员/无Cookie Agent、定向采样交集、原生100ms WAV回放、保留2段刷新、手机布局和预览不读取私有音频通过。
- 四个相关源码模块Mypy、八文件Ruff、diff检查通过。显式检查 telemetry.py 的唯一错误为旧 `DebugLogEntry` list/tuple 注解不符，已从HEAD原文件复现相同错误；不声称全项目类型门禁通过。复用Python/代码审查员分别完成核心与最后索引修复限定APPROVE。
- 仅隔离fixture服务启动/退出，查询确认本批browser所属schema已删除，Next生成配置变化已核实还原。未重启用户服务、生产迁移、改变密钥/功能开关、调用真实供应商/S3或push。

复跑入口：`.venv/bin/python -m pytest -q tests/recording/test_recording_playback_lookup.py tests/recording/test_recording_playback.py`；实际PG加 `VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 VOICEAGENT_POSTGRES_TEST_DSN='postgresql:///postgres?host=/tmp'` 后运行 `tests/recording/test_postgres_recording_playback.py`。浏览器仍使用[隔离指南](../guides/recording-browser-integration.md)。

## 范围与后续

定向查询可以找到请求附件中已经持久化的最大有效前缀，缺少回执始终是 unknown，不能当未播放或零。成功返回及 `truncated=false` 不证明采集完整；一般诊断/Agent原始遥测分页保持独立。Memory派生字典随有效附件增长，其他通用诊断仍可扫描/排序历史；这里没有承诺总历史存储、进程内存或所有查询的全局资源界。PG SQL最多3s或沿用调用方更严格限制，操作等待4s；原目录可选观察预算更短且保留实际资源归属。

生产启用需按控制流程先0039、再0040（索引必须在事务外）；错误/旧库索引不自动重建。已经建好0040后不得原地改变0039函数语义，后续版本需新函数/新索引。实际生产DDL、部署、真实S3、录音完整度/实际原renderer与设备oracle仍待验收。OBS02完整输入聚合/因果错误去重/冷暖重连，以及全部原G0–G5标注oracle、JEV并发公平性及成对延迟准确率、未知动作持久幂等、补充/手动/模型交付与非协作/renderer/断连矩阵、供应商负载仍保持原范围，未关闭任何完整阶段。
