import { afterEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  readPersonaProfile: vi.fn(),
  writeAvatarPersonaFiles: vi.fn(),
}));

vi.mock("@/lib/avatar-persona-server", () => ({
  readPersonaProfile: server.readPersonaProfile,
  writeAvatarPersonaFiles: server.writeAvatarPersonaFiles,
}));

import { GET, PATCH } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function getRequest() {
  return new Request("http://127.0.0.1:3010/api/personas/intellectual-warmth", {
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

function patchRequest(body: object) {
  return new Request("http://127.0.0.1:3010/api/personas/intellectual-warmth", {
    method: "PATCH",
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

const context = { params: Promise.resolve({ personaId: "intellectual-warmth" }) };
const profile = {
  personaId: "intellectual-warmth",
  personaName: "知性温柔",
  files: [{ filename: "SOUL.md", content: "更新" }],
  linkedAvatarIds: ["avatar-zhaoning"],
};

describe("Persona detail route GET", () => {
  it("returns the Persona profile", async () => {
    enableLocalTestMode();
    server.readPersonaProfile.mockResolvedValue(profile);

    const response = await GET(getRequest(), context);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ profile });
  });

  it("returns 404 when the Persona does not exist", async () => {
    enableLocalTestMode();
    server.readPersonaProfile.mockResolvedValue(null);

    const response = await GET(getRequest(), context);

    expect(response.status).toBe(404);
  });

  it("rejects unauthorized requests", async () => {
    const response = await GET(getRequest(), context);

    expect(response.status).toBe(403);
    expect(server.readPersonaProfile).not.toHaveBeenCalled();
  });
});

describe("Persona detail route PATCH", () => {
  it("updates Persona files and returns the refreshed profile", async () => {
    enableLocalTestMode();
    server.writeAvatarPersonaFiles.mockResolvedValue(undefined);
    server.readPersonaProfile.mockResolvedValue(profile);

    const response = await PATCH(patchRequest({
      operation: "updateFiles",
      files: [{ filename: "SOUL.md", content: "更新" }],
    }), context);

    expect(response.status).toBe(200);
    expect(server.writeAvatarPersonaFiles).toHaveBeenCalledWith("intellectual-warmth", [
      { filename: "SOUL.md", content: "更新" },
    ]);
    await expect(response.json()).resolves.toEqual({ profile });
  });

  it("rejects a malformed files payload", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({ operation: "updateFiles", files: [] }), context);

    expect(response.status).toBe(400);
    expect(server.writeAvatarPersonaFiles).not.toHaveBeenCalled();
  });

  it("rejects an invalid operation", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({ operation: "bogus" }), context);

    expect(response.status).toBe(400);
  });

  it("rejects requests that are not same-origin", async () => {
    const response = await PATCH(new Request("http://127.0.0.1:3010/api/personas/intellectual-warmth", {
      method: "PATCH",
      headers: { host: "127.0.0.1:3010", "content-type": "application/json" },
      body: JSON.stringify({ operation: "updateFiles", files: [] }),
    }), context);

    expect(response.status).toBe(403);
    expect(server.writeAvatarPersonaFiles).not.toHaveBeenCalled();
  });
});
