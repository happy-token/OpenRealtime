# Session 95a9b382：未决问题在播放结束后丢失

日期：2026-10-06。Session：`95a9b382-1c3c-4a28-b45f-3b298a5db7b5`。

## 实际事件

以下为北京时间；读取原有 observability 事件301条、debug42条、已提交对话4条。未重新录音。

|时间|证据|
|---|---|
|15:11:40.819|提交“今天还行。可以帮我查询一下北京的天气吗？”|
|15:11:48.403|播放北京今天天气时进入 dual，用户继续说话|
|15:11:49.815|独立候选“明天天气”发起打断分类|
|15:11:50.032|下一独立候选“怎么样？”发起，累计分类文本“明天天气怎么样？”|
|15:11:50.735|完整文本的最终裁决 UNCERTAIN，confidence0.26，不停播、不创建轮次；JEV请求698.9ms，整体分类701.7ms|
|15:11:50.761|旧前缀最终裁决 UNCERTAIN，confidence0.5；整体分类946.2ms；非停止旧前缀被忽略|
|15:11:54.263|客户端 completed=true，旧回复自然结束，dual→listen|
|15:12:00.032|恢复截止后 listen→idle；无第三次用户提交、LLM请求或回复|

两请求实际重叠，供应商槽位等待各约0.006ms。此例不是串行排队，也没有分类超时。原始模型标签未在旧日志保留：运行时将低于0.8阈值的任何标签转换为UNCERTAIN，所以不能断言JEV原本直接选择UNCERTAIN。原始概率亦未采集，不能据此调整阈值。

会话摘要的 error/timeout/no_response 均为0，而 turn_count=2。未提交的第三段输入没有进入已提交轮次分母；这些零值不足以证明未丢输入。诊断需要继续补充未决输入终态与计数，而非把缺失误算成成功。

## 根因与修复

`ObserveSystemResponseCompleted` 设置 yielded=true，但自然结束不设置 floor_claim_confirmed。`_advance` 对 UNCERTAIN 的“保留输入、不抢话”分支未检查 yielded，旧声已经结束仍等待有效打断确认。恢复分支随后发出 `AsrDiscardRequested(reason="unresolved_overlap")`。实际读出事件与确定性actor回放共同定位该路径。

1. 自然结束释放旧播放占用后，保留输入可正常提交，仍不把UNCERTAIN升级为STOP。提交原因单列 `deferred_overlap_after_playback`。
2. 同批结果锁绑定 floor claim/已发出的yield；自然结束仍接收晚到模型结果。未决候选仍需完成后才能处置，避免使用旧前缀过早提交。
3. 自然结束后返回的正类不制造已执行STOP，负类仍可抑制新回复。
   独立审查还复现了旧STOP前缀晚到覆盖全文UNCERTAIN、删掉新增问句的竞争条件；自然完成后旧前缀只完成调度，由当前完整累计文本决定输入接纳。尚在播放时的有效前缀快速停播仍保留。
4. 已在JEV提示定义为附和的“哼哼”加入原有精确规则；规则插件、提问上下文、前序反馈保护保留。不新增长度或模糊关键词过滤，短纠正不按长度丢弃。
5. debug记录 raw_label、confidence_threshold、below_confidence_threshold，用于区分模型原始结论与运行时降级。原有模型confidence及有效label保留。

## 验证

初始 `uv run pytest -q tests/realtime/test_unresolved_overlap.py`：等待AsrCommitRequested超时，1 failed。新增播放先结束回归再次出现2 failed；修复结果锁后恢复。

最终17项回放覆盖：原问题累计文本、双候选返回顺序、分类前/后自然完成、原始UNCERTAIN及低置信度INTERRUPT、晚到IGNORE/BACKCHANNEL抑制、真实分类降级诊断字段，以及6个旧高置信度STOP/CORRECTION/INTERRUPT前缀不能覆盖全文的竞争回归。通过ASR final继续验证UserTurnCommitted包含完整后续问题，任务令牌清理。六个新增竞争回归修复前全部失败，修复后通过；132项相关回归和静态检查通过。

首轮完整Python：1606 passed /62 skipped /3 subtests passed，38.16s；随后独立审查增加了6项竞争回归并修复。修改文件Ruff通过，两个运行时模块Mypy通过。未修改UI或声学模型。

最终完整Python：1612 passed /62 skipped /3 subtests passed，37.10s。独立代码审查与Python审查通过，旧STOP竞争缺陷已关闭。

运行中服务在 `/sessions=[]` 再次确认后于15:38安全重启加载修复；健康、会话列表、总览与该历史Session读取均HTTP200，8765/8766监听正常。新后端PID23883，管理exec session3253。未进行新一轮真实语音/物理停播验收；历史记录不重写。

## 范围及未完成项

这是ADR0136自然完成后输入出口的局部实现，不是完整回复版本纠正。尚在播放时recovery统一丢弃未确认输入、任意噪声/乱码的可靠判别、真实句末切换、误打断恢复仍开放；AC11不能全部关闭。

真实JEV复测被自动审批拒绝：向外部服务再次发送具体会话文本尚缺明确授权。没有执行该外部请求，没有声称已改善模型准确率或真实停播表现。现有捕获日志和本地回放足以确认状态根因。

随后用户明确回复“允许”，已对获准天气片段完成18次真实复测，见[复测报告](2026-10-06-jev-weather-retest.md)。原输入/提示下可出现原始UNCERTAIN，也可出现低置信度INTERRUPT被阈值降级；简洁提示与累计主字段组合在该问句2/2通过现有阈值。扩展附和/撤回/乱码矩阵另被自动审批拒绝，未执行，提示候选未上线。
