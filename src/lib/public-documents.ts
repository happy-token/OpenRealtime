export const DOCUMENT_SECTIONS = [
  { title: "认识产品与开始使用", description: "了解定位与核心能力，体验实时语音，查阅详细操作。" },
  { title: "定制语音 Agent", description: "选择声音、人设与模型服务，按体验和预算自由组合。" },
  { title: "接入你的 Agent", description: "连接已有 Chat Agent，保留业务回答逻辑，增加语音交互。" },
  { title: "知识、工具与记忆", description: "配置业务资料和工具，管理长期记忆与历史；资料问答作为上手示例。" },
  { title: "可选：添加数字人", description: "在语音交互基础上，按需求选择人物、素材与驱动方式。" },
  { title: "部署与维护", description: "在自己的环境运行，连接真实服务并管理数据。" },
  { title: "开发与扩展", description: "了解运行时、插件接口与知识服务接入。" },
  { title: "研究与规划", description: "查阅设计分析和历史规划，状态以文档日期为准。" },
] as const;

export type PublicDocument = {
  slug: string;
  title: string;
  category: typeof DOCUMENT_SECTIONS[number]["title"];
  description: string;
  file: string;
  englishFile?: string;
  language?: "zh-CN" | "en";
};

export const PUBLIC_DOCUMENTS: readonly PublicDocument[] = [
  { slug: "overview", title: "认识 OpenRealtime", category: "认识产品与开始使用", description: "实时语音交互、接入你的 Agent，用语音聊天和工作；了解定制、判停与打断。", file: "getting-started/OVERVIEW.md", englishFile: "getting-started/OVERVIEW.en.md" },
  { slug: "product-assistant", title: "用产品资料配置语音助手", category: "知识、工具与记忆", description: "从示例资料到检索测试、角色绑定和真实语音问答的完整流程。", file: "getting-started/PRODUCT-ASSISTANT.md", englishFile: "getting-started/PRODUCT-ASSISTANT.en.md" },
  { slug: "quick-start", title: "首页使用指南", category: "认识产品与开始使用", description: "开始语音对话、查看消息，处理连接、麦克风和播放问题。", file: "QUICK-START.md" },
  { slug: "role-configuration", title: "角色配置指南", category: "定制语音 Agent", description: "配置人设、声音、回答服务、知识与工具，确认角色设置生效。", file: "guides/ROLE-CONFIGURATION.md" },
  { slug: "knowledge-base", title: "知识库使用指南", category: "知识、工具与记忆", description: "导入资料、测试检索、绑定角色，让多个角色共用资料并独立配置检索范围。", file: "KNOWLEDGE-BASE-GUIDE.md" },
  { slug: "memory-and-history", title: "记忆与会话历史", category: "知识、工具与记忆", description: "区分产品资料、长期记忆和对话历史，了解查看、管理与续聊。", file: "MEMORY-AND-HISTORY-GUIDE.md" },
  { slug: "tool-permissions", title: "工具权限设置", category: "知识、工具与记忆", description: "提前授权工具，配置全局权限、角色覆盖与继承，减少语音交流中的确认。", file: "TOOL-PERMISSIONS.md" },
  { slug: "data-management", title: "知识与记忆管理指南", category: "知识、工具与记忆", description: "知识增删改、记忆归零、会话上下文区别，以及 API、部署和备份恢复。", file: "DATA-MANAGEMENT-GUIDE.md" },
  { slug: "cost-and-flexibility", title: "成本与服务选型", category: "定制语音 Agent", description: "组合更经济的语音与文本服务，了解成本来源与端到端方案的比较方式。", file: "product/COST-AND-FLEXIBILITY.md", englishFile: "product/COST-AND-FLEXIBILITY.en.md" },
  { slug: "digital-human", title: "数字人驱动方案", category: "可选：添加数字人", description: "了解实时驱动、多段式合成与动作编排的适用场景。", file: "DIGITAL-HUMAN-DRIVING.md" },
  { slug: "motion-orchestration", title: "动作编排使用指南", category: "可选：添加数字人", description: "准备配对素材，在会话中切换待机和讲话动作。", file: "MOTION-ORCHESTRATION-GUIDE.md" },
  { slug: "local-development", title: "本地启动与排错", category: "部署与维护", description: "安装开发环境、运行应用，区分演示模式与真实服务。", file: "getting-started/LOCAL-DEVELOPMENT.md", language: "en" },
  { slug: "cloud-services", title: "连接真实语音与模型服务", category: "定制语音 Agent", description: "选择兼容服务、配置凭据，验证识别、回答与语音输出。", file: "getting-started/CLOUD-SERVICES.md", language: "en" },
  { slug: "deployment", title: "自行部署指南", category: "部署与维护", description: "配置认证、存储、服务与额度，了解公开体验的部署示例。", file: "deployment/public-trial.md" },
  { slug: "reliability-operations", title: "可靠性与运维", category: "部署与维护", description: "检查服务能力，管理持久化、恢复与运行故障。", file: "RELIABILITY-OPERATIONS.md", language: "en" },
  { slug: "turn-coordination", title: "模块化话轮协调器", category: "开发与扩展", description: "替换对话协调策略、判停与打断模型，了解等待期限、连续插话和故障恢复。", file: "TURN-COORDINATION.md" },
  { slug: "semantic-decision-plugins", title: "判停与打断插件合约", category: "开发与扩展", description: "规范历史、当前文本、识别状态与语义输出，兼容纯文本和上下文模型。", file: "SEMANTIC-DECISION-PLUGINS.md" },
  { slug: "voice-pipeline", title: "语音 Pipeline 与插件接口", category: "开发与扩展", description: "梳理对话状态、语义判停、打断、ASR、LLM 与 TTS 的统一接口和替换方式。", file: "VOICE-PIPELINE.md" },
  { slug: "knowledge-integration", title: "知识库选型与接入方案", category: "开发与扩展", description: "比较结构化文档、向量与混合检索，按 Python 插件接口接入 Qdrant、pgvector 或 Dify。", file: "KNOWLEDGE-INTEGRATION.md" },
  { slug: "chat-agent-integration", title: "接入自己的 Chat Agent", category: "接入你的 Agent", description: "通过兼容 API 或适配器保留自己的对话能力，增加语音与可选数字人。", file: "guides/CHAT-AGENT-INTEGRATION.md", englishFile: "guides/CHAT-AGENT-INTEGRATION.en.md" },
  { slug: "project-improvements", title: "项目完善清单", category: "研究与规划", description: "当前管理能力、项目缺口、优先级、验收标准和完整文档导航。", file: "PROJECT-IMPROVEMENT-AUDIT.md" },
  { slug: "voice-interaction-review", title: "语音交互审查与框架规划", category: "研究与规划", description: "借鉴 VoiceLoop 与 GPT Voice 的设计，规划输入归属、响应保障及统一协调插件。", file: "VOICELOOP-INTERACTION-REVIEW.md" },
  { slug: "semantic-label-assessment", title: "判停与打断标签评估", category: "研究与规划", description: "比较主流标签、核查当前动作映射，说明上下文、暂停、噪声与故障的优化方案。", file: "SEMANTIC-LABEL-ASSESSMENT.md" },
];

/** Resolve repository Markdown links to published articles, retaining other repo links. */
export function resolveDocumentLink(href: string, sourceFile: string): string {
  if (href.startsWith("/") || href.startsWith("#") || /^[a-z][a-z\d+.-]*:/i.test(href)) return href;
  const target = new URL(href, `https://openrealtime.invalid/docs/${sourceFile}`);
  if (target.pathname === "/docs/README.md") return `/docs${target.hash}`;
  const doc = PUBLIC_DOCUMENTS.find(item => [item.file, item.englishFile].some(file => file && target.pathname === `/docs/${file}`));
  if (doc) return `/docs/${doc.slug}${target.search}${target.hash}`;
  const view = target.pathname.endsWith("/") ? "tree" : "blob";
  return `https://github.com/happy-token/OpenRealtime/${view}/main${target.pathname}${target.search}${target.hash}`;
}
