import type { AvatarDisplayConfig } from "./types";

export type PipelineChoiceStatus = "ready" | "experimental" | "requires_asset" | "requires_gpu";

export interface PipelineChoice {
  id: string;
  name: string;
  status: PipelineChoiceStatus;
  statusLabel: string;
  summary: string;
  input: string;
  output: string;
  runtime: string;
}

export interface MacLipSyncRuntimeChoice {
  id: "wav2lip256" | "wav2lip96";
  name: string;
}

/** Models that are installed, integrated with the session, and verified on this Mac. */
export const MAC_LIP_SYNC_RUNTIME_CHOICES: readonly MacLipSyncRuntimeChoice[] = [
  {
    id: "wav2lip256",
    name: "Wav2Lip 256",
  },
  {
    id: "wav2lip96",
    name: "Wav2Lip 96",
  },
] as const;

export function activateMacLipSyncRuntime(
  base: AvatarDisplayConfig,
  modelId: MacLipSyncRuntimeChoice["id"],
): AvatarDisplayConfig {
  return {
    ...base,
    renderPath: "segmented",
    segmentedLipSyncId: modelId,
  };
}

export interface AvatarIdentityChoice extends PipelineChoice {
  imageUrl?: string;
  artifactId?: string;
  rights: string;
}

export type LipSyncEffectPreview = {
  kind: "video";
  artifactId: string;
  title: string;
  note: string;
} | {
  kind: "pending";
  title: string;
  note: string;
};

export function getLipSyncEffectPreview(avatarId: string, videoId: string, lipSyncId: string): LipSyncEffectPreview {
  const testedArtifact = `${avatarId}:${videoId}:${lipSyncId}`;
  if (testedArtifact === "shuchang:liveportrait-optimized:dh-live-mini-v1") {
    return {
      kind: "video",
      artifactId: "dh-live-mini-v1-custom-003",
      title: "DH_live_mini · Shuchang 效果",
      note: "3.12 秒同人物 LivePortrait 基础底片口型参考；不代表闭嘴驱动和无缝循环优化已经完成。",
    };
  }
  if (testedArtifact === "shuchang:liveportrait-optimized:wav2lip256") {
    return {
      kind: "video",
      artifactId: "livetalking-wav2lip96-001",
      title: "LiveTalking · Wav2Lip 256 · Shuchang",
      note: "5.84 秒同人物 LivePortrait 基础底片口型参考；标准权重仅限个人、研究和非商业评测。",
    };
  }
  if (testedArtifact === "liteavatar-preset:avatar-bundled:liteavatar") {
    return {
      kind: "video",
      artifactId: "liteavatar-cpu-001",
      title: "LiteAvatar CPU 预置形象",
      note: "官方预置人物与内置底片实测片段；不能替代新人物制作。",
    };
  }
  if (testedArtifact === "dh-live-preset:avatar-bundled:dh-live-mini-v1") {
    return {
      kind: "video",
      artifactId: "dh-live-mini-browser-003",
      title: "DH_live_mini 官方预置形象",
      note: "官方人物包内置底片的 3.12 秒音频驱动参考；带 MatesX 水印，仅用于内部效果评估。",
    };
  }
  if (lipSyncId === "dh-live-mini-v1") {
    return {
      kind: "pending", title: "当前三段组合尚无 DH_live_mini 效果",
      note: "需要为当前人物与动作底片重新制作并验证特征资产，不使用其他底片样片代替。",
    };
  }
  if (lipSyncId === "liteavatar") {
    return {
      kind: "pending", title: "当前三段组合尚无 LiteAvatar 效果",
      note: "LiteAvatar 动态预览只开放给已验证的官方人物与内置底片组合。",
    };
  }
  if (lipSyncId === "wav2lip256") {
    return {
      kind: "pending", title: "当前三段组合尚无 Wav2Lip 256 效果",
      note: "需要用当前人物和动作底片重新生成后才能展示；不复用其他底片的样片。",
    };
  }
  if (lipSyncId === "feathertalk") {
    return {
      kind: "pending",
      title: "FeatherTalk 效果待训练",
      note: "需要 3–5 分钟同人物口播素材训练专属模型，当前没有可代表所选人物的可信视频。",
    };
  }
  if (lipSyncId === "musetalk15") {
    return {
      kind: "pending",
      title: "MuseTalk 1.5 效果待 GPU 实测",
      note: "等待 NVIDIA Sidecar 生成同输入对照，暂不使用网络样片或其他人物代替。",
    };
  }
  return {
    kind: "pending",
    title: "LatentSync 1.6 效果待 GPU 实测",
    note: "高质量离线候选尚未生成同人物产物，补齐 GPU 运行后再开放播放。",
  };
}

