# 数字人如何被驱动

技术说明 · 更新于 2026-09-07 · 基于本地实现与上游公开资料

数字人驱动负责把音频或运动信号转成可见的人物表现。语音识别、对话模型和语音合成决定“听到什么、回答什么、如何发声”；驱动模型决定嘴部、表情和动作如何变化；传输与播放器负责让声音和画面同步到达用户。

**OpenRealtime 当前采用两条路径：预生成动作视频配合实时口型，以及供应商托管的实时数字人。** 自有渲染路径已经有单机单会话实测；更丰富的表情、头动和生成式视频作为后续评估方向。本文中的“建议”是技术选型判断，“上游指标”是项目作者公布的数据，均不等于本项目已验收能力。

## 1. 驱动方案总览

| 路线 | 输入与输出 | 人物准备 | 优势 | 主要边界 |
| --- | --- | --- | --- | --- |
| 动作底片 + 局部口型 | 视频帧 + 音频 → 更新嘴部/下半脸 | 预生成动作视频，缓存人脸框与遮罩 | 背景与身体稳定，计算集中在局部，素材可复用 | 身体与头动主要来自底片，不能自动跟随回答语义 |
| 音频 → 面部运动 → 肖像动画 | 照片 + 音频 → 运动参数 → 人脸动画与回贴 | 参考图、运动模型及肖像模型 | 可以实时产生表情和头动 | 音频驱动与肖像渲染是不同模块；侧脸、遮挡和身份稳定需验证 |
| 摄像头/视频运动迁移 | 参考图 + 驱动视频 → 肖像动画 | 参考图及摄像头或动作视频 | 可明确控制表情、头部姿态 | 需要运动来源，本身不负责根据文本理解动作 |
| 音频条件生成式视频 | 参考图 + 音频 → 连续视频 | 参考图、模型权重与推理服务 | 表现力潜力较高 | GPU 成本、启动等待、跨片段连续性和打断后清队列更难 |
| 3D 角色驱动 | 音频/动作指令 → 面部权重与骨骼动画 → 渲染 | 建模、绑定、材质及动作库 | 动作和视角可控，适合虚拟角色与空间交互 | 资产制作和渲染体系投入大，不是照片直接转真人视频 |
| 托管数字人服务 | 自有音频或文本 → 服务端数字人 → 媒体流 | 供应商人物资产或克隆形象 | 缩短模型部署与媒体工程周期 | 依赖供应商接口、网络、额度及使用条件 |

