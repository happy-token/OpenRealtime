# ADR 0144：已保存停播事实进入原会话状态协调器

日期：2026-10-07。状态：Accepted，限 ADR0138 恢复所需的事实边界；实际误打断恢复与 G4 未完成。

## 背景

ManagedRealtimeConversation 已独立保存停播事实，使关闭/重配置期间的回执仍能落库。但它截获 RecordOutputStop 后直接返回，Core 中的新增通知不会执行。真实 Managed/Core/Journal/Bridge 测试证明存储成功时 actor 仍没有停播状态。

同一播放目标可能先获准播放当前句，再被撤销并要求立即停止。两个操作的保存/回执可以乱序；UTC 时间不能可靠决定哪个操作较新。恢复前必须知道当前操作的真实状态，不能把较旧确认当作新停止确认。

## 决策

保留应用层独立保存及关闭归属。SpeechLifecycle 返回存储确认的 canonical OutputStopFact；Managed 保存后通过可选 observe_saved_output_stop 通知原 delegate，经既有包装器进入 Core/input pipeline/actor。该通知不重复保存、不取得包装器发送锁、不启动另一业务 actor 或播放队列。没有共享应用存储时，Core 原 RecordOutputStop 路径仍先保存后通知。

重配置在取消/关闭旧 delegate 前撤销通知目标。写入开始时捕获目标；写入完成时仅原 live delegate 可收到事实。重配置期间没有可通知目标，已经保存的事实仍成功返回；替换/关闭后的会话不得继承旧状态。既有在途写入归属包含通知阶段。重配置前置屏障异常/取消且没有恢复有效观察目标时，同步关闭隔离 handle 并复用原清理所有权。旧 delegate close 尚未开始时正常清理；已经开始但未经确认时明确失败，保留 suspended 删除保护，不能依赖包装器已关闭后的短路重试宣称底层退出。已有恢复任务的取消与等待先于未确认关闭的失败报告，失败出口也必须清理它。

Bridge 为每个 stop operation 分配当前 output_epoch 内递增 operation_sequence（服务端已有最多512操作上限）。它属于不可变操作身份，所有状态沿用原序号。字段可选，旧持久行可读，不改变客户端协议和数据库表结构。ReplyRevisionController 仅保留当前回复的一个事实：校验完整 Session、turn/generation、response、speech 与已知 epoch；不同操作只有明确较新序号才能替换，缺失/相同/较旧序号不替换。UTC 只作事件时间。

纯 transition_output_stop_fact 移到 protocol/commands；原 delivery 导入保留兼容。actor 和存储共用不可变身份/第一终态规则。REQUEST 重放返回已确认的 canonical 终态；UNKNOWN 不能后来改写为成功。

观察事实只更新证据。它不恢复 delivery_permitted、不推进实际播放样本、不签发纠正/恢复许可。新回复和关闭隔离旧事实。actor 用既有输入证据 Journal 记录 reply_output_stop_observed，关联原 input_id/input_version/reply_version 和停播目标。

## 验证与后续

[实施报告](../reports/2026-10-07-canonical-output-stop-observation.md)列出真实文字输入至精确停止和纠正的组合链、存储故障、重配置/关闭竞争、旧行兼容及浏览器回归。

下一步才是可靠新 ASR 证据的误打断恢复决定、独立许可、新回复/播放 epoch、再次有效打断与未知停止出口。较旧同批 IGNORE 永远不能撤销已发送停止。本决策不关闭 ADR0138/G4，也不证明外部供应商速度或物理扬声器声学停止。
