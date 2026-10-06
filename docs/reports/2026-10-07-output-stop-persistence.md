# 2026-10-07：持久停播操作事实与交接写入屏障

承接 ADR0137 的事实前置。复用 SpeechDeliveryStore 与 SpeechLifecycle，不增加输入 actor、输出队列或纠正决策器。

## 问题和结果

live 桥接和异步诊断已经记录停播操作，但没有独立于进程的 stop 操作账本。speech 首个音频尚未到达时，也不能凭空构造 SpeechStarted 来保存取消事实。现在新增不可变 OutputStopFact，按 tenant/user/device/voice_session/thread/stop_command_id 存储 STOP_REQUESTED、STOP_CONFIRMED、STOP_UNKNOWN；原 turn/response/generation、epoch、speech、请求/观察/回执时间、精确样本位置及未知原因保持关联。

PostgreSQL 在同一事务中锁定操作行并校验不可变目标，终态不被迟到 REQUESTED 降级，相反终态和不同样本位置被拒绝，重复证据保留第一次观察。新增迁移 0034_speech_output_stops.sql，不修改已部署迁移，无历史样本回填，也没有依赖 speech 首包记录的外键。内存实现仅为本进程保存，不具有重启持久保证。

客户端停播命令不等待请求记录写入。一旦收到匹配的 queue_stopped，就立即保存确认任务；交接必须同时等待请求写入、确认写入和原播放事实投影。写入失败、取消或超时撤销后续交付许可，已经收到的本地队列确认仍保持 CONFIRMED；不能把“证据保存失败”改写为“本地没有停下来”。缺失回执的 REQUESTED 不能用于恢复播放许可，持久 CONFIRMED 也不会自动恢复旧版本/旧 epoch 的交付权限。

这里的确认仅针对本地音频队列，不保证物理扬声器已停播；尚未构成 actor 当前句许可或 heard_frontier 交接契约。

## 生产包装层和关闭边界

Review 找到真实 Managed 发送锁会让终态写入排在阻塞的 REQUESTED ack 之后，普通关闭的有界取消会丢掉终态。已先补普通、工具、工具加委派三种真实包装配置 × 收到/未收到回执的六个失败回归，再修复。

Managed 使用 Factory 绑定的同一个应用级 SpeechDeliveryStore，经 SpeechLifecycle 保存不可变事实，不等待 actor 的发送锁或可替换引擎委托。这样重配置关闭旧委托、尚未创建新委托时也能保存有效回执。原播放事实投影仍经会话屏障；新音频不因保存事实而提前获得许可。未配置共享 store 的兼容工厂继续走原串行委托路径，没有新建第二套账本，不能宣称该兼容路径也具备独立写入保障。直接 engine 命令能力和真实 Cascade 装饰器穿透另有回归。

独立事实写入由 Managed 跟踪任务归属。普通关闭及重配置/回滚双失败都先关闭新入口，再取消并最多等待 250ms；适配器尚未结算时保留 suspended 会话登记，最终写入完成回调才释放。Review 复现的“会话先注销→删除→迟到 CONFIRMED 重建记录”已补合作取消/吞一次取消 × 两种终止出口四个红绿回归。桥接关闭也有界清理自身写入；失败不会循环重试或重新放行。

## 删除和部署

停播事实加入现有会话删除流程，按服务端解析的 tenant/user/thread/voice_session 删除该会话所有 device 的记录，保留恢复会话及其他身份记录。PostgreSQL 删除与日志、输入证据、会话历史和 telemetry 共用现有事务；最后一项删除失败会整体回滚停播记录。内存删除遵循相同范围，但没有事务回滚保证。

本进程的 session_deletion_guard 拒绝活动和挂起的 owner，删除期间阻止同 Session 新 device 注册；共享 thread 上其他 Session 可以继续注册。冲突使用明确类型映射 HTTP409，普通存储故障保留 HTTP500且不暴露内部信息。这是本地进程保护，不提供跨进程删除互斥。

发布前必须经项目现有迁移流程应用 0034；本批没有对用户数据库执行迁移，也没有重启 3010/8765/8766。代码回退可以保留新增表；表删除需要单独的前向变更，不在本次提交中执行。

## 验证证据

- 最终完整 Python：1883 passed、69 skipped、3 subtests passed，41.80 秒；禁用实际数据库环境配置。69 skipped 包括 7 项明确 opt-in 的新 PG 测试，不作为通过样本。
- 新停播存储回归 28 项；另补会话删除 5 项、HTTP 冲突/普通错误 2 项。覆盖目标身份、终态冲突、错误确认、存储错误/超时、关闭、重配置、归属保护与新音频屏障。
- 自建 PostgreSQL16 私有 Unix socket 集群实测 7 项通过：迁移重复应用、新 store 回读、40 个并发写入、相反终态竞争、完整身份隔离、父事务回滚、精确删除及 ApplicationRuntime 删除失败的整体回滚。未使用应用 DSN；测试仅通过 VOICEAGENT_RUN_POSTGRES_INTEGRATION=1 与 VOICEAGENT_POSTGRES_TEST_DSN 显式启用。测试 schema 和整个临时集群均已清理。
- PG 池连接路径返回时事务已提交；加入外层事务的 connection 路径只释放 savepoint，不能把返回当作外层最终提交证据。生产 Factory 绑定应用级池 store，当前 Memory 与此持久性不同。
- 核心六模块 Mypy通过；扩展检查中的 27 条外围既有错误与 HEAD shadow-file 基线完全相同，无新增。全修改 Python Ruff、diff检查、前端 tsc/限定 ESLint及诊断目录 2 项 Vitest通过。
- 两位独立审查最终批准本批边界。真实 Cascade 测试使用确定性测试 provider，未测试真实模型延迟、真实音频或物理扬声器。

## 后续顺序和保持开放的范围

ADR0137/G3 仍开放：稳定实际句段身份、actor 签发绑定 input/reply version、epoch、句段和 deadline 的当前句许可；只保留一个实际开始句、清理未来句；生成前及实际交接时重验 heard_frontier；真实浏览器间歇首轮 finished 缺失和数字人 void cancel 没有真实 stop 确认仍需验证。

完整需求没有缩减：0136 完整语义关联、未归档动作持久检查点及全历史幂等/G2，0138 恢复新版本和新 epoch/重复打断/未知位置/G4，G0 真实标注音频、JEV 多会话公平/G1及 E01–E06 配对实验/G5，以及默认双轨录音、Agent 只读身份/API、异常因果去重和冷/热/重连指标仍未全部完成。此报告完成停播操作账本前置，不关闭整个实施计划。
