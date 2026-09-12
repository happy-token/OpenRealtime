# 开源数字人模型调研：多段式合成技术附录

调研日期：2026-09-07。面向数字人选型指南。来源为项目官方仓库、许可证和论文项目页；性能数字是作者公布的条件，本轮没有运行模型或验证实际画质。

## 如何理解多段式合成

与主指南一致，按口型对齐前的画面驱动方式分为三类：

1. **图片驱动 + 口型对齐**：以静态照片为底图，主要生成嘴形，例如照片接 Wav2Lip / MuseTalk。
2. **动作驱动 + 口型对齐**：复用实拍或预生成动作视频，再按新音频改嘴；LiveTalking、OpenTalking 的典型视频模板链路属于这一类。
3. **面部动作驱动 + 口型对齐**：单独生成或控制表情、视线和头动，再协调语音嘴形；可作为 AI 赛博女友、近景陪伴人像的参考路线。

这是工作流分类，不代表框架只能使用一种方案，也不代表所有陪伴产品采用相同实现。面部动作若离线保存为视频、在线仅循环底片改嘴，应按第 2 类理解。若音频运动模型本身完成嘴形对齐，不必额外叠加独立口型模型。下表还覆盖生成式整个人物视频及端侧轻量方案，不能将每个模型机械限定到一个类别。

“单帧推理达到 30 FPS”“长视频分块生成”和“接受实时音频并低延迟返回视频”是不同能力。模型吞吐不包含完整 ASR、LLM、TTS、排队、传输、播放与打断处理时延。人物素材预处理也不同于每人物训练。

## 代表方案对比

