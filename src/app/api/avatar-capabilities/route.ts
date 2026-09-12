import { avatarCapabilities } from "@/lib/avatar-capabilities";
import { authorizeAvatarAssetRequest } from "@/lib/avatar-assets-server";
import { currentAdmin } from "@/lib/admin-server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  return Response.json(avatarCapabilities(
    request, authorizeAvatarAssetRequest(request, false), Boolean(await currentAdmin()),
  ), { headers: { "Cache-Control": "no-store", "Vary": "Cookie" } });
}