export function getPipelineCompatibility(avatarId: string, videoId: string, lipSyncId: string) {
  if ((avatarId === "liteavatar-preset" || avatarId === "dh-live-preset") && videoId !== "avatar-bundled") {
    return {
      kind: "blocked",
      title: "请选择人物预置底片",
      detail: "当前人物包与自带循环底片绑定，不能把 FFmpeg、LivePortrait 或上传视频标记为该实测产物的输入。",
    } as const;
  }
  if (videoId === "avatar-bundled" && avatarId !== "liteavatar-preset" && avatarId !== "dh-live-preset") {
    return {
      kind: "blocked",
      title: "当前人物没有预置底片",
      detail: "人物预置底片只属于 LiteAvatar 与 DH_live 的官方人物包；Shuchang 或新上传人物需要选择 FFmpeg、LivePortrait 或上传动作底片。",
    } as const;
  }
  if (avatarId === "liteavatar-preset" && lipSyncId === "liteavatar") {
    return {
      kind: "ready",
      title: "预置资产直连，第二段跳过",
      detail: "LiteAvatar 人物包已经包含背景、参考帧和人物模型；当前视频制作选项不会覆盖这份预置资产。",
    } as const;
  }
  if (avatarId === "dh-live-preset" && lipSyncId === "dh-live-mini-v1") {
    return {
      kind: "ready",
      title: "预置资产直连，第二段跳过",
      detail: "DH_live 官方人物包已经带有循环视频和特征数据；视频制作步骤只对新人物生效。",
    } as const;
  }
  if (avatarId === "liteavatar-preset" && lipSyncId !== "liteavatar") {
    return {
      kind: "blocked",
      title: "组合需要调整",
      detail: "LiteAvatar 官方预置人物和它的人物模型资产绑定，请把口型模型切换为 LiteAvatar 音频驱动。",
    } as const;
  }
  if (lipSyncId === "liteavatar" && avatarId !== "liteavatar-preset") {
    return {
      kind: "blocked",
      title: "缺少同人物 LiteAvatar 资产",
      detail: "LiteAvatar 不能直接使用一张新人物图。当前只允许搭配已验证的官方预置形象。",
    } as const;
  }
  if (avatarId === "dh-live-preset" && lipSyncId !== "dh-live-mini-v1") {
    return {
      kind: "blocked",
      title: "官方预置形象与渲染器绑定",
      detail: "这份 DH_live 人物特征包只在 DH_live_mini v1 中验证过；其他口型模型需要原始视频或重新制作人物资产。",
    } as const;
  }
  if (avatarId === "custom-upload") {
    return {
      kind: "waiting",
      title: "需要上传并制作人物资产",
      detail: "上传图片只是身份源图；还要按当前视频制作步骤生成动作底片，再进入口型预处理。",
    } as const;
  }
  if (lipSyncId === "feathertalk") {
    return {
      kind: "waiting",
      title: "需要先训练同人物模型",
      detail: "当前人物图和动作底片不能替代 3–5 分钟同人物清晰口播训练素材，配置可以保存但暂不能运行。",
    } as const;
  }
  if (lipSyncId === "musetalk15" || lipSyncId === "latentsync16") {
    return {
      kind: "waiting",
      title: "等待 NVIDIA Sidecar",
      detail: "输入与输出契约已经确定；接入远程 GPU 后再记录真实显存、吞吐和质量结果。",
    } as const;
  }
  if (videoId === "liveportrait-optimized") {
    return {
      kind: "waiting",
      title: "基础链路已跑通，优化底片待制作",
      detail: "当前 3.12 秒基础产物可继续用于技术评测；去闪烁、首尾筛帧和交叉淡化尚未生成正式新产物。",
    } as const;
  }
  if (videoId === "prepared-video") {
    return {
      kind: "waiting",
      title: "等待动作底片",
      detail: "上传后会检查无对白、人物身份、25fps、9:16 画幅和循环接缝，合格后才能运行口型模型。",
    } as const;
  }
  return {
    kind: "ready",
    title: "组合可进入本地评测",
    detail: "这条链路的必要资产已具备；运行结果仍以评测记录和授权状态为准。",
  } as const;
}

