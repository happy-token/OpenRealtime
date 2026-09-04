# FeatherTalk 使用方式与 OpenRealtime 接入评估

- 日期：2026-08-31
- 核对版本：`fdccc3cac22040b0caee29e63c35b6bcd17de44d`（2026-08-28）
- 目标：无 NVIDIA 独显、少量固定人物、预生成动作底片、运行时只做口型
- 结论状态：可进入离线 PoC；尚不能作为已经验证的实时运行时

## 1. 先说结论

FeatherTalk 适合“少量固定人物 + 一次训练 + 长期在 CPU/MNN 上低成本推理”，但不是 Wav2Lip 的零样本替换件。

对当前项目，推荐把它作为第二条个性化口型链路：

1. 每个人物另外准备 3–5 分钟、25 FPS 的清晰口播视频，训练一份专属视觉模型。
2. 现有的闭嘴动作底片继续保留，只抽取 25 FPS 帧和逐帧人脸关键点，作为运行时的画面资源。
3. 先用 Python 离线推理验证口型和融合，再导出 ONNX，转换为 MNN，在目标 Mac/CPU 上测 25 FPS。
4. 第一版按“完整一句音频生成一段视频”的近实时方式接入；如果质量明显优于 Wav2Lip，再改成 PCM 环形缓冲、增量音频特征和逐帧 MNN 推理。

当前官方 `main` 只有离线 Python 和离线 C++/MNN。旧搜索索引里出现过的 `dihuman_run.py` 已不在当前仓库中；README 也只说音频编码器“可以按需要改为流式推理”。因此不能把 FeatherTalk 直接标记为已支持流式实时。作为对照，本轮已经在远程 RTX 8000 上跑通 MuseTalk + LiveTalking WebRTC，证明后者可以边推理边输出，但 LiveTalking 的公开音频 API 仍是整文件上传，并且存在水印要求。详见 [MuseTalk + LiveTalking GPU 流式验证报告](./2026-08-31-musetalk-livetalking-gpu-streaming-validation.md)。

## 2. FeatherTalk 实际在做什么

FeatherTalk 是逐人物训练的音频驱动口型模型：

```text
一次性人物制作
3–5 分钟人物口播视频
  -> 25 FPS 抽帧
  -> 逐帧人脸关键点
  -> FeatherHuBERT 音频特征
  -> 训练人物专属 144x144 视觉模型

每次推理
16 kHz 语音
  -> 通用 FeatherHuBERT
  -> 40 x 1024 音频上下文
  -> 人物专属视觉模型
  -> 生成 144x144 人脸局部
  -> 嘴部软遮罩回贴到动作帧
```

视觉模型输入是当前人物帧的参考人脸、遮住嘴部的当前人脸，以及音频上下文；输出为 144×144 人脸局部。官方推理代码只在嘴部附近使用生成结果，脸颊、下巴边缘和裁剪边界保留动作底片，因此技术形态与当前“动作底片 + 局部口型”一致。

与 Wav2Lip 的核心区别不是 144×144 对 96×96，而是 FeatherTalk 的视觉权重绑定人物。它可能更稳定地学习固定人物的嘴部纹理，但新增了逐人物训练、模型版本管理和素材制作成本。

## 3. 官方流程怎么跑

### 3.1 环境

官方要求 Python 3.10 和 FFmpeg：

```bash
git clone https://github.com/anliyuan/FeatherTalk.git
cd FeatherTalk

conda create -n feathertalk python=3.10
conda activate feathertalk
pip install -r requirements.txt
```

仓库根目录已经包含通用音频编码器 `feather_hubert.pth`。预处理还会使用仓库内的 SCRFD 人脸检测和关键点模型。

### 3.2 准备人物训练素材

训练素材建议：

- 同一个人物连续口播 3–5 分钟；
- 严格为 25 FPS，官方脚本遇到其他帧率会直接报错；
- 每帧完整露出人脸，嘴部无遮挡；
- 音频清晰，尽量无噪声、混响和回声；
- 机位、画幅、光照和最终动作底片尽量一致。

预处理命令：

```bash
python data_utils/process.py /path/to/person/train.mp4 \
  --feather_hubert_checkpoint ./feather_hubert.pth
```

脚本会在视频同级目录产生：

```text
person/
  train.mp4
  aud.wav
  aud_hu.npy
  full_body_img/
    0.jpg
    1.jpg
    ...
  landmarks/
    0.lms
    1.lms
    ...
```

