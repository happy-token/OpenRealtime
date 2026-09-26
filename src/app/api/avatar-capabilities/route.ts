import { avatarCapabilities } from "@/lib/avatar-capabilities";
import { authorizeAvatarAssetRequest } from "@/lib/avatar-assets-server";
import { currentAdmin } from "@/lib/admin-server";
import { avatarRendererIsReady } from "@/lib/avatar-renderer-health";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const capabilities = avatarCapabilities(
    request, authorizeAvatarAssetRequest(request, false), Boolean(await currentAdmin()),
  );
  if (capabilities.localRenderer.state === "available" && !await avatarRendererIsReady()) {
    capabilities.localRenderer = {
      state: "not_configured",
      message: "实时口型服务尚未启动或不可用，启动服务后才会显示实时口型选项。",
    };
  }
  return Response.json(capabilities, { headers: { "Cache-Control": "no-store", "Vary": "Cookie" } });
}
