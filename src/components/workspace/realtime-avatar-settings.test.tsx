import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("real-time avatar settings window", () => {
  it("uses a scrollable floating panel with adjustable dimensions", () => {
    const css = readFileSync(new URL("./realtime-avatar-settings.module.css", import.meta.url), "utf8");
    const source = readFileSync(new URL("./realtime-avatar-settings.tsx", import.meta.url), "utf8");
    expect(css).toMatch(/\.panel\s*\{[^}]*position:\s*absolute/s);
    expect(css).toMatch(/\.panelBody\s*\{[^}]*overflow-y:\s*auto/s);
    expect(css).toMatch(/\.panelBody\s*\{[^}]*scrollbar-gutter:\s*stable/s);
    expect(css).toMatch(/\.toolList\s*\{[^}]*max-height:\s*216px[^}]*overflow-y:\s*auto/s);
    expect(css).toContain("var(--panel-width)");
    expect(css).toContain("var(--panel-height)");
    expect(source).toContain("onPointerDown={startDrag}");
    expect(source).toContain("RESIZE_EDGES.map");
    expect(source).toContain("startResize(event, edge)");
    expect(source).toContain("resizeWithKeyboard(event, edge)");
    expect(css).toContain('.resizeEdge[data-edge="left"]');
    expect(css).toContain('.resizeEdge[data-edge="right"]');
    expect(css).toContain('.resizeEdge[data-edge="top"]');
    expect(css).toContain('.resizeEdge[data-edge="bottom"]');
    expect(source).toContain("aria-expanded={open}");
    expect(source).toContain("知识库");
    expect(source).toContain("长期记忆");
    expect(source).not.toContain('title="角色基础"');
    expect(source).not.toContain('title="长期记忆"');
    expect(source).toContain('aria-label="启用长期记忆"');
  });
});
