# 2026 全双工实时语音模型与 API 系统调研
## —— 两条技术路线、能力、价格与工程选型对比

> 调研日期：2026-09-17  
> 范围：面向实时语音助手、数字人、车载、客服、陪伴与 Voice Agent 的全双工 / Realtime / Live 语音模型与 API  
> 资料原则：优先采用厂商官方文档、官方 API Reference、官方博客、官方 GitHub 与技术报告。  
> 注意：实时语音产品迭代极快，模型名、价格、区域、并发和 Preview/GA 状态可能变化，生产接入前应再次核对官方控制台。

---

# 1. 执行摘要

截至 2026 年 9 月，实时语音模型已经明显分化出两条技术路线。

## 路线 A：原生端到端全双工 / 自然语音交互优先

核心目标是：

```text
一直听
+
一直理解
+
自然决定什么时候说
+
允许双方同时说
+
理解附和、迟疑、情绪、笑声、停顿
+
被打断时快速让出话权
```

代表模型：

- StepAudio 3 Realtime
- Qwen Audio 3.0 Realtime
- Doubao Seed RealtimeVoice
- Tencent Covo-Audio / Covo-Audio-Chat-FD（研究/开源状态需区分）
- Lychee-FD
- NVIDIA PersonaPlex
- OpenAI GPT-Live 也具备强 full-duplex 属性
- Gemini 3.8 Live 也属于该路线，但同时强化 Agent 能力

这条路线更关注：

- Full Duplex；
- Barge-in；
- Backchannel；
- VAD / Semantic Turn；
- Prosody；
- 情绪；
- Persona；
- Voice Clone；
- 低延迟；
- 自然话权协调。

---

## 路线 B：Live Voice + Agent / 后台推理 / 工具协同优先

核心目标是：

```text
用户一直在跟一个实时语音前台交流
              ↓
后台可以同时：
推理
搜索
查数据库
跑工具
执行业务动作
调用其他模型
              ↓
过程中语音前台仍然可以保持交互
              ↓
后台完成后自然把结果接回语音对话
```

代表模型：

- OpenAI GPT-Live + Responses / Client Delegation
- Gemini 3.8 Live Extended Thinking
- Amazon Nova 2 Sonic
- StepAudio 3 Realtime Voice Agent
- Grok Voice
- Qwen Audio 3.0 Realtime + Function Calling
- Doubao S2S-O + 外部 RAG / 联网

这条路线更关注：

- Function Calling；
- Async Tool；
- Backend Agent；
- 搜索；
- RAG；
- 中间状态播报；
- 长任务不冷场；
- Session 生命周期；
- Context 管理；
- 工具结果回灌；
- 企业后端集成。

---

# 2. 本次重点调研对象

## 商业 API / 托管服务

| 厂商 | 模型 / 产品 | 当前定位 |
|---|---|---|
| OpenAI | `gpt-live-1` | Full-duplex Voice Frontend + Backend Agent Delegation |
| Google | `gemini-3.8-live` | 低延迟原生 Audio-to-Audio Live |
| Google | `gemini-3.8-live-extended-thinking` | Live Voice + 后台高推理 + 异步工具 |
| 阿里云 | `qwen-audio-3.0-realtime-plus` | 高质量实时双工语音 |
| 阿里云 | `qwen-audio-3.0-realtime-flash` | 低成本、极致响应版本 |
| 阶跃星辰 | StepAudio 3 Realtime | 全双工、边想边说、Voice Agent |
| 字节 / 火山 | Doubao Seed RealtimeVoice | 端到端超拟人语音、S2S-O / S2S-SC |
| xAI | Grok Voice / `grok-voice-latest` | Full-duplex Voice Agent + Tools |
| Amazon | Nova 2 Sonic | Bedrock 企业级 Speech-to-Speech Agent |

---

## 开源 / 自部署

| 项目 | 形态 | 备注 |
|---|---|---|
| Tencent Covo-Audio | 7B Audio-to-Audio 开源 | Chat 版本已公开；FD 论文/架构存在，但公开 FD runtime 成熟度需谨慎 |
| Lychee-FD | 原生 Full-Duplex 开源 | 公开模型、Serving、Web Demo、训练代码 |
| NVIDIA PersonaPlex | Full-Duplex Speech-to-Speech | 强 Persona / Voice Conditioning |
| vLLM-Omni 全双工 Runtime | Serving 基础设施 | 2026 年开始推动 native duplex serving 标准化 |

---

# 3. 先定义：什么才叫“全双工实时语音”

实时语音产品经常都叫 Realtime，但技术含义并不相同。

建议区分四层。

## L0：级联实时语音

```text
VAD
 ↓
ASR
 ↓
Text LLM
 ↓
TTS
```

可以很快，但本质仍是轮次制。

---

## L1：流式级联

```text
Streaming ASR
     ↓
Streaming LLM
     ↓
Streaming TTS
```

能降低延迟，但通常仍然需要：

```text
“用户说完了”
```

才能可靠进入回答阶段。

---

## L2：半双工 Speech-to-Speech

模型直接：

```text
Audio → Model → Audio
```

但用户说话与模型说话仍然基本轮流。

---

## L3：Native Full-Duplex

真正目标是：

```text
User audio  ─────────────────────>

                model continuously listening

<──────────────────── Assistant audio

User and assistant audio may overlap
```

模型还要处理：

- 用户是不是在附和；
- 用户是不是准备真正插话；
- 当前停顿是不是句中停顿；
- 是否应该等待；
- 是否需要停止输出；
- 是否应该继续听但不说；
- 是否应该边想边说。

2026 年的竞争核心已经从：

```text
“能不能语音对话”
```

转成：

```text
“会不会像人一样管理话权”
```

---

# 4. 两条技术路线概览

# 路线 A：原生端到端全双工

架构：

```text
Microphone
    │
    ▼
┌────────────────────────┐
│ Native Speech Model    │
│                        │
│ Listening              │
│ Understanding          │
│ Turn Management        │
│ Reasoning              │
│ Speech Generation      │
└───────────┬────────────┘
            │
            ▼
         Speaker
```

理想状态下：

```text
不需要把 ASR、LLM、TTS 当成三个独立模块
```

优势：

1. 韵律信息不丢失；
2. 情绪理解更自然；
3. 打断更自然；
4. 可以理解笑声、犹豫、语调；
5. 能处理附和；
6. 端到端延迟低；
7. Voice Persona 更统一。

缺点：

1. Debug 难；
2. 精确文本控制更难；
3. 有时不保证 verbatim；
4. Tool / Agent 逻辑不一定透明；
5. 业务状态不能完全托管给模型；
6. 复杂后端任务仍需外部系统。

---

# 路线 B：Live Voice + Backend Agent

架构：

```text
                   ┌─────────────────────┐
                   │ Backend Agent       │
                   │                     │
                   │ Reasoning           │
                   │ Function Calling    │
                   │ Search              │
                   │ RAG                 │
                   │ Workflow            │
                   └──────────┬──────────┘
                              │
                         result/context
                              │
                              ▼
Microphone ──> Live Voice Frontend ──> Speaker
                    ▲
                    │
             realtime interaction
```

优势：

1. 实时体验和业务推理解耦；
2. 后端模型可更强；
3. 工具权限容易隔离；
4. 可以执行复杂 Agent；
5. 可以独立扩展 RAG、数据库、搜索；
6. 更容易做企业权限和安全。

缺点：

1. 工程更复杂；
2. 多模型成本叠加；
3. Backend latency 需要管理；
4. 需要设计中间话术；
5. 状态同步比纯端到端复杂。

---

# 5. 核心能力总表

> “✅”表示官方明确支持；“部分/模式相关”表示依赖版本或配置；“未明确”表示本次官方资料中没有足够证据，不做推断。

