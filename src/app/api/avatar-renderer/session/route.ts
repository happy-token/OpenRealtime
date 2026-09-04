import { currentAdmin } from "@/lib/admin-server";
import {
  avatarEvaluationPreviewPolicyFromEnv,
  isSameOriginAvatarPreviewRequest,
} from "@/lib/avatar-evaluation-preview";
import { resolveAvatarRendererRuntimeForModel } from "@/lib/avatar-renderer-runtime";
import { resolveAvatarRendererBinding } from "@/lib/avatar-renderer-preparation";
import { ensureLiveTalkingProcess } from "@/lib/livetalking-process";
import { DEFAULT_AVATAR_DISPLAY_CONFIG, parseAvatarDisplayConfig } from "@/components/digital-human/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request) {
  if (!await authorized(request)) {
    return Response.json({ error: "Avatar renderer requires authorized local preview access" }, { status: 403 });
  }
  try {
    const body = await request.text();
    const binding = resolveAvatarRendererBinding(body
      ? parseAvatarDisplayConfig(JSON.parse(body))
      : { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });
    if (!binding) {
      return Response.json({ error: "当前数字人组合没有可用 Renderer" }, { status: 400 });
    }
    const renderer = resolveAvatarRendererRuntimeForModel(binding.modelId);
    if (!renderer) {
      return Response.json({ error: "Self-hosted avatar renderer is disabled" }, { status: 503 });
    }
    if (renderer.mode === "managed") {
      await ensureLiveTalkingProcess(process.cwd(), renderer.port, renderer.modelSize);
    }
    return Response.json({
      endpoint: renderer.publicUrl,
      avatar_id: binding.rendererAssetId,
      avatar_name: binding.displayName,
      model: binding.modelId,
      renderer: binding.renderer,
    });
  } catch (error) {
    console.error("Failed to resolve the avatar renderer", error);
    return Response.json({ error: error instanceof Error ? error.message : "Avatar renderer is unavailable" }, { status: 503 });
  }
}

export async function DELETE(request: Request) {
  if (!await authorized(request)) return new Response(null, { status: 403 });
  return new Response(null, { status: 204 });
}

async function authorized(request: Request): Promise<boolean> {
  const policy = avatarEvaluationPreviewPolicyFromEnv();
  if (!policy.enabled) return false;
  if (policy.localDevelopmentAccess && isSameOriginAvatarPreviewRequest(request)) return true;
  return Boolean(await currentAdmin());
}
