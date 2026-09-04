import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("document scroll ownership", () => {
  it("keeps the browser document fixed so full-screen pages own their scroll", () => {
    const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(css).toMatch(/html,\s*body\s*{[^}]*height:\s*100%/s);
    expect(css).toMatch(/html\s*{[^}]*overflow:\s*hidden/s);
  });

  it("keeps the segmented motion library inside its own scroll area", () => {
    const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(css).toMatch(/avatar-motion-library-grid[^}]*max-height:[^}]*overflow-y:\s*auto[^}]*overscroll-behavior:\s*contain/s);
  });

  it("keeps the expanded segmented identity library inside its own scroll area", () => {
    const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(css).toMatch(/avatar-identity-library-body[^}]*max-height:[^}]*overflow-y:\s*auto[^}]*overscroll-behavior:\s*contain/s);
  });

  it("reveals a loaded segmented motion surface instead of leaving the fallback image visible", () => {
    const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(css).toMatch(/data-renderer-state="preview"[^}]*digital-human-motion-base-video[^}]*opacity:\s*1/s);
  });

  it("centers the content-sized page-form menu and stacks labels below each diagram", () => {
    const css = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.session-layout-menu\s*{[^}]*left:\s*50%[^}]*width:\s*max-content[^}]*grid-template-columns:\s*repeat\(3,\s*max-content\)/s);
    expect(css).toMatch(/\.session-layout-menu\[data-open="true"\]\s*{[^}]*transform:\s*translate\(-50%,\s*0\)\s*scale\(1\)/s);
    expect(css).toMatch(/\.session-layout-menu\s*>\s*button\s*{[^}]*justify-items:\s*center[^}]*text-align:\s*center/s);
  });
});
