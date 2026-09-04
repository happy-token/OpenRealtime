import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { DELETE, PATCH, POST } from "./route";

describe("voice clone route", () => {
  it("rejects cross-origin enrollment before reading an audio body", async () => {
    const response = await POST(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "POST",
      headers: { origin: "https://attacker.example" },
    }));

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ error: "不允许从当前来源创建克隆音色" });
  });

  it("requires a bounded multipart body", async () => {
    const response = await POST(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "POST",
      headers: { origin: "http://localhost:3010" },
    }));

    expect(response.status).toBe(411);
  });

  it("rejects cross-origin rename and delete management", async () => {
    const headers = { origin: "https://attacker.example", "content-length": "64" };
    const rename = await PATCH(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "PATCH",
      headers,
      body: JSON.stringify({ voiceId: "cosyvoice-v3-flash-openrt-123", displayName: "New name" }),
    }));
    const deletion = await DELETE(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "DELETE",
      headers,
      body: JSON.stringify({ voiceId: "cosyvoice-v3-flash-openrt-123" }),
    }));

    expect(rename.status).toBe(403);
    expect(deletion.status).toBe(403);
  });

  it("rejects invalid voice IDs before provider management", async () => {
    const headers = { origin: "http://localhost:3010", "content-length": "64" };
    const rename = await PATCH(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "PATCH",
      headers,
      body: JSON.stringify({ voiceId: "../../catalog.json", displayName: "New name" }),
    }));
    const deletion = await DELETE(new NextRequest("http://localhost:3010/api/voice-clones", {
      method: "DELETE",
      headers,
      body: JSON.stringify({ voiceId: "../../catalog.json" }),
    }));

    expect(rename.status).toBe(400);
    expect(deletion.status).toBe(400);
  });
});
