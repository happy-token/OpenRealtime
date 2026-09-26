import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { listPersonalMotions, personalMotionId, readPersonalMotionVideo, savePersonalMotion } from "./personal-motion-library";

let temporary = "";
const originalPath = process.env.OPENREALTIME_PERSONAL_MOTION_PATH;

afterEach(async () => {
  if (originalPath === undefined) delete process.env.OPENREALTIME_PERSONAL_MOTION_PATH;
  else process.env.OPENREALTIME_PERSONAL_MOTION_PATH = originalPath;
  if (temporary) await rm(temporary, { recursive: true, force: true });
  temporary = "";
});

describe("personal motion library", () => {
  it("saves once and isolates assets by authenticated owner", async () => {
    temporary = await mkdtemp(path.join(os.tmpdir(), "personal-motion-"));
    process.env.OPENREALTIME_PERSONAL_MOTION_PATH = temporary;
    const alice = { issuer: "issuer", subject: "alice" };
    const bob = { issuer: "issuer", subject: "bob" };
    const bytes = new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112]);
    const asset = await savePersonalMotion(alice, "task-123456", "Turn gently", 4, bytes);
    expect(asset.id).toBe(personalMotionId("task-123456"));
    expect(await savePersonalMotion(alice, "task-123456", "Changed prompt", 5, bytes)).toEqual(asset);
    expect(await listPersonalMotions(alice)).toEqual([asset]);
    expect(await listPersonalMotions(bob)).toEqual([]);
    expect(await readPersonalMotionVideo(alice, asset.id)).toEqual(Buffer.from(bytes));
    expect(await readPersonalMotionVideo(bob, asset.id)).toBeNull();
    expect(await readPersonalMotionVideo(alice, "../escape")).toBeNull();
  });
});
