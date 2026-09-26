# 离线数字人口型：质量优先评估

日期：2026-09-14。状态：全部评估与完整动作验证完成。

**用户回看后的选择：Lip Forcing 观感更好。后续只生成结果，由用户自行比较和决定，不再由自动评分替用户选模型。** 以下保留此前测试记录，指标不代表最终视觉偏好。另行生成 Lip Forcing 14B + 完整 Wan VAE 的完整“柔和回应”素材。

此前自动评估倾向的配置为 LatentSync 1.6、stage2_512、FP32、50 steps、guidance 2.0、seed 1247、DeepCache 关闭；完整 10.04 秒同步评分由 3.96 提升到 5.01，偏移均为 0 帧。该指标结论不覆盖用户对 Lip Forcing 的视觉偏好。应用默认模型尚未切换。

## 目标与范围

用户明确不以离线生成速度作为限制。本轮使用现有 GPU 比较口型同步、口部细节及原动作保持，输出可观看、可复现的样片。有限素材无法证明某个模型全局最优；结论限定在“柔和回应”动作和本轮实际参数。

不批量生成所有动作，不替换会话素材或应用默认模型。

## 环境与模型

GPU 为 Quadro RTX 8000 48GiB，SM7.5；GPU 服务器通过 `ssh dev` 访问。容器 CPU 内存上限实际为 32GiB，不能根据宿主机显示的总内存推断模型可加载。

| 模型 | 实际配置 | 状态 |
| --- | --- | --- |
| MuseTalk 1.5 | 原有 FP16、batch 8、默认人脸处理 | 已有完整基线 |
| MuseTalk 1.5 | FP32，其余保持一致 | 完整素材生成成功，短片补测完成 |
| LatentSync 1.6 | stage2_512、FP32、50 steps、seed 1247、DeepCache 关闭 | guidance 1.2/1.5/2.0 短片完成，2.0 完整动作验证通过 |
| LatentSync 1.6 | 100 steps、guidance 2.0，其余相同 | 短片完成，未观察到明显收益 |
| Lip Forcing 14B | BF16 原始权重、完整 Wan VAE、seed 42、官方两步蒸馏时间表、训练时的局部注意力窗口 | 实际生成成功 |

Lip Forcing 在 Turing GPU 上没有原生 BF16 支持，关闭 FlexAttention 与编译，使用可执行的 SDPA 路径。预计算文本条件并采用 meta 初始化、mmap 和严格 assign 加载，避免在 CPU 上同时创建 FP32 模型和完整 checkpoint 副本。14,294,081,696 个参数完整匹配，未量化、未遗漏键。其主模型 GPU 占用约 26.70GiB，生成中采样显存最高约 48,187MiB；该数值不是连续监控所得的精确峰值。

使用独立的 `venv-lipforcing`，没有改动原 MuseTalk/LatentSync 环境。PyTorch 2.6.0+cu124，最终 `pip check` 通过，预处理导入和完整输出解码通过。三份大权重下载后的 SHA256 与官方记录一致。

完整 Wan VAE 相对轻量 TAEHV 是此次主动选择的质量配置。两步蒸馏模型不能简单套用普通扩散模型的 50/100 步参数；保留 checkpoint 对应时间表。

## 对照方法

输入为同一动作视频及参考音频。guidance 筛选使用前 2.56 秒，以固定模型、步数、seed 比较。Lip Forcing 默认向下取整到完整 AR 分块，实际输出 57 帧、2.28 秒，因此跨模型评分统一截取共同的前 57 帧并配同一段参考音频。

无视频变速，无音频偏移校正。MuseTalk 基线来自已有完整生成结果的前段；其音频编码上下文与短音频重新推理可能不同。不得将不同片长的 SyncNet 分数混排。

所有用于共同片长评估的文件均经 `ffprobe -count_frames` 确认为 57 个可解码帧、2.28 秒。展示拼接视频另行验证实际解码帧数与音频时长一致，避免仅看封装声明帧数造成末帧误判。

使用 LatentSync 仓库的 `eval.eval_sync_conf`，同一 S3FD/SyncNet-v2 权重，在 CPU 上顺序运行，避免共享临时检测文件冲突。指标仅辅助判断，不等价于视觉质量或人工可感知的完全同步。

### 共同 57 帧结果

| 配置 | SyncNet confidence | AV offset |
| --- | ---: | ---: |
| 原素材配参考音频 | 0.42 | 6 帧，低置信度，不可用作可靠校正 |
| MuseTalk 1.5 FP16 | 3.94 | -1 帧 |
| MuseTalk 1.5 FP32 补测 | 4.46 | -1 帧 |
| LatentSync 1.6 / 50 steps / guidance 1.2 | 4.54 | 0 帧 |
| LatentSync 1.6 / 50 steps / guidance 1.5 | 5.34 | 0 帧 |
| LatentSync 1.6 / 50 steps / guidance 2.0 | 6.00 | 0 帧 |
| LatentSync 1.6 / 100 steps / guidance 2.0 | 6.01 | 0 帧 |
| Lip Forcing 14B / Wan VAE | 4.75 | 0 帧 |

本轮短片中，LatentSync guidance 2.0 在该素材的同步指标上领先。14B 实际可运行，但不能因模型更大而判定更优。抽查新模型帧 12/25/38/50 未发现明显口部崩坏；连续自然度仍需结合视频观看。