| 能力 | GPT-Live | Gemini 3.8 Live | Gemini Ext. Thinking | Qwen Audio 3 RT | StepAudio 3 RT | Doubao RealtimeVoice | Grok Voice | Nova 2 Sonic |
|---|---|---|---|---|---|---|---|---|
| Audio → Audio | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 真正 Full Duplex | ✅ | ✅ | ✅ | ✅ | ✅ | ✅/强调随时打断 | ✅ | 双向流 + barge-in |
| 同时听和说 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 用户 Barge-in | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 输入 Transcript | ✅ | ✅ 可配置 | ✅ | ✅ | Realtime 内置 ASR | 有 | ✅ STT 能力 | ✅ |
| 输出 Transcript | ✅ | ✅ | ✅ | ✅ | 文本事件 | 有 | 有 | ✅ |
| 显式 Turn Complete | ❌ 权威 turn done 不提供 | ✅ `turnComplete` | utterance + interaction status | ✅ `response.done` 等 | ✅ Realtime 生命周期 | 有判停配置 | 有 session/turn 事件 | ✅ structured completion |
| Acoustic VAD | API 不暴露 Realtime 同款 turn_detection | ✅ Activity detection | ✅ | ✅ | ✅ | ✅ | 支持 barge-in/session | ✅ |
| Semantic Turn | 内部处理 | 模型级 | 模型级 | ✅ `smart_turn` | ✅ 附和/话权协调 | 智能判停 | 未见同名参数 | Turn sensitivity |
| Push-to-talk | 应用自行控制 | 可应用实现 | 可 | ✅ 正式模式 | ✅ VAD 可禁用 | 可实现 | 可实现 | 可自行控制 |
| System Prompt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 运行时 Prompt 更新 | ✅ append | client content / session | ✅ | ✅ session update | ✅ session update | 参数化 | ✅ dynamic instructions | cross-modal text / prompt |
| 历史会话插入 | ✅ | ✅ prefix/content | ✅ | ✅ conversation item | ✅ 上下文自动/事件 | 支持上下文 | ✅ dynamic context | ✅ history before audio |
| Function Calling | Delegation | ✅ | ✅ Async only | ✅ | ✅ | 外部 RAG / 联网 / Agent | ✅ | ✅ |
| Async Tool | Backend delegation | ✅ | **核心能力** | 部分工具流程 | Voice Agent 可继续对话 | 后端编排 | ✅ tools | **✅ 官方明确** |
| 搜索 | Responses backend | Google Search | Google Search | 搜索模式有约束 | 内置 `web_search` | ✅联网 | ✅ Search | 可接工具/RAG |
| RAG | Backend | 外部工具 | 外部工具 | FC / 外部 | 内置 retrieval | ✅ 外部 RAG 总结播报 | Tool | ✅ |
| 图像输入 | ❌ | ✅ | ✅ | ❌ Audio RT | ❌ 主模型非视觉 | S2S-O 主体非视觉 | Voice API 主体非视觉 | Speech API 主体非视觉 |
| 视频输入 | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Voice Clone | 非主能力 | 预置 voice 为主 | 同左 | ✅复刻音色 | Voice/TTS 系列强 | **✅ SC 重点** | ✅ Custom Voices | Polly-compatible / 预置 |
| Persona | Prompt | Prompt/Voice | Prompt/Voice | Prompt+Voice | **强** | **SC 强人格** | Dynamic instructions | System prompt |
| WebSocket | ✅ | ✅ | ✅ | ✅ | ✅ | ✅/RTC 产品接入 | ✅ | Bedrock bidi stream |
| WebRTC | ✅ | 通常 Live WebSocket 体系 | 同左 | ✅ | 未作为主文档协议 | RTC 体系 | 未见主协议 | 通过集成层 |
| SIP / Telephony | ✅ SIP | 需外部 telephony | 同左 | 外部集成 | 外部 | 客服/RTC | Direct SIP/Voice 平台 | Amazon Connect/伙伴 |
| 自部署 | ❌ | ❌ | ❌ | 托管 RT API | 托管 | ❌ | ❌ | ❌ |

---

# 6. 用户最关心的四个问题统一横向比较

# 6.1 打断 + “完整度判断”

| 模型 | 打断 | “用户说完了”的判断方式 |
|---|---|---|
| GPT-Live | 原生 Full Duplex；smooth interruption | **没有 authoritative transcript_done / turn_complete**；Live 自己连续理解，若业务需要精确句界需应用层补充 |
| Gemini 3.8 Live | 支持 | `turnComplete: true` 可以明确一轮响应完成 |
| Gemini Extended Thinking | 支持 | `turnComplete` 代表一次 spoken utterance 完成；真正后台任务完成看 `interaction_status=IDLE` |
| Qwen Audio 3.0 RT | 支持且事件清晰 | `server_vad` / `smart_turn` / push-to-talk；有 `speech_started`、`speech_stopped`、`response.done` |
| StepAudio 3 RT | 官方强调真正全双工、附和识别和话权协调 | 内置 VAD；API 类似 Realtime lifecycle，可禁用 VAD 手动 commit |
| Doubao | 支持“随时打断”和主动搭话 | 可用 `end_smooth_window_ms` 显式调判停时间 |
| Grok Voice | 官方明确 interruption handling / barge-in | 以 Realtime session / turn 行为为主，本次公开首页未看到 Qwen 式 semantic-turn 参数 |
| Nova 2 Sonic | 支持 barge-in | `endpointingSensitivity` 控制结束检测敏感度 |

---

## 6.2 Prompt / 人设

| 模型 | Prompt 能力 |
|---|---|
| GPT-Live | `session.instructions` + `session.instructions.append`；Backend Responses 还有独立 instructions |
| Gemini | setup 中 system instruction / client content；Extended Thinking 可设置 thinking level |
| Qwen | session instructions；可结合 voice / modalities / turn detection |
| Step | Realtime Session 支持 Prompt + Tool；官方强调 Persona 和副语言理解 |
| Doubao | S2S-O：`system_role`、`speaking_style`；S2S-SC：`character_manifest` |
| Grok | Dynamic instructions / dynamic context |
| Nova | SYSTEM content + 可选 speech prompt，且支持后续 cross-modal text |

---

## 6.3 Backend Agent 文本结果如何重新交给语音模型播放

### GPT-Live

最明确。

Client Delegation：

```text
Backend result
   ↓
session.commentary.append
   ↓
GPT-Live
   ↓
自然语言组织
   ↓
Audio
```

如果只是内部上下文：

```text
session.thinking.append
```

如果改变行为：

```text
session.instructions.append
```

重要：

```text
commentary ≠ strict verbatim TTS
```

---

### Gemini Extended Thinking

模型本身可以：

```text
Live Voice
   │
   ├── 先说中间状态
   │
   ├── async function call
   │
   ├── backend tool result
   │
   └── 继续生成 Audio
```

与 GPT-Live 最大差异：

```text
GPT：
语音前台和后台 reasoning 模型显式解耦

Gemini Ext Thinking：
后台 reasoning 生命周期更深地整合进 Live 模型
```

---

### Qwen Audio 3.0

Function Calling 流程：

```text
model function_call
      ↓
client executes tool
      ↓
function_call_output
      ↓
response.create
      ↓
text/audio response
```

和 OpenAI Realtime 风格非常接近。

---

### StepAudio 3

官方描述：

```text
Voice Agent 识别意图
  ↓
调用工具 / 后端任务
  ↓
任务运行期间对话仍可继续
  ↓
结果回来
  ↓
自然接入交流
```

这已经非常接近路线 B。

---

### Doubao

S2S-O 官方明确支持：

```text
外部 RAG / 搜索结果
      ↓
接口传入 S2S
      ↓
按照人设做口语化总结改写
      ↓
播报
```

这是一个非常实用的“Backend Text → Natural Speech”产品化能力。

---

### Nova 2 Sonic

工具流程：

```text
toolUse
  ↓
application backend
  ↓
toolResult
  ↓
Nova 继续生成 text + audio
```

并且官方支持 async tool calling；工具执行时可以继续交流。

---

## 6.4 历史会话插入

