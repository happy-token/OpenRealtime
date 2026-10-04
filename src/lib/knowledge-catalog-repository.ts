import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";

export interface KnowledgeDocument {
  document_id: string;
  owner_id: string | null;
  title: string;
  content: string;
  content_hash: string;
  created_at: string;
  source_url?: string | null;
  role_id?: string | null;
  source_key?: string | null;
  revision?: number;
  updated_at?: string;
}

interface Catalog {
  documents: KnowledgeDocument[];
  bindings: { owner_id: string; role_id: string; document_ids: string[]; knowledge_base_id?: string }[];
}

const SAMPLE: KnowledgeDocument = {
  document_id: "shared-openrealtime-guide",
  owner_id: null,
  title: "共享示例 · OpenRealtime 使用说明",
  content: "OpenRealtime 的角色可以使用对话、离线数字人、离线加口型和实时数字人模式。声音是角色必选配置，Persona 可选。知识库资料按用户隔离，并可为不同角色分别绑定。共享示例仅用于测试检索。",
  content_hash: "builtin",
  created_at: "2026-09-23T00:00:00.000Z",
};
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;

export function knowledgeRoot() {
  return path.resolve(process.env.KNOWLEDGE_CATALOG_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "knowledge"));
}

export function roleKnowledgeBaseId(ownerId: string, roleId: string) {
  validateId(roleId);
  return `kb-${createHash("sha256").update(JSON.stringify([ownerId, roleId])).digest("hex").slice(0, 32)}`;
}

export async function listKnowledge(ownerId: string, root = knowledgeRoot(), roleId?: string) {
  if (roleId) validateId(roleId);
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    // Preserve existing bindings while moving documents to the shared user library.
    if (migrateRoleDocuments(catalog)) await writeCatalog(root, catalog);
    return [SAMPLE, ...catalog.documents.filter((doc) => doc.owner_id === ownerId)];
  });
}

function cleanDocument(title: string, content: string) {
  if (typeof title !== "string" || typeof content !== "string") throw new Error("资料内容无效");
  const cleanTitle = title.trim();
  const cleanContent = content.trim();
  if (!cleanTitle || cleanTitle.length > 120) throw new Error("资料名称无效（最多 120 字）");
  if (!cleanContent || Buffer.byteLength(cleanContent, "utf8") > 32_000) throw new Error("资料内容无效（最多 32 KB）");
  return { cleanTitle, cleanContent, hash: createHash("sha256").update(cleanContent).digest("hex") };
}

export async function createKnowledge(ownerId: string, title: string, content: string, root = knowledgeRoot(), sourceUrl: string | null = null,
  scope?: { roleId?: string; sourceKey?: string }) {
  const { cleanTitle, cleanContent, hash } = cleanDocument(title, content);
  if (scope?.roleId) validateId(scope.roleId);
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    migrateRoleDocuments(catalog);
    const matches = scope?.sourceKey ? catalog.documents.filter((doc) => doc.owner_id === ownerId
      && doc.source_key === scope.sourceKey) : [];
    if (matches.length > 1) throw new Error("资料来源冲突，请在列表中选择具体资料后编辑更新");
    const existing = matches[0];
    if (existing) {
      replaceDocument(existing, cleanTitle, cleanContent, hash, sourceUrl);
      if (scope?.roleId) bindDocument(catalog, ownerId, scope.roleId, existing.document_id);
      await writeCatalog(root, catalog);
      return existing;
    }
    if (catalog.documents.some((doc) => doc.owner_id === ownerId && doc.content_hash === hash)) {
      throw new Error("这份资料已存在，请勿重复创建");
    }
    const document: KnowledgeDocument = {
      document_id: `knowledge-${randomUUID()}`, owner_id: ownerId,
      title: cleanTitle, content: cleanContent, content_hash: hash, created_at: new Date().toISOString(),
      source_url: sourceUrl, role_id: null, source_key: scope?.sourceKey ?? null,
      revision: 1, updated_at: new Date().toISOString(),
    };
    catalog.documents.push(document);
    if (scope?.roleId) bindDocument(catalog, ownerId, scope.roleId, document.document_id);
    await writeCatalog(root, catalog);
    return document;
  });
}

export async function getKnowledgeBindings(ownerId: string, roleId: string, root = knowledgeRoot()) {
  validateId(roleId);
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    if (migrateRoleDocuments(catalog)) await writeCatalog(root, catalog);
    return catalog.bindings.find((item) => item.owner_id === ownerId && item.role_id === roleId)?.document_ids ?? [];
  });
}

export async function setKnowledgeBindings(ownerId: string, roleId: string, ids: string[], root = knowledgeRoot()) {
  validateId(roleId);
  if (ids.length > 30 || ids.some((id) => typeof id !== "string" || !ID.test(id))) throw new Error("资料 ID 无效");
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    migrateRoleDocuments(catalog);
    const allowed = new Set([SAMPLE.document_id, ...catalog.documents.filter((doc) => doc.owner_id === ownerId).map((doc) => doc.document_id)]);
    if (ids.some((id) => !allowed.has(id))) throw new Error("资料不可访问");
    const documentIds = [...new Set(ids)];
    catalog.bindings = catalog.bindings.filter((item) => item.owner_id !== ownerId || item.role_id !== roleId);
    catalog.bindings.push({ owner_id: ownerId, role_id: roleId, document_ids: documentIds,
      knowledge_base_id: roleKnowledgeBaseId(ownerId, roleId) });
    await writeCatalog(root, catalog);
    return documentIds;
  });
}

