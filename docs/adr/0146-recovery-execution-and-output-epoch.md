# ADR 0146：恢复执行许可、原输入租约与播放 epoch 切换

日期：2026-10-07。状态：Accepted，限本批受控执行链；ADR0138/G4完整验收仍开放。

## 背景

ADR0145已产生可靠新证据的恢复计划。原回复已被取消，不能重新开放原 response 的交付权限；恢复必须保留原用户授权，又拥有新的执行与播放身份。

## 决策

复用现有 ReplyRepairPermit、actor、ReplyRevisionController、Core、控制器和播放队列。actor输出规划，Core核对当前已发布原请求及其最低投影序号和原截止，再回到actor签发一次许可。所有消费入口重核当前输入、回复、证据故障和截止；计划本身仍不是执行权限。

区分原 USER 的 input_context 与当前回复的执行 context。恢复保留原 input_id/input_version/turn，递增 reply_version，记录 supersedes_response_id，并分配高于原回复及重叠输入的新 generation。再次恢复仍引用最初 USER 的 generation。Journal归档显式保存原 input_turn_id/input_generation；恢复历史拒绝损坏租约，并保持旧回复无交付权限。

Core使用原 USER 与已确认听见的历史重新生成续答，复用既有上下文纠正、原回复截止、Brain/TTS清理与工具/委派执行屏障。恢复不能重复请求工具或委派。暂不恢复已取消的供应商流，也不把精确停播样本称为可以续播的供应商游标。

恢复 preparing 的许可在首次非preparing语义发布前仍可撤销。真实新 generation 的VAD到达时撤销准备中恢复，保留新输入；迟到旧 generation 的VAD与ASR一样忽略。开始后的新语音走既有语义打断流程，不能仅凭VAD撤销已发布回复。

Bridge必须已有同 stop_command_id、原 speech/generation/epoch 的 STOP_CONFIRMED 和完成的事实/播放投影屏障，且仍在首次恢复截止内。正式 Endpoint Session compare-and-swap 原 epoch；通知在发送锁内重核附着和 epoch，发送后再次复核，不缓存到另一次连接。控制通知失败、截止或附着变化立即封锁后续PCM，再异步通知失败/关闭。通知等待受原剩余恢复截止与既有停播IO预算限制；正常关闭取消不误报失败。

新增有序 output_epoch_started 控制帧，先于新回复音频。前端核对 previous_output_epoch 后同步更新 PlaybackText/PlaybackOutput/OutputGraph，保留输入采集与输入 epoch。Bridge同时推进下一轮输入 generation，避免恢复后的真实用户输入被当作过期。已应用的完整计划身份保存在现有有界 stop 记录中，完成后重放仍幂等；其他计划不获得同等许可。

## 验证及边界

真实受控 Journal/Managed/Core/actor/Bridge/Endpoint覆盖两种证据到达顺序、恢复完成后重放、下一轮 UserText、准备期间新/旧VAD、连续两次恢复及旧epoch回执隔离。真实Chrome/WebSocket/WebAudio验证文本和语音路径的新epoch先于PCM、播放回执使用新epoch、麦克风保持开启；原句末交接四场景继续通过。

失败回归覆盖不支持轮换、CAS失败、截止、目标不符、等待发送锁时换连接、通知阻塞/失败和正常关闭。完整非合作IO/供应商、实际录音/数字人renderer、未知停播及断连组合矩阵仍需按实验计划验收；本批不关闭G4，也不启用既有默认关闭的句末切换开关。

同日提交后补充12项实际生产组合：unknown/stale/缺失回执在反馈前后到达，正式Endpoint和普通transport都保存STOP_UNKNOWN并进入有界失败出口；迟到成功回执不能重开。这是已验证的G4异常子集，不替代全部断连/非合作/renderer矩阵。
