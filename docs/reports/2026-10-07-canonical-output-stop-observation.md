# 已保存停播事实与手动输入纠正链路

日期：2026-10-07。范围：[ADR0144](../adr/0144-canonical-output-stop-observation.md)，ADR0138 前置事实边界；误打断恢复/G4 未关闭。

## 发现和修复

新增真实组合回归先红：Core 保存完成，但当前回复 output_stop 为 None；实际手动输入的精确停播命令也一直没有进入 actor。定位为 ManagedRealtimeConversation 先截获并独立保存 RecordOutputStop，随后直接返回，Core 新通知分支不会被调用。不是通过放宽回复租约校验解决。

应用层保存后读取 canonical 返回值，经原包装链的可选观察接口通知 actor；无应用共享存储的 Core 直接路径也先保存后通知。沿用现有 actor、账本和 Journal，无新增生产模块/actor/播放队列。通知阶段仍纳入在途写入所有权；重配置先撤销目标，关闭禁止晚到通知。存储失败不更新 actor；晚到旧 REQUEST 返回 canonical 已确认状态，不将已确认事实回退。

Bridge 分配 output_epoch 内服务端递增操作序号。账本只保存当前回复一个停播事实，不通过UTC排序；较旧/未知顺序操作不得覆盖新操作。不同 Session/租约/response/speech/已知epoch 不能匹配。观察事实不恢复交付权限，不把停止样本冒充已听位置，不自动签发恢复。新回复和关闭隔离旧事实。PG现有JSON可往返新可选字段并读取旧行，无表迁移。

## 回归证据

- 两个真实 UserTextFrame 用例覆盖旧/精确回执模式：输入规范化、Journal手动根ID、版本一、真实模型回复、旧已听事实变化使当前回复失效、Bridge请求停止、匹配回执/播放投影后才创建新回复版本。精确模式读取输入证据，REQUEST/CONFIRMED关联原input/reply与同服务端序号，替换版本不继承停播事实。
- 纯账本反例覆盖不恢复权限/播放位置、终态不可改写、8种范围/租约失配、speech/epoch失配、UTC逆序下服务端序号排序、缺失/重复顺序、新版本及关闭隔离。
- 实际 Core/Managed 组合对无包装、工具、工具加委派三种链路阻塞存储：保存完成前actor无事实；保存后收到canonical；REQUEST晚重放不降级；第二操作保存失败保留原事实。
- 实际 Managed 生命周期覆盖存储在重配置前/期间开始、晚到完成及非合作关闭写入，保存成功但不得通知旧或替换 delegate。现有关闭/会话删除归属测试继续通过。
- PG JSON编解码覆盖旧行及1/512序号；非法序号拒绝。这是编解码验证，本批没有启动真实Postgres。

初始PG编解码测试夹具漏填state列，3项失败；补齐真实行字段后全量通过，不把夹具失败描述为产品缺陷。早期手动链测试使用了已停止目标的自然结束，后修正为仍有效原目标的真实finished投影；不声称单独工具结果就能触发该纠正。

最终 Python：**2360 passed / 69 skipped / 3 subtests passed，53.00秒**。限定19文件Ruff、14生产模块Mypy及git diff --check通过。基础 turn_manager.py 的既有 `_pending_endpoint` 类型推断问题仍在当前639行，前批HEAD已有；不宣称全仓Mypy通过。

两位独立审查初轮各130项目标回归通过。代码审查额外复现重配置前置取消失败留下live handle/observer=None，已补4项真实Managed红→绿回归：取消旧输出/关闭旧delegate的异常及CancelledError。失败后同步关闭隔离handle，复用原owned cleanup；旧close已开始而未确认则明确失败并保留suspended删除保护，不重试已closed包装器冒充底层清理成功。初始old-close反例也暴露该包装器短路后等待pump不退出，现有失败清理出口已明确结束等待。代码审查复核批准，独立106项相关回归通过；Python复核再发现未确认关闭分支提前抛错，漏掉现有恢复任务取消。扩展4项生命周期测试，FakeDelegate通过实际Factory/包装器/Managed事件泵先发CapabilityFailed并阻塞恢复策略：旧close异常/取消两项精确红（恢复task仍pending），将原cancel/gather移到未确认关闭失败报告之前后4项绿。初始failure输入放入InMemory队列被其测试适配器白名单拒绝，改由FakeDelegate.events输出正确事件；不将该夹具错误作为产品发现。两位审查最终限定批准；代码审查额外58项相关回归通过，Python审查额外4项生命周期回归通过，Mypy/Ruff/diffcheck通过。

真实 Chrome/WebSocket/WebAudio 四场景：**4 passed，18.5秒**，覆盖文本/语音正常句末与未退出候选撤销，使用独立3027及loopback fixture。ASR/JEV/模型/TTS受控，PCM为合成静音；不是手动输入纠正的浏览器全流程验收，也不是真实录音、外部供应商延迟或声学停播验收。

## 未完成部分

新可靠ASR证据的误打断恢复、新许可/回复/播放epoch、再次有效打断及UNKNOWN停止出口仍待实施。G0/G1/G2/G3/G4/G5与诊断、双路录音、机器只读Agent接口继续按全量计划推进。既有间歇页面异常未确认原因，不因本次四场景通过就关闭。

默认关闭的句末候选产品开关未启用；用户3010/8765/8766服务未重启，用户数据库未迁移，未推送远端。
