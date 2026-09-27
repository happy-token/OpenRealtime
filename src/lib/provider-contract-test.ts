import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import { join } from "node:path";

export class ProviderContractUnavailableError extends Error {}

type Capability = "asr" | "tts";
type SpeechProvider = "doubao" | "dashscope";
type ProbeResult = { ok: boolean; message: string; firstOutputMs?: number };

function parseProbeResult(output: string): ProbeResult {
  const parsed = JSON.parse(output) as Partial<ProbeResult>;
  if (typeof parsed.ok !== "boolean" || typeof parsed.message !== "string" || parsed.message.length > 200) {
    throw new Error("invalid probe output");
  }
  return { ok: parsed.ok, message: parsed.message,
    ...(typeof parsed.firstOutputMs === "number" && Number.isFinite(parsed.firstOutputMs)
      ? { firstOutputMs: parsed.firstOutputMs } : {}) };
}

async function testOnVoiceControlPlane(base: string, body: string): Promise<ProbeResult> {
  let url: URL;
  try {
    url = new URL(base);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
      || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("invalid URL");
  } catch { throw new ProviderContractUnavailableError("语音测试服务地址必须是本机回环地址"); }
  const encodedKey = process.env.VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY;
  if (!encodedKey) throw new ProviderContractUnavailableError("语音测试服务缺少共享签名密钥");
  const key = Buffer.from(encodedKey, "base64url");
  if (key.length !== 32) throw new ProviderContractUnavailableError("语音测试服务签名密钥无效");
  const timestamp = String(Math.floor(Date.now() / 1000));
  const signature = createHmac("sha256", key)
    .update(`provider-contract-probe-v1\0${timestamp}\0${body}`).digest("hex");
  try {
    const response = await fetch(new URL("/provider-contract-test", url), {
      method: "POST", headers: { "Content-Type": "application/json",
        "X-Provider-Probe-Timestamp": timestamp, "X-Provider-Probe-Signature": signature },
      body, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(45_000),
    });
    if (!response.ok || !response.body) {
      throw new ProviderContractUnavailableError("语音实时测试服务暂不可用");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let output = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        output += decoder.decode(value, { stream: true });
        if (output.length > 4096) return { ok: false, message: "语音服务测试结果过大" };
      }
      output += decoder.decode();
    } finally { await reader.cancel().catch(() => {}); }
    return parseProbeResult(output);
  } catch (error) {
    if (error instanceof ProviderContractUnavailableError) throw error;
    throw new ProviderContractUnavailableError("无法连接语音实时测试服务");
  }
}

/** Run only the trusted built-in probe. Credentials travel over stdin, never argv or logs. */
export async function testProviderContract(
  capability: Capability, provider: SpeechProvider, apiKey: string,
  baseUrl?: string, model = "",
): Promise<ProbeResult> {
  if (!(["doubao", "dashscope"] as const).includes(provider)) {
    throw new ProviderContractUnavailableError("该供应商没有实时契约测试");
  }
  const controlPlane = process.env.VOICEAGENT_CONTROL_PLANE_URL;
  const fixtureKey = capability === "asr" ? process.env.DOUBAO_API_KEY : undefined;
  if (capability === "asr" && !fixtureKey && !controlPlane) {
    throw new ProviderContractUnavailableError("ASR 测试需要平台豆包 TTS 凭据生成测试音频");
  }
  const payload = JSON.stringify({ capability, provider, apiKey,
    ...(baseUrl ? { baseUrl } : {}), ...(model ? { model } : {}),
    ...(!controlPlane && fixtureKey ? { fixtureTtsKey: fixtureKey } : {}) });
  if (controlPlane) {
    return testOnVoiceControlPlane(controlPlane, payload);
  }
  const python = process.env.VOICEAGENT_PYTHON_EXECUTABLE || join(process.cwd(), ".venv/bin/python");
  const permittedEnv = ["PATH", "DOUBAO_RESOURCE_ID", "DASHSCOPE_WORKSPACE_ID", "BAILIAN_TTS_MODEL",
    "BAILIAN_TTS_VOICE", "BAILIAN_TTS_INSTRUCTION", "BAILIAN_API_HOST", "BAILIAN_TTS_WS_URL"];
  const env: NodeJS.ProcessEnv = { NODE_ENV: process.env.NODE_ENV ?? "production" };
  for (const name of permittedEnv) {
    if (process.env[name]) env[name] = process.env[name];
  }

  return await new Promise<ProbeResult>((resolve, reject) => {
    const child = spawn(python, ["-m", "server.speech.provider_contract_probe"], {
      cwd: process.cwd(), env, stdio: ["pipe", "pipe", "ignore"], windowsHide: true,
    });
    let output = "";
    let oversized = false;
    let settled = false;
    const finish = (error?: Error, result?: ProbeResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (error) reject(error); else resolve(result ?? { ok: false, message: "能力测试失败" });
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish(undefined, { ok: false, message: "能力测试超时" });
    }, 45_000);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      if (oversized) return;
      if (chunk.length > 4096 - output.length) {
        oversized = true;
        child.kill("SIGKILL");
        return;
      }
      output += chunk;
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      finish(error.code === "ENOENT"
        ? new ProviderContractUnavailableError("当前服务未安装实时能力测试运行环境")
        : new ProviderContractUnavailableError("实时能力测试运行环境不可用"));
    });
    child.on("close", (code) => {
      if (oversized || code !== 0) { finish(undefined, { ok: false, message: "能力测试未完成" }); return; }
      try {
        finish(undefined, parseProbeResult(output));
      } catch { finish(undefined, { ok: false, message: "能力测试结果无效" }); }
    });
    child.stdin.on("error", () => {});
    child.stdin.end(payload);
  });
}
