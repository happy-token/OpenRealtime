import { describe, expect, it } from "vitest";
import { extractKnowledgeFile, extractKnowledgeUrl } from "./knowledge-import";

describe("knowledge import", () => {
  it("extracts local text and rejects unsupported or oversized files", async () => {
    expect(await extractKnowledgeFile("notes.md", Buffer.from("# 标题\n内容"))).toBe("# 标题\n内容");
    await expect(extractKnowledgeFile("test.exe", Buffer.from("hello"))).rejects.toThrow("仅支持");
    await expect(extractKnowledgeFile("notes.txt", Buffer.alloc(5_000_001))).rejects.toThrow("5 MB");
  });

  it("rejects local and non-HTTPS URLs before a network request", async () => {
    await expect(extractKnowledgeUrl("http://example.com" )).rejects.toThrow("HTTPS");
    await expect(extractKnowledgeUrl("https://127.0.0.1/private")).rejects.toThrow("公开 HTTPS");
    await expect(extractKnowledgeUrl("https://localhost/private")).rejects.toThrow("公开 HTTPS");
  });
});
