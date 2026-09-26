import { beforeEach, describe, expect, it, vi } from "vitest";

const dependencies = vi.hoisted(() => ({ authorized: vi.fn(), start: vi.fn(), builtInAudio: vi.fn() }));
vi.mock("@/lib/avatar-assets-server", () => ({
  authorizeAvatarAssetRequest: dependencies.authorized,
  validAvatarAssetId: () => true,
  jsonError: (error: string, status: number) => Response.json({ error }, { status }),
}));
vi.mock("@/lib/wav2lip-talking-worker", () => ({ MAX_REQUEST_BYTES: 21 * 1024 * 1024, startWav2LipJob: dependencies.start }));
vi.mock("@/lib/talking-reference-audio", () => ({ readBuiltInTalkingAudio: dependencies.builtInAudio }));

import { POST } from "./route";

const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "action-123" }) };

beforeEach(() => {
  vi.clearAllMocks();
  dependencies.authorized.mockReturnValue(true);
  dependencies.builtInAudio.mockResolvedValue(Buffer.from("RIFF0000WAVEtest"));
  dependencies.start.mockResolvedValue({ id: "job-123", state: "queued" });
});

describe("Wav2Lip generation submission", () => {
  it("passes built-in audio to the worker when requested", async () => {
    const form = new FormData();
    form.set("audioSource", "builtin");
    form.set("rightsConfirmed", "true");
    form.set("usageScope", "internal_evaluation");
    const response = await POST(new Request("http://localhost:3010/api/avatars/avatar-123/actions/action-123/talking-variants/generate-wav2lip", { method: "POST", body: form, headers: { "content-length": "1000" } }), context);
    expect(response.status).toBe(202);
    const input = dependencies.start.mock.calls[0][0];
    expect(input.audio.name).toBe("reference.wav");
    expect(input.audio.type).toBe("audio/wav");
    expect(input.rightsConfirmed).toBe(true);
  });
});
