# OpenRealtime 竞品与替代路线分析

核查日期：2026-10-09。结合[2026-09-03 原调研](history/2026-09-03-openrealtime-improvement-todo.md)、项目已有语音/数字人研究、本地实现与最新官方资料。结论标注为“官方事实”“本地实现”“分析判断”“待测假设”；未部署全部竞品，不作横向性能排名。

## 1. 先分清竞争层级

用户实际在选择什么，比“是否支持语音”更重要。

| 层级 | 代表对象 | 用户选型问题 | 与 OpenRealtime 的关系 |
| --- | --- | --- | --- |
| 通用实时 Agent 框架 | Pipecat、LiveKit Agents、TEN | 怎样连接媒体、模型、工具与客户端，部署和扩展 | 直接框架竞争，也可能成为未来基础设施/组件 |
| 语音 Agent 应用运行时 | Qwen Audio Agent | 怎样持续交流并让外部 Agent 执行任务 | 最接近定位的直接竞争 |
| 角色与数字人应用 | Open-LLM-VTuber、OpenAvatarChat | 如何得到可互动形象、角色和客户端 | 体验与应用交付竞争 |
| 数字人渲染框架 | LiveTalking、OpenTalking | 如何驱动口型、人物动作与音视频输出 | 渲染替代，也有完整应用层重叠 |
| 硬件语音生态 | 小智 ESP32 | 如何把真实板卡、音频与工具接入 | 当前非主竞争；历史设备协同方向必须重新评估 |
| 原生语音模型/推理栈 | Moshi、PersonaPlex | 如何获得原生双流语音、音色和角色条件 | 交互技术替代，不是同层通用应用框架 |
| 托管原生语音 API | Gemini Live 等 | 如何用少量集成获得语音交互 | 对 API 级联方案的替代，也可成为适配目标 |
| 语义决策与呈现组件 | Jev、Anam、LiveAvatar | 如何判断和呈现 | 当前主要是供应商/互补组件，不能当成我们独有技术 |

## 2. 历史结论复核：保留什么、修正什么

原研究强调 A 模块灵活性、B 级联成本、C 会话时长、D 工具治理，并提出设备协同、国内供应商、垂直产品三条路线。当前复核如下：

