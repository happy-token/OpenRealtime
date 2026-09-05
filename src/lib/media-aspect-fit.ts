export type MediaAspectBucket = "landscape" | "square" | "portrait";

export function classifyMediaAspectRatio(width: number, height: number): MediaAspectBucket {
  if (width <= 0 || height <= 0) return "square";
  const ratio = width / height;
  if (ratio >= 1.2) return "landscape";
  if (ratio <= 0.82) return "portrait";
  return "square";
}
