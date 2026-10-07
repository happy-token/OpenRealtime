# 2026-10-07 产品装配与真实浏览器句末交接回归

## 本批范围

前批已提交 `a37f6fb`。本批继续阶段 3：产品装配增加独立环境变量 `VOICEAGENT_SENTENCE_HANDOFF_PREFETCH_ENABLED`，默认 `0`，并保留原 response-prefetch 总开关。未启用用户实例。文本/语音缓存分别验证未设置、关闭与开启的装配行为。

新增 loopback 测试服务，通过实际 Managed → Journal → Core → FrameBridge → 原生 WebSocket 接到产品 `/conversation` 页面。Chrome 使用产品播放实现和实际 AudioContext；观测代码只记录源的 start/stop 与原始通信帧，不替代播放/停止回执。HTTP 场景控制仅属于测试进程，不加入产品鉴权路径。ASR 最终结果、JEV 判定与模型/TTS 供应商受控，PCM 为合成静音，不能证明真实录音、外部供应商延迟或物理扬声器声学停止。

## 浏览器验证的契约

文本/语音两条链路各覆盖正常交接和候选撤销后供应商仍未退出，共四场景。只有真实点击开启麦克风后才释放原回复 PCM，避免测试在页面未开始对话时送入音频。

正常场景：首句仍播放时准备候选；停播前候选已有条件计划，但 ASR 尚未提交，原回复已听文本仍为空，候选文本/PCM 零外发。Chrome 将原源停止在首句末的 16000 样本、16 kHz 位置，返回匹配原目标/epoch/generation 的 stop receipt。服务端之后才提交 ASR 并外发新回复；原已听记录为「第一句。」。原回复加候选共两次模型请求。新源安排晚于真实停止回执和原句末；终态的一样本空标记与实际 PCM 源分开统计。

撤销场景：候选未退出时最终 ASR 改写使其失效。正式请求显式失败，原重要文本仍在 Journal；不取消私有供应商，不公开其缓存文字/PCM，也不启动第三次请求。测试释放供应商后证明实际退出，随后关闭页面，实际 Bridge/Managed 关闭成功。连接只有完整关闭后才能重新获得夹具所有者；并发连接被拒绝且不覆盖原状态。

## 发现并修复的生产问题

初始浏览器关闭回归失败：旧候选仍在退出时，准入失败使用 `OwnedStreamCleanupError`。Brain/TTS 因此记录永久清理故障，即使候选随后实际退出，会话仍无法关闭。三个真实适配器回归分别复现文本 Brain、语音 Brain 和 NativeTTS。

[ADR0142](../adr/0142-stream-admission-versus-cleanup-failure.md) 增加同级 `StreamAdmissionPendingError`，只替换两处临时阻塞出口，诊断复制保留类型。正式请求失败与资源归属分开：原供应商继续被所有者持有，实际退出后关闭成功；真正的 aclose/provider 清理失败仍隔离。没有添加重试循环或放宽资源释放条件。本次被拒绝的正式请求不自动重试。

## 验证结果与已知限制

- 最终生产 Python 树全量：**2298 passed、69 skipped、3 subtests passed，53.37 秒**。
- 定向：151 项通过；两位既有独立审查分别复跑 161/134 项，限定 APPROVE。
- 7 个生产/夹具模块 Mypy、8 文件 Ruff、全局 TSC、新增 E2E 的 ESLint 通过。Web server 原有 19 个 Mypy 错误与 HEAD 基线相同，不能宣称整个服务器类型检查通过。
- 三轮 Chrome：**12 passed，42.3 秒**；证据读取异常处理补强后最终四场景复跑 **4 passed，18.6 秒**。逐轮通信、源调度与关闭事实保存在[证据](evidence/2026-10-07-production-sentence-handoff.json)，PCM 仅保留长度和哈希。

此前一轮为 11 passed/1 failed：开启麦克风后页面出现客户端异常，尚未执行场景 trigger，没有新播放帧；当时未采集异常堆栈，无法确认原因。已保留该失败证据并增加 pageerror 堆栈采集，随后三轮未复现，不把它宣称已修复。初始因本机 Playwright 默认浏览器不存在的启动失败，改用已有 Google Chrome，无下载安装。

夹具自身也有先红后绿的连接所有权回归：单 active latch 必须在首次 await 前取得，完整 close 后才释放；HTTP 使用标准 Content-Length/Connection close；测试直接启动 Python，SIGTERM 等待真实退出，强制 SIGKILL 被视为失败。证据读取失败写入 artifact，不覆盖原测试失败。

## 下一项

本批补齐受控供应商下的真实浏览器生产通信/播放证据，独立产品开关保持关闭，不关闭 ADR0137/G3。继续一般补充与失配/非合作供应商的完整矩阵、手动和 DeliverItem 纠正、真实录音/模型/数字人 renderer 与配对性能验证，并定位尚未确认的间歇客户端/首轮 finished 异常。ADR0138 误打断恢复尚未实施；G0–G5 及横向诊断、默认录音、只读 Agent 接口等原需求继续开放。没有迁移数据库、重启用户 3010/8765/8766 服务或远端 push。
