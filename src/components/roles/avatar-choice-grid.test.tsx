import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./avatar-choice-grid.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./identity-choice-grid.module.css", import.meta.url), "utf8");

describe("shared avatar choice cards", () => {
  it("matches the creation task card anatomy and action count", () => {
    expect(component).toContain("styles.avatarMedia");
    expect(component).toContain("styles.avatarCopy");
    expect(component).toContain("{actionCount} 个动作");
    expect(component).not.toContain("仅对话");
    expect(css).toMatch(/\.avatarGrid\s*\{[^}]*repeat\(3,minmax\(0,1fr\)\)/s);
    expect(css).toMatch(/\.avatarMedia\s*\{[^}]*aspect-ratio:\s*4\s*\/\s*3/s);
    expect(css).toMatch(/\.avatarMedia img\s*\{[^}]*object-fit:\s*contain/s);
  });
});
