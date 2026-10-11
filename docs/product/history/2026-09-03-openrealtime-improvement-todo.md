# 历史快照说明

原调研日期：2026-09-03。归档日期：2026-10-09。来源：工作区 open/voice-agent-research/openrealtime-improvement-todo.md。

以下正文保留原文，包含当时的判断、当地路径与未完成 TODO，不代表当前现状；尤其单一 Qwen 前端、Pipecat 结构性限制、成本与无限时长等判断，必须结合 [2026-10-09 复核](../COMPETITIVE-ANALYSIS.md) 阅读。不能将原文直接用于 README 或宣传。

原始正文 SHA-256：`93d3c15c8bdb8b267e7993c1f9098e81f56e637a49c0261dd807e9ce28eb7c2f`。

---

# OpenRealtime 改进需求清单

> 来源:2026-09-03 对 pipecat / qwen-audio-agent / OpenRealtime 三个语音 Agent 项目的架构调研对比。
> 参照项目本地路径:
> - Pipecat: `/Users/forever/workspace/open/pipecat`
> - Qwen Audio Agent: `/Users/forever/workspace/open/qwen-audio-agent`
> - OpenRealtime: `/Users/forever/workspace/OpenRealtime`

## 结论摘要

- Pipecat 在**架构层面**没有"实时语音前台应答 + 复杂任务后台异步执行"的强制契约。它的 Worker+Bus+Job 是通用分布式多 Agent 计算原语(`request_job_group` 官方定义为 fire-and-forget),可以用来搭这种模式,但没有强制/内建。
  - **补充修正(2026-09-03 二次调研)**:Pipecat 在**工具调用粒度**上其实有一个精神相通的机制——`llm_service.py` 中每个 `@tool` 可设 `cancel_on_interruption=False`,官方文档原话:"the LLM continues the conversation immediately without waiting for the result, and the result is injected later via a developer message",还支持中间态更新(`is_final=False`)、`timeout_secs`、`cancellable_by_llm`。本质和 `spawn_thinking` 相通,只是粒度更细、是**可选配置**而非**架构强制契约**——是否异步由每个工具作者自己决定,没有文档层面的不可违反边界。
- Qwen Audio Agent **有**这个架构,且是文档层面强制的不变量:实时层工具集极小(不做编排),复杂任务必须经 `spawn_thinking` 派发给后端 Agent(ACP/A2A),结果在安全时机自然插回对话。这是它相对 OpenRealtime 的关键差异点之一。
- OpenRealtime 自身的 Turn Policy / Generation Lease 设计不逊色,差距主要在**工程成熟度和验证方法**,不在架构思路。
- Pipecat 保证时延靠四层叠加,而非单一"架构隔离"手段:①流式管线(LLM按句子流式吐出、TTS边生成边念,消除等待整段回复的大头时延)②语义级 turn detection(减少误判用户是否说完带来的隐藏时延)③工具调用可选异步化(见上,消除慢工具的长尾时延)④全链路 TTFB/TTFA/TTFAT 埋点(定位时延瓶颈,持续优化的前提)。

## 差异化战略方向

> 背景:如果 OpenRealtime 继续在"通用语音 pipeline 框架"赛道上跟 Pipecat 拼功能完整度(更多 provider、更多 transport、更成熟的打断机制),几乎不可能赢——Pipecat 背后是 Daily.co 商业公司持续投入 + 375 个贡献者 + 3 年生产打磨,这是资源量级差距,架构设计弥补不了。真正的问题不是"怎么做得比 Pipecat 好",而是"打哪个 Pipecat 没有认真做、或结构性做不到的战场"。

### 已确认的现有优势(2026-09-03 用户补充)

- **A. 模块级灵活性**:OpenRealtime 已经是 Protocol + plugins 架构(ASR/TTS/VAD/Brain/Transport/WebSearch/KnowledgeBase/AgentSession/DeviceFleet 每个都是独立 Seam),可以自由替换和组合模块。这一点本身不弱于 Pipecat 的 Service 抽象,应作为营销/文档层面明确强调的卖点,而不只是内部工程约定。
- **B. 相对 Qwen Audio Agent Realtime 成本更低**:qwen-audio-agent 深度绑定 DashScope Qwen-Audio/Omni Realtime(端到端语音模型,按时长/token 计费通常较贵);OpenRealtime 是级联式架构(ASR/LLM/TTS 可分别选型),可以按需换成更便宜的组合(如 Doubao/DeepSeek),对成本敏感场景是明确优势。**行动项**:
  - [ ] 补一份实际成本对比测算(相同对话场景下,OpenRealtime 当前默认栈 vs DashScope Realtime 的每分钟/每次会话成本),把"成本更低"从定性说法变成可引用的数字,用于文档和选型宣传。
