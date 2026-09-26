import { userDatabase } from "@/lib/user-db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const ready = new URL(request.url).searchParams.get("ready") === "1";
  if (ready) {
    try {
      await userDatabase().query("SELECT 1");
    } catch {
      return Response.json({ status: "unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
    }
  }
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
