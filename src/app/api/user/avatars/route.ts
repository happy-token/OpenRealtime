import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { createPersonalAvatar, listPersonalAvatars } from "@/lib/personal-avatar-library";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (value: object, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: NextRequest) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    return json({ avatars: await listPersonalAvatars(user) });
  } catch {
    return json({ error: "个人数字人目录暂时不可用" }, 503);
  }
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const length = Number(request.headers.get("content-length"));
  if (!Number.isFinite(length) || length <= 0) return json({ error: "请求缺少有效大小" }, 411);
  if (length > 4_600_000) return json({ error: "图片不能超过 4.5MB" }, 413);
  try {
    const form = await request.formData();
    const name = form.get("name");
    const image = form.get("image");
    if (typeof name !== "string" || !(image instanceof File)) return json({ error: "请提供名称和图片" }, 400);
    const avatar = await createPersonalAvatar(user, name, image.type, new Uint8Array(await image.arrayBuffer()));
    return json({ avatar }, 201);
  } catch (error) {
    const message = error instanceof Error ? error.message : "个人数字人创建失败";
    return json({ error: message }, /无效|超过|名称|上限/.test(message) ? 400 : 503);
  }
}
