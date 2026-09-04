import sharp from "sharp";
import { describe, expect, it } from "vitest";
import { prepareMiniMaxFrameImage } from "./minimax-frame-image";

describe("MiniMax frame image preparation", () => {
  it("expands a square Avatar source to a 16:9 first/last frame without cropping it", async () => {
    const source = await sharp({
      create: { width: 100, height: 100, channels: 3, background: "#48728f" },
    }).png().toBuffer();

    const prepared = await prepareMiniMaxFrameImage(
      new Uint8Array(source),
      "image/png",
      "16:9",
    );
    const metadata = await sharp(prepared.bytes).metadata();
    const corner = await sharp(prepared.bytes).extract({ left: 0, top: 0, width: 1, height: 1 }).raw().toBuffer();

    expect(metadata.width).toBe(1280);
    expect(metadata.height).toBe(720);
    expect([...corner].some((channel) => channel > 20)).toBe(true);
    expect(prepared.mediaType).toBe("image/webp");
    expect(prepared.transformed).toBe(true);
  });

  it("keeps adaptive frame input byte-identical", async () => {
    const source = Uint8Array.from([137, 80, 78, 71]);

    const prepared = await prepareMiniMaxFrameImage(source, "image/png", "adaptive");

    expect(prepared).toEqual({ bytes: source, mediaType: "image/png", transformed: false });
  });
});
