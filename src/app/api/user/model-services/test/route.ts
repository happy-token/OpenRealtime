import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { probeModelService } from "@/lib/model-service-connections";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { loadUserLipsyncService, normalizePersonalLipsyncToken, normalizePersonalLipsyncUrl } from "@/lib/user-lipsync-service";
import { loadUserTalkingService } from "@/lib/user-talking-model-services";
import { userFromRequest } from "@/lib/user-session";
import { isPersonalModelKind } from "@/lib/personal-model-kind";

export const runtime = "nodejs";
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

export async function POST(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const body = await readLimitedJson(request, 4096) as { kind?: unknown; url?: unknown; token?: unknown };
    if (!isPersonalModelKind(body?.kind)) return json({ error: "未知的个人模型服务" }, 400);
    const saved = body.kind === "lipforcing" ? await loadUserLipsyncService(user) : await loadUserTalkingService(user, body.kind);
    const url = body.url === undefined ? saved?.url ?? "" : normalizePersonalLipsyncUrl(body.url);
    const token = body.token === undefined ? (url === saved?.url ? saved?.token ?? "" : "") : normalizePersonalLipsyncToken(body.token);
    return json(await probeModelService(body.kind, { url, token }));
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    return json({ error: error instanceof Error ? error.message : "连接测试失败" }, 400);
  }
}
