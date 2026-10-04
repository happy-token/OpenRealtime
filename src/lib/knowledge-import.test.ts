import { describe, expect, it } from "vitest";
import { readFile } from "node:fs/promises";
import { extractKnowledgeFile, extractKnowledgeUrl } from "./knowledge-import";

describe("knowledge import", () => {
  it("extracts actual PDF and DOCX documents", async () => {
    const pdf = await readFile(new URL("../../tests/fixtures/knowledge/guide.pdf", import.meta.url));
    const docx = await readFile(new URL("../../tests/fixtures/knowledge/guide.docx", import.meta.url));
    expect(await extractKnowledgeFile("guide.pdf", pdf)).toContain("returns within 7 days");
    expect(await extractKnowledgeFile("guide.docx", docx)).toContain("签收后 7 天");
  });

  it("rejects an empty PDF and corrupt documents", async () => {
    const empty = await readFile(new URL("../../tests/fixtures/knowledge/empty.pdf", import.meta.url));
    await expect(extractKnowledgeFile("empty.pdf", empty)).rejects.toThrow("没有可提取");
    await expect(extractKnowledgeFile("broken.docx", Buffer.from("not a zip"))).rejects.toThrow();
    await expect(extractKnowledgeFile("broken.pdf", Buffer.from("not a pdf"))).rejects.toThrow();
  });
  it("extracts local text and rejects unsupported or oversized files", async () => {
    expect(await extractKnowledgeFile("notes.md", Buffer.from("# 标题\n内容"))).toBe("# 标题\n内容");
    await expect(extractKnowledgeFile("test.exe", Buffer.from("hello"))).rejects.toThrow("仅支持");
    await expect(extractKnowledgeFile("notes.txt", Buffer.alloc(5_000_001))).rejects.toThrow("5 MB");
  });

  it("reads Chinese TXT and UTF-16 with BOM, rejects binary or invalid UTF-8", async () => {
    expect(await extractKnowledgeFile("中文.TXT", Buffer.from("退货期限为七天"))).toBe("退货期限为七天");
    expect(await extractKnowledgeFile("unicode.txt", Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from("退货期限", "utf16le")]))).toBe("退货期限");
    await expect(extractKnowledgeFile("binary.txt", Buffer.from([0, 1, 2]))).rejects.toThrow("编码");
    await expect(extractKnowledgeFile("bad.txt", Buffer.from([0xff, 0xff]))).rejects.toThrow("编码");
    await expect(extractKnowledgeFile("long.md", Buffer.from("中".repeat(11_000)))).rejects.toThrow("32 KB");
  });

  it.runIf(process.env.KNOWLEDGE_LIVE_WEB_TEST === "1")("imports a real public HTTPS page", async () => {
    const result = await extractKnowledgeUrl("https://example.com/");
    expect(result.content).toContain("Example Domain");
    expect(result.sourceUrl).toBe("https://example.com/");
  }, 15_000);

  it("rejects local and non-HTTPS URLs before a network request", async () => {
    await expect(extractKnowledgeUrl("http://example.com" )).rejects.toThrow("HTTPS");
    await expect(extractKnowledgeUrl("https://127.0.0.1/private")).rejects.toThrow("公开 HTTPS");
    await expect(extractKnowledgeUrl("https://localhost/private")).rejects.toThrow("公开 HTTPS");
  });
});