- **C. 无会话时长限制**:qwen-audio-agent 依赖 DashScope Realtime API,大概率有会话时长上限(端到端语音模型厂商 API 普遍有此限制);OpenRealtime 级联架构下 ASR/LLM/TTS 都是独立长连接,理论上不受单一厂商 session 时长限制。**行动项**:
  - [ ] 核实 DashScope Qwen-Audio/Omni Realtime 当前官方文档的会话时长限制(避免用过时信息做对比宣传),并在 OpenRealtime 侧做一次长会话(如 1 小时+)压测,验证"无时长限制"在工程上真的立得住(而不只是理论上没有单点限制)。
- **D. 工具治理维度比两个参照项目都更完整(2026-09-03 工具调用专项调研发现)**:`server/tools/canonical.py` 的 `ToolDescriptor` 已经声明了 `ToolEffect`(含 `CONTROL_DEVICE`/`SPEND_OR_TRANSFER`/`EXECUTE_CODE` 等)、`RiskLevel`、`IdempotencyClass`、`ConfirmationRequirement`、`required_scopes` 五个安全治理维度,并有 `policy_gateway.py` 做服务端强制的 Bound Confirmation。Pipecat 的 `@tool`/`FunctionCallRegistryItem` 和千问的 `FrontendToolRegistry` 都只有"是否阻塞/超时/能否被打断"这类**执行时序**维度,没有风险分级、幂等性、授权范围这类**安全治理**维度。这对方向 1(DeviceFleet 设备控制,天然需要 `CONTROL_DEVICE` 效应的强确认)是一个可以直接复用的结构性优势,值得作为差异化卖点强调,而不只是内部实现细节。

### 待评估的新方向(按建议押注优先级排序)

1. **设备协同(DeviceFleet)+ Agent 委派(ACP)组合** —— 现有代码里 `DeviceFleet` Seam 和 `server/agent_session/plugins/acp_driver.py` 已经是雏形,但 ESP32 音频通路未接通(ISSUE-0017)。押注"一个语音入口协调多个物理设备,同时把复杂任务委派给后端 Agent"这个场景,是 Pipecat 结构性做不到(它的心智模型始终是"单会话服务单 bot")、又能和 qwen-audio-agent 错位竞争(不是同类打法,不是正面拼语音模型)的方向。
   - 权衡:需要真金白银把 ESP32/IoT 端跑通,目前只是占位,投入不小;一旦做成是功能性差异,不是难以感知的"打断更细"之类的差异。
   - [ ] 评估 DeviceFleet + ACP 组合场景的具体产品形态(智能家居/机器人/车载),拉一次专项调研评估现有实现完整度和缺口工作量。

2. **深耕国内供应商栈**(Doubao/DashScope/DeepSeek),而非追求 provider 广度。Pipecat 的 60+ provider 几乎全是欧美厂商,对国内技术栈的深度优化(网络重连策略、合规数据落地、成本更优的模型路由)是结构性长期空白,不是 Pipecat 短期会来抢的位置。
   - 权衡:天花板是国内市场而非全球开源生态,star 数不会有 Pipecat 量级,但商业变现路径更直接;单靠本地化容易被后来者复制,建议作为工程侧"顺手做"而非唯一主战场。
   - [ ] 结合上面 B/C 两条已确认优势,把"国内供应商栈+成本+无时长限制"包装成一个连贯的定位叙事,而不是三条孤立的技术点。

3. **放弃"框架"定位,做具体垂直产品**(智能座舱/陪伴机器人/客服场景之一),用 OpenRealtime 当引擎而不是拿去跟 Pipecat 正面竞争框架层面的成熟度。作为方向 1/2 都做不动时的保底选项。

## TODO

