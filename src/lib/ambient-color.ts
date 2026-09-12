export function getEdgeAmbientColor(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
): string | null {
  if (width < 1 || height < 1 || pixels.length < width * height * 4) return null;

  const horizontalBand = Math.max(1, Math.floor(width * 0.16));
  const verticalBand = Math.max(1, Math.floor(height * 0.14));
  let red = 0;
  let green = 0;
  let blue = 0;
  let weight = 0;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (x >= horizontalBand && x < width - horizontalBand && y >= verticalBand && y < height - verticalBand) continue;
      const offset = (y * width + x) * 4;
      const alpha = pixels[offset + 3] / 255;
      if (alpha < 0.45) continue;
      red += pixels[offset] * alpha;
      green += pixels[offset + 1] * alpha;
      blue += pixels[offset + 2] * alpha;
      weight += alpha;
    }
  }

  if (weight === 0) return null;
  return `rgb(${Math.round(red / weight)} ${Math.round(green / weight)} ${Math.round(blue / weight)})`;
}

export function sampleMediaAmbientColor(
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
): string | null {
  if (typeof document === "undefined" || sourceWidth < 1 || sourceHeight < 1) return null;
  try {
    const canvas = document.createElement("canvas");
    const sampleWidth = 32;
    const sampleHeight = Math.max(1, Math.round(sourceHeight * sampleWidth / sourceWidth));
    canvas.width = sampleWidth;
    canvas.height = sampleHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return null;
    context.drawImage(source, 0, 0, sampleWidth, sampleHeight);
    return getEdgeAmbientColor(context.getImageData(0, 0, sampleWidth, sampleHeight).data, sampleWidth, sampleHeight);
  } catch {
    return null;
  }
}
