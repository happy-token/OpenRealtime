# ADR 0139：分离分类执行、异步生命周期与话轮裁决

日期：2026-10-05。状态：Accepted；当前执行边界已实施。

## 背景

有界并行后，协调器同时维护任务、请求令牌、候选与具体JEV分段采集。后续再添加纠正和恢复容易让单一actor承载异步机制、业务决策及输出处理。

## 决策

- SemanticChunkScheduler：纯候选队列、修订有效性、并发数量和语义上下文。
- SemanticTaskRegistry：异步任务、任务族取消、请求令牌、迟到结果一次性接受。协调器读取jobs用于计时器状态，但所有创建/取消/令牌写入交给注册器。
- classifier_execution：通用截止时间、provider call与任务局部分段观察。插件只上报自己的stage；协调器不引用JEV专用对象。
- CoordinatedTurnManager：单一actor处理输入与播放事件，决定结果是否有效、是否提交/停止。它仍保留实际业务状态；此次没有声称完成输入/回复状态的全面重构。
- 下一阶段统一ReplyRevisionController，集中回复版本、补充、修正及恢复意图；扩展现有预生成/播放控制，不各自创建纠正控制器、恢复控制器和衔接控制器。

2026-10-06澄清：ReplyRevisionController是actor同步驱动的版本账本/纯规划器。补充关联、恢复确认和播放许可由同一actor决定，账本不异步向输出发动作。实验工具放测试边界，不另建生产状态机。完成任务记录的生命周期仍需补强，不能把当前inflight上限宣称为总元数据上限。

## 已实施

SemanticTaskRegistry集中任务族和请求令牌；classifier_execution集中截止与分段观察。原边界整理将协调器的执行机制移入两个模块；后续补强扩展这些既有边界，不新增业务控制器。JEV保持兼容诊断别名，实际观察接口归属通用模块。

2026-10-06：注册器移除完成的chunk任务、保留业务timer及等待actor接受的token；完整生命周期clear同时清理排队token。执行器跟踪未结束调用和活动owner，超时退出不等待非协作plugin，残留占槽；合作取消交接最多50ms并消耗同一deadline，容量等待单独采集，provider记录实际剩余预算；close撤销结果有效性且不取消退休owner的后续工作。详见[实施报告](../reports/2026-10-06-parallel-hardening-implementation.md)。

## 后果与验证

原Realtime/TurnPolicy429 passed；新增令牌一次接受、旧结果不删除当前令牌、任务族取消隔离2 passed。后续回复版本控制及句末切换仍依赖ADR0136—0138。不能用当前解耦替代完整异常恢复实现。
