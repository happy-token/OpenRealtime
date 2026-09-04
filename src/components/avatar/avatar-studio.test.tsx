import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AvatarStudio, isAvatarNameLocked } from "./avatar-studio";

describe("AvatarStudio", () => {
  it("chooses the creation task only after the shared Avatar selector", () => {
    const html = renderToStaticMarkup(<AvatarStudio />);

    expect(html).not.toContain("选择创建任务");
    expect(html).not.toContain('data-task="realtime"');
    expect(html).not.toContain('aria-pressed="true"');
    expect(html.match(/选择 Avatar 形象/g)).toHaveLength(1);
    expect(html).toContain("选择或创建一个 Avatar 形象，确认后再选择下一步要创建的能力。");
    expect(html).toContain('role="group" aria-label="选择下一步操作"');
    expect(html).toContain("确认形象并选择下一步");
    expect(html).toContain("创建实时驱动");
    expect(html).toContain("创建 Avatar 动作");
    expect(html).not.toContain("实时驱动配置");
    expect(html).not.toContain("动作配置");
    expect(html).not.toContain("确认 Avatar ·");
    expect(html).toContain("从资产库选择");
    expect(html).toContain("创建图片");
    expect(html).not.toContain("HappyImage 创作");
    expect(html).toContain("创建 Avatar");
    expect(html).toContain('role="group" aria-label="形象来源"');
    expect(html).not.toContain('aria-label="Avatar 预览"');
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain("digital human");
  });

  it("locks names only for Avatars selected from the asset library", () => {
    expect(isAvatarNameLocked("library")).toBe(true);
    expect(isAvatarNameLocked("upload")).toBe(false);
    expect(isAvatarNameLocked("happyimage")).toBe(false);
  });

  it("uses the primary-action height for the two next-step buttons", () => {
    const css = readFileSync(new URL("./avatar-studio.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.wizardNavigation \.nextTaskChoice \{[^}]*min-height: var\(--avatar-button-height-primary\)/);
    expect(css).not.toMatch(/\.wizardNavigation \.nextTaskChoice \{[^}]*min-height: 72px/);
  });

  it("keeps the selection, realtime, and preview cards on one shared desktop height", () => {
    const css = readFileSync(new URL("./avatar-studio.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.wizardPanel,\s*\.visualStage,\s*\.taskSidebar \{ height: var\(--avatar-workspace-height\); min-height: 0; \}/);
    expect(css).toContain(".creationWorkspace { min-height: var(--avatar-workspace-height); }");
  });
});
