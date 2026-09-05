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
    expect(html).not.toContain("创建图片");
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

  it("moves the mobile config drawer into the shared StudioConfigOverlay component", () => {
    const html = renderToStaticMarkup(<AvatarStudio />);
    const source = readFileSync(new URL("./avatar-studio.tsx", import.meta.url), "utf8");
    const css = readFileSync(new URL("./avatar-studio.module.css", import.meta.url), "utf8");

    expect(html).not.toContain("关闭配置");
    expect(html).not.toContain("收起配置");
    expect(source).toContain('import { StudioConfigOverlay } from "./studio-config-overlay";');
    expect(source).toMatch(/<StudioConfigOverlay open=\{mobileConfigOpen\} onOpenChange=\{setMobileConfigOpen\} label="配置 Avatar"/);
    expect(source).toMatch(/<StudioConfigOverlay open=\{mobileConfigOpen\} onOpenChange=\{setMobileConfigOpen\} label="实时驱动配置"/);
    expect(source).toContain("mobileConfigOpen={mobileConfigOpen}");
    expect(source).toContain("onMobileConfigOpenChange={setMobileConfigOpen}");
    expect(source).not.toContain("mobileDrawerBackdrop");
    expect(source).not.toContain("mobileConfigToggle");
    expect(source).not.toContain("data-mobile-config");
    expect(css).not.toContain("mobileDrawerBackdrop");
    expect(css).not.toContain("mobileConfigToggle");
  });

  it("auto-collapses the mobile config panel only after operations that produce a result", () => {
    const source = readFileSync(new URL("./avatar-studio.tsx", import.meta.url), "utf8");

    expect(source).toMatch(/chooseSource\(\{ id: `happyimage-\$\{crypto\.randomUUID\(\)\}`[^\n]*\}\);\s*\n\s*setMobileConfigOpen\(false\);/);
    expect(source).toMatch(/setAnamCandidate\(payload\.avatar\);\s*\n\s*setMobileConfigOpen\(false\);/);
    expect(source).toMatch(/setCurrentStep\(3\);\s*\n\s*setMobileConfigOpen\(false\);/);

    const changeAvatarBody = source.match(/function changeAvatar\(\) \{[\s\S]*?\n {2}\}/)?.[0] ?? "";
    const changeTaskBody = source.match(/function changeTask\([\s\S]*?\n {2}\}/)?.[0] ?? "";
    expect(changeAvatarBody).not.toContain("setMobileConfigOpen");
    expect(changeTaskBody).not.toContain("setMobileConfigOpen");
  });

  it("switches the stage portrait to cover for non-square avatars so tall or wide images fill the frame", () => {
    const source = readFileSync(new URL("./avatar-studio.tsx", import.meta.url), "utf8");
    const css = readFileSync(new URL("./avatar-studio.module.css", import.meta.url), "utf8");

    expect(source).toContain('import { classifyMediaAspectRatio } from "@/lib/media-aspect-fit";');
    expect(source.match(/onLoad=\{handleStagePortraitLoad\}/g)).toHaveLength(3);
    expect(source.match(/data-fit=\{stagePreviewFit\}/g)).toHaveLength(3);
    expect(source).toContain("setStagePreviewFit(classifyMediaAspectRatio(img.naturalWidth, img.naturalHeight));");

    expect(css).toMatch(/\.stageImage \.stagePortraitImage\[data-fit="landscape"\],\s*\n\.stageImage \.stagePortraitImage\[data-fit="portrait"\] \{ object-fit: cover; \}/);
    expect(css).toContain('.stageImage .stagePortraitImage[data-fit="portrait"] { object-position: 50% 22%; }');
  });

  it("switches the mobile visual stage to a portrait 9:16 box instead of a fixed height", () => {
    const css = readFileSync(new URL("./avatar-studio.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/@media \(max-width: 699px\) \{\s*\n\s*\.wizardPanel,\s*\n\s*\.taskSidebar \{ height: auto; \}\s*\n\s*\.visualStage \{ width: 100%; aspect-ratio: 9 \/ 16; height: auto; max-height: calc\(100dvh - 176px\); min-height: 0; \}\s*\n\}/);
    expect(css).not.toContain(".visualStage { height: 520px; min-height: 0; }");
  });
});
