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
}

interface Catalog {
  documents: KnowledgeDocument[];
  bindings: { owner_id: string; role_id: string; document_ids: string[] }[];
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

export async function listKnowledge(ownerId: string, root = knowledgeRoot()) {
  const catalog = await readCatalog(root);
  return [SAMPLE, ...catalog.documents.filter((doc) => doc.owner_id === ownerId)];
}

export async function createKnowledge(ownerId: string, title: string, content: string, root = knowledgeRoot(), sourceUrl: string | null = null) {
  const cleanTitle = title.trim();
  const cleanContent = content.trim();
  if (!cleanTitle || cleanTitle.length > 120) throw new Error("资料名称无效（最多 120 字）");
  if (!cleanContent || Buffer.byteLength(cleanContent, "utf8") > 32_000) throw new Error("资料内容无效（最多 32 KB）");
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    const hash = createHash("sha256").update(cleanContent).digest("hex");
    if (catalog.documents.some((doc) => doc.owner_id === ownerId && doc.content_hash === hash)) {
      throw new Error("这份资料已存在，请勿重复创建");
    }
    const document: KnowledgeDocument = {
      document_id: `knowledge-${randomUUID()}`, owner_id: ownerId,
      title: cleanTitle, content: cleanContent, content_hash: hash, created_at: new Date().toISOString(),
      source_url: sourceUrl,
    };
    catalog.documents.push(document);
    await writeCatalog(root, catalog);
    return document;
  });
}

export async function getKnowledgeBindings(ownerId: string, roleId: string, root = knowledgeRoot()) {
  validateId(roleId);
  const catalog = await readCatalog(root);
  return catalog.bindings.find((item) => item.owner_id === ownerId && item.role_id === roleId)?.document_ids ?? [];
}

export async function setKnowledgeBindings(ownerId: string, roleId: string, ids: string[], root = knowledgeRoot()) {
  validateId(roleId);
  if (ids.length > 30 || ids.some((id) => typeof id !== "string" || !ID.test(id))) throw new Error("资料 ID 无效");
  return withAvatarCatalogLock(root, async () => {
    const catalog = await readCatalog(root);
    const allowed = new Set([SAMPLE.document_id, ...catalog.documents.filter((doc) => doc.owner_id === ownerId).map((doc) => doc.document_id)]);
    if (ids.some((id) => !allowed.has(id))) throw new Error("资料不可访问");
    const documentIds = [...new Set(ids)];
    catalog.bindings = catalog.bindings.filter((item) => item.owner_id !== ownerId || item.role_id !== roleId);
    catalog.bindings.push({ owner_id: ownerId, role_id: roleId, document_ids: documentIds });
    await writeCatalog(root, catalog);
    return documentIds;
  });
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
