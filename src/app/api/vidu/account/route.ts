import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis } from "@/lib/avatar-test-access";
import { getViduCredits, ViduProviderError, viduConfig } from "@/lib/vidu-video";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取 Vidu 状态" }, 403);
  }
  try {
    const environment = {
      VIDU_API_KEY: process.env.VIDU_API_KEY,
      VIDU_API_URL: process.env.VIDU_API_URL,
    };
    const credits = await getViduCredits(environment);
    const apiUrl = viduConfig(environment).apiUrl;
    const region = apiUrl.endsWith(".cn") ? "cn" : apiUrl.endsWith(".com") ? "com" : "custom";
    return json({ configured: true, connected: true, credits, region });
  } catch (error) {
    const known = error instanceof ViduProviderError;
    return json(
      {
        configured: Boolean(process.env.VIDU_API_KEY?.trim()),
        connected: false,
        error: known ? error.message : "Vidu 状态检查失败",
      },
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