| 模型 | 历史会话 |
|---|---|
| GPT-Live | `session.input` 注入 developer/user/assistant 历史；store 后还可 fork |
| Gemini Live | 支持 client content / prefix turns；支持 session resumption + context compression |
| Qwen Audio RT | Conversation Item 可 create/query/delete；`max_history_turns` 1–50 |
| StepAudio RT | Realtime 会话自动管理历史；若手工使用 event 可维护 conversation |
| Doubao | 支持会话上下文；详细持久化方式依具体 RTC/API |
| Grok Voice | Dynamic context；多轮 session |
| Nova 2 Sonic | **明确允许在 system prompt 后、音频开始前一次性插入历史**，最大总体历史 200 KB |

---

# 7. OpenAI GPT-Live 深入分析

## 7.1 定位

`gpt-live-1`：

- Full-duplex；
- 同时 listen / speak；
- 自然打断；
- 音频输入输出；
- 文本上下文；
- Backend delegation。

官方定价：

```text
$0.05 / minute
```

按秒计费。

Backend model 和 tools：

```text
额外收费
```

---

## 7.2 与传统 Realtime API 的关键差异

GPT-Live 的哲学更偏：

```text
continuous timeline
```

而不是：

```text
VAD → commit → response
```

它不强调一个权威：

```text
turn_complete
```

所以：

- 对话自然；
- overlap 友好；
- 但业务如果需要精确判定“用户完整说完一句”，需要额外应用层逻辑。

---

## 7.3 Agent 路线

GPT-Live 很典型地代表路线 B：

```text
Voice frontend
      ↓
Delegation
      ↓
Responses model / Your agent
```

优点：

- 后端推理模型可以独立升级；
- 后端可以有自己的 system prompt；
- 工具权限放在服务器；
- WebRTC 浏览器不暴露 project key；
- Sideband Server 可以观察和控制同一会话。

---

## 7.4 输入输出

输入：

- Audio；
- startup text history；
- instructions；
- thinking context；
- commentary；
- function output。

输出：

- Audio delta；
- input transcript delta；
- output transcript delta；
- delegation event；
- nested Responses event；
- usage；
- error；
- session close。

---

## 7.5 适合场景特征

更适合：

- Voice UI 是独立“嘴和耳朵”；
- 后台已有 Agent；
- 后台模型经常需要切换；
- 工具复杂；
- 安全边界要求高；
- 需要 Browser + Server sideband。

需要注意：

- Image / Video 当前 GPT-Live 不支持；
- Commentary 不是严格 TTS；
- Turn 完整度控制没有 Qwen 那么显式。

官方：
https://developers.openai.com/api/docs/models/gpt-live-1  
https://developers.openai.com/api/docs/guides/live  
https://developers.openai.com/api/docs/guides/live-delegation

---

# 8. Google Gemini 3.8 Live

Gemini 3.8 Live 于：

```text
2026-09-15
```

正式 GA。

Google 同时发布：

```text
gemini-3.8-live
gemini-3.8-live-extended-thinking
```

这是当前实时语音市场非常关键的一次产品分层。

---

# 9. Gemini 3.8 Live：低延迟路线

定位：

```text
低延迟
快速 turn-taking
普通实时 Voice Agent
```

支持输入：

```text
Text
Image
Audio
Video
```

输出：

```text
Text
Audio
```

上下文：

```text
Input 131,072 tokens
Output 65,536 tokens
```

这是和 GPT-Live 很大的区别：

```text
Gemini Live 是原生语音 + 原生视觉 Live
```

意味着：

```text
摄像头
屏幕
图片
视频流
语音
```

可以进入同一个 Live model。

---

# 10. Gemini 3.8 Extended Thinking

这是路线 B 的代表。

## 核心创新

Google 把：

```text
background reasoning
+
async function calling
+
live audio
```

整合在一个 session 生命周期中。

例如：

```text
User:
帮我找最合适的三个航班，然后比较价格和转机时间。
```

系统可以：

```text
Gemini:
“好的，我正在比较几个方案。”

          ↓

后台同时：
searchFlights
searchHotels
compare

          ↓

interaction_status = IN_PROGRESS

          ↓

工具完成

          ↓

Gemini:
“我找到了三个比较合适的……”

interaction_status = IDLE
```

因此它解决了 Voice Agent 最痛苦的问题之一：

```text
工具等 3~8 秒时不能一直沉默
```

---

## `turnComplete` 和 `interaction_status`

普通 Gemini Live：

```text
turnComplete=true
≈ 当前一轮完成
≈ session idle
```

Extended Thinking：

```text
turnComplete=true
```

只表示：

```text
这一段模型语音说完
```

不意味着后台任务结束。

真正整体完成：

```text
interaction_status = IDLE
```

后台仍工作：

```text
interaction_status = IN_PROGRESS
```

这个设计对复杂语音 Agent 非常重要。

---

# 11. Gemini 价格

标准 Live：

## Input

```text
Text:   $0.75 / 1M tokens
Audio:  $3 / 1M tokens
        ≈ $0.005 / input audio minute

Image/Video:
        $1 / 1M
        ≈ $0.002 / minute
```

## Output

```text
Text:   $4.50 / 1M
Audio:  $12 / 1M
        ≈ $0.018 / audio minute
```

因此仅看“新增音频流”：

假设一分钟内：

```text
用户说 1 minute
模型也说 1 minute
```

音频边际费用约：

```text
$0.005 + $0.018
= $0.023
```

但这并不是完整 session 成本。

因为 Live context 会累计和重新处理历史，需要考虑：

```text
context compounding
```

Google 官方建议启用：

```text
contextWindowCompression
```

音频 token 大约：

```text
25 tokens / second
```

未启用 compression 时，官方最佳实践提示：

```text
audio-only session 约 15 分钟
audio-video session 约 2 分钟
```

启用 context compression 后可显著延长。

---

# 12. Gemini Session Resumption

Gemini 提供：

```text
sessionResumption
```

服务端会发送：

```text
SessionResumptionUpdate
```

客户端保存：

```text
handle
```

重新连接时可以恢复。

Resumption token：

```text
会话终止后最长有效约 2 小时
```

这是企业实时应用比较实用的能力。

官方：
https://ai.google.dev/gemini-api/docs/live-api  
https://ai.google.dev/gemini-api/docs/live-api/thinking  
https://ai.google.dev/gemini-api/docs/live-api/session-management  
https://ai.google.dev/gemini-api/docs/pricing

---

# 13. Qwen Audio 3.0 Realtime

当前主要有：

```text
qwen-audio-3.0-realtime-plus
qwen-audio-3.0-realtime-flash
```

Plus：

```text
质量优先
```

Flash：

```text
极致响应 / 成本优先
```

输入：

```text
Audio
Text
```

输出：

```text
Audio
Text
```

Function Calling：

```text
支持
```

上下文：

```text
40,960
```

最大输入：

```text
16,384
```

最大输出：

```text
8,192
```

---

# 14. Qwen 最大亮点：Turn 控制最清晰

Qwen 当前有三种模式。

## 14.1 server_vad

```json
{
  "turn_detection": {
    "type": "server_vad",
    "threshold": 0.5,
    "silence_duration_ms": 500
  }
}
```

纯声学判断。

可控制：

```text
threshold
silence_duration_ms
```

---

## 14.2 smart_turn

```json
{
  "turn_detection": {
    "type": "smart_turn"
  }
}
```

同时理解：

```text
声学
+
语义
```

非常关键：

```text
“嗯”
“啊”
“对对”
```

这种附和不一定会触发：

```text
用户打断
```

也不会轻易创建新的语义 turn。

这对于真实双工体验非常重要。

---

## 14.3 Push-to-talk

设置：

```text
turn_detection = null
```

客户端自己决定：

```text
commit
response.create
```

适合：

- 对讲机；
- 车载物理按钮；
- 精确录音；
- 特殊工业环境。

---

# 15. Qwen 的事件完整度

在 server_vad 中，可以直接看到：

```text
input_audio_buffer.speech_started
input_audio_buffer.speech_stopped
input_audio_buffer.committed
conversation.item.created
response.audio_transcript.delta
response.audio.delta
response.done
```

因此如果业务特别依赖：

```text
当前用户是不是开始说
当前用户是不是说完
当前 response 是不是结束
```

Qwen 的接口非常直接。

---

