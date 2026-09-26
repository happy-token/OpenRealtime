export const TOOL_KINDS = ["builtin", "function", "api", "mcp"] as const;

export type ToolKind = (typeof TOOL_KINDS)[number];

export interface ToolRecord {
  tool_id: string;
  display_name: string;
  description: string;
  kind: ToolKind;
  enabled: boolean;
  builtin: boolean;
  public_enabled?: boolean;
  risk_level?: "low" | "medium" | "high" | "critical";
  effect?: "read_public" | "read_sensitive" | "write_reversible" | "write_irreversible" | "execute_code" | "communicate_external" | "spend_or_transfer" | "control_device";
  function_name: string;
  input_schema: Record<string, unknown>;
  endpoint: string | null;
  method: "GET" | "POST" | null;
  mcp_transport: "stdio" | "streamable-http" | null;
  created_at: string;
  updated_at: string;
}

export const TOOL_KIND_LABELS: Record<ToolKind, string> = {
  builtin: "内置工具",
  function: "Function Calling",
  api: "自定义 API",
  mcp: "MCP",
};

export function isToolKind(value: unknown): value is ToolKind {
  return typeof value === "string" && TOOL_KINDS.includes(value as ToolKind);
}

export function isToolRisk(value: unknown): value is NonNullable<ToolRecord["risk_level"]> {
  return value === "low" || value === "medium" || value === "high" || value === "critical";
}

export function isToolEffect(value: unknown): value is NonNullable<ToolRecord["effect"]> {
  return typeof value === "string" && ["read_public", "read_sensitive", "write_reversible", "write_irreversible", "execute_code", "communicate_external", "spend_or_transfer", "control_device"].includes(value);
}
