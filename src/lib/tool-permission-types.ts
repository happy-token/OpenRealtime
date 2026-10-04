export const TOOL_PERMISSION_MODES = ["full", "balanced", "confirm"] as const;
export type ToolPermissionMode = typeof TOOL_PERMISSION_MODES[number];
export type ToolPermissionSettings = {
  mode: ToolPermissionMode;
  roleOverrides: Record<string, ToolPermissionMode>;
  updatedAt: string | null;
};

export function isToolPermissionMode(value: unknown): value is ToolPermissionMode {
  return typeof value === "string" && TOOL_PERMISSION_MODES.includes(value as ToolPermissionMode);
}

export const TOOL_PERMISSION_OPTIONS: { value: ToolPermissionMode; label: string; description: string }[] = [
  { value: "full", label: "全面开启", description: "助手可自动调用已启用的工具，包括执行其修改、发送等操作。" },
  { value: "balanced", label: "按需确认", description: "查询自动执行，修改、发送等操作需要确认。" },
  { value: "confirm", label: "每次确认", description: "每次工具调用都需要你的确认。" },
];

export function effectiveToolPermission(settings: ToolPermissionSettings, roleId?: string | null): ToolPermissionMode {
  return roleId && Object.hasOwn(settings.roleOverrides, roleId) ? settings.roleOverrides[roleId] : settings.mode;
}
