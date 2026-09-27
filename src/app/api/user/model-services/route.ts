import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { deleteUserLipsyncService, loadUserLipsyncService, normalizePersonalLipsyncToken, normalizePersonalLipsyncUrl, saveUserLipsyncService } from "@/lib/user-lipsync-service";
import { deleteUserTalkingService, isPersonalTalkingKind, listUserTalkingServices, saveUserTalkingService } from "@/lib/user-talking-model-services";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

function isPersonalModelKind(value: unknown): value is "lipforcing" | "musetalk" | "wav2lip" {
  return value === "lipforcing" || isPersonalTalkingKind(value);
}

export async function GET(request: Request) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const [lipforcing, others] = await Promise.all([loadUserLipsyncService(user), listUserTalkingServices(user)]);
    const services = Object.fromEntries(Object.entries({ lipforcing, ...others }).map(([kind, connection]) => [kind, {
      url: connection?.url ?? "", tokenConfigured: Boolean(connection?.token),
    }]));
    return json({ services });
  } catch { return json({ error: "读取个人模型服务失败" }, 503); }
}

export async function PATCH(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  let body: { kind?: unknown; url?: unknown; token?: unknown };
  try { body = await readLimitedJson(request, 4096) as typeof body; }
  catch (error) { return json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, error instanceof RequestBodyTooLarge ? 413 : 400); }
  if (!isPersonalModelKind(body?.kind)) return json({ error: "未知的个人模型服务" }, 400);
  try {
    if (body.url === "") {
      if (body.kind === "lipforcing") await deleteUserLipsyncService(user);
      else await deleteUserTalkingService(user, body.kind);
      return json({ kind: body.kind, url: "", tokenConfigured: false });
    }
    const url = normalizePersonalLipsyncUrl(body.url);
    const token = body.token === undefined ? undefined : normalizePersonalLipsyncToken(body.token);
    if (body.kind === "lipforcing") {
      await saveUserLipsyncService(user, url, token);
      const saved = await loadUserLipsyncService(user);
      return json({ kind: body.kind, url, tokenConfigured: Boolean(saved?.token) });
    }
    const saved = await saveUserTalkingService(user, body.kind, url, token);
    return json({ kind: body.kind, url: saved.url, tokenConfigured: Boolean(saved.token) });
  } catch (error) {
    if (error instanceof Error && /^(请输入|口型服务必须|此口型服务域名|服务令牌格式)/.test(error.message)) return json({ error: error.message }, 400);
    return json({ error: "保存个人模型服务失败" }, 503);
  }
}

export { isPersonalModelKind };