### 1. 测试要断言交互结果,不要只断言状态迁移
- **现状问题**:ISSUE-0021 记录过 425 个测试全部通过,但打断(barge-in)实际不生效这种 P0 缺陷未被发现,因为测试只验证了 Turn Policy FSM 的迁移路径,没有验证真实交互结果。
- **参照**:Pipecat 的 `pipecat.evals`(`src/pipecat/evals/`)——驱动真实 bot 端到端、以 RTVI 客户端身份合成/回放用户语音轮次,并对延迟、文本内容、function call、LLM judge 等做行为级断言,而不仅是帧流转层面的 mock 测试。
- **行动项**:
  - [ ] 为 OpenRealtime 补一层行为级评测(端到端拉起真实/模拟音频输入,断言实际打断是否发生、实际最终输出内容),参考 pipecat 的 YAML 场景 + judge 设计。
  - [ ] 针对 ISSUE-0025(合成音频无法触发 Silero VAD)先解决测试音频的真实性问题,否则打断路径永远测不出问题。

### 2. Transport 层引入类似 Serializer 的二进制/编解码抽象
- **现状问题**:当前仅 WebSocket JSON + base64 音频,带宽损耗约 33%(ISSUE-0019),且无二进制帧/codec 协商能力。
- **参照**:Pipecat 的 `serializers/`(`FrameSerializer` 基类 + Twilio/Plivo/Vonage/Telnyx/Exotel/Genesys 等电信协议实现,处理 μ-law 等编解码细节)。
- **行动项**:
  - [ ] 设计一个 `FrameSerializer`-类似的抽象层,支持二进制帧传输而非 base64。
  - [ ] 评估是否需要电话运营商协议(Twilio 等)接入,如果有对应场景可直接借鉴 pipecat 的实现思路,不必重新发明编解码细节。

### 3. 补齐生产基础设施(CI / Dockerfile / 认证 / 限流 / 多实例路由)
- **现状问题**:ISSUE-0018/0020/0024 指出——无 CI(`py.typed` 承诺无 mypy 验证)、无 Dockerfile、数据面无认证(Endpoint Session 仍匿名)、无限流、无多实例会话路由、无指标聚合。
- **参照**:Pipecat 有 Pipecat Cloud 部署路径和企业支持;Qwen Audio Agent 有 CI 覆盖多平台多 Node 版本。
- **行动项**:
  - [ ] 补 CI(至少跑 pytest + mypy + lint)。
  - [ ] 补 Dockerfile / 容器化部署路径。
  - [ ] 数据面加认证机制(即便先做最简单的 token 校验)。
  - [ ] 补基础限流和多实例会话路由,否则无法真正多用户上线。

### 4. 用真实 MCP client 替换占位实现
- **现状问题**:ISSUE-0014 指出的问题在 2026-09-03 工具调用专项复查中被重新核实,**仍然成立**——`server/tools/mcp_source.py` 只是个 schema adapter,把调用者已经构造好的 `handler`+`input_schema` 包装成 `CanonicalTool`,没有真正的 MCP transport(stdio/SSE/HTTP)、handshake 或 server 端工具发现。`policy_gateway.py` 的 `ToolOrigin` 枚举已经预留了 `MCP = "mcp"`,`canonical.py` 的模块文档字符串也明确写了"MCP servers, function-calling declarations, and skills are all adapted into this one shape"——**架构方向本身是对的,只是这一个适配器没写完**。
- **重要澄清:MCP 和 function calling 不是二选一**。逐行看过 Pipecat 的 `services/mcp_service.py`(`MCPClient.tools()` → `_convert_mcp_schema_to_pipecat` 把 MCP 工具转成标准 `FunctionSchema`,和手写 `@tool` 完全同形)和千问的 `providers/mcp/frontend-mcp-client.mjs`(把 MCP 工具转成标准 `type:'function'` schema,namespace 成 `mcp__{server}__{tool}`,并对 schema/输出做 16KB/24KB 硬限制)后确认:两个参照项目都把 MCP 当作**工具的一种动态来源**,发现到的工具最终都被拍平成和手写 native function-calling 工具完全一样的形状再喂给 LLM——从 LLM 视角根本看不出一个工具是本地实现还是转发到 MCP server。OpenRealtime 不需要在两者之间做选择,只需要让 `mcp_source.py` 从"空适配器"变成"真的连 MCP server 的适配器"。
  - **易被误传的简化说法,需要主动纠正(2026-09-03 追问确认)**:不要把结论简化成"Pipecat 用 MCP、千问用 Tools"——两个项目都是**同时支持**两者:Pipecat 原生 `@tool` + 真实 `MCPClient`;千问原生 `FrontendToolRegistry` + 真实 `frontend-mcp-client.mjs`。两者的 function-calling 都是基础机制,MCP 只是接入同一套 function-calling 接口的一种可选动态来源,不是替代关系。OpenRealtime 和它们的真实差距不是"该选哪种机制",而是 OpenRealtime 的 MCP 适配器**没有真实 transport**(见上),这一点补完之后原生 function calling(`FunctionCallingToolSource`)和 MCP(`McpToolSource`)会像参照项目一样并存,而非二选一。