# 16. Qwen 打断行为

模型播放过程中：

```text
用户开始说
```

VAD 检测后：

```text
取消当前 response
```

返回：

```text
response.done
status = cancelled
```

然后自动进入新的用户 turn。

这个事件语义对 UI 状态机非常友好。

---

# 17. Qwen 历史上下文

提供：

```text
Conversation Item
```

可以：

- create；
- query；
- delete；
- 插入历史；
- 删除无关上下文。

另有：

```text
max_history_turns
```

范围：

```text
1 - 50
```

默认：

```text
20
```

这比“黑盒自动记忆”更可控。

---

# 18. Qwen 价格

## 北京 Region

### Plus

| 类型 | ¥ / 1M tokens |
|---|---:|
| Text input | 5 |
| Audio input | 40 |
| Text output | 40 |
| Audio output | 150 |

### Flash

| 类型 | ¥ / 1M tokens |
|---|---:|
| Text input | 3 |
| Audio input | 30 |
| Text output | 30 |
| Audio output | 100 |

---

## 新加坡 Region

### Plus

| 类型 | ¥ / 1M |
|---|---:|
| Text input | 5.995 |
| Audio input | 47.963 |
| Text output | 47.963 |
| Audio output | 179.861 |

### Flash

| 类型 | ¥ / 1M |
|---|---:|
| Text input | 3.372 |
| Audio input | 33.724 |
| Text output | 33.724 |
| Audio output | 112.413 |

---

# 19. Qwen 接入协议

官方当前支持：

```text
WebSocket
AOQ
WebRTC
```

官方特别建议客户端如果关注：

- 弱网；
- 稳定延迟；
- 双工降噪；
- AEC；

可以优先考虑 AOQ。

这一点说明阿里不仅做了模型，还在做完整 RTC 实时通信链路。

官方：
https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides  
https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-realtime-plus  
https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-realtime-flash

---

# 20. StepAudio 3 Realtime

StepAudio 3 Realtime 是阶跃当前实时语音旗舰。

官方定位：

```text
真人自然交互
+
全双工
+
自适应推理
+
边想边说
+
Voice Agent
```

它非常典型地处于：

```text
路线 A
和
路线 B
的交叉位置
```

---

# 21. StepAudio 的自然交互

官方强调：

- hesitation；
- laughter；
- emotion；
- pauses；
- backchannels；
- interruptions。

也就是模型不仅判断：

```text
说了什么
```

还会判断：

```text
怎么说的
```

例如：

```text
“嗯……我觉得……”
```

里面的犹豫本身就是语义的一部分。

---

# 22. StepAudio 真正 Full Duplex

官方描述：

```text
用户和模型可以同时说
```

并且模型能区分：

```text
真正打断
vs
自然附和
vs
正常停顿
```

模型会：

- 真打断时停止；
- “嗯”“对”类附和时保持连贯；
- 根据话权协调决定谁继续。

这和 Qwen `smart_turn` 的目标类似，但 Step 更强调模型端统一学习。

---

# 23. StepAudio 自适应推理

非常有意思的一点：

```text
简单问题
→ 快速回答

复杂问题
→ 更深入思考
→ 边想边说
```

这其实和 Gemini Extended Thinking 的产品方向非常接近。

差别是：

```text
Gemini：
把 thinking lifecycle 做成明确 API 状态

Step：
更强调模型“边想边说”的自然体验
```

---

# 24. StepAudio Voice Agent

官方明确表示：

```text
Voice Agent
可以调用工具
或执行后端任务
```

并且：

```text
任务运行期间
对话仍可继续
```

最终：

```text
任务结果自然重新进入交流
```

这就是完整的路线 B 特征。

---

# 25. Step Realtime API

当前开发文档描述：

```text
WebSocket 长连接
```

包含：

- 内置 ASR；
- 自动上下文管理；
- VAD；
- web_search；
- retrieval；
- custom tool call。

默认：

```text
VAD enabled
```

也可以：

```text
turn_detection = null
```

关闭 VAD。

此时需要手工：

```text
input_audio_buffer.commit
response.create
input_audio_buffer.clear
```

整体事件协议与 OpenAI Realtime 风格相近。

---

# 26. StepAudio 价格状态

这里需要谨慎。

截至调研日：

```text
StepAudio 3 Realtime
```

官方页面仍包含 Preview / 限免及未来正式付费版本说明。

因此：

**本报告不把 StepAudio 2 的旧价格直接当成 StepAudio 3 Realtime 的正式价格。**

历史参考：

```text
StepAudio 2
Input 约 ¥10 / 1M
Output 约 ¥70 / 1M
```

官方曾给过旧代聊天：

```text
约 ¥3.8 / hour
```

但不能作为 StepAudio 3 Realtime 当前正式报价。

正式接入应以：

```text
StepFun 控制台
定价页
商务合同
```

为准。

官方：
https://platform.stepfun.com/docs/zh/guides/models/stepaudio-3-realtime  
https://static.stepfun.com/blog/stepaudio3/realtime/  
https://platform.stepfun.com/docs/zh/guides/developer/realtime

---

# 27. Doubao Seed RealtimeVoice

火山当前定位：

```text
端到端
超拟人
低时延
Speech-to-Speech
```

重点：

- 情感；
- 指令控制；
- 方言；
- 语速；
- 风格；
- 声线；
- 唱歌；
- 角色演绎；
- 随时打断；
- 主动搭话。

---

# 28. Doubao 两条产品线

## S2S-O / Omni

面向：

- 助手；
- 客服；
- 车载；
- ToB。

支持：

```text
外部 RAG
联网
搜索结果
口语化总结改写
播报
```

---

## S2S-SC / Strong Character

面向：

- 角色扮演；
- 陪伴；
- 强人格。

重点：

```text
Voice Clone
Persona consistency
声音整体控制
```

当前官方更新也显示 SC 已逐步补齐：

```text
联网
RAG 总结
```

---

# 29. Doubao 的判停控制

官方开放：

```text
end_smooth_window_ms
```

默认：

```text
1500 ms
```

范围：

```text
500 ms ～ 50 s
```

这相当于给应用非常直观的：

```text
用户沉默多久后认为结束
```

控制。

优点：

- 容易调；
- 客服场景直观；
- 产品经理也容易理解。

缺点：

- 单纯时间阈值不是完整的 semantic turn；
- 对复杂口语、犹豫可能还需模型内部判断配合。

---

# 30. Doubao Prompt

S2S-O：

```text
system_role
speaking_style
```

S2S-SC：

```text
character_manifest
```

官方已经放开更多 Prompt 信息输入。

因此它在人设型实时语音中比较有优势。

---

# 31. Doubao 延迟

火山官方宣传：

```text
裸模型交互约 700ms
整体时延约 1s
```

需要说明：

这属于：

```text
厂商自报
```

并且不同网络、Region、RTC、音频设备、buffer 都会明显影响。

不能和其他厂商采用不同 benchmark 的 latency 数字直接排名。

官方：
https://www.volcengine.com/product/realtime-voice-model  
https://www.volcengine.com/docs/6561/1594360  
https://www.volcengine.com/docs/6561/162929

---

# 32. Grok Voice

xAI Voice API 当前也是一个非常直接的商业竞争者。

核心：

```text
Speech-to-Speech
Full-duplex
Tool use
Search
Multi-turn
```

官方宣称：

```text
sub-second latency
```

---

# 33. Grok Voice 功能

当前 Voice stack 提供：

- realtime voice agent；
- TTS；
- STT；
- tool calling；
- custom voices；
- 25+ languages；
- speech tags；
- dynamic instructions；
- dynamic context；
- dynamic tool update；
- interruption / barge-in。

这意味着它不只是一个 S2S endpoint，而是完整的 Voice Agent API。

---

# 34. Grok Custom Voice

支持：

```text
约 2 分钟自然语音
```

克隆 Voice。

同时做：

```text
passphrase verification
+
speaker embedding match
```

从安全设计看，这是一个值得参考的做法。

---

# 35. Grok Voice 定价

当前最新文档显示：

