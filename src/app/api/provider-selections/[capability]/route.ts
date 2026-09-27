import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor } from "@/lib/provider-instance-access";
import { clearProviderSelection, parseBuiltinProvider, parseProviderCapability, selectPlatformEnvironmentProvider } from "@/lib/provider-instances";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Params = { params: Promise<{ capability: string }> };

export async function POST(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  const capability = parseProviderCapability((await params).capability);
  if (!capability) return NextResponse.json({ error: "能力类型无效" }, { status: 400 });
  const scope = request.nextUrl.searchParams.get("scope") ?? "personal";
  if (scope !== "personal" && scope !== "platform") return NextResponse.json({ error: "配置范围无效" }, { status: 400 });
  try {
    const actor = await providerActor(request);
    if (!actor) return NextResponse.json({ error: "请先登录" }, { status: 401 });
    if (scope === "platform" && !actor.admin) return NextResponse.json({ error: "无权设置平台默认" }, { status: 403 });
    if (scope === "personal" && !actor.signedIn) return NextResponse.json({ error: "请先登录用户账号" }, { status: 401 });
    let body: unknown;
    try { body = await readLimitedJson(request, 256); }
    catch (error) { return NextResponse.json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" },
      { status: error instanceof RequestBodyTooLarge ? 413 : 400 }); }
    const provider = parseBuiltinProvider(body && typeof body === "object" ? (body as Record<string, unknown>).provider : null, capability);
    if (!provider) return NextResponse.json({ error: "供应商无效" }, { status: 400 });
    const selected = await selectPlatformEnvironmentProvider(actor.user, capability, provider, scope);
    return selected ? NextResponse.json({ selected: true }, { headers: { "Cache-Control": "no-store" } })
      : NextResponse.json({ error: "平台尚未配置该供应商" }, { status: 404 });
  } catch { return NextResponse.json({ error: "切换供应商失败" }, { status: 503 }); }
}

export async function DELETE(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  const capability = parseProviderCapability((await params).capability);
  if (!capability) return NextResponse.json({ error: "能力类型无效" }, { status: 400 });
  const scope = request.nextUrl.searchParams.get("scope") ?? "personal";
  if (scope !== "personal" && scope !== "platform") return NextResponse.json({ error: "配置范围无效" }, { status: 400 });
  try {
    const actor = await providerActor(request);
    if (!actor) return NextResponse.json({ error: "请先登录" }, { status: 401 });
    if (scope === "platform" && !actor.admin) return NextResponse.json({ error: "无权修改平台默认" }, { status: 403 });
    if (scope === "personal" && !actor.signedIn) return NextResponse.json({ error: "请先登录用户账号" }, { status: 401 });
    const cleared = await clearProviderSelection(actor.user, capability, scope);
    return NextResponse.json({ cleared }, { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "恢复默认供应商失败" }, { status: 503 }); }
}
