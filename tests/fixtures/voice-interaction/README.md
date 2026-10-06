# 语音交互固定事件回放

`parallel-candidates.json` 为 schema v1。由 [并行协调器回归](../../realtime/test_parallel_semantic_candidates.py)直接读取，输入是固定 ASR 文本与 revision；VAD 和分类器返回顺序由测试显式控制。

|场景|固定条件|期望行为|
|---|---|---|
|累计判停|同一输入先后封出两块，并发分别为1/2|两档模型均判断截至该候选的累计文本，保留标点|
|最新负例取代旧正例|两次修订或单个快照封出两块；最新返回IGNORE/BACKCHANNEL，旧STOP/CORRECTION/INTERRUPT迟到|未发停播前不执行旧停止结果；等价revision/标点更新不丢当前证据|
|改写取消交接|旧候选未完成时改写输入，并发1|旧调用合作取消后新候选能发起，总调用2次|

测试还覆盖：已执行STOP锁定、尾部附和不能覆盖未决纠正、未达到policy阈值或完整边界的前序BACKCHANNEL不能被尾部规则升级、可靠附和仍可直接走规则、已完成但结果排队的token清理，以及等价revision/标点/空白更新保留原判停截止。

停播与丢弃的证据标准分别回归：.7降为UNCERTAIN不能压掉仍有效旧纠正；.9/.99最新累计partial BACKCHANNEL可以立即压旧停止但仍保留输入。“完整”指累计快照范围，不依赖sentence_end；不可套用严格丢弃条件来恢复旧prefix停播。

这是确定性状态回放，不是音频/真实ASR回放。分类标签来自stub，不能证明JEV语义准确率、实体设备停播或真实响应延迟。现有未标注WAV和实际renderer限制见[播放能力基线](../../../docs/reports/2026-10-06-playback-capability-baseline.md)。真实语义oracle、重要UNCERTAIN补充的最终出口和多会话供应商容量仍需后续阶段验证。
