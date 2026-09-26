import { authorizeAvatarAssetRequest, jsonError } from "./avatar-assets-server";
import { isSameOriginAvatarMutation } from "./avatar-test-access";
import { userFromRequest } from "./user-session";

export async function knowledgeOwner(request: Request, mutation = false): Promise<string | Response> {
  if (mutation && !isSameOriginAvatarMutation(request)) return jsonError("请求来源无效", 403);
  const user = await userFromRequest(request);
  if (user) return `${user.issuer}#${user.subject}`;
  if (authorizeAvatarAssetRequest(request, mutation)) return "local-user";
  return jsonError("请先登录以使用私人知识库", 401);
}
