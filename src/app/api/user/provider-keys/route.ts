import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { userFromRequest } from "@/lib/user-session";
import {
  deletePersonalKey,
  listPersonalKeyStatuses,
  parsePersonalKeyProvider,
  savePersonalKey,
} from "@/lib/user-provider-credentials";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

export async function GET(request: NextRequest) {
  try {
    const user = await userFromRequest(request);
    if (!user) return json({ error: "请先登录" }, 401);
    const platform = {
      anam: process.env.ANAM_API_KEY?.trim(),
      minimax: process.env.MINIMAX_API_KEY?.trim(),
      doubao: process.env.DOUBAO_API_KEY?.trim(),
      bella: process.env.API_KEY?.trim(),
      dashscope: process.env.DASHSCOPE_API_KEY?.trim(),
      deepseek: process.env.DEEPSEEK_API_KEY?.trim(),
      openai: process.env.OPENAI_API_KEY?.trim(),
    };
    const credentials = (await listPersonalKeyStatuses(user)).map((entry) => ({
      ...entry, platformConfigured: Boolean(platform[entry.provider]),
      ...(platform[entry.provider] ? { platformSuffix: platform[entry.provider]!.slice(-4) } : {}),
    }));
    return json({ credentials });
  } catch {
    return json({ error: "无法读取 API Key 状态" }, 503);
  }
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  try {
    const user = await userFromRequest(request);
    if (!user) return json({ error: "请先登录" }, 401);
    type KeyRequest = { provider?: unknown; apiKey?: unknown };
    let body: KeyRequest | null = null;
    try { body = await readLimitedJson(request, 2048) as KeyRequest | null; }
    catch (error) {
      if (error instanceof RequestBodyTooLarge) return json({ error: "API Key 请求内容过大" }, 413);
      return json({ error: "请求内容无效" }, 400);
    }
    const provider = parsePersonalKeyProvider(body?.provider);
    const key = body?.apiKey;
    if (!provider || typeof key !== "string" || key.length < 8 || key.length > 512
      || key !== key.trim() || /[\x00-\x1f\x7f]/.test(key)) {
      return json({ error: "请填写有效的 API Key" }, 400);
    }
    await savePersonalKey(user, provider, key);
    return json({ configured: true, suffix: key.slice(-4) });
  } catch {
    return json({ error: "保存 API Key 失败" }, 503);
  }
}

export async function DELETE(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  try {
    const user = await userFromRequest(request);
    if (!user) return json({ error: "请先登录" }, 401);
    const provider = parsePersonalKeyProvider(request.nextUrl.searchParams.get("provider"));
    if (!provider) return json({ error: "服务商无效" }, 400);
    await deletePersonalKey(user, provider);
    return json({ configured: false });
  } catch {
    return json({ error: "清空 API Key 失败" }, 503);
  }
}
