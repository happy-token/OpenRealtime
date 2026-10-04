import { NextRequest, NextResponse } from "next/server";
import { isAppAdmin } from "@/lib/app-admin-accounts";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const user = await userFromRequest(request);
    const isAdmin = user ? await isAppAdmin(user) : false;
    return NextResponse.json({ isAdmin }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ isAdmin: false }, { status: 503 });
  }
}
