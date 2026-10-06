# 2026-10-07：句子时间证据与字幕/已播文本分离

承接 ADR0137 的事实前置，复用现有 TTS capability、Realtime Event、WebSocket bridge、PlaybackTextTimeline 与 PlaybackOutputController。不增加第二套输出队列或衔接决策器。

## 复现与修复

首轮 `tests/realtime/test_sentence_alignment_identity.py` 4 项失败：第二句的全会话时间没有减去句子起点，比例字幕提前推进；重复原文句子共用锚点，后一句没有独立字幕；字幕去重跳过同时携带的真实 PCM；估算字幕缺少精度标记。

现在 provider 提供句子原文、起点及局部时长。Doubao 全会话时间减去句子起点以后计算比例；相同文字处于不同音频起点时重新定位原文，保持独立偏移。字幕去重只影响字幕，不丢弃 PCM。去重键包含句子时间与证据精度，完整证据晚到时可以升级；原文锚点不随可升级时长变化，不因估算字幕已到全文末尾而丢失证据。

新增不可变 SentenceSpan：sentence_id、原句、Unicode code-point 文本区间及整个 speech 的音频区间。ID 绑定 tenant/user/device/voice_session/thread、turn、generation、speech、原文偏移和内容；重复文字不同位置有不同 ID。时间不作为新许可，同 ID 的时间改写与重叠区间在桥接中明确拒绝。ASR 输入版本/回复版本尚未加入许可契约，不能从这些元数据推导当前句许可。

## 证据精度

`text_end_precision` 区分 estimated 与 exact。按时间比例得到的原文字符位置只能用于字幕显示，不进入服务端精确已播文本边界。只有明确的整个 speech 时间基准、完整有效且有序不重叠的词时间才能生成完整句范围；残缺尾词、无效时间、零时长或重叠词不能制造精确整句证据。

实际播放回执到达句末以后，桥接按连续文本区间推进已播前沿；完整句可以扩展句内已确认的词边界，但不能跨过缺失前文。它使用实际播放位置，不使用字幕高亮位置或 TTS 生成完成时间。供应商字幕可能晚到，元数据到达以前不能保证已知当前句边界；本批没有实现留住当前句的音频队列切分。

[Doubao 官方 WebSocket 文档](https://docs.volcengine.com/docs/DoubaoVoice/WebSocketBidirectionalStreaming-V3?lang=zh)说明后续句子时间相对整个 Session；TTS2 的字幕与音频可能不同步，因此不能使用 Start/End 事件收到时的累计 PCM 当作句子边界。[Bailian 官方事件文档](https://help.aliyun.com/zh/model-studio/cosyvoice-server-events)提供句子原文和毫秒词时间，本批未独立证实其跨句时间与整个 speech PCM 时钟关系，继续只作为估算字幕，不标成精确句子播放证据。

## 生产链路与页面

直接播报的 TtsTextAlignment 现在通过真实 Cascaded Engine 转为 SpeechTextAlignment；桥接接收 SpeechStarted/Accepted/Committed 建立 intended_text，不再丢失直接播报的文本映射。模型播报也透传相同精度与句子元数据。

线协议包含 output_epoch，所有字幕出口包括无词时间的整回复 fallback 都绑定当前 attachment。Python 在 Pydantic 类型转换前拒绝布尔/字符串计数、残缺目标及残缺句子字段；浏览器按 safe integer 与 Unicode code point 验证。旧服务不带句子元数据的帧仍可兼容，不视为完整句子证据。

真实页面启动会在 session_ack 后清屏；Chrome 失败回归证实清屏错误地清掉 epoch 会拒绝全部新字幕。Timeline.reset 现在仅清内容，新的 session_ack 才替换 epoch。精确停播后的同 generation 新 speech 可以接续字幕；旧 speech 的字幕先经过既有 PlaybackOutputController 的取消/旧路由/封锁检查。旧 epoch 的高 generation 字幕不能污染新回复。

## 验证

- 新 Python 回归 12 项，覆盖两句/重复句、PCM、残缺尾词、两种晚到完整证据、可选词起点、Unicode/严格协议、真实外部播报和实际播放前沿；相关生产回归 106 passed。
- 最终完整 Python 1895 passed、69 skipped、3 subtests passed。跳过的 live/数据库测试不计为通过，本批没有真实供应商延迟测量或数据库迁移。
- 前端 frames/timeline/hook：59 passed。TSC、限定 ESLint、全修改 Python Ruff、核心七模块 Mypy及 diff 检查通过。两个 provider 模块另有 5 条既有 Mypy 错误，HEAD shadow-file 基线复现相同错误，无新增。
- 自建 3014 Next 临时服务与真实 Chrome：精确/兼容停止 × 同代/新代替换 4 项通过，验证旧 epoch 字幕、清屏后播放字幕及实际 WebAudio finished/停播回执。测试 provider/socket 受控，没有验证物理扬声器或数字人播放。同代兼容场景没有先等待旧 speech 已经进入 active 状态，不能证明“未结算旧 speech 无停播直接替换”已覆盖；本批同代切换保证限定旧 timeline 已结算的情况。测试服务已结束，自动生成的 Next 配置恢复，用户 3010/8765/8766 未重启。
- 两位独立只读审查批准；审查复现的残缺时间精确误判、可选起点、词/句前沿合并、晚到证据升级、清屏和同代替换问题均纳入回归。

## 保持开放的任务

阶段3/ADR0137/G3 仍开放：actor 签发绑定 input/reply version、output_epoch、sentence、deadline 的精确当前句许可；只保留一个已实际开始句并清未来队列；生成前和交接时重验 heard_frontier；真实 renderer/数字人及此前间歇首轮 finished 问题。此次 4 项受控 Chrome 通过不能证明间歇问题已根治。

全量计划不缩减：0136 完整语义关联、未归档持久动作检查点/全历史幂等/G2；0138 恢复新版本与新 epoch、未知位置和重复打断/G4；G0 真实标注音频、JEV 并发公平/G1、E01–E06 配对实验/G5；默认双轨录音、Agent 只读身份/API、异常因果去重以及冷/热/重连指标继续推进。
