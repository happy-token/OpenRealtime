# 语音链路端到端验证

日期：2026-10-04。使用 e2e-testing 技能；Chrome 实际浏览器，独立 Next.js 测试端口 3022，本地真实语音服务 8765。麦克风输入由 `tmp/voice-runtime-campaign/chrome-microphone-short-turn-long-silence.wav` 驱动，未使用操作者现场麦克风。

## 已验证

1. 真实普通语音回合：主页开始对话 → Chrome PCM 麦克风 → 服务端 ASR → 用户文本 → 助手完整回复 → 浏览器音频启动 → 回到监听 → 结束通话。
2. 真实输出播放期间挂断：观察到活动 AudioBufferSourceNode 后结束通话，确认活动音频源清零且界面回到 idle。
3. 真实供应商 ASR、TTS、LLM 测试：10 passed，包含增量 TTS 与 partial/final ASR。
4. WebSocket 桥、chunk 协调、规则优先插件集成回归：41 passed。此组使用受控输入/依赖，不能等同于用户开口打断的真实浏览器测试。

浏览器真实链路两个用例第一次同时执行：2 passed，耗时 27.2s。之后加强普通回合的实际音频启动断言，再执行并保存 JSON 证据。运行命令：

```sh
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3022 \
PLAYWRIGHT_EXECUTABLE_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
VOICEAGENT_E2E_LIVE=1 VOICEAGENT_E2E_FULL_VOICE=1 \
VOICEAGENT_E2E_AUDIO_FILE=tmp/voice-runtime-campaign/chrome-microphone-short-turn-long-silence.wav \
PLAYWRIGHT_JSON_OUTPUT_NAME=tmp/voice-runtime-campaign/2026-10-04-e2e-live.json \
pnpm exec playwright test tests-e2e/voice-runtime-live.spec.ts --reporter=list,json
```

## 发现的问题与覆盖边界

全站旧 E2E 未全部通过：首次运行共 84 个用例，数字人相关 4 个失败、1 个中止，余下 79 个未运行。已有中文按钮定位与默认英文界面不匹配，数字人缩略图/卡片定位也与当前页面不符。随后语音旧模拟浏览器用例 3 个失败：回退开始按钮 disabled、ASR 用例无法完成旧入口交互、结束回复用例找不到旧 orb 状态元素。不能把这些失败直接归因于播放控制器，也不能据此宣称全站通过。

本次修复了真实语音 E2E 的语言初始化、主页入口和页面形态菜单交互；没有放宽成功断言。新增在播放期间挂断的实际音频源断言及 WebSocket 消息类型/Session ID 附件。

尚未覆盖：真实用户在助手播放时说“停一下”的语义打断、附和不误停、数字人实际停播、跨 chunk 改写的真实音频输入，以及延迟 P50/P95/P99。当前只验证上述普通回合和挂断场景，不构成全量发布验收。

最终加强断言后的浏览器结果：2 passed，26.8s；ESLint 与 git diff --check 通过。JSON 结果和每个用例的 Session ID/消息类型附件保存在 `tmp/voice-runtime-campaign/2026-10-04-e2e-live.json`。

## 本次失败用例修复

- 通话设置回调未被渲染：恢复通话控制栏的“会话设置”按钮，浏览器回归验证可打开设置并切换降噪。新单元回归先复现按钮缺失，再验证修复。
- Next.js 路由非法导出：将 `isPersonalModelKind` 移入独立库模块，由保存和测试路由共同使用。全项目 `tsc --noEmit` 通过。
- 旧模拟语音用例：固定中文及无默认角色入口；WebSocket 仅模拟语音地址，保留 Next.js 开发连接；测试服务器默认关闭公开试用流程，可通过环境变量显式启用。按当前 UI 验证回复、音频周期、降噪切换不重连、实际断线重连及迟到输出抑制。收音重建前后比较当前握手次数，而非假设整个页面只有一次连接。
- 旧数字人用例：跟随资源工作台选择形象，先关闭新建模态框再选择已有形象；验证已有形象复用不发 POST；使用独立的详情 API fixture 验证内置视频实际播放与源比例；主画布验证当前视频铺满设计，详情视频继续验证 contain。

结果：先前语音失败 3 项和数字人相关 5 项均通过。进一步重跑完整 `voice-agent.spec.ts`，6 passed、1 skipped（未在该命令启用真实双说话者场景）。数字人针对本次失败范围 5 项通过。前端全量 1216 passed、7 skipped；全局 TypeScript、修改文件 ESLint 通过。

本次没有把尚未执行的其余旧全站用例标为通过；未移除失败用例或改成 skip。真实语义说话打断和数字人停播仍属于未覆盖范围。

修复后的真实浏览器复测：普通完整语音回合、播放中挂断两个用例均通过（2 passed，28.1s），JSON 证据为 `tmp/voice-runtime-campaign/2026-10-04-e2e-live-fixed.json`。
