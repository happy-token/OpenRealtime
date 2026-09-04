import { describe, expect, it } from "vitest";
import { readJsonResponse } from "./http-json-response";

describe("readJsonResponse", () => {
  it("turns an HTML error response into a readable HTTP failure", async () => {
    const response = new Response("<pre>missing route module</pre>", {
      status: 404,
      headers: { "Content-Type": "text/html" },
    });

    await expect(readJsonResponse(response, "数字人服务请求失败"))
      .rejects.toThrow("数字人服务请求失败（HTTP 404）");
  });

  it("keeps a structured API error payload available to the caller", async () => {
    const response = Response.json({ error: "数字人尚未准备完成" }, { status: 503 });

    await expect(readJsonResponse<{ error?: string }>(response, "数字人服务请求失败"))
      .resolves.toEqual({ error: "数字人尚未准备完成" });
  });

  it("rejects a non-JSON success response without exposing parser internals", async () => {
    const response = new Response("service warming up", { status: 200 });

    await expect(readJsonResponse(response, "数字人服务请求失败"))
      .rejects.toThrow("数字人服务返回了无法识别的响应");
  });
});
