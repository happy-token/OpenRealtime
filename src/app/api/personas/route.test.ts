import { afterEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  listPersonas: vi.fn(),
  createPersona: vi.fn(),
  readPersonaProfile: vi.fn(),
  switchAvatarPersona: vi.fn(),
  writePersonaIntro: vi.fn(),
  normalizePersonaIntro: vi.fn((value: string) => value.trim()),
}));

vi.mock("@/lib/avatar-persona-server", () => ({
  listPersonas: server.listPersonas,
  createPersona: server.createPersona,
  readPersonaProfile: server.readPersonaProfile,
  switchAvatarPersona: server.switchAvatarPersona,
  writePersonaIntro: server.writePersonaIntro,
  normalizePersonaIntro: server.normalizePersonaIntro,
}));

import { GET, POST } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function personasRequest() {
  return new Request("http://127.0.0.1:3010/api/personas", {
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

describe("Personas list route", () => {
  it("returns the Persona summary list", async () => {
    enableLocalTestMode();
    server.listPersonas.mockResolvedValue([
      { personaId: "intellectual-warmth", personaName: "知性温柔" },
    ]);

    const response = await GET(personasRequest());

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      personas: [{ personaId: "intellectual-warmth", personaName: "知性温柔" }],
    });
  });

  it("rejects unauthorized requests", async () => {
    const response = await GET(personasRequest());

    expect(response.status).toBe(403);
    expect(server.listPersonas).not.toHaveBeenCalled();
  });

  it("maps a validation error to a 400 response", async () => {
    enableLocalTestMode();
    server.listPersonas.mockRejectedValue(new Error("Persona 目录无效"));

    const response = await GET(personasRequest());

    expect(response.status).toBe(400);
  });
});

function postRequest(body: object) {
  return new Request("http://127.0.0.1:3010/api/personas", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

describe("Personas create route", () => {
  it("creates a Persona with separate card intro", async () => {
    enableLocalTestMode();
    server.readPersonaProfile.mockResolvedValue({ personaId: "brand-new", personaName: "全新人格", intro: "清醒温柔的伙伴。", files: [], linkedAvatarIds: [] });

    const response = await POST(postRequest({ personaId: "brand-new", intro: " 清醒温柔的伙伴。 ", files: [
      { filename: "IDENTITY.md", content: "# 全新人格" },
      { filename: "SOUL.md", content: "性格" },
    ] }));

    expect(response.status).toBe(200);
    expect(server.writePersonaIntro).toHaveBeenCalledWith("brand-new", "清醒温柔的伙伴。");
  });
  it("creates a Persona without linking an Avatar", async () => {
    enableLocalTestMode();
    server.createPersona.mockResolvedValue(undefined);
    server.readPersonaProfile.mockResolvedValue({
      personaId: "brand-new",
      personaName: "全新人格",
      files: [{ filename: "SOUL.md", content: "性格" }],
      linkedAvatarIds: [],
    });

    const response = await POST(postRequest({
      personaId: "brand-new",
      files: [
        { filename: "IDENTITY.md", content: "# 全新人格\n\n身份定义" },
        { filename: "SOUL.md", content: "性格" },
      ],
    }));

    expect(response.status).toBe(200);
    expect(server.createPersona).toHaveBeenCalledWith("brand-new", [
      { filename: "IDENTITY.md", content: "# 全新人格\n\n身份定义" },
      { filename: "SOUL.md", content: "性格" },
    ]);
    expect(server.switchAvatarPersona).not.toHaveBeenCalled();
  });

  it("creates a Persona and links it to an Avatar when avatarId is present", async () => {
    enableLocalTestMode();
    server.createPersona.mockResolvedValue(undefined);
    server.switchAvatarPersona.mockResolvedValue(undefined);
    server.readPersonaProfile.mockResolvedValue({
      personaId: "brand-new",
      personaName: "全新人格",
      files: [{ filename: "SOUL.md", content: "性格" }],
      linkedAvatarIds: ["avatar-unknown"],
    });

    const response = await POST(postRequest({
      personaId: "brand-new",
      files: [
        { filename: "IDENTITY.md", content: "# 全新人格\n\n身份定义" },
        { filename: "SOUL.md", content: "性格" },
      ],
      avatarId: "avatar-unknown",
      avatarDisplayName: "新人",
    }));

    expect(response.status).toBe(200);
    expect(server.switchAvatarPersona).toHaveBeenCalledWith("avatar-unknown", "brand-new", "新人");
  });

  it("rejects unauthorized create requests", async () => {
    const response = await POST(postRequest({ personaId: "brand-new", files: [] }));

    expect(response.status).toBe(403);
    expect(server.createPersona).not.toHaveBeenCalled();
  });

  it("maps a duplicate Persona ID error to 409", async () => {
    enableLocalTestMode();
    server.createPersona.mockRejectedValue(new Error("Persona 已存在"));

    const response = await POST(postRequest({
      personaId: "intellectual-warmth",
      files: [{ filename: "SOUL.md", content: "性格" }],
    }));

    expect(response.status).toBe(409);
  });

  it("rejects a malformed files payload", async () => {
    enableLocalTestMode();

    const response = await POST(postRequest({ personaId: "brand-new", files: [] }));

    expect(response.status).toBe(400);
    expect(server.createPersona).not.toHaveBeenCalled();
  });
});