export const AVATAR_IDENTITY_CHOICES: AvatarIdentityChoice[] = [
  {
    id: "shuchang",
    name: "Shuchang 测试形象",
    status: "experimental",
    statusLabel: "同人物已跑通",
    summary: "当前统一评测人物，可组合 FFmpeg、LivePortrait、Wav2Lip 与 DH_live_mini。",
    input: "项目内授权待确认的正面人物图",
    output: "可复用人物身份资产",
    runtime: "图片资产",
    imageUrl: "/digital-human/shuchang-preview.jpg",
    rights: "仅内部测试，宣传前确认肖像与素材授权",
  },
  {
    id: "liteavatar-preset",
    name: "LiteAvatar 官方预置形象",
    status: "ready",
    statusLabel: "效果已验证",
    summary: "保留本次效果较好的官方角色；人物特征与 LiteAvatar 模型资产绑定。",
    input: "官方预置 Avatar 目录",
    output: "LiteAvatar CPU 数字人",
    runtime: "Mac · CPU",
    artifactId: "liteavatar-cpu-001",
    rights: "模型与预置人物许可仍需单独确认",
  },
  {
    id: "dh-live-preset",
    name: "DH_live 官方预置形象",
    status: "experimental",
    statusLabel: "浏览器已跑通",
    summary: "官方 Browser/WASM 形象，适合验证流式音频驱动和前端渲染。",
    input: "官方循环视频与人物特征包",
    output: "DH_live 浏览器数字人",
    runtime: "Browser · WASM / WebGL2",
    artifactId: "dh-live-mini-browser-003",
    rights: "带 MatesX 水印，仅内部评测",
  },
  {
    id: "custom-upload",
    name: "上传新人物图片",
    status: "requires_asset",
    statusLabel: "待上传",
    summary: "为后续新增多个授权人物预留入口，不直接把上传图片等同于可用 Avatar。",
    input: "正面、清晰、肩部以上、建议 1024px 以上图片",
    output: "待进入动作底片制作的人物源图",
    runtime: "本地文件",
    rights: "上传者必须拥有肖像与素材使用权",
  },
];