### 3.3 训练人物专属模型

官方 Quick Start 示例：

```bash
python train.py \
  --dataset_dir /path/to/person \
  --save_dir /path/to/checkpoints \
  --epochs 200 \
  --batchsize 16
```

训练脚本的设备选择顺序是 CUDA、Apple MPS、CPU。纯 CPU 必须显式增加 `--allow_cpu`；代码给出的提示把它定位为 CPU test，并且训练还使用 VGG19 感知损失，所以不能因为视觉模型只有约 5.46M 参数就认为纯 CPU 训练成本很低。

没有 NVIDIA 显卡时的实际选择：

- Apple Silicon：先试 MPS，代码会自动选择；官方没有公布 MPS 训练时间和稳定性数据。
- 纯 x86 CPU：可以用 `--allow_cpu` 跑通小样本，但不建议把 3–5 分钟素材、200 epochs 的正式训练押在 CPU 上。
- 少量固定人物：一次性短租 CUDA 机器训练，之后把模型带回本地 CPU/MNN 推理，成本结构最合理。

官方没有提供通用人物视觉 checkpoint；每个新人物都必须自行训练。仓库也没有公布训练耗时和所需显存，因此 PoC 前不能承诺单人物制作时间。

### 3.4 Python 离线推理

先为目标语音提取 FeatherHuBERT 特征：

```bash
python data_utils/feather_hubert/feather_hubert.py \
  --wav /path/to/test.wav \
  --checkpoint ./feather_hubert.pth \
  --out /path/to/test_hu.npy
```

再生成视频：

```bash
python inference.py \
  --dataset /path/to/person \
  --audio_feat /path/to/test_hu.npy \
  --audio_wav /path/to/test.wav \
  --checkpoint /path/to/checkpoints/199.pth \
  --save_path result.mp4
```

推理时，人物资源帧按“正向播放到结尾，再反向播放到开头”的方式循环。输出时长由音频特征长度决定，不由资源视频长度决定。

### 3.5 导出 ONNX，转换并运行 MNN

先把通用音频编码器和人物视觉模型导出为 ONNX：

```bash
python FeatherTalk-CPP/tools/export_models.py \
  --feather-checkpoint ./feather_hubert.pth \
  --visual-checkpoint /path/to/checkpoints/199.pth
```

在 Apple Silicon 上准备 MNN 并构建：

```bash
cd FeatherTalk-CPP
brew install ffmpeg
./setup_macos.sh
./setup_mnn_macos.sh
./convert_mnn_models.sh
./build_macos.sh
```

运行 CPU 推理：

```bash
./bin/feathertalk_mnn \
  --feather-model models/feather_hubert.mnn \
  --unet-model models/feathertalk_144_fp16.mnn \
  --dataset /path/to/person_resource \
  --audio /path/to/audio_16k_mono.wav \
  --output result.mp4 \
  --backend cpu \
  --precision low \
  --threads 1 \
  --profile
```

也可以将 `--backend` 改为 `metal` 或 `opencl`。MNN 运行时不依赖 Python、PyTorch、OpenCV 或 ONNX Runtime；但仍依赖 MNN 和 FFmpeg。官方提供 `benchmark_mnn`，没有随仓库发布任何目标硬件实测结果，所以“可纯 CPU 运行”不等于“已证明所有 CPU 都能稳定 25 FPS”。

### 3.6 无训练 Demo 核对结果

截至固定版本 `fdccc3c`，官方没有提供无需训练即可更换音频运行的完整 Demo：

| 项目 | 是否提供 | 能验证什么 |
| --- | --- | --- |
| 效果预览 `demo/feathertalk_comparison_144.mp4` | 是 | 只能观看作者生成结果，不能替换音频 |
| 通用 `feather_hubert.pth` | 是 | 只能运行音频编码器，不会生成人脸 |
| 人物专属 144×144 视觉 checkpoint | 否 | 缺失后无法运行 Python/C++ 完整口型推理 |
| 预处理人脸和关键点模型 | 是 | 可以准备训练/动作帧资源 |
| GitHub Release / Tag 模型包 | 否 | 官方 Releases 页面为空，仓库也没有 tag |

旧版 README 曾提供 Google Drive 训练资源包，但清单只有 `kanghui_training_video.MOV` 和一份 FeatherHuBERT checkpoint，仍然要求用户自己训练人物 UNet。旧版 C++ 文档中的 `demo_outputs/latest_188/unet_188_latest_last.pth` 是作者本地路径，没有提交到仓库，也没有公开下载链接。