- **参照**:
  - Pipecat `MCPClient`(`src/pipecat/services/mcp_service.py`)的 session 生命周期管理值得直接借鉴:专属内部 task 持有 anyio-bound 的 `ClientSession`(因为 MCP transport 要求开/关在同一个 task),`start()`/`close()` 允许从不同 task 调用,支持 stdio/SSE/streamable-HTTP 三种 `ServerParameters`。
  - 千问 `frontend-mcp-client.mjs` 的工具命名空间化(`mcp__{serverKey}__{toolName}`,避免多个 MCP server 工具重名冲突)和输出/schema 大小硬限制(语音场景下工具结果太长会直接拖慢 TTS,必须比一般 Agent 场景更严格截断)。
  - Qwen Audio Agent 把 `@modelcontextprotocol/sdk` 作为一等依赖,并通过 `BackendPort`/Backend Adapter SDK 统一接入十余种真实后端 Agent(Qwen Code、Claude Code、Codex、OpenCode 等)。
- **行动项**:
  - [ ] 把 `mcp_source.py` 实现为真正的 MCP client adapter(stdio + streamable HTTP 至少各一种 transport),产出的 `CanonicalTool` 一律打上 `ToolOrigin.MCP`,直接接入现有 `policy_gateway.py` 的 confirmation/risk 流程——不新建执行路径。
  - [ ] 借鉴千问的命名空间化和输出大小限制,避免语音场景下 MCP 工具的长输出拖慢 TTS 首字延迟。
  - [ ] 参考 qwen-audio-agent 的 ports-and-adapters 模式,评估是否要支持接入外部编码 Agent(而不仅是内建 Brain)。

### 5. 把"前后端边界"写成强制架构契约
- **现状问题**:Brain/ToolCallingBrain 的职责边界目前没有被文档化为不可违反的规则,长期可能被"实时层慢慢塞入过多编排职责"腐化。
- **参照**:Qwen Audio Agent 的 `docs/architecture/deep-dive.md` 把"实时前端只做轻量工具、不做多步编排,复杂任务必须走 spawn_thinking 异步派发"写成正式架构文档,任何违反都算架构变更需要评审。
- **行动项**:
  - [ ] 在 OpenRealtime 的 ADR 体系里补一篇"前后端边界契约"ADR,明确 Brain 允许做什么、不允许做什么。
  - [ ] 评估是否需要类似 `spawn_thinking` 的显式异步任务派发原语,把耗时任务(而非纯对话)从主 Turn Policy 循环里挪出去。

### 6a. 工具从未接入生产 composition root——"建了但没接线"是这个项目反复出现的失败模式(2026-09-03 追问"给最终用户接工具的灵活性"后发现)

