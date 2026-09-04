import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function uploadRequest(origin = "http://127.0.0.1:3010") {
  const form = new FormData();
  const bytes = new Uint8Array([0, 0, 0, 12, 102, 116, 121, 112, 105, 115, 111, 109]);
  form.set("video", new File([bytes], "idle.mp4", { type: "video/mp4" }));
  form.set("avatarId", "shuchang");
  form.set("rightsConfirmed", "true");
  form.set("idempotencyKey", "upload-1");
  return new Request("http://127.0.0.1:3010/api/avatar-assets/candidates/upload", {
    method: "POST",
    headers: {
      origin,
      "sec-fetch-site": "same-origin",
      "content-length": "1024",
    },
    body: form,
  });
}

describe("Motion Base candidate upload route", () => {
  it("rejects local access unless the loopback launcher enabled it", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    expect((await POST(uploadRequest())).status).toBe(403);
  });

  it("forwards verified bytes only to the fixed loopback control plane", async () => {
    enableLocalTestMode();
    const fetcher = vi.fn<typeof fetch>();
    fetcher.mockResolvedValue(Response.json({ candidate_id: "candidate-1" }, { status: 201 }));
    vi.stubGlobal("fetch", fetcher);
    const response = await POST(uploadRequest());
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ candidate_id: "candidate-1" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [target, init] = fetcher.mock.calls[0];
    const url = new URL(String(target));
    expect(url.origin).toBe("http://127.0.0.1:8766");
    expect(url.pathname).toBe("/avatar-assets/candidates/upload");
    expect(url.searchParams.get("avatar_id")).toBe("shuchang");
    expect(init?.method).toBe("POST");
  });

  it("rejects cross-origin mutation requests", async () => {
    enableLocalTestMode();
    expect((await POST(uploadRequest("http://evil.example.com"))).status).toBe(403);
  });
});