```text
grok-voice-think-fast-2.0
$0.08 / minute
≈ $4.80 / hour
```

旧版本：

```text
grok-voice-think-fast-1.0
$0.05 / minute
```

已标记 deprecated。

注意：

xAI 官网部分营销页仍可能展示：

```text
starting at $0.05/min
```

正式成本估算应以最新 Pricing Docs 的当前模型为准。

另外：

```text
text input
$0.004 / request/input unit（按其文档口径）
```

需另行确认具体调用行为。

官方：
https://x.ai/api/voice  
https://docs.x.ai/developers/model-capabilities/audio/voice  
https://docs.x.ai/developers/pricing

---

# 36. Amazon Nova 2 Sonic

Nova 2 Sonic 是：

```text
Amazon Bedrock
Speech-to-Speech
Bidirectional Streaming
```

当前非常适合企业 Voice Agent。

---

# 37. Nova 2 Sonic 关键能力

官方包括：

- streaming speech understanding；
- real-time multi-turn；
- multilingual；
- language switching；
- tool use；
- asynchronous tool calling；
- cross-modal text input；
- turn-taking control；
- conversation history；
- barge-in；
- Amazon Connect / telephony integration。

---

# 38. Nova 2 Sonic 的 Turn 控制

有：

```text
turnDetectionConfiguration
```

核心：

```text
endpointingSensitivity
```

用于控制：

```text
多快判断用户说完
```

这直接决定：

```text
响应速度
vs
误抢话概率
```

官方因此把 turn taking 暴露成明确可调参数。

---

# 39. Nova Conversation History

非常明确：

```text
System Prompt
    ↓
Conversation History
    ↓
Audio Streaming
```

历史：

- 一次性插入；
- 必须在 audio streaming 前；
- USER / ASSISTANT role；
- 最大总体约 200 KB。

这和 GPT-Live 的 startup input 很类似。

---

# 40. Nova Transcript 的一个工程优势

Nova 2 Sonic 输出 transcript 时还有：

```text
generationStage
```

可能是：

```text
SPECULATIVE
FINAL
```

官方建议：

```text
只保存 FINAL transcript 作为历史
```

这非常适合构建可恢复对话。

---

# 41. Nova Async Tool

官方明确：

```text
async tool calling
```

工具运行期间：

```text
AI 仍可以自然交流
```

这让它非常接近 Gemini Extended Thinking 路线。

Client 还能在工具运行期间发送 cross-modal text，例如：

```text
“告诉用户我正在处理。”
```

Nova 再自然生成语音。

---

# 42. Nova 2 Sonic Context

AWS 发布时宣称：

```text
1 million token context window
```

这在 Voice Agent 领域是非常大的上下文。

但实际长会话：

- token 成本；
- latency；
- history quality；

仍应通过真实业务压测。

---

# 43. Nova Region

截至 2026 年更新：

Bedrock GA：

- US East (N. Virginia)
- US West (Oregon)
- Asia Pacific (Tokyo)
- Europe (Stockholm)

Amazon Connect 还扩展到：

- Singapore
- London
- Seoul
- Frankfurt

这对于亚太企业客户非常重要。

---

# 44. Nova 延迟

2026 年 3 月 refresh：

```text
p50 user-perceived latency
降低约 150 ms
```

AWS 客户案例曾测得：

```text
Time To First Audio ≈ 1.39 s
```

注意：

后一个数字是 AWS 博客客户场景测试，不是统一 SLA。

---

# 45. Nova 价格

AWS 当前价格页面较动态，模型卡只引用 Bedrock Pricing。

一个 AWS 2026 客户案例公开：

```text
input audio 约 $0.27 / hour
```

但这不是完整 Voice Agent 小时成本：

还需要考虑：

- output audio；
- text tokens；
- tools；
- Bedrock 其他服务。

因此报告不直接给出 Nova 的“完整 $/hour”固定值。

官方：
https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-conversational-speech.html  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-tool-configuration.html  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-chat-history.html  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-turn-taking.html

---

# 46. Tencent Covo-Audio

腾讯 Covo-Audio：

```text
7B
end-to-end large audio language model
```

直接：

```text
continuous audio input
→
audio output
```

统一架构里融合：

- continuous acoustic feature；
- discrete speech token；
- text。

---

# 47. Covo-Audio Full Duplex 状态需要特别区分

技术报告明确提出：

```text
Covo-Audio-Chat-FD
```

native low-latency full duplex。

但公开 GitHub README 当前主要说：

```text
We release Covo-Audio-Chat in this repository.
```

并且截至 2026 年 7 月仍存在公开 issue：

```text
“Covo-Audio-Chat-FD 什么时候发布？”
```

以及：

```text
当前公开 Chat demo 还是半双工
```

的开发者反馈。

因此正确表述是：

```text
Covo-Audio：
开源端到端 Audio LLM ✅

Covo-Audio-Chat-FD：
论文 / 技术架构 / benchmark ✅
公开成熟 FD serving runtime：
截至本次调研不能等同确认 ✅
```

不应该把它和 GPT-Live/Qwen 商业实时 API 直接放在同一个成熟度层级。

官方：
https://github.com/Tencent/Covo-Audio

---

# 48. Lychee-FD

Lychee-FD 是 2026 年非常值得关注的开源项目。

它不是：

```text
ASR + LLM + TTS
```

而是：

```text
native end-to-end full-duplex spoken language model
```

统一：

```text
continuous listening
understanding
speech generation
interaction control
```

---

# 49. Lychee-FD 开放程度

官方已经公开：

- model；
- paper；
- online serving；
- customized multi-stream vLLM；
- browser realtime frontend；
- training code；
- domain fine-tuning。

时间线：

```text
2026-07-10
Serving + paper + web demo

2026-07-30
Training code
```

这是目前“能拿回来研究和改”的 Full Duplex 项目里非常完整的一类。

---

# 50. Lychee-FD 的意义

对商业模型最大启发不是：

```text
它一定比商业 API 好
```

而是：

```text
Full Duplex Interaction Control
本身可以被训练进统一模型
```

不必一定：

```text
外置 VAD
+
外置状态机
```

适合研究：

- 私有化；
- 数字人本地部署；
- 端侧；
- 特定领域 fine-tune；
- 特殊交互规则。

官方：
https://github.com/HITsz-TMG/Lychee-FD

---

# 51. NVIDIA PersonaPlex

PersonaPlex：

```text
real-time
full-duplex
speech-to-speech
```

基于：

```text
Moshi
```

架构。

---

# 52. PersonaPlex 最大特色

同时有：

```text
Text Role Prompt
+
Audio Voice Conditioning
```

也就是：

```text
Prompt 控制“你是谁”
Audio 控制“你怎么说”
```

这对：

- 虚拟人；
- 陪伴；
- 游戏 NPC；
- 角色 Agent；

非常重要。

---

# 53. PersonaPlex License

Code：

```text
MIT
```

Weights：

```text
NVIDIA Open Model License
```

因此做商业研究时需要分别评估：

```text
代码 License
和
模型权重 License
```

而不是简单说“MIT 全开源”。

官方：
https://github.com/NVIDIA/personaplex

---

# 54. vLLM-Omni：基础设施层正在成熟

2026 年非常值得注意的不是只有模型。

vLLM-Omni 已经开始把 Full Duplex 当成基础设施能力建设。

当前 roadmap 涉及：

- session state；
- streaming input；
- async chunk；
- cancellation；
- barge-in；
- native duplex serving。

截至 2026-09：

```text
MiniCPM-o 4.5
PersonaPlex
```

的 native duplex serving 已从 experimental 向稳定路径迁移。

说明：

```text
未来开源 Full Duplex
不会只靠每个项目自己写 runtime
```

而会出现统一 serving infrastructure。

---

# 55. 第一条路线详细对比：
# 原生全双工 / 自然交互优先

代表：

```text
StepAudio 3
Qwen Audio 3
Doubao
Lychee-FD
PersonaPlex
Covo-Audio FD
```

以及：

```text
GPT-Live / Gemini Live 的语音部分
```

---

# 56. 这条路线真正比较什么

不是单纯：

