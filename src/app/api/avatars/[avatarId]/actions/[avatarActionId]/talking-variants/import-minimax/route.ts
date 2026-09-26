import { createHash } from "node:crypto";
import { mkdir, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { NextRequest } from "next/server";
import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { attachTalkingVariant, findOwnedAvatar } from "@/lib/avatar-catalog-repository";
import { isMiniMaxModelId } from "@/lib/ltx-avatar-action";
import { downloadLtxResultVideo } from "@/lib/ltx-result-video";
import { getTrustedLocalLtxTask } from "@/lib/ltx-task-coordinator";
import { readTalkingSource } from "@/lib/musetalk-talking-worker";
import { resolveProviderApiKey, providerKeyFingerprint } from "@/lib/provider-api-key";
import { getVideoGeneration } from "@/lib/video-generation-provider";
import type { AvatarTalkingVariant } from "@/lib/avatar-records";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ avatarId: string; avatarActionId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许保存口型对齐", 403);
  try {
    const { avatarId, avatarActionId } = await context.params;
    const payload = await request.json() as { taskId?: unknown };
    if (typeof payload.taskId !== "string" || payload.taskId.length > 128) return jsonError("生成任务 ID 无效", 400);
    const avatar = await findOwnedAvatar(avatarId);
    const action = avatar?.actions.find(item => item.avatar_action_id === avatarActionId && !item.deleted_at);
    if (!avatar || avatar.deleted_at || !action?.video_url) return jsonError("找不到可用动作底片", 404);

    const trusted = getTrustedLocalLtxTask(payload.taskId);
    if (!trusted || trusted.visualIdentityId !== avatarId || !isMiniMaxModelId(trusted.model)) return jsonError("MiniMax 生成任务与数字人不匹配", 404);
    if (!trusted.referenceVideoSha256 || trusted.referenceVideoSha256 !== createHash("sha256").update(await readTalkingSource(action.video_url)).digest("hex")) {
      return jsonError("MiniMax 参考底片与当前动作不匹配", 409);
    }
    const miniMaxKey = await resolveProviderApiKey(request, "minimax");
    if (trusted.credentialFingerprint !== (miniMaxKey ? providerKeyFingerprint(miniMaxKey) : undefined)) return jsonError("请使用创建任务时的 MiniMax API Key 保存结果", 403);
    const task = await getVideoGeneration({
      LTX_API_KEY: process.env.LTX_API_KEY,
      LTX_API_URL: process.env.LTX_API_URL,
      MINIMAX_API_KEY: miniMaxKey,
      MINIMAX_API_URL: process.env.MINIMAX_API_URL,
    }, payload.taskId, trusted.model);
    if (task.state !== "success" || !task.videoUrl) return jsonError("口型对齐生成结果尚未就绪", 409);
    const result = await downloadLtxResultVideo(task.videoUrl);
    if (result.mediaType !== "video/mp4") return jsonError("口型对齐需为 MP4 视频", 400);

    const id = `minimax-${createHash("sha256").update(payload.taskId).digest("hex").slice(0, 32)}`;
    const folder = path.join(process.cwd(), "public", "digital-human", "talking-variants");
    const file = path.join(folder, `${id}.mp4`);
    await mkdir(folder, { recursive: true });
    let created = false;
    try {
      await writeFile(file, result.bytes, { flag: "wx", mode: 0o600 });
      created = true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
    const variant: AvatarTalkingVariant = {
      id,
      display_name: `${action.display_name.slice(0, 75)} · MiniMax`,
      method: "minimax",
      source_video_url: action.video_url,
      video_url: `/digital-human/talking-variants/${id}.mp4`,
      processing: "original",
      validation: "pending",
    };
    try {
      return Response.json({ action: await attachTalkingVariant(avatarId, avatarActionId, variant), variant }, { headers: { "Cache-Control": "no-store" } });
    } catch (error) {
      if (created) await unlink(file).catch(() => undefined);
      throw error;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "保存 MiniMax 口型对齐失败";
    return jsonError(message, message.includes("找不到") ? 404 : message.includes("无效") || message.includes("不匹配") ? 400 : 503);
  }
}
