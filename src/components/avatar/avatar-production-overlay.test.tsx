import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./avatar-production-overlay.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./avatar-production-overlay.module.css", import.meta.url), "utf8");

describe("AvatarProductionOverlay motion dialog", () => {
  it("renders the motion creator directly without the nested Avatar studio shell", () => {
    expect(component).toMatch(/task === "motion" \? avatarId \? <AvatarActionStudio/);
    expect(component).toContain("focusedCreation");
    expect(component).not.toMatch(/task === "motion"[\s\S]{0,240}<AvatarStudio/);
  });

  it("uses a compact lower dialog that can be dragged and resized", () => {
    expect(component).toContain("onPointerDown={startDrag}");
    expect(component).toContain("onPointerMove={moveDialog}");
    expect(component).toContain("onPointerDown={startResize}");
    expect(component).toContain('"调整生成动作窗口大小"');
    expect(css).toMatch(/\.panel\[data-task="motion"\]\s*\{[^}]*width:\s*min\(760px/s);
    expect(css).toMatch(/\.panel\[data-task="motion"\]\s*\{[^}]*bottom:\s*42px/s);
  });

  it("lets motion-configuration edge handles receive pointer hover outside the dialog", () => {
    expect(component).toContain('aria-modal={movable ? undefined : true}');
    expect(css).toMatch(/\.backdrop\[data-task="motion"\]\s*\{[^}]*pointer-events:\s*none/s);
    expect(css).toMatch(/\.backdrop\[data-task="motion"\] \.panel\s*\{[^}]*pointer-events:\s*auto/s);
  });

  it("reuses the choreography options in a movable, resizable talking dialog", () => {
    expect(component).toContain('const movable = task === "motion" || task === "talking"');
    expect(component).toContain('<TalkingProductionComposer');
    expect(component).toContain('<AvatarLightweightConfig');
    expect(component).toContain('previewBeforeSave');
    expect(component).toContain('floating');
    expect(css).toMatch(/\.panel\[data-task="talking"\]\s*\{[^}]*width:\s*min\(420px/s);
  });
});
