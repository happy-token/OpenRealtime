import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
const webServerPort = new URL(baseURL).port || "3000";
const liveAudioFile = process.env.VOICEAGENT_E2E_AUDIO_FILE
  ? resolve(process.env.VOICEAGENT_E2E_AUDIO_FILE)
  : undefined;
if (
  process.env.VOICEAGENT_E2E_FULL_VOICE
  && (!liveAudioFile || !existsSync(liveAudioFile))
) {
  throw new Error(
    "VOICEAGENT_E2E_FULL_VOICE requires an existing VOICEAGENT_E2E_AUDIO_FILE",
  );
}
const liveMediaArgs = process.env.VOICEAGENT_E2E_LIVE
  ? [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      ...(liveAudioFile
        ? [`--use-file-for-fake-audio-capture=${liveAudioFile}`]
        : []),
    ]
  : [];

export default defineConfig({
  testDir: "./tests-e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL,
    launchOptions: executablePath || liveMediaArgs.length > 0
      ? { executablePath, args: liveMediaArgs }
      : undefined,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: process.env.PLAYWRIGHT_SKIP_WEB_SERVER
    ? undefined
    : {
        command: `OPENREALTIME_NEXT_DIST_DIR=.next-e2e-${webServerPort} next dev --port ${webServerPort}`,
        url: baseURL,
        reuseExistingServer: false,
        timeout: 30_000,
      },
});
