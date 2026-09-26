export class RequestBodyTooLarge extends Error {}

export async function readLimitedJson(request: Request, maxBytes: number): Promise<unknown> {
  const bytes = await readLimitedBytes(request, maxBytes);
  return bytes.length ? JSON.parse(bytes.toString("utf8")) : null;
}

export async function readLimitedBytes(request: Request, maxBytes: number): Promise<Buffer> {
  const reader = request.body?.getReader();
  if (!reader) return Buffer.alloc(0);
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new RequestBodyTooLarge("请求内容过大");
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks);
}
