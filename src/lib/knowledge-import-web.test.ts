import { EventEmitter } from "node:events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { extractKnowledgeUrl } from "./knowledge-import";

const mocks = vi.hoisted(() => ({ resolve4: vi.fn(), request: vi.fn() }));
vi.mock("node:dns/promises", () => ({ resolve4: mocks.resolve4 }));
vi.mock("node:https", () => ({ default: { request: mocks.request } }));

type Reply = { status?: number; type?: string; location?: string; body: string | Buffer };
function respond(...replies: Reply[]) {
  mocks.request.mockImplementation((_url, _options, callback) => {
    const reply = replies.shift();
    if (!reply) throw new Error("Unexpected network request");
    const request = new EventEmitter() as EventEmitter & { end(): void; destroy(error: Error): void };
    request.end = () => queueMicrotask(() => {
      const response = Object.assign(new EventEmitter(), { statusCode: reply.status ?? 200,
        headers: { "content-type": reply.type ?? "text/html; charset=utf-8", location: reply.location }, resume: vi.fn() });
      callback(response);
      response.emit("data", Buffer.isBuffer(reply.body) ? reply.body : Buffer.from(reply.body));
      response.emit("end");
    });
    request.destroy = (error) => request.emit("error", error);
    return request;
  });
}

beforeEach(() => { vi.clearAllMocks(); vi.stubEnv("KNOWLEDGE_WEB_DNS", "system"); mocks.resolve4.mockResolvedValue(["93.184.216.34"]); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("public webpage extraction", () => {
  it("uses opt-in DoH and still refuses private addresses from its response", async () => {
    vi.stubEnv("KNOWLEDGE_WEB_DNS", "cloudflare-doh");
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ Status: 0, Answer: [{ type: 1, data: "93.184.216.34" }] }));
    vi.stubGlobal("fetch", fetchMock);
    respond({ body: "<p>verified body</p>" });
    expect((await extractKnowledgeUrl("https://example.com/guide")).content).toBe("verified body");
    expect(mocks.resolve4).not.toHaveBeenCalled();
    expect(String(fetchMock.mock.calls[0][0])).toContain("https://cloudflare-dns.com/dns-query?");
    fetchMock.mockResolvedValue(Response.json({ Status: 0, Answer: [{ type: 1, data: "127.0.0.1" }] }));
    await expect(extractKnowledgeUrl("https://example.com/secret")).rejects.toThrow("非公开");
  });
  it("extracts Chinese HTML, entities and title while removing scripts and comments", async () => {
    respond({ body: "<html><title>售后 &amp; 服务</title><script>secret script</script><!-- secret comment --><style>secret css</style><p>退货期限 &#x4E03; 天 &lt;规则&gt;</p></html>" });
    const page = await extractKnowledgeUrl("https://example.com/guide");
    expect(page.title).toBe("售后 & 服务");
    expect(page.content).toContain("退货期限 七 天 <规则>");
    expect(page.content).not.toContain("secret");
  });

  it("reads plain text and declared non-UTF8 webpage encoding", async () => {
    respond({ type: "text/plain; charset=utf-8", body: "中文正文" });
    expect((await extractKnowledgeUrl("https://example.com/notes")).content).toBe("中文正文");
    respond({ type: "text/plain; charset=gb18030", body: Buffer.from([0xd6, 0xd0, 0xce, 0xc4]) });
    expect((await extractKnowledgeUrl("https://example.com/chinese")).content).toBe("中文");
  });

  it("follows a public redirect and checks each new host", async () => {
    respond({ status: 302, location: "https://public.example/next", body: "" }, { body: "<p>new content</p>" });
    expect((await extractKnowledgeUrl("https://example.com/start")).sourceUrl).toBe("https://public.example/next");
    expect(mocks.resolve4.mock.calls.map((args) => args[0])).toEqual(["example.com", "public.example"]);
    const lookup = mocks.request.mock.calls[0][1].lookup;
    const single = vi.fn(); lookup("example.com", {}, single);
    expect(single).toHaveBeenCalledWith(null, "93.184.216.34", 4);
    const all = vi.fn(); lookup("example.com", { all: true }, all);
    expect(all).toHaveBeenCalledWith(null, [{ address: "93.184.216.34", family: 4 }]);
  });

  it("blocks redirects to local addresses and mixed private DNS answers", async () => {
    respond({ status: 302, location: "https://127.0.0.1/private", body: "" });
    await expect(extractKnowledgeUrl("https://example.com/start")).rejects.toThrow("公开 HTTPS");
    expect(mocks.request).toHaveBeenCalledTimes(1);
    mocks.resolve4.mockResolvedValue(["93.184.216.34", "10.0.0.1"]);
    await expect(extractKnowledgeUrl("https://example.com/secret")).rejects.toThrow("非公开");
  });

  it("rejects oversized, empty and non-text responses", async () => {
    respond({ body: "x".repeat(200_001) });
    await expect(extractKnowledgeUrl("https://example.com/big")).rejects.toThrow("内容过大");
    respond({ body: "<script>nothing</script>" });
    await expect(extractKnowledgeUrl("https://example.com/empty")).rejects.toThrow("没有可提取");
    respond({ type: "application/pdf", body: "%PDF" });
    await expect(extractKnowledgeUrl("https://example.com/pdf")).rejects.toThrow("不是文本");
  });
});
