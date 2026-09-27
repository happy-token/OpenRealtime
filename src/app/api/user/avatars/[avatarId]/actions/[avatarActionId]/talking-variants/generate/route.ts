import { getPersonalTalking, postPersonalTalking } from "@/lib/personal-talking-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };

export async function GET(request: Request, context: Context) {
  return getPersonalTalking(request, context, "musetalk");
}

export async function POST(request: Request, context: Context) {
  return postPersonalTalking(request, context, "musetalk");
}