export async function updateKnowledge(ownerId: string, roleId: string | null, documentId: string,
  input: { title: string; content: string; expectedRevision: number; sourceUrl?: string | null; sourceKey?: string }, root = knowledgeRoot()) {
  if (roleId) validateId(roleId);
  const { cleanTitle, cleanContent, hash } = cleanDocument(input.title, input.content);
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    migrateRoleDocuments(catalog);
    const doc = catalog.documents.find((item) => item.document_id === documentId
      && item.owner_id === ownerId);
    if (!doc) throw new Error("资料不可访问");
    if (doc.revision !== input.expectedRevision) throw new Error("资料版本冲突，请刷新后重试");
    if (input.sourceKey && input.sourceKey !== doc.source_key && catalog.documents.some((item) => item.document_id !== documentId && item.owner_id === ownerId
      && item.source_key === input.sourceKey)) throw new Error("该来源已存在，请编辑已有资料");
    replaceDocument(doc, cleanTitle, cleanContent, hash, input.sourceUrl === undefined ? doc.source_url ?? null : input.sourceUrl);
    if (input.sourceKey) doc.source_key = input.sourceKey;
    await writeCatalog(root, catalog);
    return doc;
  });
}

export async function copyKnowledgeBindings(ownerId: string, sourceRoleId: string, targetRoleId: string, ids: string[], root = knowledgeRoot()) {
  validateId(sourceRoleId); validateId(targetRoleId);
  if (ids.length > 30 || ids.some((id) => typeof id !== "string" || !ID.test(id))) throw new Error("资料 ID 无效");
  // Cloning a role copies associations; shared documents retain their IDs.
  return setKnowledgeBindings(ownerId, targetRoleId, ids, root);
}

export async function deleteKnowledge(ownerId: string, roleId: string | null, documentId: string, expectedRevision: number, root = knowledgeRoot()) {
  if (roleId) validateId(roleId);
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    migrateRoleDocuments(catalog);
    const doc = catalog.documents.find((item) => item.document_id === documentId
      && item.owner_id === ownerId);
    if (!doc) throw new Error("资料不可访问");
    if (doc.revision !== expectedRevision) throw new Error("资料版本冲突，请刷新后重试");
    catalog.documents = catalog.documents.filter((item) => item.document_id !== documentId);
    for (const binding of catalog.bindings) binding.document_ids = binding.document_ids.filter((id) => id !== documentId);
    await writeCatalog(root, catalog);
  });
}

function replaceDocument(doc: KnowledgeDocument, title: string, content: string, hash: string, sourceUrl: string | null) {
  if (doc.content_hash === hash && doc.title === title && (doc.source_url ?? null) === sourceUrl) return;
  Object.assign(doc, { title, content, content_hash: hash, source_url: sourceUrl,
    revision: (doc.revision ?? 1) + 1, updated_at: new Date().toISOString() });
}

function bindDocument(catalog: Catalog, ownerId: string, roleId: string, documentId: string) {
  let binding = catalog.bindings.find((item) => item.owner_id === ownerId && item.role_id === roleId);
  if (!binding) {
    binding = { owner_id: ownerId, role_id: roleId, document_ids: [], knowledge_base_id: roleKnowledgeBaseId(ownerId, roleId) };
    catalog.bindings.push(binding);
  }
  if (binding.document_ids.includes(documentId)) return;
  if (binding.document_ids.length >= 30) throw new Error("角色知识库已达到 30 份资料上限");
  binding.document_ids.push(documentId);
}

function migrateRoleDocuments(catalog: Catalog) {
  let changed = false;
  for (const doc of [...catalog.documents]) {
    if (doc.revision === undefined) {
      doc.revision = 1; doc.updated_at = doc.created_at; changed = true;
    }
    if (doc.role_id) { doc.role_id = null; changed = true; }
  }
  for (const binding of catalog.bindings) {
    if (!binding.knowledge_base_id) {
      binding.knowledge_base_id = roleKnowledgeBaseId(binding.owner_id, binding.role_id); changed = true;
    }
  }
  return changed;
}

export function knowledgePassages(documents: KnowledgeDocument[], query: string, topK = 3) {
  const terms = Array.from(new Set((query.toLowerCase().match(/[\p{Script=Han}]{1,2}|[\p{L}\p{N}]{2,}/gu) ?? [])));
  if (!terms.length || query.length > 500) return [];
  const passages = documents.flatMap((doc) => {
    const chunks: { document_id: string; title: string; excerpt: string; source_url: string | null; score: number }[] = [];
    for (let start = 0; start < doc.content.length; start += 480) {
      const excerpt = doc.content.slice(start, start + 560);
      const text = excerpt.toLowerCase();
      const score = terms.reduce((sum, term) => sum + (text.includes(term) ? 1 : 0), 0);
      if (score) chunks.push({ document_id: doc.document_id, title: doc.title, excerpt, source_url: doc.source_url ?? null, score });
    }
    return chunks;
  });
  return passages.sort((a, b) => b.score - a.score).slice(0, Math.max(0, Math.min(topK, 5)))
    .map(({ document_id, title, excerpt, source_url }) => ({ document_id, title, excerpt, source_url }));
}

function validateId(id: string) {
  if (!ID.test(id)) throw new Error("角色 ID 无效");
}

async function readCatalog(root: string): Promise<Catalog> {
  try {
    const catalog = JSON.parse(await readFile(path.join(root, "catalog.json"), "utf8")) as Catalog;
    if (!Array.isArray(catalog.documents) || !Array.isArray(catalog.bindings)) throw new Error("知识库目录损坏");
    return catalog;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { documents: [], bindings: [] };
    throw error;
  }
}

async function writeCatalog(root: string, catalog: Catalog) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `catalog-${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(catalog), { mode: 0o600 });
  await rename(temporary, path.join(root, "catalog.json"));
}
