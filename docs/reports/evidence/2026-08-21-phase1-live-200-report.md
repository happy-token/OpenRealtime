# Voice Runtime Quality Report

Status: **PASSED**

- Attempted turns: 200
- Live attempted turns: 200
- Minimum live attempts per Profile: 200
- Required browsers: chrome

## Profile coverage

| Engine | Provider | Capture profile | Live attempts | Browsers | Missing | Coverage |
| --- | --- | --- | ---: | --- | --- | --- |
| cascaded | doubao-asr+deepseek+doubao-tts | desktop-web-phase1-v1 | 200 | chrome | — | PASS |

## SLO groups

| Engine / provider / profile | Browser | Network | Result | Evidence | N | EOT→playback p50/p95 | Barge p95 | Reconnect p95 | Abnormal | Violations | SLO |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| cascaded / doubao-asr+deepseek+doubao-tts / desktop-web-phase1-v1 | chrome 151.0.7922.170  | cn-local | ordinary | live | 200 | 635.7 ms / 1035.8 ms | — | — | 0.000% | 0 | PASS |
