import sharp from "sharp";
import type { MiniMaxRatio } from "./minimax-video-options";

const FRAME_DIMENSIONS: Record<Exclude<MiniMaxRatio, "adaptive">, { width: number; height: number }> = {
  "21:9": { width: 1344, height: 576 },
  "16:9": { width: 1280, height: 720 },
  "4:3": { width: 1024, height: 768 },
  "1:1": { width: 1024, height: 1024 },
  "3:4": { width: 768, height: 1024 },
  "9:16": { width: 720, height: 1280 },
};

export async function prepareMiniMaxFrameImage(
  bytes: Uint8Array,
  mediaType: string,
  ratio: MiniMaxRatio,
) {
  if (ratio === "adaptive") return { bytes, mediaType, transformed: false as const };
  const dimensions = FRAME_DIMENSIONS[ratio];
  const input = Buffer.from(bytes);
  const [background, foreground] = await Promise.all([
    sharp(input)
      .resize({ ...dimensions, fit: "cover" })
      .blur(32)
      .modulate({ brightness: 0.72, saturation: 0.82 })
      .webp({ quality: 90 })
      .toBuffer(),
    sharp(input)
      .ensureAlpha()
      .resize({
        ...dimensions,
        fit: "contain",
        withoutEnlargement: true,
        background: { r: 0, g: 0, b: 0, alpha: 0 },
      })
      .png()
      .toBuffer(),
  ]);
  const output = await sharp(background)
    .composite([{ input: foreground, gravity: "center" }])
    .webp({ quality: 92 })
    .toBuffer();
  return {
    bytes: new Uint8Array(output),
    mediaType: "image/webp",
    transformed: true as const,
  };
}
