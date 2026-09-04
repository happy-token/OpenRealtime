import { describe, expect, it } from "vitest";
import {
  resolveAvatarRendererRuntime,
  resolveAvatarRendererRuntimeForModel,
} from "./avatar-renderer-runtime";

describe("avatar renderer runtime configuration", () => {
  it("uses a prewarmed managed renderer by default", () => {
    expect(resolveAvatarRendererRuntime({})).toEqual({
      mode: "managed",
      internalUrl: "http://127.0.0.1:8010",
      publicUrl: "http://127.0.0.1:8010",
      rendererId: "livetalking-wav2lip256",
      modelId: "wav2lip256",
      modelSize: 256,
      port: 8010,
    });
  });

  it("supports an independently deployed Linux renderer", () => {
    expect(resolveAvatarRendererRuntime({
      OPENREALTIME_AVATAR_RENDERER_MODE: "external",
      OPENREALTIME_AVATAR_RENDERER_URL: "http://avatar-renderer.internal:8010",
      OPENREALTIME_AVATAR_RENDERER_PUBLIC_URL: "https://avatar.example.com",
    })).toEqual({
      mode: "external",
      internalUrl: "http://avatar-renderer.internal:8010",
      publicUrl: "https://avatar.example.com",
      rendererId: "livetalking-wav2lip256",
      modelId: "wav2lip256",
      modelSize: 256,
      port: 8010,
    });
  });

  it("isolates the compatibility model on its own endpoint", () => {
    expect(resolveAvatarRendererRuntimeForModel("wav2lip96", {})).toEqual({
      mode: "managed",
      internalUrl: "http://127.0.0.1:8011",
      publicUrl: "http://127.0.0.1:8011",
      rendererId: "livetalking-wav2lip96",
      modelId: "wav2lip96",
      modelSize: 96,
      port: 8011,
    });
  });

  it("does not resolve a renderer when self-hosted avatars are disabled", () => {
    expect(resolveAvatarRendererRuntime({
      OPENREALTIME_AVATAR_RENDERER_MODE: "disabled",
    })).toBeNull();
  });
});