| 方案与官方来源 | 输入和材料准备 | 实时能力与官方硬件条件 | 适用场景和限制 | 授权情况 |
|---|---|---|---|---|
| [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk) | 人像视频或图片加音频；新人物先裁脸、编码并准备缓存，不要求每人物训练 | 官方称 Tesla V100 达到 30 FPS 以上；修改的脸区为 256×256。提供 realtime 推理脚本，复用已准备人物和音频片段；不是完整流式会话服务的延迟保证 | 改口型并保留素材动作，可接预生成动作视频；脸区中心设置显著影响结果，不会主动生成身体动作 | README 声明代码 MIT、模型可商用；第三方组件须分别遵守许可；演示素材仅供非商业研究 |
| [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 已有视频加新音频；通用预训练模型，不要求每人物训练 | 原仓库主要提供文件式推理；上层框架可做流式封装，不能据此说原模型提供完整实时通话 | 适合研究基线和已有素材改口型；旧开源模型不能代表另售商业模型画质 | 官方明确原开源代码和模型结果限个人、学术、研究等非商业用途，禁止商用。上层框架的宽松许可证不能覆盖模型限制 |
| [LatentSync 1.6](https://github.com/bytedance/LatentSync) | 已有视频加音频；无需每人物训练 | 官方最低推理显存：1.5 为 8 GB，1.6 为 18 GB。1.6 使用 512×512 训练分辨率；推荐 20–50 推理步，步数增加会变慢 | 适合离线配音质量对比；不是开箱实时会话方案。官方提示较高 guidance 可改善同步但带来失真、抖动 | 仓库 [Apache-2.0](https://github.com/bytedance/LatentSync/blob/main/LICENSE)；依赖与预训练权重应单独核查 |
| [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) / [FasterLivePortrait](https://github.com/warmshao/FasterLivePortrait) | 照片或人物视频加驱动视频、图片或运动模板；无需每人物训练 | FasterLivePortrait 宣称 RTX 3090 配合 TensorRT 达到 30 FPS 以上，包含单帧前后处理；原版支持 Apple Silicon，但提示可能比 RTX 4090 慢约 20 倍 | 迁移表情、头动和嘴部动作，适合准备待机、说话素材；自身并不是音频口型模型，模板里的嘴形不会自动匹配新语音。官方建议驱动视频聚焦头部、减少肩动，首帧正脸中性表情 | LivePortrait [许可证](https://github.com/KlingAIResearch/LivePortrait/blob/main/LICENSE)明确指出 InsightFace 检测权重仅供非商业研究，商用须移除并替换；不能只看 MIT 标签 |
| [JoyVASA](https://github.com/jdh-algo/JoyVASA) | 照片加音频，先生成面部及头部运动，再由 LivePortrait 渲染；无需每人物训练 | 官方测试 A100 和 RTX 4060 Laptop 8 GB。使用滑窗生成运动；官方介绍仍将改进实时性列为后续工作 | 适合增加表情、头动；不能把 FasterLivePortrait 的渲染 FPS 当作完整音频驱动链路速度 | 仓库 MIT；沿用 LivePortrait、InsightFace 等依赖，需分别核查模型权重 |
| [Ditto](https://github.com/antgroup/ditto-talkinghead) | 照片加音频，运动空间生成后神经渲染；无需每人物训练 | [项目页](https://digital-avatar.github.io/ai/Ditto/)明确支持流式处理、实时推理、低首帧延迟。仓库有 online/offline 配置；测试环境 A100、TensorRT 8.6.1 | 可作为自部署实时音频驱动候选；应实测消费级 GPU、并发、首帧和打断行为，不能把论文能力当本项目延迟保证 | 仓库 Apache-2.0；附属检测等权重仍需核查 |
| [SadTalker](https://github.com/OpenTalker/SadTalker) | 单张照片加音频，生成 3D 运动系数并渲染；无需每人物训练 | 官方发布视频生成工作流；本次未核实可作为完整实时通话依据的硬件指标 | 适合离线照片开口和研究基线；不默认列为画质最佳或实时首选 | 官方已取消非商用限制，改为 [Apache-2.0](https://github.com/OpenTalker/SadTalker/blob/main/LICENSE)；第三方组件例外需分别遵守 |
| [EchoMimicV2](https://github.com/antgroup/echomimic_v2) | 半身照片、音频及姿态序列；需要准备和对齐姿态素材；无需每人物训练 | 官方加速版本在 A100 上约 50 秒生成 120 帧，原版约 7 分钟；测试 A100 80 GB、RTX 4090D 24 GB、V100 16 GB | 适合离线半身、手势素材。加速不等于实时；姿态样例时长会限制生成时长 | 仓库 Apache-2.0；素材、基础模型分别核查 |
| [InfiniteTalk](https://github.com/MeiGen-AI/InfiniteTalk) | 图片或视频加音频；无需每人物训练 | 使用 Wan2.1 I2V 14B 基座，支持 480P、720P、多 GPU、量化与加速；官方把 `--mode streaming` 定义为长视频生成，而不是实时音频会话 | 适合离线长视频、配音及整体动作联动。官方提示图片驱动超过 1 分钟色偏加重；FusionX 加速会削弱身份保持。不能把长视频分块生成标成实时通话 | 官方声明模型 Apache-2.0；基础模型与其他组件单独遵守许可 |
| [FeatherTalk](https://github.com/anliyuan/FeatherTalk) | 每人物单独训练；官方推荐 3–5 分钟、25 FPS、脸部完整且收音清晰的单人口播素材 | 当前视觉输入 144×144、约 5.46M 参数；提供 Python 与 C++/MNN，可纯 CPU 运行，训练推荐 CUDA。默认对整段音频编码；官方表示可按需改成流式 | 适合固定人物、端侧部署；不是任意照片即用，也不能宣传默认已提供实时音频流链路；材料质量直接影响效果 | 仓库 Apache-2.0；个性化视觉权重由使用者训练 |
| [DH_live mini / mini2.0](https://github.com/kleinlee/DH_live) | 一段人物视频预处理；官方称无须人物训练 | 官方声明浏览器、移动端无需 GPU 可实时，提供实时对话示例；mini 脸区 128、39 Mflops/帧，mini2.0 脸区 184、52 Mflops/帧。未给能代表所有手机的统一端到端延迟保证 | 是“口型驱动未必需要服务器 GPU”的例子；需针对实际设备、画面大小和素材测画质 | README 标注 MIT，但网页形象去 logo 另有授权说明；不可直接宣传完全免费、无限制商用 |
| [Sonic](https://github.com/jixiaozhong/Sonic) | 照片加音频生成富表现力人像视频；无需每人物训练 | 官方要求 NVIDIA CUDA，测试单卡 32 GB；本次没有核实实时会话承诺 | 适合离线研究和画质对比，不宜作为商业自部署默认推荐 | 官方明确非商用，商用引导腾讯云对应服务 |

## 补充覆盖

[Hallo2](https://github.com/fudan-generative-vision/hallo2)面向长时长、高分辨率音频驱动人像，仓库代码为 MIT，适合离线生成候选。[AniPortrait](https://github.com/Zejun-Yang/AniPortrait)支持音频生成 mesh、pose，或利用驱动视频做表情迁移，再生成视频；可作为多阶段架构参考。不要因为研究演示有自然动作，就推断能接收持续实时音频或稳定处理打断。

## 对主指南的选型建议

- 已有 GPU、要继续优化当前口型：优先用同一人物与音频对比 MuseTalk，并保留 Wav2Lip 作为研究基线。比较牙齿、闭嘴、侧脸、遮挡和连续帧稳定性，不笼统断言所有开源模型效果不好。
- 希望照片有表情、头动：比较 JoyVASA、Ditto；若动作已确定，可以先用 LivePortrait 制作素材，再按需做口型修正。
- 希望半身动作丰富、允许等待：EchoMimicV2、InfiniteTalk 等更适合离线制作，生成的视频也可供动作编排复用。
- 没有服务器 GPU 但仍要口型：评估 DH_live 端侧路线；愿意为每个人物准备训练素材，可评估 FeatherTalk。
- 没有服务器 GPU、接受非逐字口型、重视自然动态与成本：预生成动作编排是值得优先验证的工程方案。它与上述模型不冲突，动作素材可以录制，也可以提前生成。

## 许可证与计费边界

LiveTalking 框架采用 **Apache-2.0**，不是 MIT。框架许可证不等于所接模型许可证，尤其不能覆盖 Wav2Lip 原模型的非商业限制。参考 [LiveTalking 官方仓库](https://github.com/lipku/LiveTalking)。

“代码开放”“模型权重可下载”“允许商用”“演示素材可复用”应分别判断。自部署模型通常没有统一每分钟 API 价格，但仍有 GPU 或端侧算力、训练与材料制作、工程维护、带宽与存储成本；本附录没有将它们估成零成本。

## 验证口径

以上链接于调研日在线查阅。硬件测试条件不等于最低要求，官方 FPS 不等于本项目实测。上线选型应在同一人物、音频、画面大小下比较首帧等待、稳定吞吐、连续运行、打断响应与用户观感；不要把不同分辨率、不同硬件、是否计入预处理不同的数字直接横向排名。