| 旧结论 | 当前状态 | 修正后的意义 | 依据 |
| --- | --- | --- | --- |
| 模块级 Protocol/plugins 灵活性 | 保留，本地实现可核对 | 可独立选型，但 Pipecat/LiveKit/TEN/数字人项目同样有模块化，不能推导全面领先 | 本地 ASR/TTS/Brain/Turn/Agent 接口；各上游模块说明 |
| Qwen Audio Agent 深度绑定单一 Realtime | 不再作为当前结论 | v2 官方已列多种云端和本地语音前端；本地旧 checkout/9月3日报告不代表最新上游 | [Qwen 官方 README](https://github.com/QwenAudio/qwen-audio-agent) |
| 我们一定比 Qwen Audio Agent 更便宜 | 待测假设 | 对比具体语音前端与工作负载，含判停/打断、被取消请求、工具、数字人和运维 | 原报告的成本 TODO；本轮未新测账单 |
| 无会话时长限制 | 撤回绝对措辞 | 应说“运行时与供应商会话解耦”；ASR、TTS、认证、云数字人仍可能有限制 | 长会话压力与供应商期限尚须逐项验收 |
| Pipecat 结构性做不到多设备/后台任务 | 不成立为排他判断 | 其多 Agent、工具与自定义机制可以构建相关功能；我们的具体生命周期契约可比，不能声称对方做不到 | [Pipecat 生态索引](https://docs.pipecat.ai/llms.txt)、[函数调用](https://docs.pipecat.ai/pipecat/learn/function-calling) |
| 国内供应商是长期空白 | 降为场景与深度假设 | TEN、Qwen 等本就覆盖相关使用者；优势应来自真实组合优化、网络/费用/交付经验 | [TEN](https://github.com/TEN-framework/ten-framework)、[Qwen](https://github.com/QwenAudio/qwen-audio-agent) |
| 工具治理值得强调 | 保留本地能力，撤回“比所有参照更完整” | effect/risk/idempotency/confirmation/scopes 是可说明的契约；需要比较执行链、策略、确认和审计 | [本地 ToolDescriptor](../../server/tools/canonical.py)、[权限指南](../TOOL-PERMISSIONS.md) |
| 设备协同应优先押注 | 战略建议仍未证实 | 与小智、TEN 等正面竞争，需真机/运维投入；当前不宜作为首发亮点 | [ESP32 状态](../../clients/esp32/README.md)、[小智](https://github.com/78/xiaozhi-esp32) |
| 没有 CI/容器/认证/持久化 | 历史快照，不能照抄 | 当前已有相关实现；多实例与可靠性需要独立验收 | [项目完善审查](../PROJECT-IMPROVEMENT-AUDIT.md)、[公开部署](../deployment/public-trial.md) |
| MCP 是声明适配而非完整客户端 | 指定模块仍成立，不能泛化整个产品 | 当前 `McpToolSource` 仍接收 handler/schema；外部 Agent 自己的 MCP 也不等于运行时统一发现已实现 | [MCP source](../../server/tools/mcp_source.py)、[Agent Driver](../../server/agent_session/plugins/) |

原报告涉及贡献者数、模型、价格、TODO 和旧源码，应作为历史依据保留，不重新赋予“当前已确认”标签。

## 3. 主要竞争对象逐项分析

### 3.1 Pipecat：通用框架与生态竞争

官方事实：提供实时语音/多模态 pipeline、客户端、Flows、部署/评测生态；默认 Smart Turn 判停，打断控制支持模型附和过滤，工具调用有独立配置。[生态](https://docs.pipecat.ai/llms.txt)、[判停](https://docs.pipecat.ai/pipecat/learn/speech-input)、[打断](https://docs.pipecat.ai/pipecat/fundamentals/interruptions)、[工具](https://docs.pipecat.ai/pipecat/learn/function-calling)

分析判断：它最强的选择理由是积累好的接入和交付生态。标准语音/电话/多客户端任务，应将它作为基准。模块化、API 和“能打断”不足以区分我们。

OpenRealtime 的比较重点：已有 Web 产品体验、Jev 三类判停/六类打断与执行策略、特定供应商组合、工具治理和目标回复取消的可追踪链路。比较的是具体设计、接入工作量与结果，不是声称 Pipecat 没有相应扩展能力。

待验证：同供应商下默认策略与增强策略各跑一次；比较误抢话、误打断、漏响应、停止延迟、首音、内存及场景配置工作量。只拿我们的规则命中样例对 Pipecat 默认 VAD，不足以支持整体领先。

### 3.2 LiveKit Agents：媒体基础设施与完整交付竞争

官方事实：提供话轮/自适应打断，数字人目录包含 Anam、LiveAvatar 等服务，数字人可接收 Agent 的音频。[话轮](https://docs.livekit.io/agents/logic/turns/)、[数字人](https://docs.livekit.io/agents/models/avatar/)、[Anam](https://docs.livekit.io/agents/models/avatar/plugins/anam/)

分析判断：RTC、多终端或实时音视频网络是首要要求时，应优先评估这一生态。其 API 数字人同样不要求用户自建渲染 GPU。

OpenRealtime 的比较重点：当前 Web 产品与独立话轮策略的适配便利；本地语音应用路径主要是 WebSocket v2，不能以云数字人的 WebRTC 输出冒充整个语音输入链路已 RTC 化。数字人/Agent 分离是好设计，但不是专属优势。

待验证：相同浏览器/地区/音频环境下的弱网、重连、自动播放、数字人取消与成本。对方托管自适应能力、开源组件与套餐条件也须分开；本轮未在相同部署条件复测。

### 3.3 Qwen Audio Agent：最接近的直接竞争

官方事实：上游 v2 已强调可替换语音前端、云端/本地路线、ACP/A2A 后端，前台交流与后台任务并行；有多个客户端和数字人等场景示例。[当前官方仓库](https://github.com/QwenAudio/qwen-audio-agent)

分析判断：这意味着宽泛的“Agent 的语音入口”已经重叠。与它竞争，必须说明用户为什么选我们的具体交互控制与应用交付。

OpenRealtime 的潜在选择理由：在当前级联路线中独立调整 ASR/TTS、Jev 判断与 Brain；研究语义话轮的可解释决策；复用本项目人物、知识、记忆与设置界面。以上是本地方案特征，不能据此断言 Qwen v2 不支持类似控制或治理。

待验证：安装至真实对话时间、接入已安装 Agent 的步骤、相同任务完成率、长任务交流、可取消性、实际运行费用。若同样采用级联前端，做机制对照；如果一方用 S2S，报告产品结果并说明语音模型不同。不能把旧版本限制拿来比较现版本。

### 3.4 TEN：可扩展实时多模态与数字人竞争

官方事实：扩展生态涵盖 RTC/WebSocket、VAD/判停、数字人、SIP、ESP32 示例；快速入门有 CPU + API 组合。[官方仓库与示例](https://github.com/TEN-framework/ten-framework)

分析判断：TEN 使“国内用户 + 数字人 + 无自建 GPU”组合不再是明显空白。需要对比完成同一目标的扩展配置、开发工作量和维护边界。

OpenRealtime 的比较重点：Python/Next.js 工作流与现有产品、Jev 话轮策略，以及特定业务集成模板。没有部署双方相同场景，不应直接宣称 OpenRealtime 更轻量或 TEN 更难安装。

待验证：新增 classifier/供应商时的文件与代码修改、目标 Demo 的首次成功时间、RTC 路径、取消语义与模块诊断。TEN 的媒体/硬件示例也说明设备协同不能被视为无人竞争。

### 3.5 Open-LLM-VTuber：角色陪伴与客户端竞争

官方事实：Live2D、语音交互、视觉感知、桌面/宠物模式、离线路线；重组件也可采用云 API。上游同时说明 v2 在讨论规划阶段。[官方仓库](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)

分析判断：用户要的是桌面陪伴、角色表达或离线隐私时，它的产品形态更贴近需求。我们选写实云数字人和 Web Agent，应解释为场景不同，不能把 Live2D 贬为低质量。

比较重点：Web 业务服务、可配置语义交互与自己的工具/知识；不是“我们有形象，对方没有”，也不是“对方必须 GPU”。待验证角色吸引力、打断、持续交流和用户偏好；两种形象风格应让目标用户选择。

### 3.6 OpenAvatarChat：模块化交互数字人竞争

官方事实：模块化 ASR/LLM/TTS/Avatar，支持多种数字人；当前说明所有数字人支持手动及双工打断，并提供含百炼 API 的配置。[官方仓库](https://github.com/HumanAIGC-Engineering/OpenAvatarChat)

分析判断：它与“开放、可替换的数字人对话”直接重叠。本项目可强调无需自建渲染推理的云方案以及 Jev/运行时控制，但云服务不是普遍领先的证据。

比较重点：人物效果、部署资源、语义附和/纠正动作、数字人停播与首帧、现有业务接入。上游页面的响应时间来自其测试，不与我们的模型请求耗时直接比较；也不推导对方缺少本轮未核实的语义策略。

### 3.7 LiveTalking：渲染组件，也有应用重叠

官方事实：支持多种渲染模型、说话打断、动作编排与多种推流输出，包含客服等应用说明；安装涉及模型权重与推理环境。[官方仓库](https://github.com/lipku/LiveTalking)

分析判断：需要自部署、定制人物和推流时，它既是强候选，也可以是互补渲染基础。不能将它描述成只有口型且完全不支持对话。

OpenRealtime 的选择理由：以交互与 Agent 管理作为主轴，提供云呈现与应用层组合。比较实际 GPU 利用率和云会话费用、人物授权、素材预处理、打断后残留音视频；是否更经济取决于利用率与视觉要求。

### 3.8 OpenTalking：应用/渲染层双重竞争

官方事实：WebUI 管理人物、语音和模型，具有实时对话、视频制作/克隆等流程；编排与渲染可分开部署，CPU mock 与真实 GPU/远程推理路线分别说明。[官方仓库](https://github.com/datascale-ai/opentalking)

分析判断：其完整应用能力与模块化削弱了单纯“我们有 WebUI/数字人”的差异。CPU mock 的链路验证不等于真实神经渲染，比较时必须保持这一边界。

比较重点：交互策略与外部 Agent、云呈现的接入成本、人物制作到真实交流的时间、可取消性与运维。若需求主要是数字人渲染、制作或私有部署，应优先考虑它；本项目不主张覆盖更多渲染模型。

### 3.9 小智 ESP32：硬件方案的强竞争者

官方事实：设备网络、Opus、唤醒、录放音与 MCP 控制等硬件能力已形成产品路线。[官方仓库](https://github.com/78/xiaozhi-esp32)

本地事实：OpenRealtime ESP32 客户端还是 demo，真实音频采集与播放尚未接入。[本地状态](../../clients/esp32/README.md)

分析判断：现在用“设备协同”宣传，会把项目带到已有强生态且自身未完成的战场。保留为长期候选，先明确机器人/设备具体任务，再验证硬件、网络、控制确认与 OTA；不能用服务端 DeviceFleet 接口证明真机可交付。

### 3.10 Moshi / PersonaPlex：原生语音的技术替代

官方事实：Moshi 发布双流语音模型、Mimi codec 与不同后端；PersonaPlex 提供角色/声音条件与实时服务，文档区分 GPU 不足时的 CPU offload 和纯 CPU 离线评测。[Moshi](https://github.com/kyutai-labs/moshi)、[PersonaPlex](https://github.com/NVIDIA/personaplex)

分析判断：这里比的是原生语音建模与级联系统的质量/控制取舍，不能拿“训练模型更复杂”证明运行时更好。Moshi 也有 Apple MLX 路线，不应说所有本地方案都只支持 NVIDIA GPU。

OpenRealtime 的选择理由：云级联下不用维护这些模型权重，文本 Brain 与工具链可独立更换。取舍是转写误差、文本路径对韵律信息的损失，以及多个云调用带来的尾延迟。需要评估自然程度、重叠交互、目标语言效果和算力成本；不把可打断的级联 runtime 说成与原生双流架构相同。

### 3.11 托管 S2S API：API 路线内部的竞争

官方事实：Gemini Live 提供托管实时交互 API；原生路线及其他供应商的历史扫描见项目9月17日模型研究，旧型号与价格仍须另行核验。[Gemini 官方概览](https://ai.google.dev/gemini-api/docs/live-api)、[历史模型研究](../GPT-live-1/realtime-full-duplex-voice-models-comparison-2026-09-17.md)

分析判断：API-only 并不一定意味着应选择级联。托管 S2S 可减少组件拼接，我们的独立选型可能增加调优/故障处理成本。两者要比较总体验与总成本，不用“开放更多接口”代替结果。

比较重点：语音模型是否适合目标语言、工具和任务反馈、会话限制、网络可达性、实际账单及独立更换服务的收益。本轮不重新给所有商业 API 下性能或价格结论。

## 4. 能力与部署矩阵

这里记录当前公开/本地路径，不给未核实能力打叉；“可扩展”与“现成可用”分开。

| 对象 | 主要交付单位 | 云 API / CPU 应用路线 | 交互控制证据 | 数字人/角色路径 | 首要选型维度 |
| --- | --- | --- | --- | --- | --- |
| OpenRealtime | Web 应用 + Python runtime | 已有；云模型不要求自建 GPU，应用仍需部署 | Jev/LLM、规则、actor/取消；真实质量按版本验收 | Anam、HeyGen LITE、可选本地/动作编排 | 语义交互策略与语音/数字人组合便利 |
| Pipecat | 框架 + SDK/Flows/部署生态 | 有 API 路线 | Smart Turn、打断、附和策略 | 多模态生态；具体 renderer 按配置核对 | 通用集成/电话/客户端 |
| LiveKit Agents | Agent + RTC/媒体生态 | 有云服务与插件路线 | turn detection、自适应打断 | 多种云 avatar | RTC、多终端、网络质量 |
| Qwen Audio Agent | 持续对话/任务 runtime + 客户端 | 云与本地前端可替换 | 前台/后台任务控制；策略细项本轮未全审 | 有数字人示例 | Agent 集成与持续任务交流 |
| TEN | 实时多模态框架/扩展 | CPU+API 示例 | VAD/判停等扩展 | 多供应商与 Live2D 示例 | 扩展/RTC/硬件 |
| Open-LLM-VTuber | 角色应用/桌面客户端 | 本地/云可选 | 语音打断；细分策略未全面审计 | Live2D | 陪伴、桌面、离线 |
| OpenAvatarChat | 交互数字人应用 | 语言组件可用 API；渲染资源按模型 | 手动/双工打断；语义细类未全审 | 多种开源渲染模型 | 人物与私有渲染 |
| LiveTalking | 渲染/对话/推流 | 云语言服务与本地渲染组合 | 支持打断，细类未全审 | 多模型与动作编排 | 渲染、推流、自部署 |
| OpenTalking | 数字人应用 + 分离部署后端 | CPU mock；真实渲染按 GPU/远程配置 | 实时对话；细类未全审 | 多种真实渲染流程 | 渲染/制作/私有部署 |
| 小智 ESP32 | 设备固件 + 服务接口 | 设备端低算力，云后端按配置 | 硬件唤醒/录放音/工具链 | 显示/表情，不等同写实云数字人 | 真机与设备生态 |
| Moshi/PersonaPlex | 原生语音模型/服务 | 本地推理资源依后端，不是免推理应用 | 原生双流；质量需实测 | 非本轮重点 | 自部署模型与语音特性 |
| Gemini Live 等 | 托管语音模型 API | 本地不必自建模型 GPU | 模型/服务控制；选项依供应商 | 另加呈现层 | S2S 质量/服务约束 |

## 5. Jev：组件、传播入口与能力边界

Jev 是结构化决策模型，不是另一套完整语音平台。它接收 state 和类型化问题，返回选择、分布和置信度；本项目实现三类判停、六类打断，并提供历史与当前观察。[官方介绍](https://docs.typesafe.ai/introduction)、[置信度](https://docs.typesafe.ai/confidence)、[本地适配器](../../server/turn_policy/plugins/jev_classifier.py)

适合传播的是“窄判断交给决策模型，回答交给 LLM，动作由运行时协调”。项目没有训练专属分类模型，可作为标签描述式 zero-shot 使用的案例；这不证明所有语言/场景无需评测，也不证明声源判别或低置信度动作可靠。

本地旧合成集和真实 API 复测已有误判。约300ms级模型调用不能等同于端到端语音延迟；官方其他任务速度倍数更不能直接引用为我们的速度。Jev 是当前方案选项与技术故事，长期定位不绑定单一模型品牌。

## 6. 成本分析：先建同口径账本

“级联可选更便宜的服务”是合理假设，“级联总是比 Realtime 便宜”不是结论。

| 路线 | 总费用应包括 | 容易漏算的部分 |
| --- | --- | --- |
| 级联 + Jev | ASR音频计费 + 判断请求 + LLM输入/输出 + TTS + 应用/网络 | 未提交候选、取消请求、重试、历史上下文、静默期间计费 |
| 托管 S2S | 输入/输出语音或时长计费 + 文本/工具 + 应用/网络 | 静默、会话保活、缓存、工具反馈与期限切换 |
| 云数字人 | 上述语音/Agent费用 + avatar会话/启动/超额/套餐 | 倾听/静默是否计费、分钟闲置、角色额度、并发档位 |
| 本地推理/渲染 | 算力租赁/折旧 + 电力 + 维护 + 存储/网络 | 空闲利用率、素材预处理、并发显存、模型授权 |
| 预生成动作编排 | 语音/Agent费用 + 一次性素材制作 + 存储/CDN | 不保证逐音素口型，不能与实时渲染当等价效果 |

建议测三组工作负载：短请求、长说明、长静默/高打断；每组保持同一脚本与模型质量目标，输出每成功会话费用、失败尝试费用、活跃/静默时长与人工维护。对数字人另外固定目标人物和画质。

历史报价仍见[数字人选型](../reports/2026-09-07-digital-human-selection-research.md)，本轮不将9月报价当作10月报价，也不提供未核实的便宜百分比。

## 7. 选择建议与失败条件

| 真实需求 | 优先候选 | OpenRealtime 何时值得选 |
| --- | --- | --- |
| 目标交互应用 + 自己的话轮策略/模型/数字人组合 | OpenRealtime 与成熟框架自定义方案 | 已有界面与组合节省交付，策略可调且实际体验验收通过 |
| 通用语音/电话/多客户端 | Pipecat、LiveKit、TEN | 我们的特定集成价值明显超过补生态成本时 |
| 已有编码 Agent，希望随时说话并持续跟任务 | Qwen Audio Agent 与 OpenRealtime | 特定交互策略、Web/数字人需求及自己的控制边界 |
| 桌面角色、Live2D、离线陪伴 | Open-LLM-VTuber | 用户确实更需要 Web/写实云呈现时 |
| 自部署数字人渲染/视频生产 | OpenAvatarChat、LiveTalking、OpenTalking | Agent/话轮是主问题，渲染作为可替换边界时 |
| 硬件/智能设备 | 小智、TEN 等 | 完成对应真机与运维验证之后 |
| 原生双流语音/本地模型研究 | Moshi/PersonaPlex 等 | 需要的是应用运行时与可替换文本 Agent，而非模型训练/推理时 |

定位失败的信号：采用者仍需修改大量内部源码；语义分类加入后真实体验更慢/更容易卡住；数字人遮掩不了漏响应；API账单抵消了便利；同样功能用成熟框架更快交付。出现这些信号，应调整交付和策略，不能只增加宣传词。

## 8. 对外内容与后续研究

本轮可以使用：语义话轮的职责分离、Jev 判停/打断适配、云 API 无自建 GPU 路线、数字人保留自己的 Agent、可诊断的回复/播放生命周期。机制有实现依据，效果仍按证据等级表述。

需要新增实验后使用：更快、更便宜、目标语言更准确、更少误打断、长会话更稳定、部署更简单。建议以 Pipecat 为级联工程基准、Qwen Audio Agent 为近似产品基准、LiveKit 为媒体交付基准、OpenAvatarChat/OpenTalking 为人物体验基准。基准不等于所有对象都要同时实现一套 Demo。

优先收敛三个产品资产：固定英文交互场景及独立验收集，再扩展多语言；可跑的 CPU+API/云数字人模板；可对账的交互时序与费用记录。这些比增加一批供应商标签更能支撑 README 和宣传。
