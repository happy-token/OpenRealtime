# 阶段0与阶段1首批实施记录

日期：2026-10-06。依据[实施计划](../design/2026-10-05-voice-correction-implementation-plan.md)、[ADR0135](../adr/0135-bounded-parallel-semantic-candidates.md)与[ADR0139](../adr/0139-separate-semantic-execution-from-turn-decisions.md)。本批落实分类执行和并行结果裁决；纠正回复、句末切换、误打断恢复仍按0136—0138推进。

## 1. 当前落地行为

独立chunk继续由稳定标点、长度阈值和停说封口触发，禁止每字符请求。并发1/2使用相同累计判停文本和模型提示词，消除了容量参数改变输入语义的问题。累计文本从有效候选映射回原始ASR文本，保留标点；尚未到该候选的后文不进入其判断。

语义打断请求保留独立局部`transcript`，另带冻结`cumulative_transcript`。规则先检查局部文本及已确认前序反馈；模型判断截至该块的累计含义。candidate/verdict绑定同一累计范围，不能将局部尾段的“不打断”误当作完整输入结论。JEV、LLM和兼容classify入口均已接入；调用触发次数不随payload范围变化。

STOP发出前，已接受的最新完整IGNORE/BACKCHANNEL取代晚到的旧停止前缀；STOP发出后锁定，同批相反结果不能撤销。只更新revision、标点或空白时保留当前证据和原判停绝对截止。真实语义改变或声学活动恢复使旧截止失效。

“完整”指候选累计快照范围完整，不等于sentence_end。抑制旧STOP只需要最新全范围标签通过通用分类阈值；丢弃前序输入才需要下文更严格的policy确认。最新partial BACKCHANNEL可以不打断并保留输入，不能因它仍需保留而让旧prefix抢话。额外回归覆盖.7转UNCERTAIN不享该优先权、.9/.99 partial不打断且不丢输入。

前序块尚未返回时，不能假定它只是附和。因此“改查上海天气，嗯。”中的尾部“嗯”不能通过局部快捷规则掩盖尚未确认的纠正。前序模型标签超过通用分类阈值，也不代表已确认附和：反馈证据必须是非fallback的BACKCHANNEL，且actor policy已经决定不停止、不接纳该输入；未达可靠附和阈值、partial未决均不算。所有前序块均有这种可靠证据后才允许尾部反馈快捷路径，正对照保留不调用模型的规则路径。

完整输入退出使用注册器clear，同时清理已完成但结果仍排队的请求token。完成的chunk执行记录移除，提交/恢复等业务timer标记保留；任务族取消不依赖执行记录是否仍在jobs中。

## 2. 执行截止与取消边界

`ClassificationExecutor`按会话限定未结束的真实分类调用数量。异步plugin不配合取消时，调用者在deadline退出，残留任务继续占槽，迟到结果和stage不能写成当前成功；满容量拒绝新调用并记录原因，避免无限创建残留任务。

ASR改写取消旧调用后，合作取消可能尚未完成。仅这种交接给最多50ms的有界等待，计入同一绝对deadline；实际仍在运行的普通请求不会进入无界队列。记录独立`turn_policy.{operation}_capacity_wait`，provider_call保留配置`timeout_ms`并补实际`effective_timeout_ms`。这段等待与JEV共享槽位等待是不同事件，不合并成纯模型推理。

close撤销执行有效性并结束仍等待的owner；已超时返回的owner与残留调用解除关系，关闭不会取消它后续的其它工作。关闭有界等待后报告残留数量。该机制约束异步等待与任务数，不能隔离同步阻塞事件循环的CPU代码，也不能声称远端供应商已经取消计算。

## 3. 回归与独立复核

本批先复现后修复的主要问题：

|问题|失败证据|修复后断言|
|---|---|---|
|并发1仍使用独立suffix判断EOT|同一累计输入对照中1失败、1通过|两档相同累计文本和标点|
|等价ASR更新清掉最新负例|revision/标点组合出现晚到旧STOP生效|完整负例保留，无旧停播命令|
|完成任务消失后漏清queued token|提交结束仍残留旧endpoint token|完整退出requests为空|
|未决纠正被尾部附和掩盖|等待停播命令超时|模型完整范围保留前序纠正|
|未可靠确认的前序标签被尾部规则升级|BACKCHANNEL .9完整/.99 partial两例丢整轮；.99完整正对照通过|反馈proof与policy完整边界/阈值一致，未决前序走累计模型|
|合作取消交接误判满容量|替换请求没有进入provider|并发1下EOT/打断改写均能继续|
|executor.close仍接收吞取消后的成功|close后调用或stage记成功|caller取消，残留隔离|
|关闭错误取消已退休owner的后续工作|caller后续工作被取消|只取消仍等待该分类的owner|
|等价更新使commit timer过期|revision/标点/空白3例均超时|保留原timer与绝对截止|

固定ASR事件与说明见[回放manifest](../../tests/fixtures/voice-interaction/README.md)。并行actor文件55项通过。独立code-reviewer和python-reviewer最终Approve，无未解决HIGH/CRITICAL；timer修改的联合复核分别103/98项通过，反馈proof及停播/输入保留的不同标准也均复核通过。

|验证|本轮结果|范围|
|---|---|---|
|Python全量|1594 passed / 62 skipped / 3 subtests passed，38.46s|最终工作树；未开启真实供应商测试，skip不算验收|
|Realtime/TurnPolicy|532 passed，7.94s|反馈proof修复后；追加3个证据标准用例已由55项actor及最终全量覆盖|
|前端播放基线|31 passed，6文件|WebAudio、输出控制、媒体时钟、Anam/LiveTalking/LiveAvatar；mock，不是实际设备|
|静态检查|本批actor、执行器、chunk/token、接口、3插件及对应测试Ruff通过；5个核心模块Mypy通过|未用局部Mypy代替全项目类型验收|

没有主动重启当前服务，没有新真实模型请求，也未提交Git。未新增业务控制器或第二个actor，复用已有调度、执行和任务边界。

## 4. 阶段0证据与未关闭门槛

[播放能力基线](2026-10-06-playback-capability-baseline.md)已区分WebAudio安排播放、SDK定时估算、服务端发送状态和实际设备事实。现有协议尚无稳定sentence_id与精确当前句许可；yield_ack仅确认服务端取消，不能放行“当前句结束后接替”或精确恢复。既有4个WAV未有本轮确认的语义/采样边界oracle，不能成为准确率或P95统计分母。G0仍部分完成。

AC13仍部分完成：pending/inflight/残留分类槽位和执行记录已补强，但buffer保留有效历史chunk及累计prefix。中文500/1000/2000字、每5字封块时，prefix副本总量分别25,250/100,500/401,000字符，约O(N²)。消息数上限也不等于字节上限：合并候选、单个英文词、标点串可以很长。当前没有明确单输入长度/字节/连续说话时长上限。

现有Journal没有完整ASR修订、候选签发和逐前缀反馈的安全回读契约，不能直接截断历史后声称证据可恢复。下一项先将累计prefix副本改为当前文本+offset/有效ID的线性表示，再随0136输入账本明确持久证据、实时窗口、payload预算及超额可解释出口。必须保留深改写有效前缀、冻结请求和未知前序证据；落盘失败不能裁掉唯一输入证据。G1未全部关闭，不以本批测试通过替代长输入资源验收。

其它未完成项：重要UNCERTAIN补充在旧回复自然结束后的归属/继续处理，未播纠正版本替换、实际句末交接、误打断恢复、双路录音存储、机器只读诊断身份。当前没有新增真实延迟平均/P95数据，也没有性能因果结论。
