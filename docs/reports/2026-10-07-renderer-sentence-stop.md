# 浏览器句末停播与页面状态隔离

日期：2026-10-07。ADR0137 的 renderer/wire 前置能力；阶段3/G3保持开放。

## 实施范围

复用 BrowserAudioOutput、PlaybackOutputController、现有 precise stop 帧与主页面 Hook。新增严格、不可变的可选 sentence_permit wire 结构，绑定 input/reply 版本、句段 identity、speech-local 样本边界、采样率及最大等待时间；外层继续绑定 epoch/speech/generation/operation。旧取消帧兼容不变。共享 SentenceSpan 移到无 runtime 依赖的 core 模块，原路径显式重导出同一类，消除 frames 独立加载的循环导入。

Browser 将句子样本边界映射到已调度 PCM，排除网络空隙；跨句 buffer 在句末截断，后续 source 立即取消。只保留已实际开始且仍在同一精确目标上的一个句子，许可边界必须已经完整调度，等待上限5秒。缺证据、过期、采样率/回复身份错误、短队列或 suspended 时立即停播，不虚构句末完成。停播期间拒绝旧及新 PCM；自然 ended 不冒充原回复 finished。

最大等待、主动立即撤销或 reset 按实际播放样本结算。相同 operation 和许可内容重放共享原等待/回执，不刷新期限、不停止替换 speech；模式/目标冲突封锁输出。无法确认物理停止时静音并封锁浏览器和数字人，异步回执跨 reset/epoch 仍保留故障封锁。数字人 void cancel 无法证明实际停播，明确 unknown 降级；混合路由 deferred complete 也遵守等待屏障。

主页面先检查准入，再更新字幕、speaking generation 和计时器。旧 permit 不清除当前回复计时器；等待中的 legacy 音频、两种文本及 completed 通知不能污染正在保留的回复。异步回执只发送到原 attachment，原停播不能结算替换回复状态。

## 回归证据

- source.stop 故障跨 reset/beginEpoch、数字人 deferred complete 先红后绿。
- 隔离3014测试实例、真实 Chrome、受控 backend Socket，真实 AudioContext 与页面 Hook：跨 PCM buffer 句末16000样本回执、重复许可、旧音频拒绝、新音频恢复、旧 target/epoch timer 隔离；legacy audio 和两种 text 在修复前都造成“正在回答”残留，修复后释放。新增6场景及既有4隔离场景最终10 passed。
- 全量 Python：1937 passed、69 skipped、3 subtests。新增24项 wire 严格字段/兼容回归；协议独立导入与同一类重导出经独立审查确认。
- 音频/frames 前端9文件74 tests passed；TSC、限定8文件 ESLint、Python3模块 Mypy/限定 Ruff、diff 检查通过。独立 Python/TS 审查通过。

## 尚未交付

这批测试的 permit 由测试 Socket 提供。生产 actor 尚未签发/保存句末许可，Bridge 尚未传播此许可或扩展相应等待期限；不能宣称用户实际补充已自动保留当前句。仍需现有 actor 绑定最新 input/reply 版本和可靠播放事实、Bridge 传递/撤销、预生成与交接的 heard_frontier 重验。本文证明浏览器队列执行，不证明实际扬声器无重叠；真实数字人及 G3 未验收。

全量其他阶段保持开放：真实标注音频/G0；共享JEV多会话公平、全局等待预算和配对实验/G1；完整关联、未归档动作检查点与历史幂等/G2；误打断恢复/G4；真实提供方、多会话综合验证/G5；默认双路录音、机器只读诊断身份、因果异常去重及冷暖/重连指标。

未重启用户3010/8765/8766服务、迁移用户数据库或 push。E2E生成的 Next 配置恢复原值。

后续已补[生产actor许可与Bridge交接](2026-10-07-production-sentence-permits.md)。上面的“尚未交付”为本批当时状态；后续生产签发和传播已实施，预生成/HF完整重验及真实renderer/G3仍开放。
