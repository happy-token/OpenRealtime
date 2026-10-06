# 播放事实与迟到事件隔离

日期：2026-10-07。实施计划阶段3 / ADR0137的前置交付，未关闭G3。

## 问题与回归

旧 generation 取消会停止新音频，并清除新回复的 speaking 状态；source.stop 引发的 ended 可能伪报自然完成。重连虽更换客户端随机 epoch，服务端未验证 epoch。TTS 分段结束被作为整回复末包，同代不同 speech 共用时长/终态；逐包微秒舍入还会导致真实 PCM 全部播完后不能确认完成。

先运行失败回归，再修复：浏览器取消/epoch/同代 speech；服务端 epoch、分段终态、同代身份、真实PCM舍入、终帧 send 与回执交错。Review补充旧取消/失败/定向yield/显示文本四出口，新回复正在播放及完成退休后分别复现失败，8项回归修复后通过。

## 实施

- EndpointSession每次物理attach签发新output_epoch，经SessionAck传到主hook。WebSocket回执必须匹配当前epoch、speech与generation，旧epoch不更改状态。V1兼容仍保留。
- BrowserAudioOutput换epoch先停止旧source与清队列。取消/替换移除source身份后再stop；迟到ended不再触发自然完成。旧generation取消仅结算旧位置，不清新音频/时钟/字幕/timer。新speech即使复用generation也使用独立时钟，换采样率前记录旧位置。
- DeviceAudioOutputRuntime按speech保存单调样本位置及完成终态；已完成speech的晚取消不产生stopped或封锁后续speech。生产generation-only取消协议仍有局限，未声称已支持按speech/句段停播。
- WebSocket按speech保存PCM总样本和生成终态，另保留generation最近speech身份。旧speech回执不删除新speech；旧响应失败/取消/yield/文本不停止或覆盖新响应，退休后同样隔离。
- Provider段末不再发布整回复末包。SpeechAudioCompleted/ResponseCompleted发布独立空终包；状态在await send前记录。完成须同时有引擎终态及足够实际PCM样本，不以累加舍入微秒、TTS段末或仅收到finished认定整段已听完。

## 验证

最终Python全量1783 passed / 62 skipped / 3 subtests passed，36.66秒；本批新增15项后端回归。

Python定向68项通过；前端全量1254 passed / 7 skipped。真实Chrome主页面使用受控WebSocket与WebAudio零PCM，旧取消不影响新音频结束、回执采用服务端epoch；与输入失败清理测试连续3轮共6项通过。未调用真实模型、真实Postgres或数字人服务，WebAudio时钟不代表实体扬声器/DAC确认。

限定6文件Ruff、3模块Mypy、前端TSC/限定ESLint与diff检查通过。两位既有独立审核者Approve；他们分别复跑后端61项、前端26项，并检查同代旧回执与新speech终态。仓库全量Mypy未宣称通过。

端到端首次组合运行有1项未收到finished，单项复跑通过；测试原先只等待session_hello，未等待页面异步启动完成。补实际麦克风启用的UI屏障后连续3轮通过，保留严格finished/epoch/旧stopped断言，没有用延长超时替代验证。

## 仍待实施

精确reply/sentence/stop_command身份、actor许可、STOP_REQUESTED/CONFIRMED/UNKNOWN、许可句保留与未来队列清除、heard_frontier交接重验、新epoch误打断恢复仍开放。数字人位置/终态仍是既有估算路径，未获得G3真实验收。generation-only取消、历史metadata及上层队列全局界限也未关闭。

3010及8765/8766未重启；Chrome测试仅使用自有3012服务，生成的Next配置修改已清理。未push。