100 步与 50 步的抽查画面近乎一致，口部矩形区域（x=588、y=360、宽=120、高=80）前 57 帧的两输出间 PSNR 为 45.90dB。这仅量化两者差异很小，不是相对真实口型的画质分数。同步分数只差 0.01，未证明有可感知收益；因此完整动作验证使用 50 steps、guidance 2.0、seed 1247、FP32，而非机械地将采样步数拉满。

MuseTalk 的 VAE 使用 `latent_dist.sample()`，原始推理入口没有固定随机种子。本轮 FP32 补测与既有 FP16 基线不是严格隔离随机性的精度消融实验，不能把 3.94→4.46 的变化全部归因于精度。但 FP32 实际生成与评估已通过，且没有在此样片上超越 LatentSync 的同步结果。

## 完整动作验证

两组完整 LatentSync 输出均统一为原动作的 251 帧、25fps、10.04 秒，使用同一原始参考音频重新封装与评估。

| 完整配置 | SyncNet confidence | AV offset |
| --- | ---: | ---: |
| 原配置：50 steps、guidance 1.5、seed 1247、FP32 | 3.96 | 0 帧 |
| 优选配置：50 steps、guidance 2.0、seed 1247、FP32 | 5.01 | 0 帧 |

新完整任务于 05:03:06–05:47:10 UTC 运行，约 44 分 04 秒，包含加载、预处理和输出校验；不以该耗时作为画质选择依据。抽查 12 个全脸时间点，并检查所有 15 个 16 帧分段边界的前两帧及首帧，未观察到明显新增口部崩坏；guidance 2.0 的张口幅度更明显。抽帧检查不等价于“完全无闪烁”的证明，保留完整对照视频供观看。

四个完整交付文件通过严格解码（`ffmpeg -xerror`）、实际可解码帧数、帧率和时长检查，结果保存为 `final-media-validation.json`。无声口型对齐与原动作严格等长，没有借助变速或音频偏移获得评分提升。

## 当前产品能力的边界

应用现有动作编排不是逐句音频驱动：

- `src/lib/musetalk-talking-worker.ts` 使用固定参考音频（可由 `MUSETALK_REFERENCE_AUDIO` 指定）。
- `scripts/generate_musetalk_talking.sh` 生成无声口型对齐。
- `src/components/digital-human/motion-orchestration.tsx` 根据讲话状态切换 `loop muted` 的待机/讲话视频，并保持动作播放位置。

因此，本轮同步评分只表示视频与**生成时参考音频**的对应程度。高质量循环素材能改善“看起来在讲话”的自然度，不能保证任意实时回复逐字对齐。若后续要求真实逐句对齐，必须使用实际回复音频生成或驱动口型。离线样片筛选与这一产品能力不能混为一谈。

## 产物与复现

本地样片、日志、脚本与环境记录位于：

`research-assets/avatar-evaluation/2026-09-14/quality-sweep/`

- `full-g2.0-preview.mp4`：最终完整预览，带参考语音，1280×720、10.04 秒。
- `full-guidance-comparison.mp4`：旧 guidance 1.5 与新 2.0 的完整近景对照。
- `full-g2.0-talking-material.mp4`：等长无声口型对齐，251 帧，未自动发布到应用。
- `full-boundary-contact.png`：全部 15 处分段边界对照；每行一个边界，左右各为旧/新配置的连续三帧。
- `full-face-contact.jpg`：完整动作的 12 个全脸抽查时间点。
- `full-sync-g1.5.log`、`full-sync-g2.0.log`：完整动作同步评估。
- `models-three-way.mp4`：MuseTalk、LatentSync g2.0、Lip Forcing，统一长度的近景对照。
- `quality-final-short-comparison.mp4`：MuseTalk FP32、Lip Forcing、LatentSync 50/100 步四路近景对照。
- `initial-four-way.mp4`：原素材、MuseTalk、LatentSync g1.5/g2.0 四路对照。
- `lipforcing14b-wanvae-seed42.mp4`：新模型原始输出。
- `common57/sync-*.log`：共同片长同步评估日志。
- `lipforcing-weights.sha256`、`lipforcing-environment.txt`：权重与环境记录。
- `infer_lowmem.py`、`prepare_text_lowmem.py`：独立评估用低内存加载和文本预计算脚本。

远端目录：`/root/lipsync-eval/quality-sweep-20260914`。长任务使用 nohup 和逐任务日志，完成后校验视频可解码并写入完成标记。

## 其他方案与来源

- [LatentSync 官方仓库](https://github.com/bytedance/LatentSync)：1.6 的 512 分辨率模型及评估实现。
- [MuseTalk 官方仓库](https://github.com/TMElyralab/MuseTalk)：1.5 及精度配置。
- [Lip Forcing 官方仓库](https://github.com/cvlab-kaist/LipForcing)：2026-07 发布的 14B 权重与推理代码；官方测试环境为 H200，本轮另行验证 RTX 8000。
- [OmniSync 官方项目](https://ziqiaopeng.github.io/OmniSync/)：页面提供论文、评测集与 Kling 在线入口，未发现可下载的本机推理权重入口，未计入可运行实测。
- [OmniEdit 论文](https://arxiv.org/abs/2603.09084)：声明的 GitHub 仓库本轮访问为 404，未计入实测。
- [InfiniteTalk 官方仓库](https://github.com/MeiGen-AI/InfiniteTalk)：涉及更大范围的重生成。为保持现有动作编排素材，本轮先检验嘴部重绘路线；没有据此断言其画质更差。