- **触发问题**:用户追问的不是架构好不好,而是"如果要把 OpenRealtime 开放给最终用户接入自己的工具,当前这种方式是不是要改项目源码"——顺着这个问题查下去,发现比"第 4 条里 MCP client 是空实现"更严重的问题:**OpenRealtime 目前没有任何一条路径把 ToolRegistry / ToolCallingBrain 接进真正跑起来的生产应用**。
- **证据**:
  - `server/application/runtime.py`(唯一的生产 composition root)对 `Brain`/`ToolRegistry` **零引用**。
  - `server/tools/*.py` 里除 `ClockToolSource`(只在 `chat_brain.py` 里被引用其 `localize` 辅助函数,不是类本身)外,`WebSearchToolSource`/`KnowledgeBaseToolSource`/`McpToolSource`/`FunctionCallingToolSource`/`SkillToolSource` 以及 `ToolCallingBrain` 本身,**除测试文件外零构造点**——`grep -rn "ToolCallingBrain(" server --include="*.py" | grep -v __pycache__` 无结果。
  - 唯一真正构造过有内容的 `ToolRegistry`/`ToolCallingBrain` 的地方是 `demos/voice_web_server.py::_build_brain`,而且:
    1. 靠一个全有全无的环境变量 `VOICEAGENT_DEMO_TOOLS` 门控(没设就是零工具的 `ChatBrain`);
    2. 工具列表是硬编码在 `_build_tool_registry()` 里的 Python list literal——`ToolRegistry([ClockToolSource(), WebSearchToolSource(_build_web_search(telemetry))])`——不是配置/清单驱动,加一个工具必须改这一行代码。
  - `docs/adr/0032-wire-web-search-tool-calling-into-live-demo.md` 记录的正是这个模式,并且明确点名这是**第三次**发生同类问题(ADR-0030 时间基准接地、ADR-0035 Silero VAD/语义 EOT/语义打断是前两次实例)。ADR-0032 修的是 `demos/voice_web_server.py`,**不是** `server/application/runtime.py`——即这个 bug 类在"demo 层"被抓到并修过一次,但在真正的生产 composition root 上从未被检查/修过。
  - 全库搜索 `tools.yaml`/`tools.json`/`register_tool`/`TOOL_PLUGIN`/`load_tools`/`discover_tools` 等关键词,**没有任何配置驱动或插件式的工具注册机制**。
- **为什么这比"需要改代码"更糟,直接决定了终端用户的工具接入体验**:对比 Pipecat(`MCPClient` 指向任意 MCP server,工具自动被发现并转换成标准 `FunctionSchema`,加一个工具零代码改动)和千问(`agentContext.frontend.tools` 在会话请求 context 里传一段 JSON 就能注入新工具,零新增源文件),OpenRealtime 今天要让一个工具在真实会话里生效,即使第 4 条里的 `mcp_source.py` 补完真实 MCP transport,用户仍然要:
  1. 在 `server/tools/` 里写一个 Python 类实现 `ToolSource`(或配置好一个 MCP server 声明);
  2. 手动改某个 composition root 的源码,把它塞进 `ToolRegistry` 并接到 `Brain`;
  3. 而第 2 步目前甚至没有一个稳定、文档化、在生产上验证过真的生效的接入点——历史上三次(ADR-0030/0035/0032)这一步都被漏掉过,且目前生产 runtime 大概率仍是"零工具"状态。
  这不只是"要改源码"的问题,而是"改的那个地方本身不可靠、还没人确认它在生产上真的通"的问题——这才是当前工具调用方式给终端用户感觉"要改项目代码"背后的真实成因。
- **行动项**:
  - [ ] 核实 `server/application/runtime.py` 目前实际部署/演示所用的入口到底走的是哪个文件、哪个 Brain,把"生产环境今天到底有没有工具调用能力"这个现状先钉死,不要继续在不确定的假设上做后续决策。
  - [ ] 建立一个**唯一、稳定、有集成测试覆盖的工具接入点**(例如启动时从环境变量/配置文件读取一份 MCP server 列表 + 本地 `ToolSource` 列表,统一交给一个 `build_tool_registry()`,demo 和生产共用同一份逻辑而不是各自决定是否接线),并补一条集成测试断言"设置了工具配置后,真实会话里 LLM 确实能看到并调用该工具"——像 ADR-0032 那样事后修一次治不了根,要断这个失败模式复发的可能性。
  - [ ] 把这一条和第 4 条(真实 MCP client)绑定成同一个验收标准:"零代码加工具"不能止于"MCP client 能连上 MCP server",必须验证到"运维/用户在配置里加一行 MCP server 地址 → 重启或热加载 → 该工具在生产会话里真的被 LLM 调用成功"这个完整链路,否则第 4 条做完也不解决终端用户的实际问题。

