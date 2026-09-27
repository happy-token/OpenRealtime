import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor, validInstanceId } from "@/lib/provider-instance-access";
import { deleteProviderInstance, updateProviderInstance, validateProviderInstanceInput } from "@/lib/provider-instances";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Params = { params: Promise<{ instanceId: string }> };
const json = (value: object, status = 200) => NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });

export async function PATCH(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const { instanceId } = await params;
  if (!validInstanceId(instanceId)) return json({ error: "实例 ID 无效" }, 400);
  try {
    const actor = await providerActor(request);
    if (!actor) return json({ error: "请先登录" }, 401);
    let body: unknown;
    try { body = await readLimitedJson(request, 2048); }
    catch (error) { return json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, error instanceof RequestBodyTooLarge ? 413 : 400); }
    const input = validateProviderInstanceInput(body, true);
    const scope = body && typeof body === "object" && "scope" in body ? body.scope : "personal";
    if (!input || (scope !== "personal" && scope !== "platform")) return json({ error: "供应商配置无效" }, 400);
    if (scope === "platform") return json({ error: "平台配置为只读，不可编辑" }, 403);
    if (scope === "personal" && !actor.signedIn) return json({ error: "请先登录用户账号" }, 401);
    const instance = await updateProviderInstance(actor.user, scope, instanceId, input);
    return instance ? json({ instance }) : json({ error: "实例不存在" }, 404);
  } catch (error) {
    return error instanceof Error && (error.message === "供应商能力和类型不可修改，请新建实例"
      || error.message === "配置已被其他操作修改，请刷新后重试")
      ? json({ error: error.message }, 409) : json({ error: "更新供应商实例失败" }, 503);
  }
}

export async function DELETE(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const { instanceId } = await params;
  if (!validInstanceId(instanceId)) return json({ error: "实例 ID 无效" }, 400);
  try {
    const actor = await providerActor(request);
    if (!actor) return json({ error: "请先登录" }, 401);
    const scope = request.nextUrl.searchParams.get("scope") ?? "personal";
    if (scope !== "personal" && scope !== "platform") return json({ error: "配置范围无效" }, 400);
    if (scope === "platform") return json({ error: "平台配置为只读，不可删除" }, 403);
    if (scope === "personal" && !actor.signedIn) return json({ error: "请先登录用户账号" }, 401);
    return await deleteProviderInstance(actor.user, scope, instanceId) ? json({ deleted: true }) : json({ error: "实例不存在" }, 404);
  } catch (error) {
    return error instanceof Error && error.message === "请先切换正在使用的实例，再删除此配置"
      ? json({ error: error.message }, 409) : json({ error: "删除供应商实例失败" }, 503);
  }
}
