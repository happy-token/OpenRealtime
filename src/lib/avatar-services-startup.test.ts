import { execFileSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

function readStartupPlan(overrides: Record<string, string | undefined> = {}) {
  const environment = { ...process.env, ...overrides };
  delete environment.OPENREALTIME_START_AVATAR_SERVICES;
  delete environment.OPENREALTIME_AVATAR_RENDERER_MODE;
  delete environment.OPENREALTIME_AVATAR_RENDERER_URL;
  for (const [name, value] of Object.entries(overrides)) {
    if (value !== undefined) environment[name] = value;
  }
  const output = execFileSync("bash", [
    path.join(process.cwd(), "scripts/avatar_services.sh"),
    "plan",
  ], {
    cwd: process.cwd(),
    encoding: "utf8",
    env: environment,
  });
  return JSON.parse(output) as unknown;
}

describe("avatar service startup", () => {
  it("prewarms the realtime digital-human renderer by default", () => {
    expect(readStartupPlan()).toEqual({
      enabled: true,
      mode: "managed",
      services: [{
        id: "avatar-renderer",
        adapter: "livetalking-wav2lip256",
        endpoint: "http://127.0.0.1:8010",
        avatar_id: "shuchang256",
        inference_stride: 2,
      }],
    });
  });

  it("allows avatar sidecars to be skipped during application startup", () => {
    expect(readStartupPlan({ OPENREALTIME_START_AVATAR_SERVICES: "false" })).toEqual({
      enabled: false,
      mode: "disabled",
      services: [],
    });
  });

  it("connects to an external Linux renderer without managing its process", () => {
    expect(readStartupPlan({
      OPENREALTIME_AVATAR_RENDERER_MODE: "external",
      OPENREALTIME_AVATAR_RENDERER_URL: "http://avatar-renderer.internal:8010",
    })).toEqual({
      enabled: true,
      mode: "external",
      services: [{
        id: "avatar-renderer",
        adapter: "livetalking-wav2lip256",
        endpoint: "http://avatar-renderer.internal:8010",
        avatar_id: "shuchang256",
        inference_stride: 2,
      }],
    });
  });

  it("exposes frame-strided Wav2Lip inference as an explicit setting", () => {
    expect(readStartupPlan({ OPENREALTIME_WAV2LIP_INFERENCE_STRIDE: "2" })).toMatchObject({
      services: [{ inference_stride: 2 }],
    });
  });
});
