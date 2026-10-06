# 2026-10-07：播放回执保留原输出上下文

承接ADR0137的播放事实前置，不实现当前句许可或句末衔接。

## 问题与修复

PlaybackState 已绑定原模型回复或直接播报上下文，但 legacy 和 V2 的 ReportPlaybackProgress 仍用 generation 合成 turn-N，并把 response_id 置空。派生 SpeechPlaybackProgress 因而与原 turn/response 身份不一致；精确停播的诊断观察虽保留原目标，实际投影命令却仍丢失关联。

三处播放投影改为 playback.context。开始、播放进度、停止、完成及精确停播投影统一保留原输出上下文。后续抢话输入不能覆盖原目标。直接播报的 response_id 缺失时仍保留缺失，不凭 speech_id 发明模型回复身份。

V2 原有 epoch/speech/generation 校验保持，legacy 仍只投影其 generation 绑定的当前播放状态。输入命令继续使用原输入上下文构造，不改变输入编号或执行generation。

Cascade 模型分支本来已通过 SpeechDelivery 恢复原 response_context 通知输入actor，本修复不能解读为此前所有actor播放回执均失效。修复直接作用于桥接命令及派生播放事件的关联，补齐后续许可/交接依赖。

## 验证

修复前已复现原turn与response丢失。19项新增回归覆盖模型/直接播报×legacy/V2×started/playing/stopped/finished、抢话后精确停播，以及真实InMemoryRealtimeConversation的SpeechLifecycle存储和事件投影。

定向114项通过；最终Python1848 passed、62 skipped、3 subtests passed（37.79秒）。限定Ruff、WebSocket Mypy与diff检查通过。独立审查87项定向通过。本批没有前端/wire字段变更，未重复浏览器或真实模型测试，未重启现有服务。

## 下一步

优先复用既有SpeechDeliveryStore、ReplyRevisionController和actor，补持久stop操作事实及稳定句段身份；再签发绑定reply_version/epoch/句段/deadline的当前句许可，清理未来句，在真实句末重验heard_frontier。诊断异步队列仍不是恢复权限账本。ADR0137/G3、误打断恢复/0138和其余实验与横向交付继续开放。
