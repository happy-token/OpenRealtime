# 输入 / 回复版本与交付隔离：ADR0136 首批实施

日期：2026-10-06。阶段2部分完成，ADR0136保持Proposed；一般补充语义关联、句末衔接、误打断恢复及真实G2尚未验收。

## 本批行为

新增 `ReplyRevisionController`：由既有协调actor同步驱动，只保存当前输入与回复记录，不启动任务、不调用模型、不操控音频。逻辑输入有 `input_id/input_version`，回复有 `response_id/reply_version/supersedes_response_id`。既有generation继续表示执行租约。续接输入沿用逻辑根并递增版本；新问题重建根。重发当前绑定不恢复已撤销的许可。

正式ASR提交将版本信息送入InputTranscriptCompleted和用户Journal记录；ResponseStarted及助手Journal记录携带对应回复版本。ASR观察上下文与正式提交上下文分别保存：输入证据封装保留实际观察身份，`logical_input_id`与嵌套`input_revision`保留逻辑根、正式turn/generation，避免重用ASR turn时日志覆写版本上下文。完整输入与修订历史留在Journal，实时账本只保留当前状态。

未播旧回复被替换或取消时，actor先撤销交付许可，再等待取消动作。许可复用同一个账本，经Cascaded engine、Journaled、Tool、Delegation、Turn、Managed和最终WebSocket边界传递；生产装饰链在出队时重新校验，终止/失败/取消事实继续可见。Managed队列记录原delegate，切换实例后不交付旧实例的payload。外部直接Speech按其speech_id校验，不能误用来源response_id。

取消与自然生成完成竞争时，固定原任务引用，避免等待后选中另一轮任务。若旧生成已自然完成，仍结算原播报并发送独立停播通知，不制造第二个ResponseCancelled终态。清理前保存原回复context，通知与日志继续关联原turn/generation。直接播报使用真实`response:delivery:<id>`键结算，清除未结算集合。preparing失败会清理已创建任务及admission，不启动Brain。

模型结论与接纳原因分离：`endpoint_decision/endpoint_source`保留原判断，`admission_reason`区分语义完整、判停等待截止、恢复截止、打断确认及旧播放自然结束后的补充。恢复截止不再伪装JEV COMPLETE。尚在播放且意图仍未确认的重叠输入达到截止时，保留输入并显式报错结束会话；这只是有限失败出口，不等于已能区分所有背景噪声与重要补充。

已执行STOP继续锁定，不重新调用JEV裁决同一停播。STOP后的新增正文继续进入提交路径；可靠本地规则仍可抑制纯STOP、附和或忽略内容。版本证据offer失败会同步冻结交付，再走显式失败出口；即使队列满而尚未形成异步recorder.failure，也不能放行旧回复。

## 失败回归与验证

先用3项协调回归、2项真实engine队列回归复现问题，再接线版本与许可。末轮审核另外复现两项失败：自然完成停播通知误用新输入context，以及直接播报完成竞争未结算交付；修复后均通过。

新增4组测试共21项：

- 账本替代、幂等、失效不可恢复、播放事实及1000次提交只保留当前记录。
- 原ASR turn重用 / 新turn的补充版本、正式turn与generation增量、结构化证据、原判停标签与截止原因分离、未决重叠失败出口、证据队列满时即时冻结。
- 实际Brain→TTS→engine的迟到文字/音频取消隔离。
- 实际生产装饰链三种装配、已取出事件的最终WebSocket校验、自然完成与取消竞争的精确停播、直接播报竞争结算、preparing失败及外部speech身份。

测试使用本地确定性桩；工具/委派装饰链验证许可透传，不代表真实工具副作用取消已验收。WebSocket停播帧证明服务器发出正确命令，不证明物理扬声器已停止。

最终全量Python：1692 passed、62 skipped、3 subtests passed，36.81秒。新增21项定向回归通过，独立两位审核复跑21项均通过；发现的业务问题已修复，最终代码审核批准本批。核心9模块Mypy通过，限定18文件Ruff及git diff --check通过。扩大类型检查时，既有Tool/runtime/endpoint bridge仍有基线类型错误，本批未宣称全仓Mypy通过。

## 尚未完成

关联判断仍复用当前协调策略，并非完整语义关联器；一般补充、新话题、澄清的可靠识别与G2仍开放。版本账本目前覆盖运行中ASR正式提交，不是跨Session恢复或持久幂等重建。

当前句精确许可、heard_frontier重验、实际stopped/STOP_UNKNOWN与句末交接按ADR0137实施；新播放epoch的误打断恢复按ADR0138实施。不能用本批整回复失效替代保留当前句的目标交付策略。

既有上层输出队列及全部外部任务的资源上界没有由本批测试证明。真实Postgres故障、外部模型、录音oracle、物理renderer、多会话负载与配对延迟未测试。用户3010及8765/8766服务未重启，当前运行服务不因此自动加载新后端实现。
