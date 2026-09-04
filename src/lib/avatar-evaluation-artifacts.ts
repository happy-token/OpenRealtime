import path from "node:path";

const ARTIFACT_PATHS: Record<string, string> = {
  "static-base": "research-assets/avatar-evaluation/2026-08-22/runs/static/static-base.mp4",
  "liveportrait-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/liveportrait/liveportrait-001.mp4",
  "wav2lip-offline-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-offline-001.mp4",
  "wav2lip-offline-box-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-offline-box-001.mp4",
  "livetalking-wav2lip96-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/livetalking/livetalking-wav2lip96-001.mp4",
  "liteavatar-cpu-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/liteavatar/liteavatar-cpu-001.mp4",
  "dh-live-mini-browser-003":
    "research-assets/avatar-evaluation/2026-08-22/runs/dh-live-mini/dh-live-mini-browser-003.mp4",
  "dh-live-mini-v1-custom-003":
    "research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/dh-live-mini-v1-custom-003.mp4",
  "wav2lip-comparison-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/wav2lip/wav2lip-comparison-001-canonical.mp4",
  "dh-live-mini-v1-comparison-001":
    "research-assets/avatar-evaluation/2026-08-22/runs/dh-live-v1-custom/dh-live-mini-v1-comparison-001-canonical.mp4",
  "motion-base-warm": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/01-warm-closeup.mp4",
  "motion-base-friendly": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/02-friendly-smile.mp4",
  "motion-base-cozy": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/03-cozy-home.mp4",
  "motion-base-cardigan": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/04-cardigan-home-reference.mp4",
  "motion-base-clean": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/05-clean-baseline.mp4",
  "motion-base-beauty": "research-assets/cyber-girlfriend-v1-comparison/2026-08-24/clips/06-kbeauty-closeup.mp4",
};

export function resolveAvatarArtifactPath(
  artifactId: string,
  {
    projectRoot = process.cwd(),
    previewEnabled = false,
  }: { projectRoot?: string; previewEnabled?: boolean } = {},
): string | null {
  if (!previewEnabled) return null;
  const relativePath = ARTIFACT_PATHS[artifactId];
  return relativePath ? path.join(projectRoot, relativePath) : null;
}

export function parseByteRange(
  rangeHeader: string,
  fileSize: number,
): { start: number; end: number } | null {
  const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader.trim());
  if (!match || fileSize <= 0) return null;
  const [, startText, endText] = match;
  if (!startText && !endText) return null;

  if (!startText) {
    const suffixLength = Number(endText);
    if (!Number.isSafeInteger(suffixLength) || suffixLength <= 0) return null;
    return { start: Math.max(0, fileSize - suffixLength), end: fileSize - 1 };
  }

  const start = Number(startText);
  const requestedEnd = endText ? Number(endText) : fileSize - 1;
  if (
    !Number.isSafeInteger(start)
    || !Number.isSafeInteger(requestedEnd)
    || start < 0
    || start >= fileSize
    || requestedEnd < start
  ) return null;
  return { start, end: Math.min(requestedEnd, fileSize - 1) };
}