因此目前能直接跑的只有模型结构测试和 FeatherHuBERT 音频编码，不能在“不训练”的前提下生成一段新的 FeatherTalk 口型视频。若作者补发与当前 144×144 结构匹配的人物视觉 checkpoint 和对应动作资源，才可以跳过训练做完整 Demo。

## 4. 如何接现有动作底片

必须把两类视频分开管理：

| 资产 | 用途 | 是否带声音 | 是否每人物必需 |
| --- | --- | --- | --- |
| 训练口播视频 | 学习该人物的嘴形、牙齿和音频到口型映射 | 必须有清晰人声 | 是，3–5 分钟 |
| 动作底片 | 提供运行时的身体、头部、表情、背景和原始皮肤纹理 | 不需要 | 是，可有多段动作 |

当前动作底片是自然闭嘴、无音轨视频，不能直接交给官方 `process.py`：这个脚本第一步会从输入视频抽取 WAV，无音轨时会失败。动作底片只需要执行以下准备：

1. 转为恒定 25 FPS；
2. 抽取 `full_body_img/{n}.jpg`；
3. 为每帧生成匹配的 `landmarks/{n}.lms`；
4. 检查所有帧的人脸框没有越界、嘴部无遮挡；
5. 缓存帧尺寸、人脸框和软遮罩，避免运行时重复读关键点和算几何。

`inference.py` 和 C++ 运行时对资源目录只读取 `full_body_img/` 与 `landmarks/`，目标语音从另一输入传入，因此为动作底片补一个“render asset prepare”脚本即可，不需要伪造训练音频特征。

建议的人物包结构：

```text
feathertalk/<avatar-id>/
  manifest.json
  models/
    feather_hubert.mnn
    visual_model.mnn
  actions/
    idle/
      full_body_img/
      landmarks/
    explain/
      full_body_img/
      landmarks/
```

通用 `feather_hubert.mnn` 可以跨人物共享；`visual_model.mnn` 必须按人物保存。动作底片可以按人物拥有多段，运行时选择一段后循环取帧。

## 5. 实时性到底如何

### 5.1 当前官方实现不是流式接口

当前 C++ API 只有 `RunOffline(options)`：输入完整 WAV 路径和输出 MP4 路径。实现会：

1. 读完整 WAV；
2. 对整段波形做全局归一化；
3. 一次生成整段 FeatherHuBERT 特征；
4. 逐帧运行视觉模型；
5. 通过 FFmpeg 管道编码完整 MP4。

它没有 `pushPcm()`、`renderFrame()`、持续状态、WebRTC 输出或中断清队列接口。Python 路径同样先生成完整 `.npy`，再生成文件。

### 5.2 模型本身存在明显前视上下文

每个 25 FPS 视频帧使用 `[i-10, i+9]` 共 20 个视频帧的音频窗口，每帧对应两个 20 ms FeatherHuBERT token，总上下文约 800 ms。要保持当前模型训练时的完整上下文，在线输出需要等待约 360–400 ms 的未来音频，再加音频编码、视觉推理、合成和传输时间。

因此 FeatherTalk 即使吞吐超过 25 FPS，也不代表能满足很低的首帧延迟。直接把未来部分补零可以更早输出，但输入分布与训练不一致，口型准确度和稳定性需要重新 A/B，不能默认等价。

### 5.3 两种可落地接法

方案 A，先做句级近实时，推荐用于第一轮 PoC：

```text
TTS 完成一句/一个较大语音块
  -> FeatherTalk 离线渲染该块
  -> 按音频时钟向 WebRTC 播放生成帧
```

优点是基本复用官方实现，最快得到同输入画质结论；缺点是首帧要等待 TTS 块和预渲染，打断时只能丢弃未播放结果。

方案 B，做真正的流式适配：

```text
16 kHz PCM 环形缓冲
  -> 增量 FeatherHuBERT 特征缓存
  -> 保留 20 帧音频上下文
  -> 25 FPS MNN 视觉推理
  -> 嘴部回贴
  -> WebRTC 视频帧
```

需要重构官方 C++ 运行时，至少增加：

