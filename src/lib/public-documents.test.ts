import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { PUBLIC_DOCUMENTS, resolveDocumentLink } from "./public-documents";

describe("public documentation routes", () => {
  it("keeps existing slugs and has a real source for every published article", () => {
    const slugs = PUBLIC_DOCUMENTS.map(doc => doc.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    expect(slugs).toEqual(expect.arrayContaining([
      "tool-permissions", "turn-coordination", "data-management", "project-improvements",
      "voice-interaction-review", "semantic-label-assessment", "semantic-decision-plugins",
      "voice-pipeline", "quick-start", "knowledge-base", "memory-and-history",
      "knowledge-integration", "digital-human", "motion-orchestration",
    ]));
    for (const doc of PUBLIC_DOCUMENTS) {
      for (const file of [doc.file, doc.englishFile].filter(Boolean) as string[]) {
        expect(existsSync(path.join(process.cwd(), "docs", file)), file).toBe(true);
      }
    }
  });
  it("resolves nested and English Markdown sources to site routes", () => {
    expect(resolveDocumentLink("../KNOWLEDGE-BASE-GUIDE.md#常见问题", "getting-started/PRODUCT-ASSISTANT.md"))
      .toBe("/docs/knowledge-base#%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98");
    expect(resolveDocumentLink("OVERVIEW.en.md?ref=guide#who-it-is-for", "getting-started/PRODUCT-ASSISTANT.en.md"))
      .toBe("/docs/overview?ref=guide#who-it-is-for");
    expect(resolveDocumentLink("../README.md", "guides/ROLE-CONFIGURATION.md")).toBe("/docs");
  });
  it("links unpublished references to the repository", () => {
    expect(resolveDocumentLink("../../ROADMAP.md", "getting-started/OVERVIEW.md"))
      .toBe("https://github.com/happy-token/OpenRealtime/blob/main/ROADMAP.md");
    expect(resolveDocumentLink("adr/", "README.md"))
      .toBe("https://github.com/happy-token/OpenRealtime/tree/main/docs/adr/");
  });
  it("retains application routes, fragments and external links", () => {
    for (const href of ["/resources?tab=knowledge", "/docs/knowledge-base", "#常见问题", "https://example.com/guide", "mailto:help@example.com"]) {
      expect(resolveDocumentLink(href, "getting-started/OVERVIEW.md")).toBe(href);
    }
  });
});
