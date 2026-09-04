import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { Readable } from "node:stream";
import { currentAdmin } from "@/lib/admin-server";
import {
  parseByteRange,
  resolveAvatarArtifactPath,
} from "@/lib/avatar-evaluation-artifacts";
import {
  avatarEvaluationPreviewPolicyFromEnv,
  isSameOriginAvatarPreviewRequest,
} from "@/lib/avatar-evaluation-preview";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ artifactId: string }> },
) {
  const previewPolicy = avatarEvaluationPreviewPolicyFromEnv();
  const localDevelopmentPreview = previewPolicy.localDevelopmentAccess
    && isSameOriginAvatarPreviewRequest(request);
  const authorized = previewPolicy.enabled
    && (localDevelopmentPreview || Boolean(await currentAdmin()));
  if (!authorized) {
    return Response.json({ error: "Artifact preview requires authorization" }, { status: 403 });
  }

  const { artifactId } = await params;
  const artifactPath = resolveAvatarArtifactPath(artifactId, { previewEnabled: true });
  if (!artifactPath) {
    return Response.json({ error: "Artifact preview is unavailable" }, { status: 404 });
  }

  try {
    const fileStats = await stat(artifactPath);
    const rangeHeader = request.headers.get("range");
    const range = rangeHeader ? parseByteRange(rangeHeader, fileStats.size) : null;
    if (rangeHeader && !range) {
      return new Response(null, {
        status: 416,
        headers: { "Content-Range": `bytes */${fileStats.size}` },
      });
    }

    const start = range?.start ?? 0;
    const end = range?.end ?? fileStats.size - 1;
    const nodeStream = createReadStream(artifactPath, { start, end });
    const body = Readable.toWeb(nodeStream) as ReadableStream<Uint8Array>;
    const responseHeaders: Record<string, string> = {
      "Accept-Ranges": "bytes",
      "Cache-Control": "private, no-store",
      "Content-Length": String(end - start + 1),
      "Content-Type": "video/mp4",
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    };
    if (range) responseHeaders["Content-Range"] = `bytes ${start}-${end}/${fileStats.size}`;
    return new Response(body, {
      status: range ? 206 : 200,
      headers: responseHeaders,
    });
  } catch (error) {
    if (isFileNotFound(error)) {
      return Response.json({ error: "Artifact file is missing" }, { status: 404 });
    }
    console.error("Failed to stream avatar evaluation artifact", error);
    return Response.json({ error: "Artifact preview failed" }, { status: 500 });
  }
}

function isFileNotFound(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}