### 6. 工具运行时补齐"单次调用级"取消与中间态更新
- **现状问题(2026-09-03 工具调用专项调研后修正)**:此前的表述——"FAST/VARIABLE/BACKGROUND 是预设死档位,不是工具自己声明"——**核实后是错的,已纠正**。实际读代码发现 `LatencyClass` 本来就是 `ToolDescriptor` 里每个工具自己声明的字段(`tools/clock_source.py` 声明 `FAST`,`tools/web_search_source.py`/`knowledge_base_source.py` 声明 `VARIABLE`),`policy_gateway.py:408`/`realtime/capabilities/brain_streaming.py:110` 也确实按每个工具的 `descriptor.latency` 分别判断,不是全局固定档位。这一点不逊于 Pipecat。
  - 真正的差距在另外两点,和 Pipecat 逐行对比后确认:
    1. **取消粒度是 response 级,不是调用级**:`realtime/tool_controller.py` 的 `ToolCancellation` 挂在 `_cancellations_by_response_id`,只在整个 response 被打断/失败/取消时联动触发;没有"LLM/用户主动取消某一个后台调用、但对话和其它并行调用继续"的独立通道,对应 Pipecat 的 `cancellable_by_llm`。
    2. **没有中间态结果更新**:`realtime/capabilities/tool_results.py` 的 `ToolResultChannel` 是"one-response, single-delivery rendezvous"——每个 `call_id` 只能 `submit` 一次,天然不支持一个 BACKGROUND 工具在完成前推送进度,对应 Pipecat 的 `FunctionCallResultProperties(is_final=False)`。
- **参照**:Pipecat 的 `cancellable_by_llm`(异步调用能否被 LLM 主动取消,而不等待/中断整个 response)+ 中间态更新(`is_final=False`,通过 developer message 多次注入)。
- **行动项**:
  - [ ] 评估是否要把取消从"response 级联"细化到"call_id 级":允许 LLM 或用户单独取消一个仍在跑的 BACKGROUND/VARIABLE 调用,不影响同一 response 里的其它调用或对话本身。
  - [ ] 评估 `ToolResultChannel` 是否要支持多次 `submit`(中间态 + 最终态),让长耗时工具(如 spawn_thinking 式后端委派)能在完成前把进度说给用户。
  - [ ] 更新/复核 ADR-0061,把"latency 已经是每工具声明式字段"写清楚,避免文档和代码脱节导致后续误判(本条修正即因文档描述滞后于代码实现而产生)。

## 优先级建议(供后续排期参考)

**工程 TODO(1-6 条 + 6a)**:
1. 第 3 条(生产基础设施)——不做的话前面架构做得再好也上不了线。
2. 第 1 条(行为级测试)——已经出过 P0 事故(打断失效未被发现),优先级应等同于线上事故修复。
3. **第 6a 条(工具接线到生产 composition root)——新增,建议提到第 4 条之前**:这是比"MCP client 是空实现"更底层的阻塞项。第 4 条(真实 MCP client)即使做完,如果没有 6a,工具依然到不了真实用户的会话里——历史上这个"建了没接线"的坑已经在 demo 层踩过三次(ADR-0030/0035/0032),生产层从未验证过,优先级应该在第 4 条动手之前先钉死。
4. 第 5 条(架构契约)——趁架构还没被腐化前定下来,成本最低。
5. 第 4 条(真实 MCP client)——做的时候直接把第 6a 条的验收标准(配置里加一行 MCP server → 生产会话里真的能调用成功)作为完成定义,不要只验证到"client 能连上 server"。
6. 第 2 条(Transport 二进制化)——收益明确但不紧急,可以和第 3 条的 Dockerfile/部署工作一起做。
7. 第 6 条(单次调用级取消 + 中间态更新)——收益明确但不紧急,可在第 5 条契约定下来之后再做,避免顺序颠倒导致契约被配置灵活性架空。

**战略方向(差异化章节)**:工程 TODO 是"补短板",不构成差异化;差异化战略方向才是决定项目长期是否值得继续投入的问题,建议先拍板方向(尤其是"设备协同+Agent委派"要不要押注),再决定工程 TODO 里哪些条目要为战略方向让路提前做(例如若押注方向1,ESP32 音频通路的优先级应显著提前)。
