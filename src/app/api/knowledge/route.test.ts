import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as createText, GET as list } from "./route";
import { POST as importFile } from "./import/route";
import { POST as search } from "./search/route";
import { PATCH as update, DELETE as remove } from "./documents/[documentId]/route";
import { getKnowledgeBindings } from "@/lib/knowledge-catalog-repository";

vi.mock("@/lib/knowledge-request-auth", () => ({ knowledgeOwner: async (request: Request) =>
  request.headers.get("x-test-auth") === "denied" ? Response.json({ error: "请先登录" }, { status: 401 })
    : request.headers.get("x-test-owner") ?? "alice" }));
vi.mock("@/lib/knowledge-role-scope", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/knowledge-role-scope")>(),
  requireKnowledgeRole: async (_request: Request, id: unknown) => ["role-one", "role-two"].includes(String(id)) ? id
    : Response.json({ error: "请选择角色" }, { status: 400 }),
}));

let directory: string;
beforeEach(async () => { directory = await mkdtemp(path.join(tmpdir(), "knowledge-api-")); vi.stubEnv("KNOWLEDGE_CATALOG_DIR", directory); });
afterEach(async () => { vi.unstubAllEnvs(); await rm(directory, { recursive: true, force: true }); });
function request(body: object, owner = "alice") {
  return new Request("https://app.example/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json", "x-test-owner": owner }, body: JSON.stringify(body) });
}
function context(documentId: string) { return { params: Promise.resolve({ documentId }) }; }

describe("knowledge API", () => {
  it("creates pasted text in the chosen role, edits in place and removes stale results", async () => {
    const created = await createText(request({ roleId: "role-one", title: "售后", content: "七天退货" }));
    expect(created.status).toBe(201);
    const { document } = await created.json();
    expect(await getKnowledgeBindings("alice", "role-one")).toEqual([document.document_id]);
    expect((await (await search(request({ roleId: "role-one", query: "七天", documentIds: [document.document_id] }))).json()).passages).toHaveLength(1);
    const changed = await update(request({ roleId: "role-one", title: "售后", content: "十五天换货", expectedRevision: 1 }), context(document.document_id));
    expect(changed.status).toBe(200); expect((await changed.json()).document.revision).toBe(2);
    expect((await (await search(request({ roleId: "role-one", query: "七天", documentIds: [document.document_id] }))).json()).passages).toEqual([]);
    expect((await update(request({ roleId: "role-one", title: "旧版", content: "七天退货", expectedRevision: 1 }), context(document.document_id))).status).toBe(409);
    expect((await remove(request({ roleId: "role-one", expectedRevision: 2 }), context(document.document_id))).status).toBe(200);
    expect(await getKnowledgeBindings("alice", "role-one")).toEqual([]);
  });

  it("edits and deletes standalone library documents without requiring a role", async () => {
    const { document } = await (await createText(request({ title: "Standalone", content: "apples" }))).json();
    expect((await update(request({ title: "Standalone", content: "bananas", expectedRevision: 1 }), context(document.document_id))).status).toBe(200);
    expect((await remove(request({ expectedRevision: 2 }, "bob"), context(document.document_id))).status).toBe(403);
    expect((await remove(request({ expectedRevision: 2 }), context(document.document_id))).status).toBe(200);
  });
  it("imports real PDF, DOCX, TXT and Markdown through multipart requests", async () => {
    for (const [name, bytes] of [
      ["guide.pdf", await readFile(path.join(process.cwd(), "tests/fixtures/knowledge/guide.pdf"))],
      ["guide.docx", await readFile(path.join(process.cwd(), "tests/fixtures/knowledge/guide.docx"))],
      ["notes.txt", Buffer.from("TXT 正文")], ["notes.md", Buffer.from("# Markdown 正文")],
    ] as const) {
      const form = new FormData(); form.set("roleId", "role-one"); form.set("file", new File([new Uint8Array(bytes)], name));
      const response = await importFile(new Request("https://app.example/api/knowledge/import", { method: "POST", body: form }));
      expect(response.status).toBe(201); expect((await response.json()).document.content.length).toBeGreaterThan(0);
    }
    expect(await getKnowledgeBindings("alice", "role-one")).toHaveLength(4);
  });

  it("upserts same filename and preserves the role binding and document ID", async () => {
    async function upload(text: string) {
      const form = new FormData(); form.set("roleId", "role-one"); form.set("file", new File([text], "notes.txt"));
      return (await (await importFile(new Request("https://app.example/import", { method: "POST", body: form }))).json()).document;
    }
    const original = await upload("旧条款");
    const updated = await upload("新条款");
    expect(updated.document_id).toBe(original.document_id); expect(updated.revision).toBe(2);
    expect((await upload("新条款")).revision).toBe(2);
    expect(await getKnowledgeBindings("alice", "role-one")).toEqual([original.document_id]);
  });

  it("allows shared documents across roles but blocks another owner", async () => {
    const { document } = await (await createText(request({ roleId: "role-one", title: "私有", content: "private apples" }))).json();
    const edit = { roleId: "role-two", title: "change", content: "bananas", expectedRevision: 1 };
    expect((await update(request(edit), context(document.document_id))).status).toBe(200);
    expect((await update(request({ ...edit, roleId: "role-one" }, "bob"), context(document.document_id))).status).toBe(403);
    expect((await search(request({ roleId: "role-two", query: "apples", documentIds: [document.document_id] }))).status).toBe(200);
    const documents = (await (await list(new Request("https://app.example/api/knowledge?roleId=role-two"))).json()).documents;
    expect(documents.some((doc: { document_id: string }) => doc.document_id === document.document_id)).toBe(true);
  });

  it("allows standalone library creation, requires authorization and rejects invalid imports", async () => {
    expect((await createText(request({ title: "text", content: "body" }))).status).toBe(201);
    expect(await getKnowledgeBindings("alice", "role-one")).toEqual([]);
    const denied = request({ roleId: "role-one", title: "text", content: "body" }); denied.headers.set("x-test-auth", "denied");
    expect((await createText(denied)).status).toBe(401);
    expect((await createText(request({ roleId: "role-one", title: "text", content: " " }))).status).toBe(400);
    const form = new FormData(); form.set("roleId", "role-one"); form.set("file", new File(["not supported"], "spreadsheet.xlsx"));
    expect((await importFile(new Request("https://app.example/import", { method: "POST", body: form }))).status).toBe(400);
  });
});
