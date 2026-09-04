import { describe, expect, it } from "vitest";
import { parseByteRange, resolveAvatarArtifactPath } from "./avatar-evaluation-artifacts";

describe("resolveAvatarArtifactPath", () => {
  it("allows only known artifacts when internal preview is enabled", () => {
    expect(resolveAvatarArtifactPath("static-base", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe("/workspace/research-assets/avatar-evaluation/2026-08-22/runs/static/static-base.mp4");
    expect(resolveAvatarArtifactPath("liveportrait-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/liveportrait/liveportrait-001.mp4",
    );
    expect(resolveAvatarArtifactPath("wav2lip-offline-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-offline-001.mp4",
    );
    expect(resolveAvatarArtifactPath("wav2lip-offline-box-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-offline-box-001.mp4",
    );
    expect(resolveAvatarArtifactPath("livetalking-wav2lip96-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/livetalking/livetalking-wav2lip96-001.mp4",
    );
    expect(resolveAvatarArtifactPath("liteavatar-cpu-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/liteavatar/liteavatar-cpu-001.mp4",
    );
    expect(resolveAvatarArtifactPath("dh-live-mini-browser-003", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/dh-live-mini/dh-live-mini-browser-003.mp4",
    );
    expect(resolveAvatarArtifactPath("dh-live-mini-v1-custom-003", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/dh-live-mini-v1-custom-003.mp4",
    );
    expect(resolveAvatarArtifactPath("wav2lip-comparison-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-comparison-001-canonical.mp4",
    );
    expect(resolveAvatarArtifactPath("dh-live-mini-v1-comparison-001", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/dh-live-mini-v1-comparison-001-canonical.mp4",
    );
    expect(resolveAvatarArtifactPath("motion-base-warm", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBe(
      "/workspace/research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/01-warm-closeup.mp4",
    );
  });

  it("rejects unknown paths and production-disabled previews", () => {
    expect(resolveAvatarArtifactPath("../../.env", {
      projectRoot: "/workspace",
      previewEnabled: true,
    })).toBeNull();
    expect(resolveAvatarArtifactPath("static-base", {
      projectRoot: "/workspace",
      previewEnabled: false,
    })).toBeNull();
  });

  it("parses browser byte ranges for video seeking", () => {
    expect(parseByteRange("bytes=10-19", 100)).toEqual({ start: 10, end: 19 });
    expect(parseByteRange("bytes=90-", 100)).toEqual({ start: 90, end: 99 });
    expect(parseByteRange("bytes=-10", 100)).toEqual({ start: 90, end: 99 });
    expect(parseByteRange("bytes=100-", 100)).toBeNull();
  });
});
