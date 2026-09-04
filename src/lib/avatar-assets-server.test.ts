import { describe, expect, it } from "vitest";
import { avatarAssetJsonResponse } from "./avatar-assets-server";

describe("avatarAssetJsonResponse", () => {
  it("does not relay an upstream HTML error page as JSON", async () => {
    const upstream = new Response("<!DOCTYPE html><h1>Not Found</h1>", {
      status: 404,
      headers: { "Content-Type": "text/html" },
    });

    const response = avatarAssetJsonResponse(upstream, await upstream.text());

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({
      error: "动作资产服务连接异常（HTTP 404）",
    });
  });

  it("keeps a valid upstream JSON response", async () => {
    const upstream = Response.json({ candidate_id: "candidate-1" }, { status: 201 });

    const response = avatarAssetJsonResponse(upstream, await upstream.text());

    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ candidate_id: "candidate-1" });
  });
});
