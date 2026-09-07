# stride=1 与不同 blend 的实录对比

同一人物“萨曼莎 / 柔和回应”，同一组 4.95 秒与 20 秒既有语音，768×768 输出、256 模型输入、batch=8、320 ms 分块按实时速度到达。使用当前 OpenRealtime 自有 WebRTC 服务，在 8011 端口逐组运行；没有运行或修改 LiveTalking/OpenTalking 应用，也没有修改生产代码或 8010 的默认参数。

[完整视频对比页](http://localhost:3010/digital-human/evaluations/stride1-blend-comparison/index.html)

| stride | blend | 推理与合成吞吐 | 最大音频交付迟到 | 完整视频 |
| --- | --- | --- | --- | --- |
| 1 | 0.4 | 15.05 FPS | 12.77 秒 | [播放](/Users/forever/workspace/OpenRealtime/research-assets/avatar-evaluation/2026-09-07/stride1-blend-comparison/stride1-blend04.mp4) |
| 1 | 0.6 | 15.08 FPS | 12.73 秒 | [播放](/Users/forever/workspace/OpenRealtime/research-assets/avatar-evaluation/2026-09-07/stride1-blend-comparison/stride1-blend06.mp4) |
| 1 | 0.8 | 14.27 FPS | 15.10 秒 | [播放](/Users/forever/workspace/OpenRealtime/research-assets/avatar-evaluation/2026-09-07/stride1-blend-comparison/stride1-blend08.mp4) |

三组均完整生成 624 个语音帧、两段状态均为 completed，包含 H.264 画面和 AAC 音轨。交付文件仅为接收端原始录制的 faststart 重封装，未删掉语句或停顿。录制使用音视频时间戳保存，因此文件约 25 FPS 不代表实际运行达到 25 FPS；实测吞吐和累积交付迟到表明，当前 M1 机器无法实时运行这三组 stride=1 配置。录制后的平滑播放也不能证明实时链路不卡顿。

从画面对比看，0.4 更多保留源嘴部纹理，变化偏柔和；0.6 居中；0.8 的模型口型和口腔颜色更突出。均沿用嘴部局部遮罩，没有改为整脸融合。自然度仍应通过完整视频判断，不将主观视觉差异当作量化画质结论。

上一轮 stride=2、blend=0.6 的实录渲染吞吐约 28.67 FPS。三组 stride=1 的速度相近，降低 blend 并没有解决逐帧推理的性能成本；因此本轮只交付实验结果，默认服务仍为 stride=2、blend=0.6。临时 8011 服务已停止。

原始 WebRTC 录制、逐轮健康采样和汇总 comparison.json 位于 research-assets/avatar-evaluation/2026-09-07/stride1-blend-comparison。没有用像素统计或单元测试代替视频验收。
