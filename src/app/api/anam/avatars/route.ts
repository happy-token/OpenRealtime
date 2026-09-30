import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "@/lib/avatar-test-access";
import {
  AnamAvatarError,
  createAnamAvatar,
  listAnamAvatars,
  updateAnamAvatarName,
} from "@/lib/anam-avatars";
import { hasMatchingImageSignature } from "@/lib/media-signatures";
import { resolveProviderApiKey } from "@/lib/provider-api-key";
import { userFromRequest } from "@/lib/user-session";
import { loadPersonalKey } from "@/lib/user-provider-credentials";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_ANAM_IMAGE_BYTES = 4_500_000;

export async function GET(request: NextRequest) {
  const admin = canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const user = admin ? null : await userFromRequest(request);
  if (!admin && !user) {
    return json({ error: "不允许从当前来源同步 Anam 形象目录" }, 403);
  }
  try {
    const personalKey = user ? await loadPersonalKey(user, "anam") : null;
    const platformKey = process.env.ANAM_API_KEY?.trim();
    const catalog = await listAnamAvatars({ ANAM_API_KEY: personalKey ?? await resolveProviderApiKey(request, "anam") });
    const platformCatalog = personalKey && platformKey && platformKey !== personalKey
      ? await listAnamAvatars({ ANAM_API_KEY: platformKey }).catch(() => null)
      : null;
    const avatars = platformCatalog
      ? [...catalog.avatars, ...platformCatalog.avatars.filter((avatar) => !catalog.avatars.some((owned) => owned.id === avatar.id))
        .map((avatar) => ({ ...avatar, origin: "official" as const }))]
      : catalog.avatars;
    return json({
      configured: true,
      connected: true,
      avatars,
      total: avatars.length,
      defaultAvatarId: process.env.ANAM_AVATAR_ID?.trim() || null,
      syncedAt: new Date().toISOString(),
    });
  } catch (error) {
    const known = error instanceof AnamAvatarError;
    return json({
      configured: false,
      connected: false,
      error: known ? error.message : "Anam 形象目录同步失败",
    }, known ? error.status : 500);
  }
}

export async function POST(request: NextRequest) {
  const admin = canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const user = admin ? null : await userFromRequest(request);
  if (
    (!admin && !user)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源创建 Anam 形象" }, 403);
  }
  const contentLength = Number(request.headers.get("content-length"));
  if (!Number.isFinite(contentLength) || contentLength <= 0) {
    return json({ error: "请求缺少有效的 Content-Length" }, 411);
  }
  if (contentLength > MAX_ANAM_IMAGE_BYTES + 64 * 1024) {
    return json({ error: "Anam 身份源图不能超过 4.5MB" }, 413);
  }
  try {
    const personalKey = user ? await loadPersonalKey(user, "anam") : null;
    if (user && !personalKey) return json({ error: "请先配置个人 Anam API Key" }, 403);
    const form = await request.formData();
    const displayName = form.get("displayName");
    const image = form.get("image");
    if (typeof displayName !== "string") return json({ error: "请填写 Anam 形象名称" }, 400);
    if (!(image instanceof File) || !ALLOWED_IMAGE_TYPES.has(image.type)) {
      return json({ error: "仅支持 JPEG、PNG 或 WebP 身份源图" }, 400);
    }
    if (!image.size || image.size > MAX_ANAM_IMAGE_BYTES) {
      return json({ error: "Anam 身份源图不能为空且不能超过 4.5MB" }, 400);
    }
    const bytes = new Uint8Array(await image.arrayBuffer());
    if (!hasMatchingImageSignature(image.type, bytes)) {
      return json({ error: "身份源图内容与文件类型不匹配" }, 400);
    }
    if (personalKey) {
      const existing = await listAnamAvatars({ ANAM_API_KEY: personalKey });
      if (existing.avatars.some((avatar) => avatar.origin === "personal")) {
        return json({ error: "当前 Anam 账号已有一个自建形象，请在形象库选择已有形象" }, 409);
      }
    }
    const avatar = await createAnamAvatar(
      { ANAM_API_KEY: personalKey ?? await resolveProviderApiKey(request, "anam") },
      {
        displayName,
        image,
        avatarModel: process.env.ANAM_AVATAR_MODEL?.trim() || undefined,
      },
    );
    return json({ avatar }, 201);
  } catch (error) {
    const known = error instanceof AnamAvatarError;
    return json(
      { error: known ? error.message : "Anam 形象创建失败" },
      known ? error.status : 500,
    );
  }
}

export async function PUT(request: NextRequest) {
  const admin = canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const user = admin ? null : await userFromRequest(request);
  if (
    (!admin && !user)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源修改 Anam 形象" }, 403);
  }
  try {
    const personalKey = user ? await loadPersonalKey(user, "anam") : null;
    if (user && !personalKey) return json({ error: "请先配置个人 Anam API Key" }, 403);
    const payload = await request.json() as { avatarId?: unknown; displayName?: unknown };
    if (typeof payload.avatarId !== "string" || typeof payload.displayName !== "string") {
      return json({ error: "请提供要修改的 Anam 形象和新名称" }, 400);
    }
    const avatar = await updateAnamAvatarName(
      { ANAM_API_KEY: personalKey ?? await resolveProviderApiKey(request, "anam") },
      { avatarId: payload.avatarId, displayName: payload.displayName },
    );
    return json({ avatar });
  } catch (error) {
    const known = error instanceof AnamAvatarError;
    return json(
      { error: known ? error.message : "Anam 形象名称修改失败" },
      known ? error.status : 500,
    );
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}
