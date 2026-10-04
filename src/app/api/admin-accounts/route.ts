import { currentAppAdmin, isAuthorizedForAdminAccountManagement } from "@/lib/admin-server";
import { grantAppAdmin, listAppAdmins, revokeAppAdmin } from "@/lib/app-admin-accounts";
import { jsonError } from "@/lib/avatar-assets-server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { findUserBySubject } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };

async function authorizationError(request: Request): Promise<Response | null> {
  try {
    return await isAuthorizedForAdminAccountManagement(request) ? null : jsonError("未授权", 403);
  } catch {
    return jsonError("管理员权限服务暂时不可用", 503);
  }
}

async function actorIdentity(request: Request): Promise<string | null> {
  const appAdmin = await currentAppAdmin(request);
  if (appAdmin) return appAdmin.subject;
  return null;
}

export async function GET(request: Request) {
  const denied = await authorizationError(request);
  if (denied) return denied;
  try {
    return Response.json({ admins: await listAppAdmins() }, { headers });
  } catch {
    return jsonError("管理员列表读取失败", 503);
  }
}

export async function POST(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return jsonError("请求来源无效", 403);
  const denied = await authorizationError(request);
  if (denied) return denied;
  let body: { subject?: unknown; issuer?: unknown };
  try {
    body = await readLimitedJson(request, 1024) as typeof body;
  } catch (error) {
    return jsonError(error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效", error instanceof RequestBodyTooLarge ? 413 : 400);
  }
  const subject = typeof body?.subject === "string" ? body.subject.trim() : "";
  if (!subject) return jsonError("请输入账号 ID", 400);
  if (body.issuer !== undefined && (typeof body.issuer !== "string" || !body.issuer.trim())) return jsonError("身份来源无效", 400);
  const issuer = typeof body.issuer === "string" ? body.issuer.trim() : undefined;
  try {
    const target = await findUserBySubject(subject, issuer);
    if (!target) return jsonError("找不到该账号，请确认账号 ID 并确保该账号已登录过一次", 404);
    const grantedBy = await actorIdentity(request);
    if (!grantedBy) return jsonError("未授权", 403);
    await grantAppAdmin(target, grantedBy);
    return Response.json({ admins: await listAppAdmins() }, { headers });
  } catch (error) {
    if (error instanceof Error && error.message.includes("多个身份来源")) return jsonError(error.message, 400);
    return jsonError("设置管理员失败", 503);
  }
}

export async function DELETE(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return jsonError("请求来源无效", 403);
  const denied = await authorizationError(request);
  if (denied) return denied;
  let body: { subject?: unknown; issuer?: unknown };
  try {
    body = await readLimitedJson(request, 1024) as typeof body;
  } catch (error) {
    return jsonError(error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效", error instanceof RequestBodyTooLarge ? 413 : 400);
  }
  const subject = typeof body?.subject === "string" ? body.subject.trim() : "";
  if (!subject) return jsonError("请输入账号 ID", 400);
  if (body.issuer !== undefined && (typeof body.issuer !== "string" || !body.issuer.trim())) return jsonError("身份来源无效", 400);
  const issuer = typeof body.issuer === "string" ? body.issuer.trim() : undefined;
  try {
    const admins = await listAppAdmins();
    const matches = admins.filter((admin) => admin.subject === subject && (!issuer || admin.issuer === issuer));
    if (matches.length > 1) return jsonError("账号 ID 对应多个身份来源，请填写 issuer", 400);
    const target = matches[0];
    if (!target) return jsonError("该账号不是管理员", 404);
    const outcome = await revokeAppAdmin(target);
    if (outcome === "last-admin") return jsonError("不能移除最后一个管理员账号", 400);
    if (outcome === "not-found") return jsonError("该账号不是管理员", 404);
    return Response.json({ admins: await listAppAdmins() }, { headers });
  } catch {
    return jsonError("移除管理员失败", 503);
  }
}
