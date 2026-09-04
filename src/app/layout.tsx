import type { Metadata } from "next";
import "@/styles/globals.css";
import { AppThemeProvider } from "@/components/theme/app-theme-provider";
import { DEFAULT_APP_THEME } from "@/lib/app-theme";

export const metadata: Metadata = {
  title: "OpenRealtime — 自然开口，即刻回应",
  description: "实时、自然、可打断的全双工语音智能体",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body data-theme={DEFAULT_APP_THEME} data-color-scheme="dark">
        <AppThemeProvider>{children}</AppThemeProvider>
      </body>
    </html>
  );
}