```text
WER
```

也不是：

```text
LLM benchmark
```

核心体验指标应该是：

### Listening

- 多久能听懂；
- 是否保留韵律；
- 背景噪音；
- 远场；
- 多说话人。

### Turn Taking

- 抢话率；
- 错误打断率；
- 附和误判；
- 停顿理解；
- Barge-in latency。

### Speaking

- First audio latency；
- 韵律；
- 情绪；
- 停顿；
- 发音准确；
- Speaker drift。

### Interaction

- 用户和模型同时说时是否稳定；
- 模型能不能停；
- 停了以后能不能继续理解；
- 是否会“装没听见”；
- 是否会把 backchannel 当新问题。

---

# 57. 路线 A 的模型差异

## Qwen

偏：

```text
工程控制面最明确
```

优势：

```text
server_vad
smart_turn
push-to-talk
speech_started/stopped
response.done
```

---

## StepAudio

偏：

```text
模型自然话权
+
副语言理解
+
边想边说
```

---

## Doubao

偏：

```text
声音表现
+
角色
+
Voice Clone
+
低时延
+
产品化判停参数
```

---

## PersonaPlex

偏：

```text
自部署
+
Persona
+
Voice Conditioning
```

---

## Lychee-FD

偏：

```text
Native FD research
+
训练
+
serving
+
私有化
```

---

# 58. 路线 A 的适合场景

### AI Companion

重点：

- 情绪；
- Persona；
- Backchannel；
- 自然打断。

重点候选：

```text
Doubao S2S-SC
StepAudio 3
PersonaPlex
```

---

### 车载 / IoT

重点：

- 噪音；
- 低延迟；
- 免提；
- 不误抢话；
- 网络波动。

重点候选：

```text
Qwen RT + AOQ
StepAudio
Doubao
```

---

### 实时数字人

重点：

- 连续音频；
- 输出音频 chunk；
- Transcript；
- Barge-in；
- Persona；
- 嘴型同步。

候选：

```text
GPT-Live
Gemini Live
Qwen
Step
Doubao
```

---

# 59. 第二条路线详细对比：
# Live Voice + Agent / 后台推理

代表：

```text
GPT-Live
Gemini Extended Thinking
Nova 2 Sonic
StepAudio 3 Voice Agent
Grok Voice
Qwen FC
```

---

# 60. 这条路线真正比较什么

## 60.1 工具期间是否继续讲话

最关键问题：

```text
调用一个 5 秒 API 时
用户听到什么？
```

可能方案：

### A

```text
沉默 5 秒
```

体验最差。

### B

```text
先说：
“稍等，我帮你看一下。”
然后静默
```

可接受。

### C

```text
后台工具跑
同时模型还能继续听、回答其他话
```

最好。

---

# 61. GPT-Live 的解耦方式

```text
Live
  ↓
Delegation
  ↓
Responses Backend
```

特点：

```text
强解耦
```

好处：

- Voice 模型不需要承担所有 reasoning；
- Backend 可以使用不同 model；
- Backend 可有 tool；
- Frontend Prompt 和 Backend Prompt 分离。

---

# 62. Gemini Extended Thinking 的整合方式

```text
Live model
  ├── voice
  ├── reasoning
  └── async tool
```

特点：

```text
强整合
```

好处：

- 中间状态天然；
- interaction lifecycle 清晰；
- 不需要自己设计太多“前台代理”。

---

# 63. Nova 2 Sonic 的企业方式

```text
Bedrock bidi speech
      ↓
toolUse
      ↓
Enterprise backend
      ↓
toolResult
      ↓
speech
```

同时：

```text
IAM
VPC
Amazon Connect
```

等企业基础设施很强。

---

# 64. StepAudio 的一体化 Voice Agent

Step 的描述更像：

```text
一个原生语音模型
内部同时完成：
理解
话权
推理
工具判断
边想边说
```

并允许后端任务运行期间继续对话。

它是两条路线融合度非常高的产品之一。

---

# 65. Grok 的 Agent 路线

Grok Voice 主打：

```text
dozens of tools
ambiguous workflow
reasoning
voice
```

并且 API 允许：

```text
dynamic tool updates
```

对动态业务工具比较有吸引力。

---

# 66. Agent 路线对比表

| 维度 | GPT-Live | Gemini Extended | Nova 2 Sonic | StepAudio 3 | Grok Voice | Qwen |
|---|---|---|---|---|---|---|
| Backend 分离 | **强** | 中等 | 中等 | 中等 | 中等 | Client tool |
| Background reasoning | 后端模型 | **原生核心** | 模型+async tools | **边想边说** | built-in reasoning | 思考模式/工具 |
| Async tool | ✅ | **✅核心** | **✅** | ✅描述支持 | ✅ | FC 流程 |
| 工具期间继续交流 | ✅ 前台 Live 可继续 | **✅设计目标** | **✅** | **✅** | 支持 | 取决于应用 |
| 搜索 | Responses | Google Search | 外部/Bedrock | web_search | Search | Search/FC 有限制 |
| 私有业务工具 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 中间状态控制 | commentary / thinking | interaction_status | cross-modal input | 模型自然表达 | dynamic context | 应用控制 |
| 安全权限分离 | **Sideband 很强** | Server tool | IAM 强 | Server API | API Agent | Server |

---

# 67. 价格比较：为什么不能简单排“最便宜”

目前至少有四种计费方式。

## A. 按实时会话时间

例如：

```text
GPT-Live
Grok Voice
```

优势：

```text
成本极易预测
```

---

## B. Audio Token

例如：

```text
Gemini
Qwen
Nova
```

成本与：

```text
用户说话长度
模型说话长度
历史 context
```

有关。

---

## C. Token + 工具

复杂 Agent：

```text
audio token
+
text/reasoning token
+
search
+
function
```

---

## D. 企业合同 / RTC 套餐

部分国内语音产品：

```text
实时音频
RTC
音色
并发
SLA
```

可能通过商务合同综合计价。

---

# 68. 已公开的直接价格

| 产品 | 官方当前公开价格 |
|---|---|
| GPT-Live | `$0.05 / min`，约 `$3 / h`，Backend 另计 |
| Grok Voice Think Fast 2.0 | `$0.08 / min`，约 `$4.80 / h` |
| Gemini 3.8 Live | Input audio 约 `$0.005/min`；Output audio 约 `$0.018/min` + context/token |
| Qwen Plus 北京 | audio in ¥40/M；audio out ¥150/M |
| Qwen Flash 北京 | audio in ¥30/M；audio out ¥100/M |
| Qwen Plus 新加坡 | audio in ¥47.963/M；audio out ¥179.861/M |
| StepAudio 3 | 当前正式价格需控制台确认，不能用旧版直接替代 |
| Doubao | 本次公开搜索未找到一个足够明确且稳定的统一实时 S2S 公价，建议控制台/商务确认 |
| Nova 2 Sonic | Bedrock token pricing；公开客户案例仅可作为局部参考 |

---

# 69. 统一 1 小时成本计算方法

不要直接假设：

```text
1 小时 session
=
用户说 60 分钟
+
AI 说 60 分钟
```

真实语音 Agent 通常有 silence。

建议定义：

```text
T = session wall time
U = 用户实际说话时间
A = AI 实际说话时间
H = 历史 context 重复处理
R = backend reasoning
F = function/search
```

---

## 时间制

例如 GPT：

```text
Cost = T × $0.05/min
     + Backend cost
```

如果 T=60：

```text
Voice base = $3
```

---

## Gemini

```text
Cost_audio ≈
U × $0.005/min
+
A × $0.018/min
```

假设一小时会话：

```text
用户实际讲话 20 min
AI 实际讲话 20 min
```

则 audio 边际：

```text
20×0.005 + 20×0.018
= $0.46
```

但这不是总价，还必须加：

```text
历史 context
text
thinking
search
```

所以不能得出：

```text
Gemini 只要 $0.46/hour
```

这样的结论。

---

# 70. 延迟对比不能只看一个数字

建议拆：

