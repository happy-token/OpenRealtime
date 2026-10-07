# ADR 0145：新 ASR 证据的误打断恢复规划

日期：2026-10-07。状态：Accepted，限规划证据；实际恢复执行及 G4 未完成。

## 背景

打断已执行后，ASR 全文可能实质改写为附和。原协调器会丢弃附和，但原回复仍被撤销，不能直接恢复其交付权限。ADR0144 提供已保存停播事实，本批把可靠新证据与原回复关联，供后续独立执行准入使用。

## 决策

复用现有 actor、ReplyRevisionController 和输入证据 Journal。接受可靠 INTERRUPT/CORRECTION 时，在撤销交付前冻结原 input/version/reply、重叠输入身份、触发文本和首次绝对恢复截止；STOP 不创建恢复锚。只有同观察输入的更高 ASR 修订且实质替换已接受停止前缀，才能提供恢复证据。单纯追加、等价标点变化、迟到同批结果不能翻案。

反馈必须是自然结束后的当前完整全文、同 generation/revision、SENTENCE_END、非 fallback 且达到阈值的 BACKCHANNEL/IGNORE；回答助手问题不作为附和恢复。当前完整可靠相反结论清除未执行规划，过期、partial、foreign、低置信和 fallback 继续忽略。已发停止不撤销，旧回复交付权限不恢复。

规划还必须具备 canonical STOP_CONFIRMED 与同 speech/epoch 的终态播放投影；未知停播不得签计划。精确样本/时钟相符才标 sample；否则如实标 unknown，依据已确认听见内容重新生成续答。原流取消后无法续播，本批策略为 regenerate_continuation。ReplyRecoveryPlan 为不可变证据 DTO，包含原 input/reply、观察修订、文本摘要、停播身份、已听位置、首次截止和拟议新执行租约/epoch。拟议 UUID 不改变实际上下文、版本或物理队列，也不构成播放/工具许可。

一个当前回复最多一份锚、最新全文及一份规划；不引入业务模块、第二个 actor 或播放队列。相同事实只记录一次；新语音/逻辑输入/回复/关闭、语义 STOP、截止或停止操作变化使旧计划不可消费。下一消费者在任何 await 后仍须重核当前性。

## 范围与下一步

当前真实 actor 只接入封口全文的本地规则反馈。账本接受 model 证据的契约已验证，但新 JEV 复核批尚未接入。事实/反馈两种到达顺序与并发容量 1/2 均有 actor 回归。计划用原输入证据记录 reply_recovery_planned，不发恢复动作。

接下来需接入有界、独立的新全文模型复核，规划消费与执行许可、Core 原输入/已听上下文准入、新回复及物理 epoch 切换、再次打断、幂等和未知停止失败出口。详见[报告](../reports/2026-10-07-misinterruption-recovery-planning.md)。本决策不关闭 ADR0138 或整体计划。
