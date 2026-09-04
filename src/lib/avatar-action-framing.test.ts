import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Avatar action preview framing", () => {
  it("keeps portrait action videos fully visible across asset and session workbench previews", () => {
    const detailCss = readFileSync(
      new URL("../components/avatar/avatar-detail-screen.module.css", import.meta.url),
      "utf8",
    );
    const coverflowCss = readFileSync(
      new URL("../components/avatar/avatar-media-coverflow.module.css", import.meta.url),
      "utf8",
    );
    const libraryCss = readFileSync(
      new URL("../components/avatar/avatar-asset-library.module.css", import.meta.url),
      "utf8",
    );
    const workspaceCss = readFileSync(
      new URL("../components/call/preview-workspace-lab.module.css", import.meta.url),
      "utf8",
    );
    const globalCss = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");

    expect(detailCss).toMatch(/\.stageMedia\s*>\s*video\s*{[^}]*object-fit:\s*contain/s);
    expect(coverflowCss).toMatch(/\.media\s*>\s*video\s*{[^}]*object-fit:\s*contain/s);
    expect(libraryCss).toMatch(/\.collapsedActionVideo\s*{[^}]*object-fit:\s*contain/s);
    expect(workspaceCss).toMatch(/\.avatarPreviewForeground\s*{[^}]*object-fit:\s*contain/s);
    expect(workspaceCss).toMatch(/\.avatarPreviewForeground\[data-fit="cover"\]\s*{[^}]*object-fit:\s*cover/s);
    expect(globalCss).toMatch(/\.segmented-avatar-card-stage\s*>\s*\.segmented-avatar-card-action-video\s*{[^}]*object-fit:\s*contain/s);
  });

  it("uses the selected action as a blurred full-bleed backdrop on the session main screen", () => {
    const workspaceSource = readFileSync(
      new URL("../components/call/home-preview-workspace.tsx", import.meta.url),
      "utf8",
    );
    const workspaceCss = readFileSync(
      new URL("../components/call/preview-workspace-lab.module.css", import.meta.url),
      "utf8",
    );

    expect(workspaceSource.match(/<source src=\{motion\}/g)).toHaveLength(2);
    expect(workspaceSource).toContain("styles.avatarPreviewMotionBackdrop");
    expect(workspaceSource).toContain("styles.avatarPreviewForeground");
    expect(workspaceCss).toMatch(/\.avatarPreview\s*>\s*\.avatarPreviewMotionBackdrop\s*{[^}]*object-fit:\s*cover[^}]*filter:[^}]*blur\([^}]*brightness\(\.76\)/s);
    expect(workspaceCss).toMatch(/\.workspace\[data-mode="avatar"\]\s+\.preview::before\s*{[^}]*rgba\(5, 7, 13, \.14\)/s);
    expect(workspaceCss).toMatch(/\.avatarPreviewForeground\s*{[^}]*object-fit:\s*contain/s);
  });
});
