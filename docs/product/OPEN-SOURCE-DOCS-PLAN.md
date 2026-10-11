# OpenRealtime 开源 README 与文档整理计划

日期：2026-10-11。状态：用户已确认总体方向；本轮只新增计划，不改 README 正文，不移动文档或代码。实施时重新读取工作区，保留其他任务正在进行的修改。

## 1. 目前 README 修改到了哪里

此前本任务在 README 的 Project status 中增加了 docs/product/README.md 导航。英文首屏定位与四个亮点写在 docs/product/README-HIGHLIGHTS-DRAFT.md，尚未合入根 README。当前本地 README 共 561 行；相对本地 HEAD 的 diff 是新增 7 行，不代表这 7 行都来自本任务，也不代表已经推送到公开仓库。

用户确认项目已开源。远程地址为 https://github.com/happy-token/OpenRealtime.git；本轮公开页面抓取失败，尚未独立核实 GitHub 默认分支正文与本地工作区的一致性。实施第一步应核对公开默认分支、HEAD 和未提交版本，不能直接把当前大批本地变更视为已发布能力。

## 2. 需要先对齐的建议

1. 默认英文 README，保留 README.zh-CN.md；面向全球 Agent 开发者与小型产品团队。
2. 首屏采用已认可的主张 Bring your AI agents to life with real-time voice and avatars.，突出自然交流、数字人呈现、独立选型、轻松启动按需组合。
3. 连接已有 Agent 的统一体验继续标记 TODO；当前已存在的适配按后端逐项说明，不把全部外部 Agent 能力写成未实现，也不宣传任意 Agent 零代码接入。
4. 产品表述为实时语音与数字人 Agent 运行时，并说明仓库包含 Next.js 参考应用；避免“framework, not an application”掩盖已投入的工作区与角色配置。
5. 先重组文档入口、修正过时内容，再分批迁移正文。保留代码目录，不在本轮做源码架构重构。
6. 研究与验证资料作为证据层，保留历史，不在 README 首屏堆叠报告。公开与本地排除资料分别管理。

用户已确认：按全球开发者快速体验与接入方向推进，英文 README 默认、中文保留，四个亮点进入首屏，Agent 接入保留 TODO，先整理文档导航、不移动代码目录。具体正文与迁移清单在实施时形成可评审差异。

## 3. 本轮发现的具体问题

| 文件/区域 | 现象 | 计划处理 |
| --- | --- | --- |
| README 首屏 | 中英文混排、先给 Seam/Protocol 等术语；亮点草案未合入 | 用产品收益开场；机制与框架接口移入开发者路径 |
| README 安装 | Requirements 只列 Python/uv，Web 路径随后才出现 | 按实际配置补齐 Node/pnpm、Python/uv及平台要求，版本以 manifest/CI 为依据 |
| README 篇幅 | 561 行；用户要越过实现清单才到安装，数字人厂商和认证配置占大段 | 根 README 约 180–250 行作为目标；复杂配置落专项指南，长度服从信息完整性 |
| README / PROJECT_STRUCTURE | 五状态 FSM、旧 client/plugin 描述；布局正文写根 app/components，实际前端在 src；worklet 行重复 | 对照当前 runtime、组合根、目录和测试修正，历史 FSM 标明背景 |
| CONTRIBUTING | 写 mypy 在 CI 不阻断，而当前工作流运行 check_mypy.py 阻断新增错误 | 说明实际基线策略、检查命令和不同测试费用/外部服务条件 |
| ROADMAP / ISSUES / COMPLETION_STATUS | Roadmap 仍有 private remote、旧认证/传输/CI 等描述，可能与新实现冲突 | 逐项核对状态和版本；统一现有支持、实验能力、TODO，不直接删除旧问题 |
| QUICK-START | 实际是首页使用指南，不是开发者安装 quickstart；描述可能滞后于角色配置 UI | 拆分“体验使用”和“本地启动”，保留旧站点 slug |
| docs 导航 | 没有统一 docs/README.md；首页路径混用规划、技术文章与用户操作指南 | 新增角色化索引：体验者、部署者、开发者、贡献者 |
| 站点文档 | public-documents.ts 有 14 项，其中完善清单和审查规划也在用户入口；仅中文文件映射 | 区分用户指南、开发者文章和项目研究；制定英文文件与语言解析策略 |
| 开源配套 | LICENSE、CONTRIBUTING、SECURITY、CODE_OF_CONDUCT、THIRD_PARTY_NOTICES 已存在 | 核对内容和入口；不重复新建。问题模板/PR 模板按维护需求补齐 |
| 本地资料范围 | docs 本地 1,104 文件、Git 跟踪 340；reports 本地 786、adr 161；多个研究目录被 gitignore 排除 | 建立 tracked/untracked/ignored 清单后决策；不能将本地文件总数称为已公开数量 |

这是文档审计发现，不是完整的功能验证。新贡献指南不能借文档任务擅自修改 CI；文档与代码不一致时记录问题并另行处理。

## 4. README 建议结构

1. 名称、英文定位、真实产品截图或短视频、Demo/GitHub入口。
2. Why OpenRealtime：已确认的四个亮点；Jev 作为可选决策 provider 的技术说明。
3. What you can build：数字人导览、知识助手、工具型语音助手，关联可复现示例。
4. Quickstart：先跑本地确定性演示，再配置真实云语音；明确 mock/fallback 与真实服务区别。
5. Supported capabilities：回答、语音、数字人、知识/工具、外部 Agent 的支持与限制摘要。
6. Configuration & deployment：纯语音与云数字人两条路径，所需应用后端/数据库/凭据/费用；本地 GPU 呈现另列可选路线。
7. Architecture：一张职责图与简短真实目录树，链接技术正文。
8. Roadmap：英文 API 路线、统一 Agent 接入等 TODO；发布时逐项核对是否已完成。
9. Documentation / Contributing / License：清晰入口。

