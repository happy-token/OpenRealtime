import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clampSidebarWidth, conversationHref, formatGithubStars, isResourceWorkspacePath, transitionSidebarMode, WorkspaceShell } from "./workspace-shell";
import type { RoleRecord } from "@/lib/role-records";

const navigation = vi.hoisted(() => ({ pathname: "/conversation", push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));

describe("WorkspaceShell", () => {
  beforeEach(() => {
    navigation.pathname = "/conversation";
    navigation.push.mockClear();
  });

  it("opens a configured realtime avatar through the resource-library conversation entry", () => {
    const role = {
      role_id: "role-test", avatar_id: null,
      default_selections: { realtime: { avatar_id: "anam-avatar-123" } },
    } as RoleRecord;
    expect(conversationHref(role, "realtime")).toBe("/conversation?realtime_avatar_id=anam-avatar-123");
  });

  it("moves between collapsed, hover preview, and pinned sidebar states", () => {
    expect(transitionSidebarMode("collapsed", "hover-enter")).toBe("preview");
    expect(transitionSidebarMode("preview", "hover-leave")).toBe("collapsed");
    expect(transitionSidebarMode("preview", "pin")).toBe("pinned");
    expect(transitionSidebarMode("pinned", "hover-leave")).toBe("pinned");
    expect(transitionSidebarMode("pinned", "collapse")).toBe("collapsed");
  });

  it("shows GitHub Star counts in the compact reference style", () => {
    expect(formatGithubStars(125_000)).toBe("125k");
    expect(formatGithubStars(1_250)).toBe("1.3k");
    expect(formatGithubStars(null)).toBe("—");
  });

  it("bounds a saved sidebar width to the desktop viewport", () => {
    expect(clampSidebarWidth(120, 1440)).toBe(196);
    expect(clampSidebarWidth(330, 1440)).toBe(330);
    expect(clampSidebarWidth(500, 1440)).toBe(420);
    expect(clampSidebarWidth(420, 800)).toBe(420);
  });

  it("uses a persistent hover-reveal floating sidebar on the home conversation", () => {
    const html = renderToStaticMarkup(<WorkspaceShell session><div>主页</div></WorkspaceShell>);

    expect(html).toContain('data-floating-sidebar="true"');
    expect(html).toContain('data-sidebar-open="false"');
    expect(html).toContain('data-sidebar-mode="collapsed"');
    expect(html).toContain('data-sidebar-pinned="false"');
    expect(html).toContain('data-hover-reveal="true"');
    expect(html).toContain('data-floating="true"');
    expect(html).toContain('aria-label="固定展开侧边栏"');
    expect(html).toContain('data-hover-reveal="true"');
    expect(html).toContain("lucide-panel-left");
    expect(html).toContain('aria-controls="workspace-navigation"');
    expect(html).toContain('inert=""');
    expect(html).toContain('aria-label="调整侧边栏宽度"');
    expect(html).toContain('aria-valuenow="236"');
    expect(html).not.toMatch(/aria-label="调整侧边栏宽度"[^>]*><span/);
    expect(html).not.toContain('data-page-glass="true"');
    expect(html).toContain('href="https://github.com/happy-token/OpenRealtime"');
    expect(html).toContain('aria-label="界面语言"');
  });

  it.each([
    ["/roles", "角色"],
    ["/resources", "资源"],
    ["/docs", "文档"],
    ["/settings/appearance", "设置"],
  ])("uses the same floating sidebar and glass page over the home background on %s", (pathname, label) => {
    navigation.pathname = pathname;
    const html = renderToStaticMarkup(<WorkspaceShell><div>{label}</div></WorkspaceShell>);

    expect(html).toContain('data-floating-sidebar="true"');
    expect(html).toContain('data-sidebar-open="false"');
    expect(html).toContain('data-floating="true"');
    expect(html).toContain('aria-label="固定展开侧边栏"');
    expect(html).toContain('data-hover-reveal="true"');
    expect(html).toContain('aria-controls="workspace-navigation"');
    expect(html).toContain('inert=""');
    expect(html).toContain('data-home-background="true"');
    expect(html).toContain('data-page-glass="true"');
    expect(html).not.toContain('title="在 GitHub 为 OpenRealtime 点 Star"');
    expect(html).not.toContain('href="https://github.com/happy-token/OpenRealtime"');
    expect(html).not.toContain('data-compact="true"');
  });

  it("keeps the resource library beside roles in primary navigation", () => {
    navigation.pathname = "/roles";
    const html = renderToStaticMarkup(<WorkspaceShell><div>角色</div></WorkspaceShell>);

    expect(html).toContain('href="/resources"');
    expect(html).toContain("lucide-library-big");
    expect(html).toContain(">资源</span>");
  });

  it("keeps model services under the supplier settings entry", () => {
    navigation.pathname = "/settings/providers";
    const html = renderToStaticMarkup(<WorkspaceShell><div>供应商设置</div></WorkspaceShell>);

    expect(html).toContain('href="/settings/providers"');
    expect(html).toContain(">供应商</span>");
    expect(html).toContain('href="/settings/services"');
  });

  it("reuses the settings-style secondary sidebar for resource categories", () => {
    navigation.pathname = "/resources";
    const html = renderToStaticMarkup(<WorkspaceShell resourceTab="avatars" resourceReturnTo="role-personal-123"><div>数字人</div></WorkspaceShell>);

    expect(html).toContain('aria-label="资源导航"');
    expect(html).toContain(">资源库</div>");
    expect(html).toContain('href="/resources?tab=avatars&amp;return_to=role-personal-123"');
    expect(html).toContain(">声音</span>");
    expect(html).toContain(">人设</span>");
    expect(html).toContain(">离线数字人</span>");
    expect(html).toContain(">实时数字人</span>");
    expect(html).not.toContain(">动作与口型对齐</span>");
    expect(html).toContain(">工具</span>");
    expect(html).toContain(">知识库</span>");
    expect(html).toContain('aria-current="page"');
    expect(html).not.toContain("最近对话");
  });

  it("lets the digital-human library use the full home stage without a page-glass wrapper", () => {
    navigation.pathname = "/resources";
    const html = renderToStaticMarkup(<WorkspaceShell resourceTab="avatars" immersive><div>数字人主页</div></WorkspaceShell>);

    expect(html).toContain("数字人主页");
    expect(html).not.toContain('data-page-glass="true"');
  });

  it.each(["/resources", "/resources?tab=motion", "/services/motion", "/services/talking"])(
    "keeps resource workspaces active for %s",
    (pathname) => expect(isResourceWorkspacePath(pathname)).toBe(true),
  );

  it("uses the shared adjustable liquid-glass material for every sidebar", () => {
    const css = readFileSync(new URL("./workspace-shell.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.sidebar\s*\{[^}]*var\(--panel-surface-alpha,.58\)[^}]*backdrop-filter:\s*blur\(var\(--panel-blur,30px\)\)/s);
    expect(css).toContain('backdrop-filter: blur(var(--panel-blur,30px)) saturate(175%)');
    expect(css).toContain('var(--panel-surface-alpha,.58)');
    expect(css).toContain('.sidebar[data-floating="true"][data-open="true"]');
    expect(css).toMatch(/\.sidebarToggle\s*\{[^}]*top:\s*30px;[^}]*width:\s*24px;[^}]*height:\s*24px;[^}]*border-radius:\s*8px/s);
    expect(css).toContain('.sidebarToggle[data-open="true"] { left: calc(var(--sidebar-width,236px) - 20px); }');
    expect(css).toMatch(/\.sidebarToggle::after\s*\{[^}]*inset:\s*-10px/s);
    expect(css).toMatch(/\.sidebarToggle svg\s*\{[^}]*width:\s*11px;[^}]*height:\s*11px/s);
    expect(css).toMatch(/\.sidebarHoverRail\s*\{[^}]*width:\s*18px;[^}]*height:\s*112px/s);
    expect(css).toMatch(/\.sidebarHoverRailLine\s*\{[^}]*width:\s*3px;[^}]*height:\s*58px/s);
    expect(css).toMatch(/\.pageGlass\s*\{[^}]*backdrop-filter:\s*blur\(var\(--panel-blur,30px\)\)/s);
    expect(css).toContain('.shell[data-session="false"] { background: transparent; }');
    expect(css).toContain('.sidebar,.searchField,.accountAvatar,.accountMenu,.sidebarToggle,.sidebarHoverRail,.pageGlass');
    expect(css).toContain('@media (prefers-reduced-motion: reduce)');
  });
});