局部口型代表有 Wav2Lip、MuseTalk；运动迁移代表有 LivePortrait；生成式路线包括 SoulX-FlashTalk、SoulX-FlashHead。3D 路线中，Audio2Face-3D 输出面部 blendshape 权重，仍需角色绑定与渲染器，不直接输出真人视频。[MuseTalk](https://github.com/TMElyralab/MuseTalk)、[LivePortrait](https://github.com/KlingAIResearch/LivePortrait)、[Audio2Face-3D](https://build.nvidia.com/nvidia/audio2face-3d/api)

## 2. LiveTalking：模型驱动与实时推流框架

LiveTalking 将人物模型、TTS、会话和媒体输出串成实时链路。它支持 Wav2Lip、MuseTalk、ER-NeRF、Ultralight-Digital-Human，并提供打断、自定义空闲动作、WebRTC、RTMP 和虚拟摄像头等能力。全身视频拼接表示将驱动结果与全身素材合成，不能据此宣称可以实时生成语义手势。[LiveTalking 官方仓库](https://github.com/lipku/LiveTalking)

| 模型 | 驱动方式 | 资产与计算特点 | 适合用途 |
| --- | --- | --- | --- |
| Wav2Lip | 音频驱动局部口型，回贴到原帧 | 需要人脸区域预处理；原版 96 与 LiveTalking 的 256 权重需要分开记录 | 低成本口型基线、已有动作视频 |
| MuseTalk | 音频条件的潜空间局部重建 | 头像预处理与缓存，通常使用 CUDA GPU | 对嘴部画质要求更高的同素材对比 |
| ER-NeRF | 人物专属神经辐射场驱动 | 需要针对人物的数据和训练，人物准备较重 | 固定人物、可承担训练的场景 |
| Ultralight-Digital-Human | 轻量人物口型模型 | 专属人物素材与模型准备需单独评估 | 固定角色、强调运行成本的试验 |

本地检查确认，LiveTalking 的 `/humanaudio` 读取上传的完整音频文件，再交给人物会话。**内部流式推理不等于外部接口支持增量 PCM。** 如果 OpenRealtime 的 TTS 持续产生音频块，需要适配连续音频状态、序号、结束标记和取消，不能简单将每个小块作为独立 WAV 重播。

本项目现有名称中保留了 `LiveTalkingSession` 等历史命名，但当前启动器运行的是 OpenRealtime 自有 `avatar_renderer.py`，健康检查要求 `renderer=openrealtime`。不能把自有流式改造成果直接归为上游原生能力。

## 3. OpenTalking：编排层与多模型后端分离

OpenTalking 把人物资产、语音服务、会话与推理服务分层。模型回答“使用哪种生成方法”，backend 回答“在哪里、通过什么接口调用”。本地代码支持 `mock`、`local`、`direct_ws`、`omnirt` 四种 backend；OmniRT 是独立推理服务，不是新的数字人模型。[OpenTalking 官方仓库](https://github.com/datascale-ai/opentalking)

| 模型/工作流 | 本地实现与接入方式 | 需要注意 |
| --- | --- | --- |
| Mock | 静态帧，验证对话与媒体链路 | 不产生真实口型，不能用于画质或模型延迟验收 |
| Wav2Lip | 有本地 adapter，默认 backend 为 `local` | 本地框架可用不代表所有设备都能实时 |
| QuickTalk | 有本地 adapter；代码默认 `omnirt`，可显式选择 `local` | 模板视频、音频特征与人物缓存；会话保留独立运动状态 |
| MuseTalk | 有本地 adapter；代码默认 `omnirt` | 可以本地验证，但需匹配权重、预处理和 GPU 运行环境 |
| FlashTalk | 远端模型，默认 `omnirt` | 需要独立模型服务与硬件资源 |
| FlashHead | 默认 `direct_ws`，同时存在 HTTP 与 WebSocket 客户端 | 必须核实实际选中的客户端，不能仅按 backend 名称判断是否流式 |
| FasterLivePortrait + JoyVASA | 推荐 OmniRT：音频先生成运动，再渲染肖像 | LivePortrait 单独使用不等于音频驱动 |
| FasterLivePortrait 视频克隆 | 摄像头/上传视频提供运动，参考图提供身份 | 与 STT/LLM/TTS 对话链路是不同工作流 |

本地文档与代码有一处值得特别说明的差异：FlashHead 文档主要描述“音频写 WAV → HTTP 生成视频 → 解码成帧”，而代码已经包含 `FlashHeadWSClient`。所以本文保留两种路径，不将旧文档的“仅片段式”结论泛化到整个模型，也不将 WebSocket 客户端存在视为实时性能已验证。

对 OpenRealtime 的启发是复用其模型服务边界、人物资产预热和能力检查思路。我们已有对话与打断运行时，建议通过渲染适配层连接模型服务，避免同时维护两套对话状态机。这是架构建议，本轮没有迁移或运行 OpenTalking 服务。

## 4. 候选模型怎么选

| 目标 | 优先验证 | 判断依据与限制 |
| --- | --- | --- |
| 延续当前低成本本地路线 | 当前 Wav2Lip 256 + 自有合成/流式链路 | 已有本项目单路证据；模型来源、输入尺寸与许可单独登记 |
| 保留底片，提高嘴部画质 | MuseTalk | 与当前素材做同音频 A/B；不能只比较模型宣传视频 |
| 固定少量角色，降低运行成本 | FeatherTalk | 需要逐人物训练；官方提供轻量推理路径，流式接入仍需验证 |
| 浏览器端口型 | DH_live | 需要专用 Web 人物资产；品牌与资产授权条件独立核实 |
| 让照片产生表情与头动 | FasterLivePortrait + JoyVASA | 将音频到运动、运动到画面分别测量，再验整条链路 |
| 生成式单卡探索 | FlashHead Lite | 上游宣称单 RTX 4090 可实时；本项目尚未复现 |
| 更高质量生成式探索 | FlashHead Pro / FlashTalk | 计算开销显著增加；优先独立 GPU 服务评估 |
| 快速交付托管形象 | Anam / LiveAvatar | 项目已有供应商接入代码；需按具体模式验收自有音频和取消行为 |

FlashHead 官方将 Lite 与 Pro 分开：Lite 宣称单 RTX 4090 可实时，Pro 的实时条件为两张 RTX 5090 配合 SageAttention；这些是上游条件，不是任意单卡保证。FlashTalk 官方公布 14B 模型在 8×H800 上约 32 FPS、启动约 0.87 秒，不能将该数字套到消费卡或完整对话延迟。[FlashHead](https://github.com/Soul-AILab/SoulX-FlashHead)、[FlashTalk](https://github.com/Soul-AILab/SoulX-FlashTalk)

FeatherTalk 和 DH_live 应按各自人物准备流程评估；运行轻量并不意味着上传任意照片即可零准备使用。LiveAvatar 的 LITE 模式允许使用自有对话栈，适合与已有语音运行时分工。[FeatherTalk](https://github.com/anliyuan/FeatherTalk)、[DH_live](https://github.com/kleinlee/DH_live)、[LiveAvatar 模式说明](https://docs.liveavatar.com/)

## 5. OpenRealtime 当前工作链路

```text
离线准备
人物图片 → 动作底片 → 人脸区域与遮罩预处理 → 可复用人物资产

在线对话
用户语音 → 识别/轮次判断 → 对话模型 → 流式 TTS
                                          ↓
                         连续音频块 + 回答 ID + 块序号
                                          ↓
                  口型推理 → 局部合成 → 同步音视频 → WebRTC 播放

用户打断 → 取消旧回答 → 丢弃旧回答待播音画 → 接收新回答
```

当前动作路径默认选择 `wav2lip256`；启动器默认 256 输入、推理步长 2，中间帧通过合成处理补足播放帧率。人物有 Anam 实时绑定时，配置进入对应托管路径。因此“照片”“动作底片”“实时绑定”代表不同的资产与驱动能力，页面应分别说明。

建议继续保留统一渲染适配边界：人物初始化、增量音频、回答结束、取消、释放，以及播放进度和错误事件。音频采样率、时间戳、音频前视、队列上限和取消隔离必须成为明确约定。把上传成功当作用户已听到声音，会使打断状态与界面不同步。

## 6. 已测到什么，以及尚未证明什么

以下数据引用项目 2026-09-07 连续口型验收记录，**本次文档整理没有重新跑模型 benchmark**。条件为 Apple M1、16 GB、MPS、单会话，256 模型输入，768×768 输出，25 FPS，推理步长 2。

| 指标 | 记录结果 | 正确解释 |
| --- | --- | --- |
| 推理与合成吞吐 | 28.67 FPS | 单路持续产帧速度，有一定实时余量 |
| 接收视频帧率 | 约 25 FPS | 媒体输出节奏，不等于逐帧都重新推理 |
| 首块上传到服务端首音交付 | 872 / 883 ms | 两段实时音频分块样本；不含 TTS 首包、前端攒块、扬声器延迟 |
| 分块缺音造成的空闲帧 | 0 / 0 | 该两段样本没有因缺块插入空闲帧 |
| 浏览器短片独立验证 | 首音约 691 ms；最大服务端音频迟到约 188 ms | 网页负载有调度抖动，不可替换成专门录制时的较低迟到值 |

这些数据不证明纯 CPU、多会话、所有人物或逐音素同步均达标。2026-08-31 的 Wav2Lip 96 报告是历史基线，不能用来描述当前默认 256 路径。MPS 是 Apple 集成加速，也不能等同于纯 CPU。

完整交互延迟还包括轮次判断、模型首字、TTS 首包、攒块、模型音频前视、推理合成、编码传输及浏览器缓冲；其中部分步骤会重叠。应记录时间戳拆分关键路径，不能把 FPS 或模型启动时间当成用户体感延迟。

## 7. 下一步验证与成本口径

建议顺序为：**稳定当前本地口型 → MuseTalk 同素材画质对比 → FasterLivePortrait + JoyVASA 表情头动验证 → FlashHead Lite 生成式验证**。固定角色 CPU 路线和 3D 角色路线按产品需求单独立项。

每次评测固定人物素材、音频、输出尺寸和播放 FPS，分别记录冷启动与预热后表现。覆盖中文快慢语速、英文夹杂、长句、静音、转头、遮挡、连续分块与打断后立即重答；用完整音画录屏验嘴形、牙齿、下巴边缘、闪烁和身份一致性。

| 验收维度 | 应记录的内容 |
| --- | --- |
| 实时性 | 首音/首动 P50 与 P95、持续产帧速度、队列是否随时长增长 |
| 同步 | 同一媒体时基上的音画偏移、可见口型与声音对齐；时间戳正常不等于嘴形准确 |
| 打断 | 打断到静音/闭嘴时长、旧回答残留、旧取消是否误伤新回答 |
| 稳定性 | 长会话、重连、切人物、资源释放，以及 1/2/4 路并发时退化 |
| 质量 | 同输入完整视频盲测，覆盖嘴部与整个人物，不只看静态截图 |
| 成本 | 单个人物准备工时、资产存储、每并发算力与显存、实际利用率及带宽 |

自部署每有效会话分钟的计算成本可按“GPU 小时成本 ÷（60 × 达标并发 × 实际利用率）”估算，再加语音、网络、存储和运维；托管方案按当前报价和实际计费规则核算。两者都应摊入人物制作与训练成本，本页不承诺尚未实测的并发或固定单价。

## 8. 模型来源与版本边界

框架许可证、模型权重、训练数据和第三方人脸组件是独立来源。原版 Wav2Lip 明确限制非商业用途；不能因为外层框架采用 Apache-2.0，就推导其全部模型可商用。LiveTalking 的 256 权重也不能仅凭名字继承原版 96 的来源或授权结论。[Wav2Lip 官方使用说明](https://github.com/Rudrabha/Wav2Lip)

本地 LiveTalking README 有公开视频保留水印与标识的说明；这是本地快照的条件，不能不加版本地概括所有上游版本。本文不替任何候选权重作商用授权确认，正式选型时应记录具体权重来源与对应使用条件。

本次审阅基线：LiveTalking 本地 checkout `36837f90f8db3f59e1d7fcdd111a7db3842515d0`；OpenTalking 本地 checkout `cddd1228d5e39b2057b65a224e58d26a57fec158`。以本地工作树实际文件为准，提交号只标记基线，不代表不存在本地修改。

维护者可在仓库中核对以下证据：

- LiveTalking：`models/livetalking/repository/README.md`、`server/routes.py` 的 `humanaudio`。
- OpenTalking（相邻 open 目录）：`opentalking/models/registry.py`、`core/model_config.py`、`models/quicktalk/adapter.py`、`providers/synthesis/flashhead/{http_client,ws_client}.py`、`docs/zh/model-support/`。
- OpenRealtime：`src/lib/avatar-session-config.ts`、`src/lib/livetalking-process.ts`、`scripts/avatar_renderer.py`。
- 项目实测记录：`docs/reports/2026-09-07-streaming-mouth-optimization.md`；历史对照：`docs/reports/2026-08-31-open-source-cpu-lip-sync-research.md`。

本页仅展示技术资料与已有证据，列入候选不代表当前页面已提供相应模型切换能力。
