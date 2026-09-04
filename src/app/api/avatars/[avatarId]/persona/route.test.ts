import { afterEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  read: vi.fn(),
  writeFiles: vi.fn(),
  switchPersona: vi.fn(),
}));

vi.mock("@/lib/avatar-persona-server", () => ({
  readAvatarPersonaProfile: server.read,
  writeAvatarPersonaFiles: server.writeFiles,
  switchAvatarPersona: server.switchPersona,
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

function patchRequest(body: object) {
  return new Request("http://127.0.0.1:3010/api/avatars/avatar-zhaoning/persona", {
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

const context = { params: Promise.resolve({ avatarId: "avatar-zhaoning" }) };
const profile = {
  avatarId: "avatar-zhaoning",
  personaId: "intellectual-warmth",
  personaName: "知性温柔",
  avatarDisplayName: "昭宁",
  files: [{ filename: "SOUL.md", content: "更新" }],
  linkedAvatarIds: ["avatar-zhaoning"],
};

describe("Avatar Persona route GET", () => {
  it("returns the linked profile", async () => {
    enableLocalTestMode();
    server.read.mockResolvedValue(profile);

    const response = await GET(new Request("http://127.0.0.1:3010/api/avatars/avatar-zhaoning/persona", {
      headers: {
        host: "127.0.0.1:3010",
        origin: "http://127.0.0.1:3010",
        "sec-fetch-site": "same-origin",
      },
    }), context);

    expect(response.status).toBe(200);
  });
});

describe("Avatar Persona route PATCH", () => {
  it("rejects requests that are not same-origin", async () => {
    const response = await PATCH(new Request("http://127.0.0.1:3010/api/avatars/avatar-zhaoning/persona", {
      method: "PATCH",
      headers: { host: "127.0.0.1:3010", "content-type": "application/json" },
      body: JSON.stringify({ operation: "switchPersona", personaId: "sweet-sunshine" }),
    }), context);

    expect(response.status).toBe(403);
    expect(server.switchPersona).not.toHaveBeenCalled();
  });

  it("updates Persona files and returns the refreshed profile", async () => {
    enableLocalTestMode();
    server.read.mockResolvedValueOnce({ ...profile, files: [{ filename: "SOUL.md", content: "旧" }] });
    server.writeFiles.mockResolvedValue(undefined);
    server.read.mockResolvedValueOnce(profile);

    const response = await PATCH(patchRequest({
      operation: "updateFiles",
      files: [{ filename: "SOUL.md", content: "更新" }],
    }), context);

    expect(response.status).toBe(200);
    expect(server.writeFiles).toHaveBeenCalledWith("intellectual-warmth", [
      { filename: "SOUL.md", content: "更新" },
    ]);
    await expect(response.json()).resolves.toEqual({ profile });
  });

  it("rejects updateFiles when the Avatar has no linked Persona", async () => {
    enableLocalTestMode();
    server.read.mockResolvedValueOnce(null);

    const response = await PATCH(patchRequest({
      operation: "updateFiles",
      files: [{ filename: "SOUL.md", content: "更新" }],
    }), context);

    expect(response.status).toBe(404);
    expect(server.writeFiles).not.toHaveBeenCalled();
  });

  it("rejects a malformed files payload", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({ operation: "updateFiles", files: [] }), context);

    expect(response.status).toBe(400);
    expect(server.writeFiles).not.toHaveBeenCalled();
  });

  it("rejects an unknown persona filename", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({
      operation: "updateFiles",
      files: [{ filename: "USER.md", content: "x" }],
    }), context);

    expect(response.status).toBe(400);
    expect(server.writeFiles).not.toHaveBeenCalled();
  });

  it("switches the Avatar's Persona and returns the refreshed profile", async () => {
    enableLocalTestMode();
    server.switchPersona.mockResolvedValue(undefined);
    server.read.mockResolvedValue(profile);

    const response = await PATCH(patchRequest({
      operation: "switchPersona",
      personaId: "intellectual-warmth",
    }), context);

    expect(response.status).toBe(200);
    expect(server.switchPersona).toHaveBeenCalledWith("avatar-zhaoning", "intellectual-warmth", undefined);
  });

  it("passes an avatarDisplayName through when linking a previously-unlinked Avatar", async () => {
    enableLocalTestMode();
    server.switchPersona.mockResolvedValue(undefined);
    server.read.mockResolvedValue(profile);

    const response = await PATCH(patchRequest({
      operation: "switchPersona",
      personaId: "intellectual-warmth",
      avatarDisplayName: "昭宁",
    }), context);

    expect(response.status).toBe(200);
    expect(server.switchPersona).toHaveBeenCalledWith("avatar-zhaoning", "intellectual-warmth", "昭宁");
  });

  it("rejects an invalid operation", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({ operation: "bogus" }), context);

    expect(response.status).toBe(400);
  });

  it("rejects oversized PATCH bodies before parsing JSON", async () => {
    enableLocalTestMode();
    const request = patchRequest({ operation: "switchPersona", personaId: "sweet-sunshine" });
    request.headers.set("content-length", "64001");

    const response = await PATCH(request, context);

    expect(response.status).toBe(413);
    expect(server.switchPersona).not.toHaveBeenCalled();
  });

  it("maps an underlying validation error to 400", async () => {
    enableLocalTestMode();
    server.switchPersona.mockRejectedValue(new Error("Persona ID 无效"));

    const response = await PATCH(patchRequest({
      operation: "switchPersona",
      personaId: "sweet-sunshine",
    }), context);

    expect(response.status).toBe(400);
  });
});
