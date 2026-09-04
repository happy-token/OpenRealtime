import { describe, expect, it, vi } from "vitest";
import {
  fetchAvatarActionCatalog,
  selectAvatarActionRendition,
  type AvatarActionAsset,
} from "./avatar-motion-catalog";

const motionBase: AvatarActionAsset = {
  avatar_action_id: "motion-1",
  avatar_id: "shuchang",
  candidate_id: "candidate-1",
  phase: "ready",
  source_master_artifact_id: "source-1",
  source_media: { duration_ms: 3100, width: 720, height: 1280, video_codec: "h264", has_audio: false },
  renditions: [
    {
      rendition_id: "mobile-1",
      profile: "mobile_fullscreen",
      phase: "approved",
      artifact_id: "mobile-artifact",
      media: { duration_ms: 3100, width: 720, height: 1280, video_codec: "h264", has_audio: false },
    },
    {
      rendition_id: "desktop-1",
      profile: "desktop_fullscreen",
      phase: "approved",
      artifact_id: "desktop-artifact",
      media: { duration_ms: 3100, width: 1280, height: 720, video_codec: "h264", has_audio: false },
    },
  ],
};

describe("Motion Base catalog client", () => {
  it("does not expose JSON parser internals for an HTML route failure", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(
      "<pre>missing route module</pre>",
      { status: 404, headers: { "Content-Type": "text/html" } },
    ));

    await expect(fetchAvatarActionCatalog(undefined, fetcher as typeof fetch))
      .rejects.toThrow("动作底片目录请求失败（HTTP 404）");
  });

  it("reads the authoritative catalog and current independent selection", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      actions: [motionBase],
      selection: { avatar_id: "shuchang", avatar_action_id: "motion-1", revision: 2 },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(fetchAvatarActionCatalog("shuchang", fetcher as typeof fetch)).resolves.toMatchObject({
      avatarActions: [motionBase],
      selection: { avatar_action_id: "motion-1" },
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/avatar-assets/actions?avatarId=shuchang",
      { cache: "no-store", signal: undefined },
    );
  });

  it("reads the cross-identity motion asset library when no identity filter is supplied", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      actions: [motionBase],
      selection: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    await expect(fetchAvatarActionCatalog(undefined, fetcher as typeof fetch)).resolves.toEqual({
      avatarActions: [motionBase],
      selection: null,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/avatar-assets/actions",
      { cache: "no-store", signal: undefined },
    );
  });

  it("chooses the approved rendition matching phone or desktop ratio", () => {
    expect(selectAvatarActionRendition(motionBase, "9:16")).toMatchObject({
      rendition: { artifact_id: "mobile-artifact" },
      temporaryFit: false,
    });
    expect(selectAvatarActionRendition(motionBase, "16:9")).toMatchObject({
      rendition: { artifact_id: "desktop-artifact" },
      temporaryFit: false,
    });
    expect(selectAvatarActionRendition(motionBase, "1:1")).toMatchObject({
      rendition: { artifact_id: "desktop-artifact" },
      temporaryFit: true,
    });
  });

  it("uses the other approved profile as an explicit temporary fit", () => {
    const mobileOnly = { ...motionBase, renditions: [motionBase.renditions[0]] };
    expect(selectAvatarActionRendition(mobileOnly, "16:9")).toMatchObject({
      rendition: { artifact_id: "mobile-artifact" },
      temporaryFit: true,
    });
  });
});
