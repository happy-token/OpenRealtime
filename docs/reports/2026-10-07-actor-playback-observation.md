# Actor 接收实际播放事实

日期：2026-10-07。对应 ADR0137 前置任务；阶段3仍未完成。

## 问题与修改

原播放回执经实际 Cascade 到输入 actor 时，只保留 `playback_started` 和已听文本，丢失输出 epoch、采样位置、当前句和服务端接收时间。不能据此安全签发未来的当前句许可。新增不可变 `ReplyPlayback`，复用现有 Bridge → Cascade → InputPipeline → TurnManager actor → ReplyRevision 链路，未新增控制器或业务队列。

V2 回执仅绑定原五项会话 scope、turn/generation、实际 speech route 的回复租约和已验证句子 identity。外部播报可以保留源条目的 response_id，但当前交付仍绑定自己的 speech_id。仅完整精确句段、且位置严格位于句中时保存 current_sentence；句界、终态和 legacy/estimated 位置均不授予当前句事实。

重复回执不刷新位置年龄，回执时间不参与命令内容相等性；晚到句子证据使用独立语义命令 identity。同一不可变句子不在每次采样回执重复哈希。actor 只持有当前回复，不新增全历史内存账本；历史恢复不恢复 live 播放所有权。

停播投影保留原接收时刻，不使用持久化完成时刻。终态锁定后，晚处理进度可精炼已听前沿，不能重写首次终态时刻、恢复当前句或恢复交付权限。输入证据只记录句段/精度/终态转换；原文以哈希和长度引用，避免长输出重复占用输入证据预算。

## 验证

- 初始真实 model speech＋Bridge 回归红：actor 只保留 started，缺失实际目标事实。重复 V2 回执亦曾触发不同命令内容错误，修复后通过。
- 终态后晚处理 playing 覆盖停播时刻由独立 review 发现；ledger 回归先红后绿。实际 Store＋Cascade＋Bridge 用持久写入与 progress 写入屏障覆盖两种投影顺序。
- 新增11项回归，含实际 model/direct speech、重复/旧 epoch/错误目标、终态竞争、80k 长句证据预算和逐采样免重复哈希。
- 最终全量 Python：1906 passed、69 skipped、3 subtests；核心7模块 Mypy、限定 Ruff 和 diff 检查通过。独立审核136项回归通过并批准。

这里测试的是受控 provider 和本地回执事实；不是实际扬声器、真实模型延迟或真实数字人验收。公开客户端 V2 协议未改，无本批前端变更；未重启用户3010/8765/8766服务、应用用户数据库迁移或 push。

## 未完成

本批提供签发许可所需的事实，不签发许可。仍需绑定输入/回复版本、epoch、句段和 deadline 的 actor 许可；renderer 保留一个实际已开始句并清除未来音频；预生成与交付时 heard_frontier 重验。未知位置、字幕晚到和 renderer 能力差异必须有明确降级出口，阶段3/G3继续开放。

全量计划其余阶段与横向交付不变：真实标注音频/G0、共享模型多会话公平及真实配对/G1、未归档动作持久幂等和完整关联/G2、误打断恢复/G4、综合负载/G5、双路录音、机器只读身份、故障因果去重与冷暖/重连指标继续推进。
