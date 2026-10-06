# 附和打断与播放缺失：最近会话核查

Session ID：97879dcd-128b-42d2-8666-8c6c1bb8f237，2026-10-04 21:54:22–21:55:58（北京时间）。依据 control-plane session detail、conversation 和 debug-log，662 个事件，无分页尾页遗漏。

## 已确认

- 21:55:26 的“好。”、21:55:28 的“可以。”均命中规则 BACKCHANNEL，没有打断。
- 21:55:32.629 的“哼哼。”没有命中规则，JEV 返回 UNCERTAIN / 0.37；debug decision 明确 should_stop=false、creates_turn=false。21:55:32.630 却发生 barge_in_floor_claim。
- DefaultTurnCoordinationPolicy 对 UNCERTAIN 返回 stop_response=false、admit_input=true；CoordinatedTurnManager._advance 对允许保留的输入最终执行 _yield。因此“不确定，需要保留输入”实际会变成打断，debug should_stop 与实际行为不一致。这不是 JEV 直接返回 INTERRUPT。
- 故事 generation 5 的服务端 ResponseCompleted 在 21:55:27.892，客户端仍播放到至少 21:55:33.840。WebSocket bridge 在 ResponseCompleted 删除 response→generation 映射；后续带明确 response_id 的 yield 查不到 generation，无法发出对应即时取消帧。生成结束和播放结束混用了生命周期。
- generation 6 创建“哼哼”的新回复；21:55:33.919 下一段语音在新回复尚未播放时触发 continuation yield，取消 generation 6。该路径在语义分类前就执行让出话权，不能把这次取消描述成“嗯被模型判为打断”。
- generation 7 的“嗯。”chunk 21:55:34.876 sealed，但没有 requested/result。直到 21:55:44.876 恢复截止路径推进，约 10 秒；21:55:45.390 ASR final，21:55:46.606 TTS 首音，21:55:48.032 ResponseCompleted。
- generation 7 没有客户端 started/progress 回执。可以证明服务端生成了回复和音频，无法仅凭当前日志证明浏览器接收或拒绝音频的具体原因。不能宣称模型卡死，也不能宣称已定位最终播放故障。

## 后续修复边界

1. 不确定附和不得仅因为保留输入就自动让出话权；规则覆盖需处理实际 ASR 变体并保留问题回答等上下文边界。
2. response→generation 映射应持续到播放终止，取消必须锁定具体旧 speech/response。
3. 新回复首播前的 continuation 不应无条件将短附和当作内容续写并立即取消。
4. 重放 stop acknowledgement 后到达的 chunk，验证会被请求、结束，不靠 10 秒 recovery 推进。
5. 添加客户端音频接收/丢弃原因证据，定位最后一段生成但无播放回执的问题。

本次按用户要求完成定位，并添加历史详情管理员 Session ID 入口；未在这次核查中修改打断行为。界面权限由服务端 isAppAdmin 验证，非管理员不渲染 ID；诊断目标页面仍独立鉴权。权限和链接 6 项单测、tsc、修改文件 eslint 通过。尚未完成上述打断链路的确定性重放回归或实际浏览器音频验收。

## 同意优化后实施

- JEV 服务端 interruption instructions 明确短附和、识别乱码/意图不清、首播前判断边界；不确定不是抢话授权，音源身份仍需要 observation 证据。
- IGNORE 丢弃且继续播放；UNCERTAIN/低置信度附和/供应商失败保留等待独立 chunk，不从 admit_input 隐式触发 yield；恢复截止仅丢弃未确认的重叠输入，不强制停播。
- 删除 preparing/首播前 VAD onset 的无条件 yield 和 before_playback 的无条件 INTERRUPT 规则，真实补充要求必须通过语义确认，明确停止保留规则路径。
- 增加 floor_claim_confirmed 区分有效打断和自然播放结束，后者不把 uncertain 自动提交成新轮次；明确打断后的后续文本仍可提交。
- WebSocket 定向取消在生成结束后从尚未结束的 playback state 找旧 generation，保持映射清理且可以停止缓冲音频。
- 回归涵盖 uncertain sentence end/recovery 不停播、首播前短附和、自然结束不升级未知输入、生成结束后定向停播，既有明确纠正/停止/续写仍验证。之前把 uncertain/ignore/模型失败当作应打断的测试改成新约定；续写夹具显式提供确认抢话的模型判定。

这些修改修复了日志中已确定的服务端误打断路径；尚未用真实麦克风复测最后一段音频无客户端播放回执的现象，不能宣称整个播放问题已验收。

验证：全量后端 1472 passed、62 skipped、3 subtests passed（33.36s）；最终补强“明确 verdict 在旧回复自然结束后仍保留确认状态”后重跑协调器/chunk/WebSocket 71 passed。diff check 通过。本地服务在确认 /sessions 空列表后重启，healthz=ok；未提交 commit。
