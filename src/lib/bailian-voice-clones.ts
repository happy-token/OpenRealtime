export interface BailianClonedVoice {
  id: string;
  displayName: string;
  status: "OK" | "UNDEPLOYED" | "UNKNOWN";
  createdAt: string | null;
}

export function mergeBailianClonedVoiceCatalog(
  activeEnvironmentVoice: BailianClonedVoice,
  providerVoices: BailianClonedVoice[],
) {
  const activeName = normalizeVoiceDisplayName(activeEnvironmentVoice.displayName);
  const providerHasActiveVoice = providerVoices.some((voice) => (
    voice.id === activeEnvironmentVoice.id
    || normalizeVoiceDisplayName(voice.displayName) === activeName
  ));
  return providerHasActiveVoice ? providerVoices : [activeEnvironmentVoice, ...providerVoices];
}

interface ProviderVoice {
  voice_id?: unknown;
  status?: unknown;
  gmt_create?: unknown;
}

const VOICE_ID_PATTERN = /^[A-Za-z0-9._-]{2,128}$/;
type Environment = Readonly<Record<string, string | undefined>>;

export function resolveBailianCloneEndpoint(environment: Environment = process.env) {
  const configured = environment.BAILIAN_API_HOST?.trim();
  const workspaceId = environment.DASHSCOPE_WORKSPACE_ID?.trim();
  const host = configured
    ? configured.replace(/^https?:\/\//, "").split("/", 1)[0]
    : workspaceId
      ? `${workspaceId}.cn-beijing.maas.aliyuncs.com`
      : "dashscope.aliyuncs.com";
  return `https://${host}/api/v1/services/audio/tts/customization`;
}

export function voiceCloneConfiguration(environment: Environment = process.env) {
  const required = [
    "DASHSCOPE_API_KEY",
    "S3_ENDPOINT_URL",
    "S3_BUCKET",
    "S3_AK",
    "S3_SK",
    "S3_PUBLIC_BASE_URL",
  ] as const;
  const missing = required.filter((name) => !environment[name]?.trim());
  return {
    configured: missing.length === 0,
    missing,
    targetModel: environment.BAILIAN_VOICE_CLONE_MODEL?.trim()
      || environment.BAILIAN_TTS_MODEL?.trim()
      || "cosyvoice-v3-flash",
  };
}

export async function listBailianClonedVoices(
  labels: Record<string, string>,
  environment: Environment = process.env,
  fetchImpl: typeof fetch = fetch,
): Promise<BailianClonedVoice[]> {
  const apiKey = environment.DASHSCOPE_API_KEY?.trim();
  if (!apiKey) return [];
  const response = await fetchImpl(resolveBailianCloneEndpoint(environment), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "voice-enrollment",
      input: { action: "list_voice", page_index: 0, page_size: 100 },
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await response.json().catch(() => null) as {
    output?: { voice_list?: ProviderVoice[] };
    message?: string;
    code?: string;
  } | null;
  if (!response.ok) {
    throw new Error(payload?.message || payload?.code || `Bailian voice list failed (${response.status})`);
  }
  const list = Array.isArray(payload?.output?.voice_list) ? payload.output.voice_list : [];
  return list.flatMap((voice) => {
    if (typeof voice.voice_id !== "string" || !VOICE_ID_PATTERN.test(voice.voice_id)) return [];
    const status = voice.status === "OK" || voice.status === "UNDEPLOYED" ? voice.status : "UNKNOWN";
    return [{
      id: voice.voice_id,
      displayName: labels[voice.voice_id] || humanizeVoiceId(voice.voice_id),
      status,
      createdAt: typeof voice.gmt_create === "string" ? voice.gmt_create : null,
    } satisfies BailianClonedVoice];
  });
}

export async function deleteBailianClonedVoice(
  voiceId: string,
  environment: Environment = process.env,
  fetchImpl: typeof fetch = fetch,
) {
  const apiKey = environment.DASHSCOPE_API_KEY?.trim();
  if (!apiKey) throw new Error("missing DASHSCOPE_API_KEY");
  if (!isValidBailianVoiceId(voiceId)) throw new Error("invalid Bailian voice ID");
  const response = await fetchImpl(resolveBailianCloneEndpoint(environment), {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "voice-enrollment",
      input: { action: "delete_voice", voice_id: voiceId },
    }),
    cache: "no-store",
    signal: AbortSignal.timeout(15_000),
  });
  const payload = await response.json().catch(() => null) as { message?: string; code?: string } | null;
  if (!response.ok) {
    throw new Error(payload?.message || payload?.code || `Bailian voice deletion failed (${response.status})`);
  }
}

export function isValidBailianVoiceId(voiceId: string) {
  return VOICE_ID_PATTERN.test(voiceId);
}

export function humanizeVoiceId(voiceId: string) {
  const fragments = voiceId.split("-").filter(Boolean);
  const useful = fragments.length > 2 ? fragments.slice(-2, -1)[0] : fragments[0];
  return useful ? `${useful.slice(0, 18)} 克隆音色` : "克隆音色";
}

function normalizeVoiceDisplayName(value: string) {
  return value.trim().replace(/\s+/gu, " ").toLocaleLowerCase();
}
