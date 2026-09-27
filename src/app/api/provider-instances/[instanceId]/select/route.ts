import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { providerActor, validInstanceId } from "@/lib/provider-instance-access";
import { ProviderInstanceNotReadyError, selectProviderInstance } from "@/lib/provider-instances";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Params = { params: Promise<{ instanceId: string }> };

export async function POST(request: NextRequest, { params }: Params) {
  if (!isSameOriginAvatarMutation(request)) return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  const { instanceId } = await params;
  if (!validInstanceId(instanceId)) return NextResponse.json({ error: "实例 ID 无效" }, { status: 400 });
  try {
    const actor = await providerActor(request);
    if (!actor) return NextResponse.json({ error: "请先登录" }, { status: 401 });
    const scope = request.nextUrl.searchParams.get("scope") ?? "personal";
    if (scope !== "personal" && scope !== "platform") return NextResponse.json({ error: "配置范围无效" }, { status: 400 });
    if (scope === "platform" && !actor.admin) return NextResponse.json({ error: "无权设置平台默认" }, { status: 403 });
    if (scope === "personal" && !actor.signedIn) return NextResponse.json({ error: "请先登录用户账号" }, { status: 401 });
    const instance = await selectProviderInstance(actor.user, instanceId, scope);
    return instance ? NextResponse.json({ instance }) : NextResponse.json({ error: "实例不可选" }, { status: 404 });
  } catch (error) { return error instanceof ProviderInstanceNotReadyError
    ? NextResponse.json({ error: error.message }, { status: 409 })
    : NextResponse.json({ error: "切换供应商失败" }, { status: 503 }); }
}
