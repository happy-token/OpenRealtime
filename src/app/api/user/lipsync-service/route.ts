import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";
import {
  deleteUserLipsyncService, loadUserLipsyncService, normalizePersonalLipsyncToken,
  normalizePersonalLipsyncUrl, probeUserLipsyncService, saveUserLipsyncService,
} from "@/lib/user-lipsync-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: Request) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const service = await loadUserLipsyncService(user);
    return json({ configured: Boolean(service), url: service?.url ?? "", tokenConfigured: Boolean(service?.token) });
  } catch { return json({ error: "读取口型服务配置失败" }, 503); }
}

export async function PUT(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  let url: string;
  let token: string | undefined;
  try {
    const body = await readLimitedJson(request, 4096) as { url?: unknown; token?: unknown };
    url = normalizePersonalLipsyncUrl(body?.url);
    token = body.token === undefined ? undefined : normalizePersonalLipsyncToken(body.token);
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    return json({ error: error instanceof Error ? error.message : "配置格式无效" }, 400);
  }
  try {
    await saveUserLipsyncService(user, url, token);
    const saved = await loadUserLipsyncService(user);
    return json({ configured: true, url, tokenConfigured: Boolean(saved?.token) });
  } catch { return json({ error: "保存口型服务失败" }, 503); }
}

export async function POST(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const service = await loadUserLipsyncService(user);
    if (!service) return json({ error: "请先保存口型服务" }, 400);
    const ready = await probeUserLipsyncService(service);
    return json({ ready, message: ready ? "口型服务已就绪" : "服务未就绪，请检查地址或令牌" });
  } catch { return json({ ready: false, message: "服务连接失败，请检查地址或令牌" }); }
}

export async function DELETE(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try { await deleteUserLipsyncService(user); return json({ configured: false }); }
  catch { return json({ error: "删除失败" }, 503); }
}
