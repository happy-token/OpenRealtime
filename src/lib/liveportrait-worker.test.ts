import { lstat, mkdir, mkdtemp, rm, symlink, utimes } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { createLivePortraitMotionConfig } from "./liveportrait-motion-config";
import {
  buildLivePortraitDrivingInspectionInvocation,
  buildLivePortraitRenderInvocation,
  isPathInside,
  livePortraitTaskMatchesInput,
  parseLivePortraitDrivingInspectionResult,
  parseLivePortraitRenderResult,
  reconcileLivePortraitTaskRoot,
  resolveLivePortraitTemplate,
} from "./liveportrait-worker";

describe("LivePortrait worker contract", () => {
  it("builds a closed-mouth inspection command for uploaded driving media", () => {
    expect(buildLivePortraitDrivingInspectionInvocation({
      drivingPath: "/tmp/task/driving.mp4",
      projectRoot: "/workspace",
      runtimeRoot: "/runtime/liveportrait",
      wrapperPython: "/usr/bin/python3",
    })).toEqual({
      command: "/usr/bin/python3",
      args: [
        "/workspace/scripts/liveportrait_provider.py",
        "inspect-driving",
        "/tmp/task/driving.mp4",
        "--runtime-root",
        "/runtime/liveportrait",
      ],
      cwd: "/workspace",
    });
  });

  it("maps each user-facing action to an installed LivePortrait driving asset", () => {
    expect(resolveLivePortraitTemplate("sweet-vitality", "/workspace", "/runtime/liveportrait")).toContain("sweet-vitality.mp4");
    expect(resolveLivePortraitTemplate("melancholy-empathy", "/workspace", "/runtime/liveportrait")).toContain("melancholy-empathy.mp4");
    expect(resolveLivePortraitTemplate("idle", "/workspace", "/runtime/liveportrait")).toBeNull();
    expect(resolveLivePortraitTemplate("unknown", "/workspace", "/runtime/liveportrait")).toBeNull();
  });

  it("builds an argument-array invocation with rights and timeout guards", () => {
    const invocation = buildLivePortraitRenderInvocation({
      sourcePath: "/tmp/task/source.jpg",
      drivingPath: "/tmp/task/driving.mp4",
      outputDir: "/tmp/task/output",
      projectRoot: "/workspace",
      runtimeRoot: "/runtime/liveportrait",
      wrapperPython: "/usr/bin/python3",
    });
    expect(invocation.command).toBe("/usr/bin/python3");
    expect(invocation.cwd).toBe("/workspace");
    expect(invocation.args).toEqual([
      path.join("/workspace", "scripts/liveportrait_provider.py"),
      "render",
      "/tmp/task/source.jpg",
      "/tmp/task/driving.mp4",
      "/tmp/task/output",
      "--runtime-root",
      "/runtime/liveportrait",
      "--rights-confirmed",
      "--timeout-seconds",
      "900",
    ]);
  });

  it("passes the native LivePortrait motion snapshot to the isolated renderer", () => {
    const invocation = buildLivePortraitRenderInvocation({
      sourcePath: "/tmp/task/source.jpg",
      drivingPath: "/tmp/task/driving.mp4",
      outputDir: "/tmp/task/output",
      configPath: "/tmp/task/liveportrait-motion-config.json",
      projectRoot: "/workspace",
      runtimeRoot: "/runtime/liveportrait",
      wrapperPython: "/usr/bin/python3",
    });
    expect(invocation.args).toContain("--config-json");
    expect(invocation.args).toContain("/tmp/task/liveportrait-motion-config.json");
  });

  it("parses the final JSON after carriage-return progress output", () => {
    expect(parseLivePortraitRenderResult(
      "Rendering 50%\rRendering 100%\r{\"device\":\"mps\",\"output\":\"/tmp/result.mp4\",\"render_seconds\":12.5}\n",
    )).toEqual({
      device: "mps",
      output: "/tmp/result.mp4",
      render_seconds: 12.5,
    });
  });

  it("parses a server-authoritative driving rejection", () => {
    expect(parseLivePortraitDrivingInspectionResult(JSON.stringify({
      eligible: false,
      reason: "自定义参考视频需为 5–15 秒",
      duration_seconds: 4.2,
      sample_count: 0,
      median_ratio: 0,
      maximum_ratio: 0,
    }))).toEqual({
      eligible: false,
      reason: "自定义参考视频需为 5–15 秒",
      durationSeconds: 4.2,
      sampleCount: 0,
      medianRatio: 0,
      maximumRatio: 0,
    });
  });

  it("only permits cleanup targets strictly below the task root", () => {
    expect(isPathInside("/tmp/tasks", "/tmp/tasks/one")).toBe(true);
    expect(isPathInside("/tmp/tasks", "/tmp/tasks")).toBe(false);
    expect(isPathInside("/tmp/tasks", "/tmp/tasks-escaped/one")).toBe(false);
    expect(isPathInside("/tmp/tasks", "/tmp/other")).toBe(false);
  });

  it("binds a worker task to the identity, source digest, and selected action", () => {
    const sourceBytes = Uint8Array.from([1, 2, 3]);
    const livePortraitConfig = createLivePortraitMotionConfig();
    const task = {
      visualIdentityId: "shuchang",
      sourceSha256: "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81",
      driverId: "sweet-vitality",
      livePortraitConfig,
    };
    const input = { visualIdentityId: "shuchang", sourceBytes, driverId: "sweet-vitality", livePortraitConfig };
    expect(livePortraitTaskMatchesInput(task, input)).toBe(true);
    expect(livePortraitTaskMatchesInput(task, { ...input, visualIdentityId: "other" })).toBe(false);
    expect(livePortraitTaskMatchesInput(task, { ...input, sourceBytes: Uint8Array.from([3, 2, 1]) })).toBe(false);
    expect(livePortraitTaskMatchesInput(task, { ...input, driverId: "blink" })).toBe(false);
    expect(livePortraitTaskMatchesInput(task, {
      ...input,
      livePortraitConfig: { ...livePortraitConfig, driving_multiplier: 0.8 },
    })).toBe(false);
  });

  it("reclaims only expired UUID directories and skips symbolic links", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-lp-reconcile-"));
    const expiredId = "11111111-1111-4111-8111-111111111111";
    const linkedId = "22222222-2222-4222-8222-222222222222";
    const expiredDir = path.join(root, expiredId);
    const unrelatedDir = path.join(root, "keep-me");
    const outsideDir = await mkdtemp(path.join(os.tmpdir(), "openrealtime-lp-outside-"));
    try {
      await mkdir(expiredDir, { mode: 0o700 });
      await mkdir(unrelatedDir, { mode: 0o700 });
      await symlink(outsideDir, path.join(root, linkedId));
      const old = new Date(Date.now() - 8 * 24 * 60 * 60 * 1_000);
      await utimes(expiredDir, old, old);
      await reconcileLivePortraitTaskRoot(root);
      await expect(lstat(expiredDir)).rejects.toMatchObject({ code: "ENOENT" });
      await expect(lstat(unrelatedDir)).resolves.toBeDefined();
      await expect(lstat(path.join(root, linkedId))).resolves.toMatchObject({});
      await expect(lstat(outsideDir)).resolves.toBeDefined();
    } finally {
      await rm(root, { recursive: true, force: true });
      await rm(outsideDir, { recursive: true, force: true });
    }
  });
});
