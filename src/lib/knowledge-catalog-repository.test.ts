import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createKnowledge, getKnowledgeBindings, knowledgePassages, listKnowledge, setKnowledgeBindings } from "./knowledge-catalog-repository";

const roots: string[] = [];
afterEach(async () => { await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true }))); });
async function root() { const directory = await mkdtemp(path.join(os.tmpdir(), "openrealtime-knowledge-")); roots.push(directory); return directory; }

describe("knowledge catalog isolation", () => {
  it("exposes a shared read-only sample but never another user's documents", async () => {
    const directory = await root();
    const secret = await createKnowledge("issuer#alice", "Alice", "private orchard notes", directory);
    const alice = await listKnowledge("issuer#alice", directory);
    const bob = await listKnowledge("issuer#bob", directory);
    expect(alice.map((doc) => doc.document_id)).toContain(secret.document_id);
    expect(bob.map((doc) => doc.document_id)).toEqual(["shared-openrealtime-guide"]);
    await expect(setKnowledgeBindings("issuer#bob", "role-one", [secret.document_id], directory)).rejects.toThrow(/不可访问/);
    expect(await getKnowledgeBindings("issuer#bob", "role-one", directory)).toEqual([]);
  });

  it("keeps bindings separate per user and role, deduplicates documents", async () => {
    const directory = await root();
    const doc = await createKnowledge("issuer#alice", "Guide", "The apples are green", directory);
    await expect(createKnowledge("issuer#alice", "Copy", "The apples are green", directory)).rejects.toThrow(/已存在/);
    await setKnowledgeBindings("issuer#alice", "role-one", [doc.document_id, doc.document_id], directory);
    expect(await getKnowledgeBindings("issuer#alice", "role-one", directory)).toEqual([doc.document_id]);
    expect(await getKnowledgeBindings("issuer#alice", "role-two", directory)).toEqual([]);
    expect(await getKnowledgeBindings("issuer#bob", "role-one", directory)).toEqual([]);
  });

  it("returns source excerpts only when keywords match", async () => {
    const docs = await listKnowledge("any", await root());
    expect(knowledgePassages(docs, "声音")[0]).toMatchObject({ title: docs[0].title });
    expect(knowledgePassages(docs, "unrelated zebra")).toEqual([]);
  });
});