- 16 kHz 单声道 PCM push API 和有界环形缓冲；
- 与离线特征一致的增量归一化/音频编码策略；
- 可配置的右上下文和首帧等待策略；
- 预加载动作帧、关键点、人脸框和参考张量；
- 每 40 ms 生成一帧的调度器；
- VAD 静音旁路、自然闭嘴和短过渡；
- 中断时清空音频/视频队列并立即回到底片；
- 不经中间 MP4/FFmpeg 的原始帧输出接口。

第一版不建议直接投入方案 B。先确认专属模型的画质收益足够大，否则这部分工程投入没有回报。

### 5.4 旧“流式 Demo”审计与本机实测

2026-07-22 的旧提交 `f7d69b8` 确实包含 `dihuman_run.py`，其 `DiHumanProcessor.process()` 接受 10 ms、16 kHz PCM 块，所以核心类具备流式输入外形。但它不能作为当前版本的生产流式实现：

- 命令行 `main()` 会先用 `soundfile` 读完整 WAV，再在普通 `for` 循环里模拟 10 ms 分块，没有麦克风、socket、WebRTC，也没有按真实时钟节流；输出仍是完整 MP4 和 WAV 文件。
- FeatherHuBERT 路径每收到新音频都会对“从本句开始到当前时刻”的完整波形重新编码，计算量随句长持续增长，不是有界状态的增量编码器。
- 旧视觉模型输入是 160×160、8 帧音频窗口和 `[1,16,32,32]` 音频张量；当前正式模型是 144×144、20 帧窗口和 `[1,40,1024]`，checkpoint 与运行协议不兼容。
- 这份文件在 2026-08-27 的正式 144×144 精简提交中被删除；当前 C++ `RunOffline` 也仍然读取完整 WAV 并输出完整 MP4。

本机 Apple M1、PyTorch CPU 单线程验证结果：

| 验证项 | 结果 |
| --- | ---: |
| 官方当前模型结构测试 | 2 项通过 |
| 内置 FeatherHuBERT | 3,364,096 参数，可正常加载 |
| 单次编码 40 ms 波形 | 约 10.76 ms |
| 单次编码 1 秒完整波形 | 约 16.17 ms |
| 单次编码 5 秒完整波形 | 约 45.70 ms |
| 旧策略模拟：增长到 1 秒，每 40 ms 重算 | 平均约 13.27 ms/步 |
| 旧策略模拟：增长到 5 秒，每 40 ms 重算 | 平均约 24.42 ms/步 |
| 旧策略模拟：增长到 10 秒，每 40 ms 重算 | 平均约 41.88 ms/步 |
| 当前 144×144 视觉模型，PyTorch CPU 单线程 | 平均约 42.60 ms/帧，P95 约 48.49 ms，约 23.47 FPS |
| 当前 144×144 视觉模型，PyTorch MPS | 平均约 33.82 ms/帧，P95 约 39.48 ms，约 29.57 FPS |

视觉模型使用随机初始化权重，只测当前网络结构的前向性能，不代表口型效果。25 FPS 每帧预算是 40 ms：PyTorch CPU 单线程的视觉模型本身已经略超预算；MPS 虽超过 25 FPS，但没有给读帧、音频编码、回贴和传输留下足够余量。到 10 秒时，旧策略仅音频编码平均耗时也已超过 40 ms。这不是 MNN 性能结论，但足以证明旧 Python 参考实现的“整段重算”算法不具备稳定的长句实时性。真正流式需要有界缓存或带状态的增量 FeatherHuBERT，并重新验证它与离线特征的一致性。

## 6. 与当前 Wav2Lip 链路的差异

| 项目 | Wav2Lip 96 | FeatherTalk |
| --- | --- | --- |
| 新人物上线 | 准备动作视频和人脸资产 | 另外需要 3–5 分钟口播和逐人物训练 |
| 视觉输入 | 96×96 | 144×144 |
| 人物权重 | 通用 | 每人物专属 |
| 本地运行 | 当前已接入 LiveTalking/WebRTC | 官方只提供离线文件接口 |
| 无 NVIDIA 训练 | 不需要逐人物训练 | MPS 可尝试；纯 CPU仅适合试跑，正式训练建议一次性远程 GPU |
| 推理成本 | 已在本机 M1/MPS 实测 | MNN CPU/Metal 路线明确，但本项目未实测 |
| 许可 | 官方预训练权重限制非商业用途 | 仓库 Apache-2.0；附带权重的单独来源/许可仍需确认 |

