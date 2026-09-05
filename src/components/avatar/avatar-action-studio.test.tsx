import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VIDEO_GENERATION_MODELS } from "@/lib/ltx-avatar-action";
import { AvatarActionStudio, estimateGenerationProgress, formatElapsedTime } from "./avatar-action-studio";

describe("AvatarActionStudio", () => {
  it("offers a compact action picker, separate upload entry, and continuous strength control", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded onChangeAvatar={() => undefined} />);
    expect(html).toContain("当前共享 Avatar");
    expect(html).toContain("上一步：返回选择 Avatar 形象");
    expect(html).toContain("上一步");
    expect(html).not.toContain(">更换<");
    expect(html).toContain("动作创作");
    expect(html).toContain("创建 Avatar 动作方式");
    expect(html).toContain("LivePortrait");
    expect(html).toContain("视频生成");
    expect(html).toContain('data-provider="liveportrait"');
    expect(html).toContain("提示词驱动");
    expect(html).not.toContain("LivePortrait 动作创作");
    expect(html).not.toContain("02 / LivePortrait");
    expect(html).not.toContain("Step 02 / Preview");
    expect(html).not.toContain(">动作选项<");
    expect(html).toContain('aria-label="动作选项"');
    expect(html).toContain("甜美元气");
    expect(html).toContain("纯欲柔光");
    expect(html).toContain("冷艳夜色");
    expect(html).toContain("知性温柔");
    expect(html).toContain("忧郁共鸣");
    expect(html).not.toContain("柔和回应");
    expect(html).not.toContain("侧头微笑");
    expect(html).not.toContain("自然注视");
    expect(html).not.toContain("侧头回正");
    expect(html).not.toContain("沉静凝思");
    expect(html).not.toContain("闭目思考");
    expect(html).toContain("上传动作");
    expect(html).toContain("动作幅度");
    expect(html).toContain('type="range"');
    expect(html).toContain('min="0.5"');
    expect(html).toContain('max="1.5"');
    expect(html).toContain('step="0.01"');
    expect(html).toContain("1.00×");
    expect(html).toContain("0.80×");
    expect(html).toContain("1.20×");
    expect(html).toContain("轻微");
    expect(html).toContain("自然");
    expect(html).toContain("明显");
    expect(html).toContain("生成动作");
    expect(html).toContain("创建动作资产");
    expect(html).toContain("lucide-check");
    expect(html).not.toContain("动作预览已生成，请确认效果");
    expect(html).not.toContain("生成后在这里确认动作效果");
    expect(html).not.toContain("保存后自动开始口型预处理");
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain("单帧");
  });

  it("does not expose technical step labels or the Avatar ID in the creation workspace", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" />);

    expect(html).not.toContain("Step 01");
    expect(html).not.toContain("avatar_id");
    expect(html).not.toContain("<code>avatar-123</code>");
  });

  it("keeps action selection on the left and uses the right side as one preview canvas", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded onChangeAvatar={() => undefined} />);

    expect(html).toContain('data-floating-preview="true"');
    expect(html).not.toContain('aria-label="切换内置动作参考"');
    expect(html).not.toContain("data-reference-action");
    expect(html).toContain('aria-label="预览内容"');
    expect(html).toContain("当前形象");
    expect(html).toContain("参考动作");
    expect(html).toContain("生成效果");
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('aria-pressed="false"');
  });

  it("keeps the LTX prompt compact with a view button beside the list", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);

    expect(html).toContain('aria-label="视频生成提示词选择"');
    expect(html).toContain('aria-label="查看当前视频生成提示词"');
    expect(html).toContain("自定义提示词");
    expect(html).not.toContain('aria-label="LTX 自定义提示词"');
    expect(html).not.toContain('role="dialog"');
  });

  it("offers each reviewed companion style directly in the prompt selection list", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);

    expect(html).toContain('role="listbox" aria-label="视频生成提示词选项"');
    expect(html).not.toContain('aria-label="提示词风格模块"');
    expect(html).toContain("甜美元气");
    expect(html).toContain("纯欲柔光");
    expect(html).toContain("冷艳夜色");
    expect(html).toContain("知性温柔");
    expect(html).toContain("忧郁共鸣");
    expect(html).not.toContain("自然对话");
    expect(html).not.toContain("专业主播");
    expect(html).not.toContain("亲和客服");
    expect(html).not.toContain("未来科技");
  });

  it("keeps the preview action label provider-neutral and free of leading icons", () => {
    const livePortraitHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded />);
    const ltxHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);

    expect(livePortraitHtml).toMatch(/<button[^>]*data-generate-action="true"[^>]*>生成动作<\/button>/);
    expect(ltxHtml).toMatch(/<button[^>]*data-generate-action="true"[^>]*>生成动作<\/button>/);
    expect(livePortraitHtml).not.toContain("lucide-sparkles");
    expect(ltxHtml).not.toContain("生成 LTX 动作预览");
  });

  it("uses one unnumbered custom list style for LivePortrait actions and LTX prompts", () => {
    const livePortraitHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded />);
    const ltxHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);

    expect(livePortraitHtml).toContain('role="combobox" aria-label="动作选项"');
    expect(ltxHtml).toContain('role="combobox" aria-label="视频生成提示词选择"');
    expect(ltxHtml).toContain('role="listbox" aria-label="视频生成提示词选项"');
    expect(ltxHtml).not.toContain('<select aria-label="视频生成提示词选择"');
    expect(livePortraitHtml).not.toContain(">内置动作</span>");
    expect(livePortraitHtml).not.toContain(">01</span>");
    expect(livePortraitHtml).not.toContain(">02</span>");
  });

  it("presents LivePortrait action selection and upload as parallel compact sources", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded />);
    const uploadHintId = html.match(/aria-label="上传动作" aria-describedby="([^"]+)"/)?.[1];

    expect(html).toContain('aria-label="动作来源"');
    expect(uploadHintId).toBeTruthy();
    expect(html).toContain(`id="${uploadHintId}" role="tooltip">MP4、WebM 或 MOV，最大 50MB</span>`);
    expect(html).toContain(">上传动作</strong>");
    expect(html).not.toContain(">上传动作参考</strong>");
  });

  it("keeps the action name field and preview action in one stable footer", () => {
    const livePortraitHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded />);
    const ltxHtml = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);
    const stableFooter = /role="group" aria-label="动作名称与生成"[\s\S]*>动作名称<\/span>[\s\S]*data-generate-action="true"/;

    expect(livePortraitHtml).toMatch(stableFooter);
    expect(ltxHtml).toMatch(stableFooter);
  });

  it("keeps expanded dropdowns above the fixed action footer", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    const actionSelectRule = css.match(/\.actionSelect \{[^}]*\}/)?.[0] || "";
    const actionFooterRule = css.match(/\.embedded \.actionFooter \{[^}]*\}/)?.[0] || "";

    expect(actionSelectRule).toContain("z-index: 12");
    expect(actionFooterRule).toContain("z-index: 9");
  });

  it("keeps the completed action button on the Avatar theme palette", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    const savedButtonRule = css.match(/\.accept\[data-saved="true"\] \{[^}]*\}/)?.[0] || "";

    expect(savedButtonRule).toContain("var(--accent)");
    expect(savedButtonRule).toContain("var(--accent-deep)");
    expect(savedButtonRule).not.toContain("#257956");
  });

  it("uses compact action menu rows without shrinking the picker triggers", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");

    expect(css).toContain("--avatar-action-menu-row-height: 44px");
    expect(css).toMatch(/\.actionSelectMenu > button \{[^}]*min-height: var\(--avatar-action-menu-row-height\)/);
    expect(css).toMatch(/\.actionSelectTrigger \{[^}]*min-height: var\(--avatar-button-height-standard\)/);
  });

  it("aligns both custom pickers, their options, upload, and prompt action heights", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.actionSelectTrigger \{[^}]*min-height: var\(--avatar-button-height-standard\)/);
    expect(css).toMatch(/\.actionSelectMenu > button \{[^}]*min-height: var\(--avatar-action-menu-row-height\)/);
    expect(css).toMatch(/\.actionSourcePicker \{[^}]*grid-template-columns: minmax\(0,1fr\) minmax\(0,1fr\)/);
    expect(css).toMatch(/\.uploadMotion > button:first-child \{[^}]*min-height: var\(--avatar-button-height-standard\)/);
    expect(css).toMatch(/\.promptViewButton \{[^}]*min-height: var\(--avatar-button-height-standard\)/);
  });

  it("splits provider and model into side-by-side custom lists and exposes all MiniMax H3 models", () => {
    const html = renderToStaticMarkup(<AvatarActionStudio avatarId="avatar-123" embedded initialProvider="ltx" />);

    expect(html).toContain('role="combobox" aria-label="视频生成供应商选择"');
    expect(html).toContain('role="listbox" aria-label="视频生成供应商选项"');
    expect(html).toContain('role="combobox" aria-label="视频生成模型选择"');
    expect(html).toContain('role="listbox" aria-label="视频生成模型选项"');
    expect(html).toContain("MiniMax");
    expect(html).toMatch(/aria-label="视频生成供应商选择"[\s\S]*?<strong>MiniMax<\/strong>/);
    expect(html).toMatch(/aria-label="视频生成模型选择"[\s\S]*?<strong>H3<\/strong>/);
    expect(html).toContain('aria-label="数字人形象角色"');
    expect(html).toContain("首帧 + 尾帧");
    expect(html).toContain("仅首帧");
    expect(html).toContain("仅尾帧");
    expect(html).toContain("多模态参考图");
    const durationOptions = html.match(/role="listbox" aria-label="MiniMax 时长选项"[^>]*>([\s\S]*?)<\/div>/)?.[1] || "";
    expect(durationOptions).toContain("6 秒");
    expect(durationOptions).not.toContain("4 秒");
    expect(durationOptions).not.toContain("15 秒");
    expect(html).toContain("固定 role · reference_video");
    expect(html.indexOf(">供应商</span>")).toBeLessThan(html.indexOf(">提示词选择</span>"));
    expect(VIDEO_GENERATION_MODELS.filter((model) => model.provider === "minimax").map((model) => model.name)).toEqual([
      "H3", "H3 Max", "H3-Context-IR",
    ]);
    expect(html).not.toContain('<select aria-label="视频生成模型选择"');
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    expect(css).toMatch(/\.videoProviderModelGrid \{[^}]*grid-template-columns:/);
    expect(css).toMatch(/\.videoProviderModelGrid \.selectField:first-child \.actionSelectMenu \{[^}]*width: calc\(200% \+ 8px\)/);
    expect(css).toMatch(/\.promptChoiceRow \.actionSelectMenu \{[^}]*width: calc\(100% \+ 69px\)/);
  });

  it("keeps the LTX model note legible below the selector", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    const costNoteRule = css.match(/\.costNote \{[^}]*\}/)?.[0] || "";

    expect(costNoteRule).toContain("color: color-mix(in srgb,var(--text) 72%,var(--surface-solid))");
    expect(costNoteRule).toContain("font-size: .55rem");
    expect(costNoteRule).not.toContain("background");
    expect(costNoteRule).not.toContain("border");
  });

  it("uses legible liquid-glass surfaces for MiniMax controls and compact reference upload", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    const source = readFileSync(new URL("./avatar-action-studio.tsx", import.meta.url), "utf8");
    const triggerRule = css.match(/\.actionSelectTrigger \{[^}]*\}/)?.[0] || "";
    const menuRule = css.match(/\.actionSelectMenu \{[^}]*\}/)?.[0] || "";

    expect(source.match(/<GenerationParameterSelect/g)).toHaveLength(4);
    expect(source).toContain("aria-activedescendant={videoVendorMenuOpen");
    expect(source).not.toContain("miniMaxAvatarInput");
    expect(source).not.toContain("数字人资产形象");
    expect(css).not.toContain(".miniMaxParameterGrid select");
    expect(triggerRule).toContain("var(--action-glass-surface)");
    expect(triggerRule).toContain("backdrop-filter: blur(20px) saturate(150%)");
    expect(menuRule).toContain("var(--action-glass-menu)");
    expect(menuRule).toContain("backdrop-filter: blur(26px) saturate(155%)");
    expect(css).toContain('.actionSelect[data-open="true"] { z-index: 40; }');
    expect(css).toMatch(/\.parameterSelect \.actionSelectMenu \{[^}]*border-radius: 16px/);
    expect(css).toMatch(/\.miniMaxVideoInput \{[^}]*min-height: var\(--avatar-button-height-standard\)/);
    expect(css).toMatch(/\.miniMaxContent \{[^}]*display: grid;[^}]*gap: 4px/);
  });

  it("keeps action controls and preview on the shared desktop workspace height", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");

    expect(css).toContain(".embedded .layout { height: var(--avatar-workspace-height); }");
    expect(css).toMatch(/\.embedded \.controls,\s*\.embedded \.previewPanel \{ height: 100%; min-height: 0; \}/);
    expect(css).toMatch(/\.embedded \.controls \{[^}]*display: flex;[^}]*flex-direction: column/);
    expect(css).toMatch(/\.embedded \.actionFooter \{[^}]*position: sticky;[^}]*bottom: 0;[^}]*margin-top: auto/);
    expect(css).toMatch(/\.embedded \.actionFooter \{[^}]*grid-template-columns: minmax\(0,1fr\) auto;[^}]*align-items: end/);
    expect(css).toMatch(/\.actionFooter \.generate \{[^}]*width: auto;[^}]*min-width: 112px/);
  });

  it("hides the generation progress indicator while idle and keeps the accept flow reachable", () => {
    const livePortraitHtml = renderToStaticMarkup(
      <AvatarActionStudio avatarId="avatar-123" embedded onChangeAvatar={() => undefined} />,
    );

    expect(livePortraitHtml).not.toContain("排队中");
    expect(livePortraitHtml).not.toContain("视频生成中");
    expect(livePortraitHtml).not.toContain("请勿关闭或刷新此页面");
    expect(livePortraitHtml).toContain("创建动作资产");
  });

  it("wires up a queueing/processing progress overlay with an unload guard while a task is busy", () => {
    const source = readFileSync(new URL("./avatar-action-studio.tsx", import.meta.url), "utf8");

    expect(source).toContain('const busy = taskState === "queueing" || taskState === "processing";');
    expect(source).toContain('taskState === "queueing" ? "排队中…" : "视频生成中…"');
    expect(source).toContain("已用时 {formatElapsedTime(elapsedMs)} · 请勿关闭或刷新此页面");
    expect(source).toContain('window.addEventListener("beforeunload", confirmBeforeUnload)');
    expect(source).toContain("event.preventDefault();");
  });

  it("keeps the ticking elapsed-time clock out of the polite live region so it isn't re-announced every tick", () => {
    const source = readFileSync(new URL("./avatar-action-studio.tsx", import.meta.url), "utf8");

    expect(source).toMatch(/<strong role="status" aria-live="polite">\{taskState === "queueing"/);
    expect(source).toContain('<span aria-live="off">已用时 {formatElapsedTime(elapsedMs)}');
  });

  it("estimates generation progress with an asymptotic curve capped below 100%, per provider duration", () => {
    expect(estimateGenerationProgress(0, "ltx")).toBe(0);
    expect(estimateGenerationProgress(70_000, "ltx")).toBeCloseTo(1 - Math.exp(-1), 5);
    expect(estimateGenerationProgress(10_000_000, "minimax")).toBeCloseTo(0.96, 5);
    expect(estimateGenerationProgress(40_000, "liveportrait")).toBeGreaterThan(
      estimateGenerationProgress(40_000, "minimax"),
    );
  });

  it("formats elapsed milliseconds as mm:ss", () => {
    expect(formatElapsedTime(0)).toBe("00:00");
    expect(formatElapsedTime(65_000)).toBe("01:05");
    expect(formatElapsedTime(-500)).toBe("00:00");
  });

  it("animates the generation progress fill with a compositor-friendly transform, not layout properties", () => {
    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");

    const fillRule = css.match(/\.generationProgressFill \{[^}]*\}/)?.[0] ?? "";
    expect(fillRule).toContain("transform: scaleX(var(--progress,0))");
    expect(fillRule).toContain("transition: transform");
    expect(fillRule).not.toMatch(/transition:[^;]*width/);

    expect(css).toMatch(/\.generationProgress \{[^}]*bottom: 70px;[^}]*left: 50%/);
    expect(css).toMatch(/@media \(max-width: 699px\) \{[\s\S]*\.generationProgress \{ bottom: 66px; width: calc\(100% - 24px\); \}/);
  });

  it("renders identical output whether or not a mobile config handler is supplied, since the overlay only activates on narrow viewports", () => {
    const withHandler = renderToStaticMarkup(
      <AvatarActionStudio avatarId="avatar-123" embedded onChangeAvatar={() => undefined} mobileConfigOpen onMobileConfigOpenChange={() => undefined} />,
    );
    const withoutHandler = renderToStaticMarkup(
      <AvatarActionStudio avatarId="avatar-123" embedded onChangeAvatar={() => undefined} />,
    );

    expect(withHandler).toBe(withoutHandler);
    expect(withoutHandler).not.toContain('role="dialog"');
  });

  it("wires the embedded controls panel into the shared StudioConfigOverlay and auto-collapses on success", () => {
    const source = readFileSync(new URL("./avatar-action-studio.tsx", import.meta.url), "utf8");

    expect(source).toContain('import { StudioConfigOverlay } from "./studio-config-overlay";');
    expect(source).toContain("mobileConfigOpen?: boolean;");
    expect(source).toContain("onMobileConfigOpenChange?: (open: boolean) => void;");
    expect(source).toMatch(/embedded && onMobileConfigOpenChange \? \(\s*<StudioConfigOverlay/);
    expect(source.match(/onMobileConfigOpenChange\?\.\(false\);/g)).toHaveLength(2);
    expect(source).not.toContain("[data-mobile-config");

    const css = readFileSync(new URL("./avatar-action-studio.module.css", import.meta.url), "utf8");
    expect(css).not.toContain("data-mobile-config");
    expect(css).not.toMatch(/\.embedded \.controls \{[^}]*position: fixed/);
  });
});
