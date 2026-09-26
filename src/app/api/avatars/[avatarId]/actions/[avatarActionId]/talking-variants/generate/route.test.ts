import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ authorized: vi.fn(), start: vi.fn(), signature: vi.fn() }));
vi.mock("@/lib/avatar-assets-server", () => ({
  authorizeAvatarAssetRequest: dependencies.authorized,
  validAvatarAssetId: () => true,
  jsonError: (error: string, status: number) => Response.json({ error }, { status }),
}));
vi.mock("@/lib/musetalk-talking-worker", () => ({ startTalkingJob: dependencies.start }));
vi.mock("@/lib/media-signatures", () => ({ hasMatchingAudioSignature: dependencies.signature }));

import { POST } from "./route";

const url = "http://localhost:3010/api/avatars/avatar-123/actions/action-123/talking-variants/generate";
const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "action-123" }) };

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.authorized.mockReturnValue(true);
  dependencies.signature.mockReturnValue(true);
  dependencies.start.mockResolvedValue({ id: "job-123", state: "queued" });
});

describe("MuseTalk generation submission", () => {
  it("keeps built-in audio by default", async () => {
    const response = await POST(new Request(url, { method: "POST" }), context);
    expect(response.status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith("avatar-123", "action-123", false, undefined);
  });

  it("passes uploaded audio to the worker", async () => {
    const form = new FormData();
    form.set("audio", new File([Uint8Array.from([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69])], "speech.wav", { type: "audio/wav" }));
    const response = await POST(new Request(url, { method: "POST", body: form }), context);
    expect(response.status).toBe(202);
    expect(dependencies.start).toHaveBeenCalledWith("avatar-123", "action-123", false, expect.any(Buffer));
  });
});
