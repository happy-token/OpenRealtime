import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createTool, listTools, setToolEnabled, setToolPublicEnabled, updateTool } from "./tool-catalog-repository";

const roots: string[] = [];

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function temporaryRoot() {
  const root = await mkdtemp(path.join(os.tmpdir(), "openrealtime-tools-"));
  roots.push(root);
  return root;
}

describe("tool catalog repository", () => {
  it("always exposes the runtime built-in tools", async () => {
    const tools = await listTools(await temporaryRoot());
    expect(tools.map((tool) => tool.tool_id)).toEqual(["tool-current-time", "tool-web-search"]);
    expect(tools.every((tool) => tool.builtin && tool.enabled)).toBe(true);
  });

  it("persists and disables a custom API tool", async () => {
    const root = await temporaryRoot();
    const created = await createTool({
      displayName: "查询天气",
      description: "查询城市天气",
      kind: "api",
      functionName: "get_weather",
      inputSchema: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
      endpoint: "https://api.example.com/weather",
      method: "GET",
    }, root);
    expect(created).toMatchObject({ kind: "api", enabled: true, method: "GET" });

    const disabled = await setToolEnabled(created.tool_id, false, root);
    expect(disabled.enabled).toBe(false);
    expect((await listTools(root)).find((tool) => tool.tool_id === created.tool_id)?.enabled).toBe(false);
  });

  it("rejects unsafe schemas and API protocols", async () => {
    const root = await temporaryRoot();
    await expect(createTool({
      displayName: "脚本",
      description: "错误示例",
      kind: "api",
      functionName: "run_script",
      inputSchema: { type: "array" },
      endpoint: "file:///tmp/action",
    }, root)).rejects.toThrow(/Schema/);
  });

  it("requires an executable endpoint and rejects duplicate callable names", async () => {
    const root = await temporaryRoot();
    const input = { displayName: "订单", description: "查询订单", kind: "function" as const, functionName: "get_order_status", inputSchema: { type: "object", properties: {} } };
    await expect(createTool(input, root)).rejects.toThrow("执行服务地址");
    await createTool({ ...input, endpoint: "https://api.example.com/order" }, root);
    await expect(createTool({ ...input, endpoint: "https://api.example.com/order" }, root)).rejects.toThrow("已存在");
    await expect(createTool({ ...input, functionName: "search_web", endpoint: "https://api.example.com/order" }, root)).rejects.toThrow("已存在");
  });

  it("updates an existing tool endpoint without changing its identity or binding ID", async () => {
    const root = await temporaryRoot();
    const input = { displayName: "订单", description: "查询订单", kind: "function" as const, functionName: "get_order_status", inputSchema: { type: "object", properties: {} }, endpoint: "https://api.example.com/old" };
    const original = await createTool(input, root);
    const updated = await updateTool(original.tool_id, { ...input, endpoint: "https://api.example.com/new" }, root);
    expect(updated).toMatchObject({ tool_id: original.tool_id, endpoint: "https://api.example.com/new" });
    expect((await listTools(root)).find(tool => tool.tool_id === original.tool_id)?.endpoint).toBe("https://api.example.com/new");
  });

  it("keeps custom tools private until an administrator explicitly exposes them", async () => {
    const root = await temporaryRoot();
    const created = await createTool({ displayName: "天气", description: "查询天气", kind: "api", functionName: "get_weather", inputSchema: { type: "object", properties: {} }, endpoint: "https://api.example.com/weather" }, root);
    expect(created.public_enabled).toBe(false);
    expect((await setToolPublicEnabled(created.tool_id, true, root)).public_enabled).toBe(true);
    expect((await listTools(root)).find(tool => tool.tool_id === created.tool_id)?.public_enabled).toBe(true);
  });
});