export const VIDEO_BASE_CHOICES: PipelineChoice[] = [
  {
    id: "avatar-bundled",
    name: "人物预置底片",
    status: "ready",
    statusLabel: "绑定资产",
    summary: "LiteAvatar / DH_live 官方人物包自带的循环底片，只用于对应预置人物。",
    input: "已验证人物包",
    output: "人物包内置循环帧与特征数据",
    runtime: "无需重新制作",
  },
  {
    id: "ffmpeg-static",
    name: "FFmpeg 静态底片",
    status: "ready",
    statusLabel: "可运行",
    summary: "零动作对照组，适合验证口型模型、格式和传输，不作为最终自然动作效果。",
    input: "单张人物图 + 时长 / 画幅 / 帧率",
    output: "5 秒、720×1280、25fps、H.264 静音 MP4",
    runtime: "Mac · CPU",
  },
  {
    id: "liveportrait-optimized",
    name: "LivePortrait 优化动作底片",
    status: "experimental",
    statusLabel: "基础版已跑通",
    summary: "已有 3.12 秒基础底片；闭嘴驱动、锁裁切、去闪烁和无缝循环是下一版优化流程。",
    input: "正面人物图 + 6–10 秒闭嘴驱动视频",
    output: "优化目标：6–8 秒、9:16、25fps、无明显原始口型的循环 MP4",
    runtime: "Mac · MPS + CPU fallback",
  },
  {
    id: "prepared-video",
    name: "上传已有动作底片",
    status: "requires_asset",
    statusLabel: "可接入",
    summary: "允许使用商业 I2V 或人工拍摄的视频，但必须先通过无说话、循环接缝和身份一致性检查。",
    input: "4–10 秒、无对白、正面半身动作视频",
    output: "规范化 720×1280、25fps 静音循环 MP4",
    runtime: "FFmpeg 规范化",
  },
];

export const LIP_SYNC_CHOICES: PipelineChoice[] = [
  {
    id: "dh-live-mini-v1",
    name: "DH_live_mini v1",
    status: "ready",
    statusLabel: "本机已跑通",
    summary: "无需按人物训练；动作底片预处理后在浏览器按流式音频更新口型。",
    input: "无明显说话的循环底片 + 16kHz PCM 音频",
    output: "Browser Canvas / WebGL2 实时画面",
    runtime: "Mac · Browser WASM",
  },
  {
    id: "liteavatar",
    name: "LiteAvatar 音频驱动",
    status: "requires_asset",
    statusLabel: "运行时不完整",
    summary: "CPU 路线历史效果可保留，但当前缺语音特征权重，且只适配预先制作的 LiteAvatar 人物资产。",
    input: "LiteAvatar 人物模型 + 16kHz 音频",
    output: "合成视频帧",
    runtime: "Mac · CPU · 历史约 15 FPS",
  },
  {
    id: "wav2lip256",
    name: "Wav2Lip 256",
    status: "ready",
    statusLabel: "本机已跑通",
    summary: "通用视频口型基线，可离线或接入 LiveTalking；标准权重仅限非商业评测。",
    input: "人物视频 + 16kHz 单声道音频",
    output: "重绘嘴部的视频帧 / MP4",
    runtime: "Mac · MPS / CPU",
  },
  {
    id: "feathertalk",
    name: "FeatherTalk",
    status: "requires_asset",
    statusLabel: "缺训练素材",
    summary: "Apple Silicon/MNN 候选，但每个人物需要 3–5 分钟清晰口播视频训练专属 UNet。",
    input: "同人物 3–5 分钟 25fps 口播 + 实时音频",
    output: "专属人物口型帧",
    runtime: "Mac · MNN / Metal · 待实测",
  },
  {
    id: "musetalk15",
    name: "MuseTalk 1.5",
    status: "requires_gpu",
    statusLabel: "需 NVIDIA Sidecar",
    summary: "高质量 256×256 脸部重绘候选，官方实时数据来自 NVIDIA，Mac 不作为运行目标。",
    input: "动作底片 + 音频 + 人脸区域参数",
    output: "25fps 口型视频帧",
    runtime: "远程 NVIDIA · 12GB+ 起测",
  },
  {
    id: "latentsync16",
    name: "LatentSync 1.6",
    status: "requires_gpu",
    statusLabel: "GPU 离线候选",
    summary: "扩散式视频口型同步，优先作为高质量离线对照，不宣称实时。",
    input: "已有视频 + 音频",
    output: "口型同步 MP4",
    runtime: "远程 NVIDIA · CUDA",
  },
];
