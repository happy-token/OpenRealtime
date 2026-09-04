const MAX_SOURCE_EDGE = 1280;
const TARGET_SOURCE_BYTES = 1_200_000;
const OUTPUT_TYPE = "image/webp";

export function fitAvatarImageDimensions(
  width: number,
  height: number,
  maxEdge = MAX_SOURCE_EDGE,
) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("Avatar 图片尺寸无效");
  }
  const scale = Math.min(1, maxEdge / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

export async function normalizeAvatarSourceImage(imageUrl: string): Promise<string> {
  const response = await fetch(imageUrl, { cache: "no-store" });
  if (!response.ok) throw new Error("Avatar 源图读取失败");
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) throw new Error("Avatar 源图格式无效");

  const bitmap = await createImageBitmap(blob);
  try {
    const dimensions = fitAvatarImageDimensions(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = dimensions.width;
    canvas.height = dimensions.height;
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("当前浏览器无法处理 Avatar 图片");
    context.fillStyle = "#f4f2ee";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    let output = await canvasBlob(canvas, 0.84);
    if (output.size > TARGET_SOURCE_BYTES) output = await canvasBlob(canvas, 0.68);
    if (output.size > 4_500_000) throw new Error("Avatar 源图处理后仍超过 4.5MB");
    return blobToDataUrl(output);
  } finally {
    bitmap.close();
  }
}

function canvasBlob(canvas: HTMLCanvasElement, quality: number) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Avatar 图片编码失败")),
      OUTPUT_TYPE,
      quality,
    );
  });
}

function blobToDataUrl(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Avatar 图片编码失败"));
    reader.onload = () => typeof reader.result === "string"
      ? resolve(reader.result)
      : reject(new Error("Avatar 图片编码失败"));
    reader.readAsDataURL(blob);
  });
}
