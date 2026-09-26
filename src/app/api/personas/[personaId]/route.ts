import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { archivePersona, normalizePersonaIntro, readPersonaProfile, renamePersona, writeAvatarPersonaFiles, writePersonaIntro } from "@/lib/avatar-persona-server";
import { parsePersonaFiles, personaErrorStatus, readBoundedJson } from "@/lib/persona-api-helpers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ personaId: string }> };

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Persona", 403);
  try {
    const profile = await readPersonaProfile((await context.params).personaId);
    return profile
      ? Response.json({ profile }, { headers: { "Cache-Control": "no-store" } })
      : jsonError("找不到 Persona", 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 读取失败";
    return jsonError(message, /无效/.test(message) ? 400 : 503);
  }
}

export async function PATCH(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改 Persona", 403);
  try {
    const { personaId } = await context.params;
    const payload = await readBoundedJson(request) as { operation?: unknown; files?: unknown; intro?: unknown; displayName?: unknown };

    if (payload.operation === "rename") {
      if (typeof payload.displayName !== "string") return jsonError("人设名称无效", 400);
      const profile = await renamePersona(personaId, payload.displayName);
      return Response.json({ profile }, { headers: { "Cache-Control": "no-store" } });
    }

    if (payload.operation === "updateFiles") {
      const files = parsePersonaFiles(payload.files);
      await writeAvatarPersonaFiles(personaId, files);
      const updated = await readPersonaProfile(personaId);
      return updated
        ? Response.json({ profile: updated }, { headers: { "Cache-Control": "no-store" } })
        : jsonError("找不到 Persona", 404);
    }

    if (payload.operation === "updateProfile") {
      const files = payload.files === undefined ? [] : parsePersonaFiles(payload.files);
      const intro = payload.intro === undefined ? undefined : normalizePersonaIntro(payload.intro);
      if (!files.length && intro === undefined) return jsonError("没有需要保存的 Persona 内容", 400);
      if (files.length) await writeAvatarPersonaFiles(personaId, files);
      if (intro !== undefined) await writePersonaIntro(personaId, intro);
      const updated = await readPersonaProfile(personaId);
      return updated
        ? Response.json({ profile: updated }, { headers: { "Cache-Control": "no-store" } })
        : jsonError("找不到 Persona", 404);
    }

    return jsonError("Persona 更新操作无效", 400);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 更新失败";
    return jsonError(message, personaErrorStatus(error, message));
  }
}

export async function DELETE(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许删除 Persona", 403);
  try {
    await archivePersona((await context.params).personaId);
    return Response.json({ archived: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 删除失败";
    return jsonError(message, personaErrorStatus(error, message));
  }
}
