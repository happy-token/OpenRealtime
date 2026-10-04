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
  if (extension === "txt" || extension === "md") content = decodeText(bytes);
  else if (extension === "docx") {
    try { content = (await mammoth.extractRawText({ buffer: bytes })).value; }
    catch { throw new Error("DOCX 文件无法读取，请检查是否损坏或格式不符"); }
  }
  else if (extension === "pdf") {
    const parser = new PDFParse({ data: bytes });
    try { content = (await parser.getText()).pages.map((page) => page.text).join("\n\n"); }
    catch { throw new Error("PDF 文件无法读取，请检查是否损坏或需要密码"); }
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
    const pageTitle = response.contentType.startsWith("text/html")
      ? response.body.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1] : undefined;
    return { title: pageTitle ? htmlToText(pageTitle, "text/html").trim().slice(0, 120) : (url.hostname + url.pathname).slice(0, 120), content, sourceUrl: url.toString() };
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
  const addresses = await resolveWebAddresses(url.hostname);
  if (!addresses.length || addresses.some((address) => !publicIpv4(address))) throw new Error("网页地址指向非公开网络；请检查 DNS 是否返回代理 Fake-IP");
  const address = addresses[0];
  return new Promise((resolve, reject) => {
    const request = https.request(url, {
      method: "GET", timeout: 8_000, family: 4,
      headers: { Accept: "text/html,text/plain", "User-Agent": "OpenRealtime-KnowledgeImport/1.0" },
      lookup: (_hostname, options, callback) => options.all
        ? callback(null, [{ address, family: 4 }]) : callback(null, address, 4),
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
      response.on("end", () => {
        try {
          const bytes = Buffer.concat(chunks);
          const declared = contentType.match(/charset\s*=\s*["']?([^\s;"']+)/i)?.[1]
            ?? bytes.subarray(0, 4096).toString("latin1").match(/<meta\b[^>]*charset\s*=\s*["']?([^\s;"'/>]+)/i)?.[1];
          resolve({ body: decodeText(bytes, declared), contentType });
        } catch (error) { reject(error); }
      });
      response.on("error", reject);
    });
    request.on("timeout", () => request.destroy(new Error("网页请求超时")));
    request.on("error", reject);
    request.end();
  });
}

async function resolveWebAddresses(hostname: string): Promise<string[]> {
  const mode = process.env.KNOWLEDGE_WEB_DNS?.trim() || "system";
  if (mode === "system") return resolve4(hostname);
  if (mode !== "cloudflare-doh") throw new Error("知识库 DNS 配置无效");
  // Fixed trusted resolver, opt-in only. Target addresses are still validated
  // and pinned by https.request; DoH never permits private network targets.
  const endpoint = new URL("https://cloudflare-dns.com/dns-query");
  endpoint.searchParams.set("name", hostname); endpoint.searchParams.set("type", "A");
  const response = await fetch(endpoint, { headers: { Accept: "application/dns-json" },
    redirect: "error", signal: AbortSignal.timeout(8_000) });
  if (!response.ok || !response.body) throw new Error("公网 DNS 解析失败");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16_000) { await reader.cancel(); throw new Error("公网 DNS 响应过大"); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const data = JSON.parse(Buffer.concat(chunks).toString("utf8")) as { Status?: unknown; Answer?: unknown };
  if (data.Status !== 0 || !Array.isArray(data.Answer)) throw new Error("公网 DNS 解析失败");
  return data.Answer.flatMap((answer: unknown) => {
    if (!answer || typeof answer !== "object") return [];
    const record = answer as { type?: unknown; data?: unknown };
    return record.type === 1 && typeof record.data === "string" ? [record.data] : [];
  });
}

function htmlToText(body: string, contentType: string) {
  if (contentType.startsWith("text/plain")) return body;
  return body.replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<(?:br|\/p|\/div|\/li|\/h[1-6])\b[^>]*>/gi, "\n")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|amp|lt|gt|quot|#\d+|#x[\da-f]+);/gi, (entity) => {
      const named = ({ "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": "\"" })[entity.toLowerCase()];
      if (named !== undefined) return named;
      const value = entity.slice(2, -1);
      const code = /^x/i.test(value) ? parseInt(value.slice(1), 16) : Number(value);
      return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff) ? String.fromCodePoint(code) : " ";
    })
    .replace(/[ \t]+/g, " ").replace(/\n\s*\n\s*\n/g, "\n\n");
}

function decodeText(bytes: Buffer, charset?: string) {
  const encoding = charset ?? (bytes[0] === 0xff && bytes[1] === 0xfe ? "utf-16le"
    : bytes[0] === 0xfe && bytes[1] === 0xff ? "utf-16be" : "utf-8");
  try {
    const text = new TextDecoder(encoding, { fatal: true }).decode(bytes);
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text)) throw new Error("binary");
    return text;
  } catch { throw new Error("文本编码无法读取，请转为 UTF-8 文本后导入"); }
}
