import { NextRequest, NextResponse } from "next/server";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const user = await userFromRequest(request);
    return NextResponse.json(user ? { signedIn: true, user } : { signedIn: false }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ signedIn: false }, { status: 503 });
  }
}