```text
TTFS = Time To First Speech
Barge-in Stop Latency
Turn Detection Delay
Tool Waiting Latency
Network RTT
Playback Buffer
```

---

## 厂商自报/公开指标

### Doubao

```text
裸模型 ~700ms
整体 ~1s
```

厂商自报。

### Grok

```text
sub-second
```

厂商定位。

### Nova 2 Sonic

公开客户场景：

```text
TTFA ≈ 1.39s
```

并且 2026 Refresh：

```text
p50 latency -150ms
```

### StepAudio 3

官方强调：

```text
extremely low latency
```

但本次抓取的正式页未给一个可与其他厂商统一比较的 ms 数。

### Gemini / GPT-Live

官方强调 low latency / realtime，但不应写死一个跨网络 SLA。

---

# 71. Voice / Persona 对比

| 模型 | Voice 方向 |
|---|---|
| GPT-Live | 多 built-in voice；自然表达；运行时 voice 一般不可随意热切 |
| Gemini | Prebuilt voices；原生多模态上下文影响表达 |
| Qwen | 系统音色 + 声音复刻 |
| Step | 强副语言、TTS/Persona 体系 |
| Doubao | **Voice Clone + Strong Character 是核心卖点** |
| Grok | Custom Voice，约两分钟样本 |
| Nova | Polyglot / Polly-compatible voices |
| PersonaPlex | **Audio Voice Conditioning** |

---

# 72. 历史和长会话

## GPT-Live

```text
128K context
自动 long-session context management
store + fork
```

---

## Gemini

```text
131K input
context window compression
session resumption
```

---

## Qwen

```text
40,960
max_history_turns 1-50
```

---

## Nova

```text
1M context（官方发布口径）
历史可在 audio 前注入
```

---

# 73. 接入协议对比

| 产品 | 主要协议 |
|---|---|
| GPT-Live | WebSocket / WebRTC / SIP / Sideband |
| Gemini Live | WebSocket Live API |
| Qwen | WebSocket / AOQ / WebRTC |
| StepAudio | WebSocket |
| Doubao | 实时语音 API + RTC 产品体系 |
| Grok | WebSocket Realtime |
| Nova | Bedrock Bidirectional Streaming |
| Lychee | 自部署 browser frontend + custom serving |
| PersonaPlex | 自部署 realtime WebUI/runtime |

---

# 74. 如果是 Browser / App

重点：

### GPT

```text
WebRTC 原生方便
```

### Qwen

```text
WebRTC / AOQ
```

特别适合弱网/AEC。

### Gemini

通常需要自己处理：

```text
Live WebSocket
+
browser audio capture/playback
```

### Doubao

RTC 产品化能力比较强。

---

# 75. 如果是电话客服

重点候选：

```text
GPT-Live SIP
Grok Direct SIP
Nova + Amazon Connect
Doubao
Qwen + telephony bridge
Step + bridge
```

其中企业电信生态：

```text
Nova
```

很有优势。

---

# 76. 如果是数字人

除了语音模型还要关注：

```text
Audio chunk timestamp
Transcript timestamp
interrupt event
generation state
```

因为需要驱动：

```text
lip sync
facial expression
gesture
```

更推荐输出 event 清晰的协议：

```text
Qwen
Nova
GPT-Live
Gemini
```

如果要精确知道“模型这一段是否结束”，Qwen/Nova/Gemini 比 GPT-Live 更直接。

---

# 77. 选型框架：不要问“哪个最好”

应该先问：

## 问题 1

你最在意：

```text
自然聊天
还是
复杂任务
```

自然聊天偏路线 A。

复杂工具偏路线 B。

---

## 问题 2

是否需要视觉？

如果：

```text
实时摄像头/屏幕
+
语音
```

Gemini Live 当前原生优势明显。

---

## 问题 3

是否需要精准 Turn 状态？

如果非常重要：

```text
Qwen
Gemini
Nova
```

事件层更明确。

GPT-Live 更偏自然 continuous conversation。

---

## 问题 4

是否已有 Backend Agent？

如果你已经有成熟 Agent：

```text
GPT-Live
```

的 frontend/backend 分层非常自然。

---

## 问题 5

是否非常强调中文“活人感”？

应该重点实际 A/B：

```text
StepAudio 3
Doubao
Qwen Audio 3
```

不要只看文本 benchmark。

---

## 问题 6

是否要声音克隆？

重点：

```text
Doubao
Qwen
Grok
PersonaPlex
```

---

## 问题 7

是否必须私有部署？

商业 API 基本排除。

优先研究：

```text
Lychee-FD
PersonaPlex
Covo-Audio
```

同时关注：

```text
vLLM-Omni
```

的 native duplex serving。

---

# 78. 面向不同产品类型的技术关注点

## A. AI Companion

优先测试：

```text
Backchannel
emotion
laugh
hesitation
persona consistency
voice clone
long conversation
```

---

## B. Customer Service

优先：

```text
tool calling
verbatim numbers
barge-in
telephony
history
audit
SLA
security
```

Nova 2026 refresh 特别强化：

- 数字；
- 地址；
- 电话；
- currency；
- email；

的语音 fidelity。

---

## C. Car / Smart Device

优先：

```text
noise
far-field
AEC
offline fallback
false interruption
latency
```

Qwen 的 AOQ + speaker enhancement 是值得重点验证的方向。

---

## D. Digital Human

优先：

```text
audio delta cadence
timestamp
transcript
interrupt
speaker state
backend agent latency
emotion
```

---

# 79. 建议真实 PoC Benchmark

任何最终选型都应跑自己的语料。

建议至少 100~300 轮。

---

## 79.1 打断测试

模型说话过程中：

```text
用户在 200ms / 500ms / 1s 插话
```

测：

```text
Stop latency
ASR 是否丢失新用户输入
旧音频是否继续播放
```

---

## 79.2 附和测试

用户说：

```text
嗯
对
是
没错
啊哈
```

看是否错误取消模型。

---

## 79.3 犹豫测试

```text
“我想订……嗯……明天吧……上海到北京……”
```

测抢话率。

---

## 79.4 工具测试

Tool latency：

```text
0.1s
1s
3s
10s
```

观察：

```text
是否冷场
是否 filler
是否还能接用户新问题
```

---

## 79.5 Verbatim 测试

播报：

```text
订单号
验证码
邮箱
金额
日期
地址
英文+数字
```

这是 S2S 模型常见问题。

---

## 79.6 长会话

```text
5 min
15 min
30 min
60 min
```

测：

- memory；
- cost；
- drift；
- latency；
- context truncation；
- speaker consistency。

---

# 80. 推荐记录的量化指标

```text
TTFA / TTFS
Barge-in stop latency
False barge-in rate
Premature response rate
Turn completion accuracy
ASR WER/CER
Tool success rate
Tool latency masking score
Voice MOS
Persona consistency
Verbatim accuracy
Hourly cost
Concurrent session capacity
```

---

# 81. 当前市场的一个重要趋势

2025 年 Voice Agent 更多是在解决：

```text
怎么做到 Speech-to-Speech
```

2026 年明显转成：

```text
怎么做到“会听、会等、会插话、会办事”
```

竞争从：

```text
语音生成
```

进入：

```text
Interaction Intelligence
```

---

# 82. 趋势 1：Semantic Turn 会逐渐替代纯 VAD

纯 VAD：

```text
检测没有声音
```

Semantic Turn：

```text
判断用户语义是不是结束
```

Qwen 已经直接产品化：

```text
smart_turn
```

Step 也把：

```text
附和识别
话权协调
```

放进模型能力。

未来：

```text
silence_duration_ms
```

更可能成为 fallback，而不是唯一机制。

---

# 83. 趋势 2：Thinking 不再等于沉默

传统 Agent：

```text
模型想 5 秒
用户等 5 秒
```

2026：

```text
模型可以边想边说
```

代表：

- Gemini Extended Thinking；
- StepAudio 3；
- Nova async tools；
- GPT-Live frontend + backend delegation。

---

# 84. 趋势 3：Voice Model 会逐渐变成“前台 Agent”

也就是：

```text
Voice model
不一定需要做全部深度 reasoning
```

