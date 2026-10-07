# 自动回复公开后上下文纠正

日期：2026-10-07。前置提交：`9d4541c`。本批完成自动 ASR 回复的有限新版本纠正，不关闭 ADR0137、阶段3/G3或全量实施计划。

## 行为与模块边界

公开后的有效回复因迟到已听事实或持久工具结果改变上下文时，Core先撤销旧交付权限，确认原 Brain/TTS 真正清理，然后通知现有输入 actor。actor与 ReplyRevisionController 签发单份 ReplyRepairPermit；既有 TurnController 仅为自己创建的自动 ASR 请求发起新回复，不增加决策 actor或轮询任务。

新回复使用新 response_id，继承当前 input_id/input_version，增加 reply_version，记录 supersedes_response_id。每条纠正链最多两次，准备投影、准入和生成共享原绝对截止时间；新输入优先，清理未确认、证据失败或截止已过时不能准入。旧版本不能恢复交付许可。

音频仅在服务端生成或排队时不要求等待不存在的 renderer 回执。Bridge 最终 PCM 准入在 transport.send 让出执行前同步记录可选 observe_output_admitted 事实，穿过 Endpoint 重连槽位、Managed、工具/委派、TurnController、Journal 到 Core 单份公开依据。此事实表示外发准入，不表示实际播放，不能代替 started/playing 或句末许可。当 PCM 已准入或已有播放事实时，新生成等旧 speech 的 stopped/completed 实际已听内容投影后才开始；自然完成清理标记，后续历史变化不重复等待旧停播。

上下文变化导致的旧 speech 使用 INTERRUPTED 收束，继续接收迟到实际停播进度；普通供应商失败仍走 FAILED。处于附和或空 VAD 临时输入时，actor保存一份有界 Ready 提示。确认反馈结束或无文字 idle结束后重新检查当前输入、回复与原截止；如果准备已被临时输入拒绝，重用尚未准入的同一许可，不增加次数、不发布虚假新 ID 终态。真实新输入提交、新回复绑定、关闭及证据故障清除提示。明确 STOP（含锁定后最终规则判为 STOP）清提示并以 semantic_stop撤权，迟到 Core失效不得恢复许可；STOP与附和分别处理。

## 上下文与动作

续答基于原当前输入、最新已听历史及迟到持久工具/委派结果；当前输入只作为 TurnContent.text呈现，不变成新用户授权。压缩来源保留连续 Journal 身份，内部排除项撤销 MODEL 可见性；自身 assistant 输出尾部不进入依据，避免 Completed写入自行触发纠正。与自身 response_id 相同的 TOOL_RESULT仍保留；新增有效结果可触发下一次有界纠正。

TurnContent.context_repair 同时进入两类预生成缓存比较，并添加只续答、保留未知执行状态的提示。生产工具和委派外发边界硬拒绝本次纠正中的新动作请求，即使模型换了 call_id。迟到工具结果仍进入持久历史，但不恢复已经失效的原 Brain。

这项禁止重复动作的保护不等于完整的工具未知状态持久对账。手动 RequestResponse、DeliverItem MODEL_RESPONSE仍由原调用者编排，本批没有自动接管它们。

## 回归与审查

新增 `tests/realtime/test_automatic_context_repair.py`，使用生产 actor、Core、Managed、Journal、TurnController、Endpoint槽位及Bridge，只有归一化ASR、模型/TTS与renderer回执受控，不调用真实供应商或用户服务。

- 初始生成中/生成后两条测试复制到隔离 HEAD archive，两项均在等待新 Brain 回复时失败；当前实现通过。
- 审查期间先重现再修复：已播放内容遗漏、反馈/空 VAD 后无续答、Budgeted来源缺口、准备超过原截止、播放回执在途时提前耗费修正预算。
- 新增22项覆盖上述问题、自然播放完成、连续两次预算、新输入抢先、重复回执、原截止已过、真实清理失败及不同新身份的工具/委派重放拒绝；准备超时后新用户输入仍能正常生成。供应商自身 TimeoutError首因保留，不误报原预算耗尽。
- 明确 STOP在许可签发前/准备拒绝后两个场景先红后绿，迟到失效及重复offer不重启回复。
- actor准备许可的两次时钟读取竞争已修复为单次取值；确定性临界时钟回归确认不会杀死actor。
- 两位独立审查曾复现问题，修复后分别复核；最终验证结果见下方。

## 验证结果

- 最终全量 Python：2177 passed、69 skipped、3 subtests passed，47.58秒。
- 新增22项实际组合链回归通过；实时模块早期整组852项通过。全量首轮两项新测试因未等包装层消费语义文本/最终失败事实而失败；修正实际边界等待条件后保留原回复数量、终态与动作拒绝断言，最终全量通过。
- 18个生产模块 Mypy、23个本批Python文件 Ruff、git diff检查通过；这不代表整个仓库类型检查。
- 代码审查先后独立复跑93/79项，Endpoint增量3项、STOP增量76项通过；Python审查最后独立复跑121项（3.25秒）通过，并复核限定静态检查；两位审查者最终均限定APPROVE。原已确认问题均以回归修复，没有临时DEBUG日志。

## 仍未完成

ADR0137及阶段3保持开放。一般补充的预生成/完整语义纠正衔接、误打断恢复 ADR0138/G4、手动与直接交付的纠正契约、工具未知状态持久对账、真实浏览器生产语音链及数字人仍需继续实现/验收。

这些测试验证受控本地回执与资源关闭，不证明真实物理扬声器停止或实际供应商性能。永久不协作provider的整体shutdown硬截止、actor预算/历史内存完整边界、真实音频标注/配对实验/并发公平以及诊断、默认双路录音、Agent接口横向轨道仍按原全量计划推进。未重启用户服务、迁移用户数据库或推送远端。
