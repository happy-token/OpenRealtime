type PrivateMedia = {
  bytes: Uint8Array;
  mediaType: string;
  version: string;
};

const IMMUTABLE_PRIVATE_CACHE = "private, max-age=31536000, immutable";
const REVALIDATED_PRIVATE_CACHE = "private, no-cache";

export function privateMediaResponse(request: Request, media: PrivateMedia) {
  const etag = `"${media.version.replace(/[^A-Za-z0-9._:-]/g, "") || "asset"}"`;
  const requestedVersion = new URL(request.url).searchParams.get("v");
  const cacheControl = requestedVersion === media.version
    ? IMMUTABLE_PRIVATE_CACHE
    : REVALIDATED_PRIVATE_CACHE;
  const headers = new Headers({
    "Cache-Control": cacheControl,
    "Content-Type": media.mediaType,
    "Cross-Origin-Resource-Policy": "same-origin",
    ETag: etag,
    Vary: "Cookie",
    "X-Content-Type-Options": "nosniff",
  });
  const validators = request.headers.get("if-none-match")?.split(",").map((value) => value.trim()) ?? [];
  if (validators.includes(etag) || validators.includes("*")) {
    return new Response(null, { status: 304, headers });
  }
  headers.set("Content-Length", String(media.bytes.byteLength));
  return new Response(media.bytes.slice().buffer as ArrayBuffer, { headers });
}
