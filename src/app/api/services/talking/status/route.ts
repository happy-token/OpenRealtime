import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { resolveProviderApiKey } from "@/lib/provider-api-key";
import { paidGenerationEnabled } from "@/lib/paid-generation-policy";
import { modelServiceConnections, probeModelService } from "@/lib/model-service-connections";

const run = promisify(execFile);
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取讲话服务状态", 403);
  const connections = await modelServiceConnections();
  let wav2lipReady = false;
  let wav2lipIssue = "Wav2Lip 运行环境尚未就绪";
  if (!connections.wav2lip.url) try {
    const script = path.join(process.cwd(), "scripts", "wav2lip_provider.py");
    const root = process.env.WAV2LIP_RUNTIME_ROOT || path.join(process.cwd(), "models", "wav2lip");
    const result = await run("python3", [script, "diagnose", "--runtime-root", root], { timeout: 15_000, maxBuffer: 64 * 1024 });
    const diagnostic = JSON.parse(result.stdout) as { ready?: boolean; issues?: string[] };
    wav2lipReady = diagnostic.ready === true;
    wav2lipIssue = diagnostic.issues?.[0] || wav2lipIssue;
  } catch (error) {
    if (error && typeof error === "object" && "stdout" in error && typeof error.stdout === "string") {
      try {
        const diagnostic = JSON.parse(error.stdout) as { issues?: string[] };
        wav2lipIssue = diagnostic.issues?.[0] || wav2lipIssue;
      } catch { /* Diagnostic output is optional. */ }
    }
  }
  const [wavRemote, museRemote, lipRemote] = await Promise.all([
    connections.wav2lip.url ? probeModelService("wav2lip", connections.wav2lip) : null,
    connections.musetalk.url ? probeModelService("musetalk", connections.musetalk) : null,
    connections.lipforcing.url ? probeModelService("lipforcing", connections.lipforcing) : null,
  ]);
  const generationEnabled = paidGenerationEnabled();
  const miniMaxReady = generationEnabled && Boolean(await resolveProviderApiKey(request, "minimax"));
  const lipForcingHost = process.env.LIPFORCING_API_URL || process.env.LIPFORCING_SSH_HOST || process.env.MUSETALK_SSH_HOST;
  const wavReady = wavRemote?.ready ?? wav2lipReady;
  const museReady = museRemote?.ready ?? Boolean(process.env.MUSETALK_SSH_HOST);
  const lipReady = lipRemote?.ready ?? Boolean(lipForcingHost);
  return Response.json({
    ready: wavReady || museReady || lipReady || miniMaxReady,
    methods: {
      wav2lip: { ready: wavReady, detail: wavRemote ? wavRemote.message : wav2lipReady ? "本地离线渲染可用" : wav2lipIssue },
      musetalk: { ready: museReady, detail: museRemote ? museRemote.message : process.env.MUSETALK_SSH_HOST ? "远端 GPU 已配置，任务状态以提交结果为准" : "尚未配置远端 GPU" },
      minimax: { ready: miniMaxReady, detail: miniMaxReady ? "MiniMax Key 已配置；以生成接口的状态为准" : !generationEnabled ? "生产付费任务尚未开放" : "尚未配置 MiniMax Key" },
      lipforcing: { ready: lipReady, detail: lipRemote ? lipRemote.message : lipForcingHost ? "远端 GPU 服务已配置，任务状态以提交结果为准" : "尚未配置 Lip Forcing GPU 服务" },
    },
  }, { headers: { "Cache-Control": "no-store" } });
}
