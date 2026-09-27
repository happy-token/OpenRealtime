type TtsProvider = "doubao" | "dashscope";

export interface ProviderVoiceCatalog {
  instances?: { id: string; capability?: string; provider: string; enabled?: boolean; connectionStatus?: string }[];
  platformCredentials?: { capability: string; provider: string }[];
  selections?: { tts?: string };
  platformSelections?: { tts?: string };
  pipelineFallbacks?: { tts?: { provider: string } };
}

/** Use the same personal-over-platform selection shown on the supplier page. */
export function selectedDefaultTtsProvider(catalog: ProviderVoiceCatalog): TtsProvider | null {
  const target = catalog.selections?.tts ?? catalog.platformSelections?.tts;
  let provider: string | undefined;
  if (target?.startsWith("env:")) {
    provider = catalog.platformCredentials?.find((item) => item.capability === "tts" && `env:${item.provider}` === target)?.provider;
  } else if (target) {
    provider = catalog.instances?.find((item) => item.id === target && item.capability === "tts"
      && item.enabled && item.connectionStatus === "passed")?.provider;
  } else {
    provider = catalog.pipelineFallbacks?.tts?.provider;
  }
  return provider === "doubao" || provider === "dashscope" ? provider : null;
}
