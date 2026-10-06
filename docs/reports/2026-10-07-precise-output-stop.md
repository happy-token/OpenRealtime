# 精确停播操作与有界交接

日期：2026-10-07。续`cbbdbd8`；ADR0137前置交付，阶段3/G3仍开放。

## 行为与身份

生产VoiceSession桥接发送携带`output_epoch + speech_id + generation + stop_command_id`的停播请求。客户端只停目标speech，重复操作复用原回执；同代替换speech不被旧请求误杀，旧epoch不改变当前输出。当前epoch的stale请求也绑定命令身份，禁止换目标复用ID。旧版无精确身份的取消帧保留兼容。

浏览器返回`queue_stopped`及实际样本时钟位置，含尚未收到音频的零位置停止；它证明本地WebAudio排队源已停止，不是物理DAC确认。数字人只有void取消API，返回`unknown`，不把提交命令伪装成停止成功。任何停止失败、操作预算耗尽或身份冲突均静音并封锁后续入队、数字人complete提交和调音量；reset/新epoch不清除未知停止锁，需要重新打开页面重建输出控制器。隐式替换旧source停止失败也不启动新source。

服务端维护一个live操作账本：`STOP_REQUESTED / STOP_CONFIRMED / STOP_UNKNOWN`。新音频通过既有出队边界等待匹配停播回执与播放事实投影，默认回执等待上限1500ms。身份错配不能放行；缺失、unknown、迟到及关闭有显式失败出口。已收到的本地确认保留为历史事实，但投影中断连、epoch改变或关闭会撤销后续交付许可，不让旧确认打开新epoch。通知与graceful close也有界，独立失败信号让Endpoint取消泵并释放运行时，即使底层receive仍等待关闭。没有新增决策actor或第二套音频队列。

## 失败回归与验证

前端先复现源停止失败后调音量重新出声、隐式替换仍启动新源、数字人锁可绕过、stale命令换目标；随后复现命令预算和ID冲突的静音遗漏。修复后限定音频/帧42项通过。最终前端1270 passed / 7 skipped，21.24秒；TSC、限定ESLint通过，独立复审批准。

服务端新增回归涵盖精确匹配、重复/乱序、缺失回执、unknown、超时、投影中的detach/epoch/close、发送停播命令阻塞，以及实际Endpoint编排下慢通知/慢关闭的模拟运行时释放。新增14项先失败后通过；独立审查再发现等待期间回复许可可作废，已补AudioDelta/SpeechAudioDelta两路失败回归并在等待后重读原事件许可。收尾再补terminal发送中关闭的失败回归：普通帧发送前统一重验关闭状态，阻止其恢复后启动新的完成帧发送；只允许一次失败通知越过关闭锁。最终定向82 passed，全量1810 passed / 62 skipped / 3 subtests，37.48秒；限定7文件Ruff和bridge/protocol两模块Mypy通过。独立后端复审65项通过并批准，额外alignment发送中关闭交错也无后续终态发送。未测试完整EndpointBridge的Mypy历史问题，不以限定检查宣称整个项目类型检查通过。

IO等待上界依赖已装配WebSocket适配器能正常传播取消；慢close测试验证了其被取消后receive仍等待时Endpoint也能释放运行时。这不证明任意吞掉CancelledError的自定义适配器都能硬截止，未增加第二套IO执行器。

Chrome主页面使用受控WebSocket、真实WebAudio零PCM，不请求真实模型或数字人：同代/跨代精确取消、legacy取消和输入失败退出首轮5项通过。三轮组合首次14 passed / 1 failed，首个精确取消同代场景3秒内未收到finished。这与上一批间歇首轮问题一致，未确认根因。新增失败附件记录AudioContext时钟、源start/stop/ended和完整回执，保持3秒阈值；随后单场1项及与全量前端同负载的三轮15项通过。不能以重跑通过宣称该间歇问题已修复；G3继续开放。

## 未完成边界

当前停播账本只在live桥接，不是actor签发的句段许可或持久恢复账本。停播请求/确认/unknown的时间与因果链尚需接入统一诊断存储。完整句段身份、当前句限时许可、清未来句保留当前句、heard_frontier预生成与交付重验、误打断恢复仍未实现。真实模型配对实验、标注录音、真实Postgres/数字人/物理扬声器验收，以及双路录音和机器只读Agent身份仍未完成。

本批未重启用户3010/8765/8766服务，未push。测试用3012服务退出后已还原Next自动改写的配置。
