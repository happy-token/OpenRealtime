export type ModelProtocol =
  | "openai-chat-completions"
  | "openai-responses"
  | "anthropic-messages"
  | "google-generate-content";

export type ModelProvider =
  | "deepseek"
  | "bailian"
  | "volcengine"
  | "zhipu"
  | "moonshot"
  | "minimax"
  | "openai"
  | "anthropic"
  | "google"
  | "custom";

export interface ModelProviderOption {
  value: ModelProvider;
  label: string;
  region: "国内" | "海外" | "自定义";
  description: string;
  protocol: ModelProtocol;
  baseUrl: string;
  apiKeyEnv: string;
  models: ReadonlyArray<{ value: string; label: string; description: string }>;
}

export const MODEL_PROTOCOL_OPTIONS = [
  { value: "openai-chat-completions", label: "OpenAI Chat Completions", description: "当前运行时已支持" },
  { value: "openai-responses", label: "OpenAI Responses", description: "适合新模型与内置工具" },
  { value: "anthropic-messages", label: "Anthropic Messages", description: "Claude 原生协议" },
  { value: "google-generate-content", label: "Google GenerateContent", description: "Gemini 原生协议" },
] as const;

export const MODEL_PROVIDER_OPTIONS: ReadonlyArray<ModelProviderOption> = [
  {
    value: "deepseek",
    label: "DeepSeek",
    region: "国内",
    description: "推理与性价比",
    protocol: "openai-chat-completions",
    baseUrl: "https://api.deepseek.com",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    models: [
      { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash", description: "低延迟实时对话" },
      { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro", description: "复杂推理与工具调用" },
    ],
  },
  {
    value: "bailian",
    label: "阿里云百炼",
    region: "国内",
    description: "Qwen 与多模型平台",
    protocol: "openai-chat-completions",
    baseUrl: "https://{workspace-id}.cn-beijing.maas.aliyuncs.com/api/v1",
    apiKeyEnv: "DASHSCOPE_API_KEY",
    models: [
      { value: "qwen3.8-max", label: "Qwen 3.8 Max", description: "旗舰效果" },
      { value: "qwen3.7-plus", label: "Qwen 3.7 Plus", description: "效果与成本平衡" },
      { value: "qwen3.7-flash", label: "Qwen 3.7 Flash", description: "低延迟、高并发" },
    ],
  },
  {
    value: "volcengine",
    label: "火山方舟",
    region: "国内",
    description: "豆包 Seed 系列",
    protocol: "openai-chat-completions",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    apiKeyEnv: "ARK_API_KEY",
    models: [
      { value: "doubao-seed-2-0-lite-260215", label: "Doubao Seed 2.0 Lite", description: "实时对话优先" },
      { value: "doubao-seed-2-0-pro-260215", label: "Doubao Seed 2.0 Pro", description: "复杂任务优先" },
    ],
  },
  {
    value: "zhipu",
    label: "智谱 AI",
    region: "国内",
    description: "GLM 系列",
    protocol: "openai-chat-completions",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    apiKeyEnv: "ZHIPU_API_KEY",
    models: [
      { value: "glm-5.2", label: "GLM 5.2", description: "通用旗舰模型" },
      { value: "glm-4-flash", label: "GLM 4 Flash", description: "高速低成本" },
    ],
  },
  {
    value: "moonshot",
    label: "月之暗面",
    region: "国内",
    description: "Kimi 长上下文",
    protocol: "openai-chat-completions",
    baseUrl: "https://api.moonshot.cn/v1",
    apiKeyEnv: "MOONSHOT_API_KEY",
    models: [
      { value: "kimi-k2.5", label: "Kimi K2.5", description: "通用与工具调用" },
      { value: "moonshot-v1-32k", label: "Moonshot V1 32K", description: "稳定长上下文" },
    ],
  },
  {
    value: "minimax",
    label: "MiniMax",
    region: "国内",
    description: "角色与长文本",
    protocol: "openai-chat-completions",
    baseUrl: "https://api.minimax.chat/v1",
    apiKeyEnv: "MINIMAX_API_KEY",
    models: [
      { value: "MiniMax-M3", label: "MiniMax M3", description: "旗舰文本模型" },
      { value: "MiniMax-M2.5", label: "MiniMax M2.5", description: "通用对话" },
    ],
  },
  {
    value: "openai",
    label: "OpenAI",
    region: "海外",
    description: "GPT 系列",
    protocol: "openai-responses",
    baseUrl: "https://api.openai.com/v1",
    apiKeyEnv: "OPENAI_API_KEY",
    models: [
      { value: "gpt-5.6", label: "GPT-5.6", description: "旗舰能力" },
      { value: "gpt-5.6-terra", label: "GPT-5.6 Terra", description: "效果与成本平衡" },
      { value: "gpt-5.6-luna", label: "GPT-5.6 Luna", description: "低延迟、高吞吐" },
    ],
  },
  {
    value: "anthropic",
    label: "Anthropic",
    region: "海外",
    description: "Claude 系列",
    protocol: "anthropic-messages",
    baseUrl: "https://api.anthropic.com/v1",
    apiKeyEnv: "ANTHROPIC_API_KEY",
    models: [
      { value: "claude-sonnet-5", label: "Claude Sonnet 5", description: "速度与智能平衡" },
      { value: "claude-opus-5", label: "Claude Opus 5", description: "复杂 Agent 任务" },
      { value: "claude-haiku-4-5", label: "Claude Haiku 4.5", description: "实时与高并发" },
    ],
  },
  {
    value: "google",
    label: "Google Gemini",
    region: "海外",
    description: "Gemini 多模态",
    protocol: "google-generate-content",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
    apiKeyEnv: "GEMINI_API_KEY",
    models: [
      { value: "gemini-3.7-flash", label: "Gemini 3.7 Flash", description: "实时与 Agent 工作流" },
      { value: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro", description: "复杂推理" },
      { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash", description: "稳定低延迟" },
    ],
  },
  {
    value: "custom",
    label: "自定义接口",
    region: "自定义",
    description: "兼容服务或私有网关",
    protocol: "openai-chat-completions",
    baseUrl: "",
    apiKeyEnv: "VOICEAGENT_LLM_API_KEY",
    models: [
      { value: "custom-chat-model", label: "自定义模型 ID", description: "按服务端文档填写" },
    ],
  },
];

export function findModelProvider(provider: ModelProvider) {
  return MODEL_PROVIDER_OPTIONS.find((option) => option.value === provider) ?? MODEL_PROVIDER_OPTIONS[0];
}
