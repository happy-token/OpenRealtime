import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import {
  readAvatarPersonaProfile,
  switchAvatarPersona,
  writeAvatarPersonaFiles,
} from "@/lib/avatar-persona-server";
import { PersonaRequestError, parsePersonaFiles, personaErrorStatus, readBoundedJson } from "@/lib/persona-api-helpers";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ avatarId: string }> };

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Persona", 403);
  try {
    const profile = await readAvatarPersonaProfile((await context.params).avatarId);
    return profile
      ? Response.json({ profile }, { headers: { "Cache-Control": "no-store" } })
      : jsonError("Avatar 尚未关联 Persona", 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 读取失败";
    return jsonError(message, /无效/.test(message) ? 400 : 503);
  }
}

export async function PATCH(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改 Persona", 403);
  try {
    const { avatarId } = await context.params;
    const payload = await readBoundedJson(request) as {
      operation?: unknown;
      files?: unknown;
      personaId?: unknown;
      avatarDisplayName?: unknown;
    };

    if (payload.operation === "updateFiles") {
      const files = parsePersonaFiles(payload.files);
      const profile = await readAvatarPersonaProfile(avatarId);
      if (!profile) throw new PersonaRequestError("Avatar 尚未关联 Persona", 404);
      await writeAvatarPersonaFiles(profile.personaId, files);
      const updated = await readAvatarPersonaProfile(avatarId);
      return Response.json({ profile: updated }, { headers: { "Cache-Control": "no-store" } });
    }

    if (payload.operation === "switchPersona" && typeof payload.personaId === "string") {
      const avatarDisplayName = typeof payload.avatarDisplayName === "string" ? payload.avatarDisplayName : undefined;
      await switchAvatarPersona(avatarId, payload.personaId, avatarDisplayName);
      const updated = await readAvatarPersonaProfile(avatarId);
      return Response.json({ profile: updated }, { headers: { "Cache-Control": "no-store" } });
    }

    return jsonError("Persona 更新操作无效", 400);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Persona 更新失败";
    return jsonError(message, personaErrorStatus(error, message));
  }
}
