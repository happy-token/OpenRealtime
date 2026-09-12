import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveAvatarArtifactPath } from "./avatar-evaluation-artifacts";
import { LIP_SYNC_COMPARISON } from "./lip-sync-comparison";

type ComparisonRun = {
  provider: string;
  avatar_source_video_sha256?: string;
  evidence_path?: string;
  raw_output: { sha256: string };
  preview_output: {
    artifact_id: string;
    path: string;
    sha256: string;
    duration_seconds: number;
    width: number;
    height: number;
    frame_rate: number;
  };
};

describe("pinned lip-sync comparison manifest", () => {
  it.runIf(process.env.RUN_LOCAL_MEDIA === "1")("binds both allowlisted previews to the same input evidence", () => {
    const campaignRoot = path.join(process.cwd(), "research-assets/avatar-evaluation/2026-08-22");
    const manifest = JSON.parse(fs.readFileSync(path.join(
      campaignRoot,
      "runs/lip-sync-comparison/lip-sync-comparison-001.json",
    ), "utf8")) as {
      motion_base: { sha256: string };
      fixed_audio: { sha256: string; duration_seconds: number };
      preview_normalization: { applied_to_both_runs: boolean };
      runs: ComparisonRun[];
    };
    const runs = Object.fromEntries(manifest.runs.map((run) => [run.provider, run]));
    const wav2lip = runs["wav2lip-96"];
    const dhLive = runs["dh-live-mini-v1"];

    expect(manifest.fixed_audio.duration_seconds).toBe(5);
    expect(manifest.preview_normalization.applied_to_both_runs).toBe(true);
    expect(LIP_SYNC_COMPARISON).toMatchObject({
      id: "lip-sync-comparison-001",
      motionBaseSha256: manifest.motion_base.sha256,
      audioSha256: manifest.fixed_audio.sha256,
      durationSeconds: 5,
      width: 720,
      height: 1280,
      frameRate: 25,
    });
    expect(dhLive.avatar_source_video_sha256).toBe(manifest.motion_base.sha256);
    for (const run of [wav2lip, dhLive]) {
      expect(run.preview_output).toMatchObject({
        duration_seconds: 5,
        width: 720,
        height: 1280,
        frame_rate: 25,
      });
      expect(resolveAvatarArtifactPath(run.preview_output.artifact_id, {
        projectRoot: process.cwd(),
        previewEnabled: true,
      })).toBe(path.join(campaignRoot, run.preview_output.path));
    }

    const dhEvidence = JSON.parse(fs.readFileSync(
      path.join(campaignRoot, dhLive.evidence_path!),
      "utf8",
    )) as {
      input: { sha256: string };
      avatar: { source_video: { sha256: string } };
      artifact: { sha256: string };
    };
    expect(dhEvidence.input.sha256).toBe(manifest.fixed_audio.sha256);
    expect(dhEvidence.avatar.source_video.sha256).toBe(manifest.motion_base.sha256);
    expect(dhEvidence.artifact.sha256).toBe(dhLive.raw_output.sha256);
    expect(LIP_SYNC_COMPARISON.artifacts.wav2lip).toBe(wav2lip.preview_output.artifact_id);
    expect(LIP_SYNC_COMPARISON.artifacts.dhLive).toBe(dhLive.preview_output.artifact_id);
  });
});
