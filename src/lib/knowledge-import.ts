import { resolve4 } from "node:dns/promises";
import https from "node:https";
import { isIP } from "node:net";
import mammoth from "mammoth";
import { PDFParse } from "pdf-parse";

const MAX_FILE_BYTES = 5_000_000;
const MAX_WEB_BYTES = 200_000;

export async function extractKnowledgeFile(name: string, bytes: Buffer) {
  if (!bytes.length || bytes.length > MAX_FILE_BYTES) throw new Error("文件大小无效（最多 5 MB）");
  const extension = name.toLowerCase().split(".").pop();
  let content: string;
  if (extension === "txt" || extension === "md") content = bytes.toString("utf8");
  else if (extension === "docx") content = (await mammoth.extractRawText({ buffer: bytes })).value;
  else if (extension === "pdf") {
    const parser = new PDFParse({ data: bytes });
    try { content = (await parser.getText()).text; }
    finally { await parser.destroy(); }
  } else throw new Error("仅支持 PDF、DOCX、Markdown 和 TXT 文件");
  content = content.trim();
  if (!content) throw new Error("文件没有可提取的文本");
  if (Buffer.byteLength(content, "utf8") > 32_000) throw new Error("提取文本过长（最多 32 KB）");
  return content;
}

export async function extractKnowledgeUrl(raw: string) {
  let url: URL;
  try { url = new URL(raw); } catch { throw new Error("网页地址无效"); }
  for (let redirects = 0; redirects <= 2; redirects++) {
    const response = await fetchPublicText(url);
    if (response.redirect) { url = new URL(response.redirect, url); continue; }
    const content = htmlToText(response.body, response.contentType).trim();
    if (!content) throw new Error("网页没有可提取的文本");
    if (Buffer.byteLength(content, "utf8") > 32_000) throw new Error("网页文本过长（最多 32 KB）");
    return { title: url.hostname + url.pathname, content, sourceUrl: url.toString() };
  }
  throw new Error("网页跳转次数过多");
}

function publicIpv4(ip: string) {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return false;
  const [a, b, c] = parts;
  return !(a === 0 || a === 10 || a === 127 || a >= 224
    || (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254)
    || (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0))
    || (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100)))
    || (a === 203 && b === 0 && c === 113));
}

async function fetchPublicText(url: URL): Promise<{ body: string; contentType: string; redirect?: string }> {
  if (url.protocol !== "https:" || url.port || url.username || url.password || isIP(url.hostname)
    || /(?:^|\.)(?:localhost|local|internal)$/.test(url.hostname)) throw new Error("仅支持公开 HTTPS 网页");
  const addresses = await resolve4(url.hostname);
  if (!addresses.length || addresses.some((address) => !publicIpv4(address))) throw new Error("网页地址指向非公开网络");
  const address = addresses[0];
  return new Promise((resolve, reject) => {
    const request = https.request(url, {
      method: "GET", timeout: 8_000,
      headers: { Accept: "text/html,text/plain", "User-Agent": "OpenRealtime-KnowledgeImport/1.0" },
      lookup: (_hostname, _options, callback) => callback(null, address, 4),
    }, (response) => {
      const status = response.statusCode ?? 0;
      if (status >= 300 && status < 400 && response.headers.location) {
        response.resume(); resolve({ body: "", contentType: "", redirect: response.headers.location }); return;
      }
      const contentType = String(response.headers["content-type"] ?? "").toLowerCase();
      if (status !== 200 || !/^(text\/html|text\/plain)(?:;|$)/.test(contentType)) {
        response.resume(); reject(new Error("网页无法读取或不是文本内容")); return;
      }
      const chunks: Buffer[] = [];
      let length = 0;
      response.on("data", (chunk: Buffer) => {
        length += chunk.length;
        if (length > MAX_WEB_BYTES) { request.destroy(new Error("网页内容过大")); return; }
        chunks.push(chunk);
      });
      response.on("end", () => resolve({ body: Buffer.concat(chunks).toString("utf8"), contentType }));
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error("网页请求超时")));
    request.on("error", reject);
    request.end();
  });
}

function htmlToText(body: string, contentType: string) {
  if (contentType.startsWith("text/plain")) return body;
  return body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<(?:br|\/p|\/div|\/li|\/h[1-6])\b[^>]*>/gi, "\n")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|amp|lt|gt|quot|#39);/g, (entity) => ({ "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"", "&#39;": "'" })[entity] ?? entity)
    .replace(/[ \t]+/g, " ").replace(/\n\s*\n\s*\n/g, "\n\n");
}