FeatherTalk 的价值主要是人物专属训练和更高的局部输入分辨率，不是它已经提供了更完整的实时服务框架。当前不能替换掉 LiveTalking 的会话、WebRTC、音频桥接和打断控制，只能替换其中的口型推理核心，并补写适配层。

## 7. 建议 PoC 顺序与通过门槛

### 阶段 1：离线画质验证

只选一个有授权的固定人物：

1. 获取 3–5 分钟 25 FPS 口播素材；
2. 在 MPS 或短租 CUDA 上训练专属模型；
3. 将同一段动作底片和同一段中文测试音频分别交给优化后的 Wav2Lip 与 FeatherTalk；
4. 比较口型准确、牙齿/嘴唇细节、融合边缘、非嘴区域稳定和静音闭嘴；
5. 只有盲测明显优于 Wav2Lip，才进入运行时改造。

### 阶段 2：目标机器吞吐验证

在实际部署机器上运行 `benchmark_mnn` 和完整合成：

- 模型推理平均耗时小于 32 ms/帧，给 25 FPS 留至少 20% 余量；
- 完整解码、读帧、关键点、人脸裁剪、MNN、回贴和输出稳定达到 25 FPS；
- 连续 10 分钟无队列增长、内存持续增长和帧率衰减；
- 分别测试 CPU 与 Metal，不能只引用模型级 benchmark。

### 阶段 3：近实时接入

先接完整 TTS 响应或句级音频块，复用当前 WebRTC 播放与中断控制。验收首帧、音画偏移和中断后闭嘴后，再决定是否开发真正流式 FeatherHuBERT。

### Go / No-Go

满足以下条件才建议继续：

- 人物数量少且稳定，逐人物训练可接受；
- 有同人物高质量口播素材，或能低成本生成；
- 离线盲测相对优化后的 Wav2Lip 有明显收益；
- 目标机器完整链路稳定超过 25 FPS；
- 约 360–400 ms 的模型前视上下文不突破产品延迟预算，或降低前视后的质量仍可接受。

以下情况直接停止：

- 用户可以任意上传新人物且要求立即可用；
- 只有无音轨闭嘴动作底片，没有同人物口播训练素材；
- 必须做到低于约 200 ms 的音频到可见嘴形变化，但又不允许改模型或重新训练；
- 不允许任何一次性 GPU/MPS 训练，且纯 CPU 训练时间无法接受。

## 8. 许可和维护风险

官方仓库声明 Apache-2.0，代码层面比 Wav2Lip 的非商业限制更适合后续开源。但仍需在发布人物包前单独核查：

- `feather_hubert.pth`、SCRFD ONNX 和关键点 checkpoint 没有在 `docs/WEIGHTS.md` 中列出各自的上游来源和独立许可证；
- 人物专属模型可能记住训练人物的外观，训练视频、肖像和生成物必须有授权；
- 项目当前提交历史很短，最近一次更新重做了模型结构，旧 checkpoint、旧 ONNX 和旧教程可能与当前 144×144 模型不兼容；
- 应固定 commit、所有权重 SHA-256、MNN 版本和导出参数，不能持续跟随 `main`。

## 9. 最终建议

FeatherTalk 值得做一个人物的离线 PoC，但暂时不要把产品默认口型从 Wav2Lip 切过去，也不要在页面上标记“实时可用”。

最经济的路线是：用一次性 MPS/云 GPU 训练人物专属模型，本地先完成 Python A/B；画质通过后再导出 MNN 做 CPU/Metal 完整链路测试。只有这两关都通过，才开发句级近实时适配；真正流式改造放在最后。

## 10. 官方依据

- [FeatherTalk 固定版本](https://github.com/anliyuan/FeatherTalk/tree/fdccc3cac22040b0caee29e63c35b6bcd17de44d)
- [官方 Quick Start 与模型说明](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/README.md)
- [训练数据预处理](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/data_utils/process.py)
- [训练设备选择和损失](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/train.py)
- [Python 离线推理](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/inference.py)
- [144×144 视觉模型与 40-token 音频输入](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/model.py)
- [音频窗口、裁剪和软融合](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/face_utils.py)
- [C++/MNN 构建、转换和运行](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/FeatherTalk-CPP/README.md)
- [C++ 离线运行时](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/FeatherTalk-CPP/src/main.cc)
- [模型权重说明](https://github.com/anliyuan/FeatherTalk/blob/fdccc3cac22040b0caee29e63c35b6bcd17de44d/docs/WEIGHTS.md)
