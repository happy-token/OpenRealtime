import { describe, expect, it, vi } from "vitest";
import {
  acceptMotionCandidate,
  approveMotionRendition,
  persistLivePortraitCandidate,
  selectAvatarAction,
} from "./digital-human-motion-asset-workflow";

describe("digital human motion asset workflow", () => {
  it("persists a successful LivePortrait task as a trusted motion candidate", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      candidate_id: "candidate-1",
      artifact_id: "artifact-1",
      source_kind: "liveportrait",
      phase: "candidate",
      media: {
        duration_ms: 5000,
        width: 720,
        height: 1280,
        video_codec: "h264",
        has_audio: false,
      },
    }, { status: 201 }));

    const candidate = await persistLivePortraitCandidate({
      taskId: "task-1",
      avatarId: "shuchang",
      idempotencyKey: "candidate-save-1",
      fetcher,
    });

    expect(candidate.candidateId).toBe("candidate-1");
    expect(candidate.hasAudio).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/avatar-assets/candidates/provider",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      sourceKind: "liveportrait",
      taskId: "task-1",
      avatarId: "shuchang",
      idempotencyKey: "candidate-save-1",
      rightsConfirmed: true,
    });
  });

  it("accepts a reviewed candidate only with the complete quality checklist", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      avatar_action_id: "motion-1",
      avatar_id: "shuchang",
      candidate_id: "candidate-1",
      phase: "ready",
      source_master_artifact_id: "master-1",
      source_media: {
        duration_ms: 5000,
        width: 720,
        height: 1280,
        video_codec: "h264",
        has_audio: false,
      },
      renditions: [],
    }));
    const checks = {
      identity_match: true,
      single_person: true,
      closed_mouth: true,
      fixed_camera: true,
      no_gestures: true,
      rights_confirmed: true,
    } as const;

    const motionBase = await acceptMotionCandidate({
      candidateId: "candidate-1",
      idempotencyKey: "accept-1",
      checks,
      fetcher,
    });

    expect(motionBase.avatarActionId).toBe("motion-1");
    expect(motionBase.phase).toBe("ready");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/avatar-assets/candidates/candidate-1/accept",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      idempotencyKey: "accept-1",
      checks,
    });
  });

  it("approves a generated rendition with a bounded loop window", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      avatar_action_id: "motion-1",
      avatar_id: "shuchang",
      candidate_id: "candidate-1",
      phase: "ready",
      source_master_artifact_id: "master-1",
      source_media: { duration_ms: 5000, has_audio: false },
      renditions: [{
        rendition_id: "rendition-1",
        profile: "mobile_fullscreen",
        phase: "approved",
        artifact_id: "rendition-artifact-1",
        media: { duration_ms: 5000 },
      }],
    }));

    const motionBase = await approveMotionRendition({
      renditionId: "rendition-1",
      durationMs: 5000,
      fetcher,
    });

    expect(motionBase.phase).toBe("ready");
    expect(motionBase.renditions[0]?.phase).toBe("approved");
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      startMs: 0,
      endMs: 5000,
      crossfadeMs: 100,
    });
  });

  it("selects an accepted motion base only for its bound visual identity", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      avatar_id: "shuchang",
      avatar_action_id: "motion-1",
      revision: 3,
    }));

    const selection = await selectAvatarAction({
      avatarId: "shuchang",
      avatarActionId: "motion-1",
      fetcher,
    });

    expect(selection).toEqual({
      avatarId: "shuchang",
      avatarActionId: "motion-1",
      revision: 3,
    });
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
      avatarId: "shuchang",
      avatarActionId: "motion-1",
    });
  });
});
