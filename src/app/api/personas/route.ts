import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { createPersona, listPersonas, normalizePersonaIntro, readPersonaProfile, switchAvatarPersona, writePersonaIntro } from "@/lib/avatar-persona-server";
import { parsePersonaFiles, personaErrorStatus, readBoundedJson } from "@/lib/persona-api-helpers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Persona 列表", 403);
  try {
    const personas = await listPersonas();
    return Response.json({ personas }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 列表读取失败";
    return jsonError(message, /无效/.test(message) ? 400 : 503);
  }
}

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许创建 Persona", 403);
  try {
    const payload = await readBoundedJson(request) as {
      personaId?: unknown;
      files?: unknown;
      avatarId?: unknown;
      avatarDisplayName?: unknown;
      intro?: unknown;
    };
    if (typeof payload.personaId !== "string") return jsonError("Persona ID 无效", 400);

    const files = parsePersonaFiles(payload.files);
    const intro = payload.intro === undefined ? undefined : normalizePersonaIntro(payload.intro);
    await createPersona(payload.personaId, files);
    if (intro !== undefined) await writePersonaIntro(payload.personaId, intro);

    if (typeof payload.avatarId === "string") {
      const avatarDisplayName = typeof payload.avatarDisplayName === "string" ? payload.avatarDisplayName : undefined;
      await switchAvatarPersona(payload.avatarId, payload.personaId, avatarDisplayName);
    }

    const profile = await readPersonaProfile(payload.personaId);
    return Response.json({ profile }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 创建失败";
    return jsonError(message, personaErrorStatus(error, message));
  }
}
