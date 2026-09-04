export const APP_THEME_STORAGE_KEY = "openrealtime-app-theme";

export const APP_THEME_OPTIONS = [
  {
    value: "catppuccin",
    label: "Catppuccin Mocha",
    description: "暖黑淡紫",
    colors: ["#1e1e2e", "#313244", "#cba6f7", "#b4befe"],
  },
  {
    value: "tokyo-night",
    label: "Tokyo Night",
    description: "清爽蓝紫",
    colors: ["#1a1b26", "#24283b", "#7aa2f7", "#bb9af7"],
  },
  {
    value: "rose-pine",
    label: "Rosé Pine",
    description: "克制墨紫",
    colors: ["#191724", "#26233a", "#c4a7e7", "#ebbcba"],
  },
  {
    value: "kanagawa",
    label: "Kanagawa Wave",
    description: "和风暖黑",
    colors: ["#1f1f28", "#363646", "#957fb8", "#7e9cd8"],
  },
  {
    value: "duskfox",
    label: "Duskfox",
    description: "暮色蓝紫",
    colors: ["#232136", "#393552", "#9a7ecc", "#6085b6"],
  },
  {
    value: "onedark",
    label: "OneDark",
    description: "产品深灰",
    colors: ["#282c34", "#3e4451", "#61afef", "#c678dd"],
  },
  {
    value: "night-owl",
    label: "Night Owl",
    description: "深海高可读",
    colors: ["#011627", "#0d263b", "#82aaff", "#c792ea"],
  },
  {
    value: "dracula",
    label: "Dracula",
    description: "经典高对比",
    colors: ["#282a36", "#44475a", "#bd93f9", "#ff79c6"],
  },
  {
    value: "nord",
    label: "Nord",
    description: "冷静蓝灰",
    colors: ["#2e3440", "#3b4252", "#88c0d0", "#b48ead"],
  },
] as const;

export type AppTheme = (typeof APP_THEME_OPTIONS)[number]["value"];

export const DEFAULT_APP_THEME: AppTheme = "dracula";

export function isAppTheme(value: unknown): value is AppTheme {
  return APP_THEME_OPTIONS.some((theme) => theme.value === value);
}