但它必须非常擅长：

```text
什么时候说
说多少
怎么说
什么时候闭嘴
怎么等工具
怎么接回结果
```

GPT-Live 是这种思想最清晰的例子。

---

# 85. 趋势 4：开源 Full Duplex Runtime 开始标准化

过去开源模型的问题是：

```text
论文说 Full Duplex
但 serving demo 不能 Full Duplex
```

2026 vLLM-Omni、SGLang-Omni 已经开始正式补：

- native duplex session；
- barge-in；
- stream lifecycle；
- async output。

这会快速缩短：

```text
论文模型
→
真实产品
```

之间的距离。

---

# 86. 当前各产品最值得进一步实测的点

## GPT-Live

重点：

```text
真实中文自然度
长会话 compaction 后记忆
backend commentary 自然度
打断后 audio playback 截断
```

---

## Gemini 3.8

重点：

```text
Live video + voice
Extended Thinking filler
复杂工具期间用户再次插话
context compounding cost
```

---

## Qwen Audio 3

重点：

```text
smart_turn 中文口语
speaker enhancement
AOQ 弱网
Plus vs Flash
```

---

## StepAudio 3

重点：

```text
边想边说
附和识别
复杂 Voice Agent
正式价格 / SLA
```

---

## Doubao

重点：

```text
SC Persona
RAG 口语化播报
Voice Clone
700ms 指标在真实公网表现
```

---

## Grok Voice

重点：

```text
Think Fast 2.0
custom voice
dynamic tools
中文表现
```

---

## Nova 2 Sonic

重点：

```text
电话客服
数字/地址 verbatim
async tool
Amazon Connect
APAC latency
```

---

# 87. 一个更实用的选型矩阵

| 产品需求 | 重点关注 |
|---|---|
| 最自然中文聊天 | Step / Doubao / Qwen 做真人 A/B |
| 显式 Turn 状态机 | Qwen / Gemini / Nova |
| 已有强 Backend Agent | GPT-Live |
| 原生视觉 + Voice | Gemini |
| 复杂后台推理不冷场 | Gemini Extended / GPT-Live / Nova / Step |
| 电话客服 | Nova / GPT SIP / Grok SIP / 国内 RTC |
| Voice Clone | Doubao / Qwen / Grok / PersonaPlex |
| 私有部署 | Lychee-FD / PersonaPlex / Covo |
| Browser WebRTC | GPT-Live / Qwen |
| 弱网+AEC | Qwen AOQ / RTC 方案 |
| AWS 企业生态 | Nova 2 Sonic |
| 强角色陪伴 | Doubao SC / Step / PersonaPlex |

这个表不是“排名”，只是把产品需求映射到值得优先测试的技术方向。

---

# 88. 结论

目前的全双工语音模型不能再简单看成：

```text
ASR + LLM + TTS 的升级版
```

它实际上正在形成新的模型类别：

```text
Realtime Interaction Model
```

真正竞争的是：

```text
Listening
+
Turn Taking
+
Reasoning
+
Speaking
+
Tool Use
+
Conversation State
```

两条路线会长期并存：

## 路线 A

```text
Native Full Duplex
```

目标：

```text
像人一样说话
```

## 路线 B

```text
Live Voice + Agent
```

目标：

```text
一边跟人说话，一边真正把事情办完
```

当前越来越多模型在融合两条路线。

尤其：

```text
Gemini 3.8 Extended Thinking
StepAudio 3 Realtime
Nova 2 Sonic
```

已经不是纯 A 或纯 B。

而 GPT-Live 的特点是：

```text
主动保持 Voice Frontend 与 Backend Intelligence 的架构解耦
```

Qwen 则非常强调：

```text
明确、工程可控的 Turn / Event / VAD 接口
```

Doubao / Step 则继续强化：

```text
中文活人感
Persona
情感和声音表现
```

开源领域：

```text
Lychee-FD
PersonaPlex
Covo-Audio
```

说明原生全双工已经开始从封闭商业 API 下沉到可训练、可私有部署的基础模型与 Serving 层。

---

# 89. 官方资料索引

## OpenAI

GPT-Live Model  
https://developers.openai.com/api/docs/models/gpt-live-1

Getting Started with GPT-Live  
https://developers.openai.com/api/docs/guides/live

Live Delegation  
https://developers.openai.com/api/docs/guides/live-delegation

---

## Google

Gemini 3.8 Live  
https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live

Gemini 3.8 Live Extended Thinking  
https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live-extended-thinking

Thinking in Live API  
https://ai.google.dev/gemini-api/docs/live-api/thinking

Live API Session Management  
https://ai.google.dev/gemini-api/docs/live-api/session-management

Gemini Pricing  
https://ai.google.dev/gemini-api/docs/pricing

Release Notes  
https://ai.google.dev/gemini-api/docs/changelog

---

## Alibaba / Qwen

Qwen Audio Realtime Guide  
https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides

Qwen Audio 3.0 Realtime Plus  
https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-realtime-plus

Qwen Audio 3.0 Realtime Flash  
https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-realtime-flash

Realtime WebSocket API  
https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api

Model Pricing  
https://help.aliyun.com/zh/model-studio/model-pricing

---

## StepFun

StepAudio 3 Realtime  
https://platform.stepfun.com/docs/zh/guides/models/stepaudio-3-realtime

StepAudio 3 Realtime Technical / Demo Page  
https://static.stepfun.com/blog/stepaudio3/realtime/

Realtime Developer Guide  
https://platform.stepfun.com/docs/zh/guides/developer/realtime

Model Overview  
https://platform.stepfun.com/docs/zh/guides/models/overview

---

## ByteDance / Volcengine

Doubao Realtime Voice Product  
https://www.volcengine.com/product/realtime-voice-model

Realtime Voice Product Introduction  
https://www.volcengine.com/docs/6561/1594360

Realtime Voice Updates / Parameters  
https://www.volcengine.com/docs/6561/162929

---

## xAI

Grok Voice  
https://x.ai/api/voice

Voice API Docs  
https://docs.x.ai/developers/model-capabilities/audio/voice

Pricing  
https://docs.x.ai/developers/pricing

---

## AWS

Nova 2 Sonic  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-conversational-speech.html

Input Events / History  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-input-events.html

Chat History  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-chat-history.html

Tool Configuration  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-tool-configuration.html

Turn Taking  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-turn-taking.html

Release Notes  
https://docs.aws.amazon.com/nova/latest/nova2-userguide/release-notes.html

---

## Tencent

Covo-Audio  
https://github.com/Tencent/Covo-Audio

---

## Lychee-FD

https://github.com/HITsz-TMG/Lychee-FD

---

## NVIDIA PersonaPlex

https://github.com/NVIDIA/personaplex

---

## Full-Duplex Survey / Runtime Research

Speaking While Listening — Full Duplex Survey  
https://github.com/MM-Speech/DuplexSurvey

vLLM-Omni  
https://github.com/vllm-project/vllm-omni

---

# 90. 文档使用建议

如果后续要进入真实技术选型，建议下一步不要继续扩大厂商数量，而是从本报告选：

```text
3~5 个商业模型
+
1~2 个开源方案
```

用同一套中文语音测试集做真正 A/B Benchmark。

建议核心测试组合：

```text
GPT-Live
Gemini 3.8 Live Extended Thinking
Qwen Audio 3.0 Realtime Plus
StepAudio 3 Realtime
Doubao Seed RealtimeVoice
```

开源补充：

```text
Lychee-FD
PersonaPlex
```

最终评估不只听 Demo，而要同时记录：

```text
自然度
打断
完整度
工具
价格
长会话
延迟
并发
工程复杂度
```

因为对全双工语音模型来说：

```text
“声音最好听”
并不等于
“最适合做实时 Voice Agent”
```

而：

```text
“文本智商最高”
也不等于
“真人语音交互最好”
```

真正的选型对象已经不是单一模型能力，而是：

```text
模型
+
实时通信协议
+
Turn 管理
+
Agent 架构
+
上下文
+
成本
+
部署条件
```

共同组成的完整实时语音系统。
