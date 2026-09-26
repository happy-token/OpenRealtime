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
    expect(globalCss).toMatch(/\.segmented-avatar-card-stage\s*>\s*\.segmented-avatar-card-action-video\s*{[^}]*object-fit:\s*contain/s);
    expect(globalCss).toMatch(/\.avatar-motion-card-preview\s*>\s*video,[^{]*\{[^}]*object-fit:\s*contain/s);
    expect(globalCss).toMatch(/\.digital-human-call-image\s*\{[^}]*object-fit:\s*contain/s);
    expect(globalCss).toMatch(/\.digital-human-live-video\s*\{[^}]*object-fit:\s*contain/s);
  });

  it("uses one stable, fully visible action video on the session main screen", () => {
    const workspaceSource = readFileSync(
      new URL("../components/call/home-preview-workspace.tsx", import.meta.url),
      "utf8",
    );
    const workspaceCss = readFileSync(
      new URL("../components/call/preview-workspace-lab.module.css", import.meta.url),
      "utf8",
    );
    const mainPreviewSource = workspaceSource.slice(
      workspaceSource.indexOf("function MainAvatarMotionPreview"),
      workspaceSource.indexOf("function OfflineMotionPreview"),
    );
    const offlinePreviewSource = workspaceSource.slice(
      workspaceSource.indexOf("function OfflineMotionPreview"),
      workspaceSource.indexOf("export function HomePreviewWorkspace"),
    );

    expect(mainPreviewSource).not.toContain("avatarPreviewMotionBackdrop");
    expect(mainPreviewSource.match(/<video\b/g)).toHaveLength(1);
    expect(mainPreviewSource).toContain("poster={choice.preview}");
    expect(mainPreviewSource).toContain("data-fit={fit}");
    expect(mainPreviewSource).toMatch(/className=\{styles\.avatarPreviewForeground\}[^>]*src=\{motion\}/);
    expect(offlinePreviewSource.match(/<video\b/g)).toHaveLength(1);
    expect(offlinePreviewSource).toContain("poster={choice.preview}");
    expect(offlinePreviewSource).toContain("data-fit={fit}");
    expect(offlinePreviewSource).toContain("resolveAvatarStagePreviewSource");
    expect(offlinePreviewSource).toContain("onError={() => setMotionFailed(true)}");
    expect(offlinePreviewSource).toContain("const activeUrl = motionFailed ? talkingUrl");
    expect(workspaceCss).toMatch(/\.workspace\[data-mode="avatar"\]\s+\.preview::before\s*{[^}]*rgba\(5, 7, 13, \.14\)/s);
    expect(workspaceCss).toMatch(/\.avatarPreviewForeground\s*{[^}]*width:\s*100%[^}]*height:\s*100%[^}]*object-fit:\s*contain/s);
    expect(workspaceCss).toMatch(/\.avatarPreviewForeground\[data-fit="cover"\]\s*{[^}]*object-fit:\s*cover/s);
  });
});
