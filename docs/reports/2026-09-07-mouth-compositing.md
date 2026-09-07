# 当前实时链路口型修复验收

日期：2026-09-07。人物：萨曼莎，动作：柔和回应。

## 完整视频

- 本地文件：`research-assets/avatar-evaluation/2026-09-07/compositing-fix/openrealtime-mouth-fixed.mp4`
- 开发服务播放地址：`http://localhost:3010/digital-human/evaluations/openrealtime-mouth-fixed-2026-09-07.mp4`
- 原始录制及健康采样：同目录 `realtime-candidate.mp4`、`realtime-candidate.json`。

视频为当前 8010 服务实际 WebRTC 音视频接收端的完整录制，包含两段已有语音（4.95 秒、20 秒）和前后停顿，未加速、未剪掉语句，也没有通过离线合成替换接收画面。交付文件仅重封装为支持快速播放的 MP4。视觉复核可见张嘴、闭嘴与停顿变化，未见明显整脸变形；没有做逐音素同步评分，完整视频是视觉验收依据。

## 修复原因与接入

1. 原有 OpenRealtime 合成器只供独立 CLI 使用，当前服务仍走另一套粘贴路径。现在进程管理器和服务脚本启动 `scripts/avatar_renderer.py`，由 OpenRealtime 自有运行时处理 `/offer`、`/humanaudio`、中断和素材准备；启动就绪检查验证 `/health` 的运行时身份。
2. 闭嘴形状的遮罩会截掉张嘴预测；闭嘴原图直接以 40% 叠加又留下重叠唇线。现在遮罩覆盖张嘴范围，只对源嘴部纹理做有界对齐，保留 `blend=0.6` 的混合比例，最后向原帧应用一次空间羽化。眼睛、鼻子与其余脸部不参与嘴部形变。
3. `stride=2` 跨批次保留下一关键帧，修复每段末尾重复帧；每段语音重新建立预测缓存，末尾 mel 窗口补静音。音视频使用同一播放时钟；上传与中断携带 generation，取消后的旧语音不会重新进入播放。
4. 素材帧预解码并缓存；输出最长边限制为 768，推理仍为 256，批次为 8。数字人模式不再挂载隐藏的 Orb GPU 动画，减少图形资源竞争。

LiveTalking/OpenTalking 应用未运行或修改。现有权重、素材只读复用；需要的推理网络架构位于自有包 `server/avatar_compositing/models`，来源与原有限制记录在该目录 NOTICE 中。既有 LiveTalking 工作树差异哈希保持不变。

## 本机结果与范围

设备：Apple M1，16 GB，MPS，单数字人会话，`stride=2`、`blend=0.6`、批次 8。

| 项目 | 结果 |
| --- | --- |
| 完整录制 | 28.63 秒，768 × 768，716 视频帧，含音轨 |
| 接收视频平均帧率 | 24.99 FPS |
| 两段语音生成帧数 | 624 |
| 推理及合成平均吞吐 | 28.51 FPS |
| 批次耗时折算到每帧的 P95 | 38.07 ms（不是首帧或端到端延迟） |
| 运行时错误 | 无 |

另外通过实际前端 `LiveTalkingSession` 与 `LiveTalkingAudioBridge`、当前 `/api/avatar-renderer/session` 完成一段网页播放，页面收到完整输出回调且显示人物。该短片运行时吞吐为 24.91 FPS，说明浏览器负载下性能余量有限；上述结果不代表多会话、高分辨率或任意后台负载都能维持实时速度。初次素材准备与模型热身不计入稳态渲染吞吐。

Python 相关检查 9 项通过；前端相关测试 24 项通过，TypeScript 类型检查通过。测试用于覆盖跨批插帧、中断与接入行为，不替代视频验收。

## 复现录制

使用当前项目 Python 依赖环境启动 `scripts/avatar_renderer.py --port 8010`，或按现有服务脚本启动。通过 `scripts/record_avatar_realtime.py --endpoint http://127.0.0.1:8010 --avatar <已准备的素材 ID> --audio <已有 WAV 文件...> --output <输出.mp4>` 录制；脚本同时保存对应 JSON 健康采样。普通网页仍经现有数字人会话入口连接，无需改用独立测试脚本。
