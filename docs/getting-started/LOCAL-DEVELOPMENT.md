# Local development

[Documentation index](../README.md) · [中文项目入口](../../README.zh-CN.md)

## Prerequisites

Python 3.12+, uv, Node.js 22 and pnpm 10. These versions follow pyproject.toml, .python-version and CI. Use a shell capable of running the repository's Bash launch scripts. Native Windows users should use a compatible environment such as WSL; this documentation update has not validated native Windows startup.

## Start the demo

```bash
git clone https://github.com/happy-token/OpenRealtime.git
cd OpenRealtime
uv sync
pnpm install
pnpm dev
```

Open `http://localhost:3000`. `pnpm dev` starts the Web frontend, Python WebSocket service (8765), control plane (8766), and the optional avatar-service launcher. Local neural avatar rendering is disabled by default; it does not require a GPU to open the application. The Python launcher requests optional dependency extras through uv, so its first run can install more packages than `uv sync` alone.

Without configured provider credentials the server uses deterministic model/speech adapters. Test the page and typed-chat path first. If available, browser speech is an explicit fallback, with browser/platform limitations. Neither fallback nor a synthetic reply proves that cloud ASR/LLM/TTS is connected.

To enable real providers, follow [cloud services](CLOUD-SERVICES.md). For persistent deployment use [the deployment guide](../deployment/public-trial.md); the fixed local development identity is not production authentication.

## Stop and troubleshoot

Stop the foreground launcher with Ctrl+C. If ports remain occupied, identify the old processes before restarting; do not start duplicate backends.

| Symptom | Check |
| --- | --- |
| uv/pnpm command missing | Install the prerequisite tool and confirm it is on your shell PATH |
| Frontend cannot connect | Check launcher output and whether ports 3000/8765/8766 are already occupied |
| Microphone unavailable | Allow permission; use localhost/HTTPS and select the correct system input |
| No audio | Check browser/site mute, system output, advertised speech capabilities and provider configuration |
| Avatar unavailable | Check the selected mode's assets, credentials and service readiness; a video preview is not real-time lip sync |
| Only demo responses | Configure compatible providers; inspect errors without exposing credentials |

These commands were checked against repository configuration during this documentation update; a fresh-machine installation and real-provider calls were not rerun.
