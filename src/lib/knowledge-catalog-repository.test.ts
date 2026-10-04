import { mkdtemp, rm, writeFile, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { createKnowledge, copyKnowledgeBindings, getKnowledgeBindings, knowledgePassages, listKnowledge, setKnowledgeBindings, updateKnowledge, deleteKnowledge, roleKnowledgeBaseId } from "./knowledge-catalog-repository";

const roots: string[] = [];
afterEach(async () => { await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true }))); });
async function root() { const directory = await mkdtemp(path.join(os.tmpdir(), "openrealtime-knowledge-")); roots.push(directory); return directory; }

describe("knowledge catalog isolation", () => {
  it("copies role associations without duplicating shared documents", async () => {
    const directory = await root();
    const source = await createKnowledge("alice", "Guide", "original rule", directory, null, { roleId: "role-one" });
    const ids = await copyKnowledgeBindings("alice", "role-one", "role-two", [source.document_id], directory);
    expect(ids[0]).toBe(source.document_id);
    await updateKnowledge("alice", "role-one", source.document_id, { title: "Guide", content: "changed rule", expectedRevision: 1 }, directory);
    expect((await listKnowledge("alice", directory, "role-two")).find((doc) => doc.document_id === ids[0])?.content).toBe("changed rule");
    expect(await copyKnowledgeBindings("alice", "role-one", "role-two", [source.document_id], directory)).toEqual(ids);
    expect((await listKnowledge("alice", directory, "role-two")).find((doc) => doc.document_id === ids[0])?.revision).toBe(2);
    await expect(copyKnowledgeBindings("bob", "role-one", "role-two", [source.document_id], directory)).rejects.toThrow("不可访问");
  });
  it("rejects ambiguous legacy sources and updates only an explicitly selected document", async () => {
    const directory = await root();
    await writeFile(path.join(directory, "catalog.json"), JSON.stringify({ documents: [
      { document_id: "knowledge-a", owner_id: "alice", role_id: "role-one", title: "A", content: "apples", content_hash: "a", source_key: "file:guide.md", created_at: "now" },
      { document_id: "knowledge-b", owner_id: "alice", role_id: "role-two", title: "B", content: "bananas", content_hash: "b", source_key: "file:guide.md", created_at: "now" },
    ], bindings: [
      { owner_id: "alice", role_id: "role-one", document_ids: ["knowledge-a"] },
      { owner_id: "alice", role_id: "role-two", document_ids: ["knowledge-b"] },
    ] }));
    await listKnowledge("alice", directory);
    await expect(createKnowledge("alice", "Guide", "new rules", directory, null, { sourceKey: "file:guide.md" })).rejects.toThrow("来源冲突");
    await updateKnowledge("alice", null, "knowledge-b", { title: "B", content: "new bananas", sourceKey: "file:guide.md", expectedRevision: 1 }, directory);
    const documents = await listKnowledge("alice", directory);
    expect(documents.find((doc) => doc.document_id === "knowledge-a")?.content).toBe("apples");
    expect(documents.find((doc) => doc.document_id === "knowledge-b")?.content).toBe("new bananas");
    expect(await getKnowledgeBindings("alice", "role-one", directory)).toEqual(["knowledge-a"]);
    expect(await getKnowledgeBindings("alice", "role-two", directory)).toEqual(["knowledge-b"]);
  });
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

  it("keeps one stable base per role and updates only the changed source", async () => {
    const directory = await root();
    const one = await createKnowledge("alice", "Guide", "old orchard rule", directory, null, { roleId: "role-one", sourceKey: "file:guide.md" });
    const two = await createKnowledge("alice", "Other", "other rule", directory, null, { roleId: "role-one", sourceKey: "file:other.md" });
    const updated = await createKnowledge("alice", "Guide", "new orchard rule", directory, null, { roleId: "role-one", sourceKey: "file:guide.md" });
    expect(updated.document_id).toBe(one.document_id);
    expect(updated.revision).toBe(2);
    const unchanged = await createKnowledge("alice", "Guide", "new orchard rule", directory, null, { roleId: "role-one", sourceKey: "file:guide.md" });
    expect(unchanged.revision).toBe(2);
    expect(unchanged.updated_at).toBe(updated.updated_at);
    expect(await getKnowledgeBindings("alice", "role-one", directory)).toEqual([one.document_id, two.document_id]);
    const docs = await listKnowledge("alice", directory, "role-one");
    expect(docs.find((doc) => doc.document_id === two.document_id)).toEqual(two);
    expect(knowledgePassages(docs, "old")).toEqual([]);
    expect(roleKnowledgeBaseId("alice", "role-one")).not.toBe(roleKnowledgeBaseId("alice", "role-two"));
    await setKnowledgeBindings("alice", "role-two", [one.document_id], directory);
    const ownCopy = await createKnowledge("alice", "Guide", "new orchard rule", directory, null, { roleId: "role-two", sourceKey: "file:guide.md" });
    expect(ownCopy.document_id).toBe(one.document_id);
    expect((await listKnowledge("alice", directory, "role-two")).map((doc) => doc.document_id)).toContain(one.document_id);
  });

  it("checks owner and revision on edits and removes all role associations on deletion", async () => {
    const directory = await root();
    const doc = await createKnowledge("alice", "Guide", "apples", directory, null, { roleId: "role-one" });
    const change = { title: "Updated", content: "bananas", expectedRevision: 1 };
    await expect(updateKnowledge("bob", "role-one", doc.document_id, change, directory)).rejects.toThrow("不可访问");
    await setKnowledgeBindings("alice", "role-two", [doc.document_id], directory);
    const edited = await updateKnowledge("alice", "role-one", doc.document_id, change, directory);
    expect(edited.revision).toBe(2);
    await expect(updateKnowledge("alice", "role-one", doc.document_id, change, directory)).rejects.toThrow("版本冲突");
    await expect(deleteKnowledge("alice", "role-one", doc.document_id, 1, directory)).rejects.toThrow("版本冲突");
    await deleteKnowledge("alice", "role-one", doc.document_id, 2, directory);
    expect(await getKnowledgeBindings("alice", "role-one", directory)).toEqual([]);
    expect(await getKnowledgeBindings("alice", "role-two", directory)).toEqual([]);
    expect((await listKnowledge("alice", directory)).map((item) => item.document_id)).not.toContain(doc.document_id);
  });

  it("migrates role documents into the shared library without losing IDs or bindings", async () => {
    const directory = await root();
    await writeFile(path.join(directory, "catalog.json"), JSON.stringify({
      documents: [{ document_id: "knowledge-legacy", owner_id: "alice", title: "Legacy", content: "apples", content_hash: "old", created_at: "now", role_id: "role-one" }],
      bindings: [{ owner_id: "alice", role_id: "role-one", document_ids: ["knowledge-legacy"] },
        { owner_id: "alice", role_id: "role-two", document_ids: ["knowledge-legacy"] }],
    }));
    await listKnowledge("alice", directory);
    const one = await getKnowledgeBindings("alice", "role-one", directory);
    const two = await getKnowledgeBindings("alice", "role-two", directory);
    expect(one).toEqual(["knowledge-legacy"]);
    expect(two).toEqual(one);
    await updateKnowledge("alice", "role-one", one[0], { title: "Legacy", content: "bananas", expectedRevision: 1 }, directory);
    expect((await listKnowledge("alice", directory, "role-two")).find((doc) => doc.document_id === two[0])?.content).toBe("bananas");
    const saved = JSON.parse(await readFile(path.join(directory, "catalog.json"), "utf8"));
    expect(saved.documents).toHaveLength(1);
    expect(saved.documents[0].role_id).toBeNull();
    expect(saved.bindings[0].knowledge_base_id).toBe(roleKnowledgeBaseId("alice", "role-one"));
  });
});
