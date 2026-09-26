import { describe, expect, it } from "vitest";
import { privateMediaResponse } from "./private-media-response";

const image = {
  bytes: new Uint8Array([1, 2, 3]),
  mediaType: "image/webp",
  version: "image-v1",
};

describe("privateMediaResponse", () => {
  it("uses immutable browser caching for a matching versioned URL", async () => {
    const response = privateMediaResponse(new Request("http://localhost/image?v=image-v1"), image);

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, max-age=31536000, immutable");
    expect(response.headers.get("etag")).toBe('"image-v1"');
    expect(response.headers.get("content-length")).toBe("3");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(image.bytes);
  });

  it("revalidates unversioned URLs and returns 304 for a matching ETag", () => {
    const unversioned = privateMediaResponse(new Request("http://localhost/image"), image);
    const notModified = privateMediaResponse(new Request("http://localhost/image?v=image-v1", {
      headers: { "If-None-Match": '"image-v1"' },
    }), image);

    expect(unversioned.headers.get("cache-control")).toBe("private, no-cache");
    expect(notModified.status).toBe(304);
    expect(notModified.headers.get("cache-control")).toBe("private, max-age=31536000, immutable");
  });
});
