import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AvatarPageShell } from "./avatar-page-shell";

describe("AvatarPageShell", () => {
  it("renders the main-screen Avatar scene as the asset page background", () => {
    const html = renderToStaticMarkup(
      <AvatarPageShell active="library" pageTitle="数字人资产">
        <div>资产内容</div>
      </AvatarPageShell>,
    );

    expect(html).toContain('data-scene-key="none"');
    expect(html).toContain('data-media="fallback"');
    expect(html).not.toContain("%2Fdigital-human%2Fshuchang-preview.jpg");
    expect(html).not.toContain("ambientOne");
    expect(html).toContain("资产内容");
    expect(html).toContain('data-active="library"');
  });

  it("defines one shared control-density scale for Avatar workflows", () => {
    const css = readFileSync(new URL("./avatar-page-shell.module.css", import.meta.url), "utf8");

    expect(css).toContain("--avatar-button-height-compact: 32px");
    expect(css).toContain("--avatar-button-height-standard: 40px");
    expect(css).toContain("--avatar-button-height-primary: 44px");
    expect(css).toContain("--avatar-button-height-choice: 52px");
    expect(css).toContain("--avatar-workspace-height: clamp(520px, calc(100svh - 150px), 680px)");
  });
});
