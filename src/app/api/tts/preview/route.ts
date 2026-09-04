import { NextRequest, NextResponse } from "next/server";

const CONTROL_PLANE_URL =
  process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";

export async function GET(request: NextRequest) {
  const target = new URL("/tts/preview", CONTROL_PLANE_URL);
  target.search = request.nextUrl.search;
  try {
    const response = await fetch(target, { cache: "force-cache" });
    const body = await response.arrayBuffer();
    return new NextResponse(body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "application/json",
        "Cache-Control": response.headers.get("cache-control") ?? "no-store",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "语音试听服务暂不可用",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 503 },
    );
  }
}
