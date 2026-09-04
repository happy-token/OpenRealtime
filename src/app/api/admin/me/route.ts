import { NextResponse } from "next/server";
import { currentAdmin } from "@/lib/admin-server";

export async function GET() {
  const admin = await currentAdmin();
  return admin
    ? NextResponse.json(admin)
    : NextResponse.json({ error: "未登录" }, { status: 401 });
}