不把分类请求耗时当端到端延迟，不提前宣传未验收的英文、多语言与并发效果。截图必须对应当前公开版本，使用虚构或授权演示数据。

## 5. 文档目标结构（先逻辑分类，后物理移动）

```text
README.md                       英文项目入口
README.zh-CN.md                  中文项目入口
CONTRIBUTING.md / SECURITY.md    保留根目录标准入口
ROADMAP.md / CHANGELOG.md        当前计划与发布记录

docs/
  README.md                     文档总索引
  getting-started/               本地演示、真实云服务、常见启动问题
  guides/                       角色/声音/模型/工具/知识/记忆/形象/动作
  deployment/                   通用部署、存储、备份、升级与运维
  architecture/                 运行时、话轮、会话、工具与数据边界
  reference/                    配置变量、provider 支持表、接口/协议
  product/                      定位、竞品与主张证据（已有）
  adr/                          架构决策（保留编号和历史）
  reports/                      版本化验证证据及精选索引
  archive/                      被明确替代的历史规划（按需创建）
```

英文为新默认入口，中文用户操作指南先保留。双语采用统一导航和互链，不一次翻译全部 ADR、报告或历史研究。规划路径是建议，不在计划阶段批量搬迁。

站点 /docs 的 slug 与仓库物理文件解耦，保持已有 quick-start、knowledge-base 等地址。迁移时同步 src/lib/public-documents.ts、Markdown 相对链接、README、脚本/测试引用与容器文件复制规则。凡涉及代码修改需代码审查及适当构建/路由测试。

## 6. 优先补齐的文档

### P0：开源采用入口

- 英文/中文 README：主张、四个亮点、真实 Demo、能力状态。
- 本地 quickstart：干净环境前提、命令、预期结果、常见错误及停止方法。
- 云 API quickstart：按已支持路线列凭据与配置，说明语音/数字人与付费条件；未实现英文 provider 作为功能 TODO，不用文档假补齐。
- Provider/能力矩阵：集成存在、确定性测试、真实服务验收、公开版本支持分别标注；包含流式、打断、语言与地区限制。
- 文档总索引与项目结构说明；修正 CI、Roadmap 的高影响旧描述。

### P1：产品与开发者使用

- 角色指南：名称/声音/人设/模型/工具/知识/记忆如何组合；全局供应商与角色覆盖的关系。
- 数字人路线对照：实时云呈现、动作视频、口型对齐的不同要求与行为。
- 配置参考：默认值、作用域、凭据存放、可选服务和数据目录；与 env example 对照。
- 部署指南：通用自托管步骤作为主体，当前运营站的域名/拓扑案例另列。
- 扩展指南：接入一个真实 provider、一个工具、一个已支持 Agent 后端；标记 MCP 声明与真正连接的差别。
- Troubleshooting：连接/麦克风/播放/资料检索/数字人启动的可执行排查。

### P2：维护与历史

- 发布和升级说明，依现有 VERSIONING/CHANGELOG 整合。
- reports 精选索引、过时规划归档与替代链接。
- 按需要补 issue/PR 模板；不复制已有治理文件。

## 7. 执行阶段与验收

| 阶段 | 产物 | 验收与边界 |
| --- | --- | --- |
| A 对齐与基线 | 本计划、默认分支对照、文件与引用清单 | 用户确认入口语言/定位/调整范围；只读确认公开版本 |
| B README 与索引 | 英文 README、中文 README、docs/README | 首屏可理解项目，三步以内找到体验/启动/扩展路径；相对链接可用 |
| C 核心指南 | quickstart、能力矩阵、角色与部署文档、项目结构说明 | 按干净环境复现确定性 quickstart；真实云服务另列授权与验证条件 |
| D 路由与目录整理 | 必要文件迁移、站点导航映射与兼容链接 | Markdown 链接、锚点、旧 /docs slug、构建与 Docker 文档可用性通过 |
| E 历史与发布核查 | Roadmap/状态同步、报告索引、文档更新差异 | 不修改历史证据数据；每项能力关联实际发布版本；提交/推送按后续授权执行 |

推荐先完成 B/C，看到可评审结果后再执行 D，避免为目录美观先制造大批 rename。仅改文档时无需跑全量业务测试；改路由或加载代码时做相应测试与构建。发现功能不成立列为独立任务，不扩张成本轮功能重构。

## 8. 本轮交付范围

只新增本计划。未改 README 正文、未新增双语正文、未搬迁目录、未实现 API、未提交或推送。当前工作区存在大量其他修改，后续实施前必须核对并保留。


## 9. 第一阶段实施记录（2026-10-11）

用户已授权开始修改。英文/中文 README、docs 总索引、本地启动/云服务/角色配置指南、项目结构说明已完成；旧 README 的详细服务/控制台示例保留到 docs/reference/WEB-DEMO-CONFIGURATION.md。贡献指南修正 mypy 基线门禁；Roadmap 修正公开仓库与 WebSocket v2/CI 的历史冲突，状态审计加日期边界。代码目录与站点 slug 未改，未提交或推送。

已检查新增入口的本地相对链接与 diff 格式。未重跑干净机器安装、付费 API 或完整业务测试；历史 ADR/报告未逐项重审，完整 provider 支持矩阵与英文服务验收仍需后续补齐。
