import { authorizeAvatarAssetRequest, jsonError } from "./avatar-assets-server";
import { isSameOriginAvatarMutation } from "./avatar-test-access";
import { userFromRequest } from "./user-session";

export async function conversationOwner(request: Request, mutation = false): Promise<string | Response> {
  if (mutation && !isSameOriginAvatarMutation(request)) return jsonError("请求来源无效", 403);
  const user = await userFromRequest(request);
  if (user) return `${user.issuer}#${user.subject}`;
  if (authorizeAvatarAssetRequest(request, mutation)) return "local-user";
  if (!mutation && process.env.NODE_ENV === "development"
    && process.env.AVATAR_LOCAL_TEST_MODE === "true"
    && process.env.AVATAR_EVALUATION_LOOPBACK_BOUND === "true"
    && ["localhost", "127.0.0.1", "[::1]"].includes(new URL(request.url).hostname)) return "local-user";
  return jsonError("请先登录以使用对话历史", 401);
}
