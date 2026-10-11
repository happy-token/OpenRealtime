# 产品定位与竞品研究

更新日期：2026-10-09。这组文档用于开源选型、README 和宣传内容，也作为后续产品决策的依据。它不替代架构设计、功能验收或性能报告。

| 文档 | 解决的问题 |
| --- | --- |
| [定位与差异化](POSITIONING.md) | 做给谁、解决什么问题、为什么选择我们、哪些方向暂不押注 |
| [竞品与替代路线分析](COMPETITIVE-ANALYSIS.md) | 框架、Agent 交互、数字人、硬件、原生语音及托管 API 的竞争关系 |
| [亮点与证据矩阵](CLAIMS-AND-EVIDENCE.md) | 每条宣传主张的实现依据、验证范围、缺口和可用措辞 |
| [README 亮点草案](README-HIGHLIGHTS-DRAFT.md) | 将定位转成可阅读的首屏文案，保留待验证边界 |
| [2026-09-03 历史研究快照](history/2026-09-03-openrealtime-improvement-todo.md) | 保留原先 Pipecat / Qwen Audio Agent / OpenRealtime 调研及战略建议 |

建议先读定位，再看竞品分析的历史复核，最后依据证据矩阵制作 README 和视频。全球开源受众与不限定中文应用已明确；具体传播措辞和差异化优势仍需 Demo、英文 API 路线与比较实验支撑。

## 与已有研究的关系

本次补充已有研究，不覆盖历史结论或重新宣布旧 TODO 完成：

- GPT Voice 产品对照与目标架构（本地研究资料，尚未随仓库发布）：媒体面、控制面、后台任务边界；其中目标架构不等于当前已交付能力。
- [Realtime / 全双工模型比较（2026-09-17）](../GPT-live-1/realtime-full-duplex-voice-models-comparison-2026-09-17.md)：保留原生语音与 Agent 协同两条路线；模型名、价格和 API 状态按原调研日期理解。
- [全双工调研](../full-duplex-survey.md)：架构、交互意图与系统动作的分类依据。
- [数字人选型（2026-09-07）](../reports/2026-09-07-digital-human-selection-research.md)：云实时驱动、多段式合成、预生成动作编排；价格是历史快照。
- [项目完善审查](../PROJECT-IMPROVEMENT-AUDIT.md)：维护、记忆、知识、恢复和验证边界。
- [Jev PRD](../JEV-TURN-TAKING-PRD.md)、[语义插件](../SEMANTIC-DECISION-PLUGINS.md)：接入与评测要求。

历史外部研究原位于工作区 `open/voice-agent-research/openrealtime-improvement-todo.md`，现保留副本在 history；2026-10-09 的修正集中记录在竞品分析，历史文件仍保持快照性质。

## 研究口径

外部功能以官方仓库、文档和当前公开说明为依据；没有重新部署所有竞品。OpenRealtime 状态以本地工作区实现与版本化报告为依据，本地存在未提交开发，不能自动等同 GitHub 发布版。未查到某项能力记作“本轮未核实”，不推导为“不支持”。技术模型、应用、运行时和托管服务分别比较，不用一张全绿功能表制造全面领先的印象。

维护时同时记录核查日期、来源、版本及结论状态。涉及速度、成本、长会话和语音质量的横向领先结论，必须有同条件实验。
