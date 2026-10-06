# 跨 Voice Session 历史与版本恢复

日期：2026-10-07。对应实施计划阶段2 / ADR0136，部分交付。

## 问题与失败回归

同一 tenant/user/thread 在新的 Voice Session 或设备继续时，RuntimeFactory 读取原 Journal，但 ProjectCommittedItem 要求历史记录的实时 Session 与当前 Session 完全相等，导致恢复失败。协调器也只恢复模型历史，没有恢复输入身份和正文，“不是，上海”无法延续“查北京天气”，版本重新从1开始。

先运行失败回归：`test_new_voice_session_restores_same_thread_without_rewriting_history` 复现 different realtime scope 错误；`test_revision_history_restore.py` 首两项纠正回归复现原问题丢失。修复后相同命令通过。

## 实施边界

- 历史投影命令使用当前 Session 上下文，原 Journal item/context/digest 不改写。只允许同 JournalScope（tenant/user/thread）历史；公开 AppendItem、实时命令、ASR 和播放回执仍要求当前 Session。ProjectCommittedItem 仍是控制平面专用，公共 Journaled handle 拒绝直投。
- JournalCommittedProjector 补齐旧 Session 序列缺口也使用当前 owner context，继续从 Journal 重读和验证目标 digest。
- 既有 ReplyRevisionController 在 Journal 恢复屏障中同步重建当前输入和已归档回复，不增加 actor、I/O 或业务队列。实时提交/绑定开始后，后续 Journal 投影不能重置账本。重复/较旧 sequence 不重复递增；同 root 的新记录不能回退版本或复用当前 observation identity。
- 输入正文和 turn 恢复到 `_last_committed`，明确纠正保持逻辑 root、递增 input_version；新回复继承已归档回复版本和 supersedes_response_id。ASR observation identity 经事件链写入用户 Journal，可恢复相同 InputRevision。
- 旧回复 delivery_permitted 恒为 false，不恢复 pending response 或执行租约，不自动触发 Brain 或播放。生成归档不等于已听证据，恢复后的未知播放状态不被标成“未播”；当前句衔接仍由0137处理。
- Legacy 无 input_id/input_version 时以不可变 Journal item_id 作为稳定初始身份。旧版已带版本但未保存 observation identity 的记录以 item_id 兼容。手动/外部回复可没有 ASR input 关联，不伪造 input 链。部分版本字段、错误类型、版本断链和当前版本 reply 的 turn/generation 错配明确失败，不默默降级成版本1。

## 验证

新增30项回归，定向6文件64 passed；最终全量 Python **1768 passed / 62 skipped / 3 subtests passed，36.86秒**。限定12文件 Ruff、7模块 Mypy、diff 检查通过。直接检查旧 turn_manager 模块与未修改 runtime 文件仍有既有类型错误，未宣称仓库全量 Mypy 通过。

实际 RuntimeFactory→Cascaded→actor→Journal→自动 Brain 回归先生成旧 input/reply，close 后换 Voice Session/device，再输入纠正；验证 root、observation identity、input/reply version、原上下文不可变与旧输出禁止。ASR/model/TTS/renderer 使用确定性 doubles，不是物理音频测试。回复生成归档与客户端播放完成分开等待。

负例覆盖 tenant/user/thread 三轴隔离、旧 Session 命令拒绝、gap 补齐、digest 伪造拒绝、非法版本/身份/类型、legacy/manual 兼容与实时开始后迟到历史不回滚。两位现有独立审核者均 Approve，必要校验问题和覆盖建议已关闭。

## 仍未完成

本批只从已提交的主 Journal 重建。进程退出前未归档的 reply、全部历史命令幂等身份与当前 root 以外的版本索引仍无持久检查点，不能称为完整跨 Session 幂等；独立输入证据也不等于任意业务动作可重放。

完整语义关联/G2、实际当前句许可与 heard_frontier 重验、STOP_CONFIRMED/STOP_UNKNOWN、误打断后新 epoch 恢复、录音和机器只读接口、真实配对模型/renderer/负载验收仍开放。未重启3010或8765/8766，未调用真实付费模型、真实 Postgres 或物理设备，未 push。
