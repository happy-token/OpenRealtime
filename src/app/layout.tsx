import type { Metadata } from "next";
import "@/styles/globals.css";
import { AppThemeProvider } from "@/components/theme/app-theme-provider";
import { DEFAULT_APP_THEME } from "@/lib/app-theme";
import { ProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { WorkbenchGlassProvider } from "@/components/theme/workbench-glass-provider";
import { NavigationFeedback } from "@/components/navigation/navigation-feedback";
import { Suspense } from "react";
import { HomeBackdrop } from "@/components/workspace/home-backdrop";

export const metadata: Metadata = {
  title: "OpenRealtime — 自然开口，即刻回应",
  description: "实时、自然、可打断的全双工语音智能体",
};

export default function RootLayout({ children, modal }: { children: React.ReactNode; modal: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body data-theme={DEFAULT_APP_THEME} data-color-scheme="dark">
        <AppThemeProvider><WorkbenchGlassProvider /><Suspense fallback={null}><NavigationFeedback /></Suspense><ProviderKeyGate><HomeBackdrop />{children}{modal}</ProviderKeyGate></AppThemeProvider>
      </body>
    </html>
  );
}
