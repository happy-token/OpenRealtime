export const VIDEO_GENERATION_DEFAULT_MODEL = "ltx-2-3-fast" as const;

export const VIDEO_GENERATION_PROVIDERS = [
  { id: "ltx", name: "LTX", detail: "LTX Video API" },
  { id: "minimax", name: "MiniMax", detail: "H3 系列" },
] as const;

export const VIDEO_GENERATION_MODELS = [
  { id: "ltx-2-3-fast", name: "LTX 2.3 Fast", detail: "默认 · 低成本", provider: "ltx" },
  { id: "ltx-2-3-pro", name: "LTX 2.3 Pro", detail: "更高保真", provider: "ltx" },
  { id: "ltx-2-5-fast", name: "LTX 2.5 Fast", detail: "新版本快速模型", provider: "ltx" },
  { id: "ltx-2-5-pro", name: "LTX 2.5 Pro", detail: "新版本高质量模型", provider: "ltx" },
  { id: "MiniMax-H3", name: "H3", detail: "768P / 2K · 多模态", provider: "minimax" },
  { id: "MiniMax-H3-Max", name: "H3 Max", detail: "极速生成 · 480P / 768P", provider: "minimax" },
  { id: "MiniMax-H3-Context-IR", name: "H3-Context-IR", detail: "独立增强提示词后由 H3 生成", provider: "minimax" },
] as const;

export type VideoGenerationModelId = (typeof VIDEO_GENERATION_MODELS)[number]["id"];
export type VideoGenerationProvider = (typeof VIDEO_GENERATION_MODELS)[number]["provider"];
export type LtxModelId = Extract<VideoGenerationModelId, `ltx-${string}`>;
export type MiniMaxModelId = Extract<VideoGenerationModelId, `MiniMax-${string}`>;

export const VIDEO_GENERATION_DEFAULT_MODELS = {
  ltx: VIDEO_GENERATION_DEFAULT_MODEL,
  minimax: "MiniMax-H3",
} as const satisfies Record<VideoGenerationProvider, VideoGenerationModelId>;

const MOUTH_AND_IDENTITY_CONSTRAINTS = `Keep the lips gently closed in the natural resting shape from the reference frame, with no visible gap, teeth, or tongue. The closed mouth and relaxed jaw must move coherently with the cheeks, head, breathing, and whole-face perspective instead of remaining pinned to a fixed screen position. Allow only tiny non-articulatory soft-tissue settling around the closed lips; there are no phoneme or viseme transitions, no speech articulation, and no lip-sync movement. Preserve the exact identity, facial proportions, hairstyle, clothing, background, lighting, crop, and focal length.`;

const LOOP_RETURN_CONSTRAINTS = `From 4.5 to 5.5 seconds, settle smoothly and precisely back to the original reference pose. From 5.5 to 6.0 seconds, hold the exact starting pose for loop continuity. No hand movement, camera movement, zoom, cut, background motion, new objects, identity drift, facial deformation, or flicker.`;

const SPEECH_COMPATIBLE_MOTION_CONSTRAINTS = `This is a speech-ready base-motion plate for a downstream lip-sync model. Follow the style-specific gaze and head-pose choreography exactly, keeping the face within 8 degrees of frontal yaw, pitch, and roll so the mouth remains fully visible. Keep the mouth region unobstructed and stable relative to the face in scale, perspective, and lighting, while allowing it to travel naturally with whole-face motion. No deep bow, large lean toward or away from the camera, or motion beyond the explicitly described choreography that would disrupt continuous speaking. Emotional emphasis must use eyes, eyebrows, blinking, and small shoulder or upper-torso motion timed like natural phrase-boundary gestures.`;

export const LTX_PROMPT_PRESETS = [
  {
    id: "video-conversation",
    name: "视频对话",
    actionName: "视频对话 · 甜美元气",
    description: "视频通话构图，适合后续口型模型的说话兼容动作",
    prompt: `A seamless silent base-motion loop for a person who will appear to speak continuously in a one-to-one video-call conversation after downstream lip-sync processing, shot as one locked-off medium close-up. From 0.0 to 0.7 seconds, hold the exact reference pose. From 0.7 to 4.5 seconds, perform exactly the style-specific choreography described above with smooth human timing, natural easing, subtle upper-chest breathing, one or two blinks, and phrase-boundary emotional emphasis. Keep the lips gently closed and the jaw relaxed while allowing the mouth region to follow the whole face naturally; never freeze, paste, or pixel-lock the mouth in screen space. Diegetic audio is quiet room tone only: no speech, no vocalization, no music, and no sound effects. ${SPEECH_COMPATIBLE_MOTION_CONSTRAINTS} ${MOUTH_AND_IDENTITY_CONSTRAINTS} ${LOOP_RETURN_CONSTRAINTS} No extra gesture or motion beyond the explicitly described style-specific choreography.` ,
  },
] as const;

export type LtxPromptPresetId = (typeof LTX_PROMPT_PRESETS)[number]["id"] | "custom";

const COMPANION_REFERENCE_LOCK = "Use the current reference image exactly as supplied: do not restyle or change the person's hairstyle, makeup, facial features, clothing, accessories, lighting, background, or setting. The persona's visual reference is metadata for future source-image creation only. This action must remain compatible with continuous downstream lip-sync: keep the mouth region visible and geometrically stable relative to the face, and express the persona through eyes, eyebrows, blinking, shoulders, small upper-torso motion, and timing.";

export const COMPANION_EMOTION_STYLES = [
  {
    id: "sweet-vitality",
    name: "甜美元气",
    emotion: "开心惊喜",
    description: "可爱活泼 · 眉眼双拍与轻快肩部律动",
    visualReference: "高马尾、圆眼、酒窝、落日屋顶",
    speechCompatible: true,
    prompt: `${COMPANION_REFERENCE_LOCK} Choreography: create buoyant speaking energy with no nod and no downward head movement. Keep the head, chin, and mouth region level and frontal. From 0.7 to 1.6 seconds, brighten the eyes, lift both eyebrows in one quick happy recognition beat, and open the shoulders laterally by about 1 centimeter. From 1.6 to 3.2 seconds, create two lively phrase-emphasis beats using alternating eyebrow lifts and a tiny 1-centimeter lateral shoulder sway, separated by one quick natural blink. From 3.2 to 4.5 seconds, settle the shoulders while keeping warm direct lens eye contact. Emotional tone: cute, energetic, eager, affectionate, and spontaneous without becoming childish or theatrical.`,
  },
  {
    id: "soft-glow",
    name: "纯欲柔光",
    emotion: "害羞依恋",
    description: "乖巧甜美 · 害羞眉眼与轻柔肩部收放",
    visualReference: "低马尾、清透妆感、象牙白缎面、窗边柔光",
    speechCompatible: true,
    prompt: `${COMPANION_REFERENCE_LOCK} Choreography: create shy but connected speaking presence that feels trusting and emotionally close. Keep the head, chin, and gaze level toward the lens; do not look down. From 0.7 to 1.8 seconds, let the shoulders draw inward laterally by about 1 centimeter while the inner eyebrows soften. From 1.8 to 3.1 seconds, use one soft blink and a tiny asymmetrical eyebrow response, as if quietly gathering courage, without changing the lips. From 3.1 to 4.5 seconds, let the shoulders relax open and maintain gentle direct eye contact. Emotional tone: sweet, well-behaved, shy, trusting, affectionate, and soft; never sexualized or performative.`,
  },
  {
    id: "cool-night",
    name: "冷艳夜色",
    emotion: "冷静自持",
    description: "冷艳自信 · 稳定直视与克制眉眼强调",
    visualReference: "猫系眼型、黑色长发、单肩造型、城市夜景",
    speechCompatible: true,
    prompt: `${COMPANION_REFERENCE_LOCK} Choreography: create cool self-possessed speaking presence without looking away. Keep the head and chin level and frontal. From 0.7 to 1.8 seconds, settle one shoulder laterally by about 1 centimeter while holding steady cat-like lens eye contact. From 1.8 to 3.2 seconds, make one precise outer-eyebrow emphasis followed by a slow controlled blink. From 3.2 to 4.5 seconds, re-balance the shoulders and maintain calm direct gaze. Emotional tone: cool, elegant, confident, restrained, subtly intriguing, and never hostile.`,
  },
  {
    id: "gentle-intellectual",
    name: "知性温柔",
    emotion: "共情安慰",
    description: "温柔共情 · 内眉安慰与稳定陪伴感",
    visualReference: "低发髻、克制妆容、燕麦色针织、温暖书房",
    speechCompatible: true,
    prompt: `${COMPANION_REFERENCE_LOCK} Choreography: create empathetic reassuring speaking presence that feels like fully understanding the other person's feelings. Keep the head and chin level and frontal. From 0.7 to 1.9 seconds, let both shoulders settle down about 1 centimeter while lifting the inner eyebrows gently. From 1.9 to 3.2 seconds, hold direct lens eye contact with one soft blink and a second smaller sympathetic eyebrow emphasis. From 3.2 to 4.5 seconds, let the upper torso shift laterally about 1 centimeter and return to center. Emotional tone: intelligent, warm, patient, accepting, emotionally grounded, and quietly reassuring.`,
  },
  {
    id: "melancholy-empathy",
    name: "忧郁共鸣",
    emotion: "温柔忧郁",
    description: "夜晚独处 · 侧垂避视与脆弱停顿",
    visualReference: "柔顺深色长发、低饱和妆容、雾蓝针织、雨夜窗边",
    speechCompatible: true,
    prompt: `${COMPANION_REFERENCE_LOCK} Choreography: create the private loneliness of a quiet late night when she believes she is alone, not a face-to-face reassurance moment. Once motion begins, she does not look into the lens. From 0.7 to 1.55 seconds, her gaze slowly slips about 12 degrees below and to one side of the camera as her head inclines laterally 4 to 6 degrees and lowers only 3 to 4 degrees, like a small involuntary droop rather than a nod or bow. Her shoulders draw inward about 1 centimeter and the inner eyebrows pull gently upward and together. From 1.55 to 3.25 seconds, hold the lowered off-camera gaze through a fragile still pause, followed by one slow heavy blink and a restrained breath catch; keep the lips softly closed and naturally coupled to the cheeks and jaw, with no smile or speech articulation. From 3.25 to 4.5 seconds, release a long silent exhale while the shoulders sink about 1 centimeter and the head remains slightly side-dropped, never meeting the lens during the emotional beat. Convey a young woman quietly enduring sadness by herself, making the viewer instinctively want to comfort, protect, and stay beside her. Emotional tone: lonely, vulnerable, tender, quietly heartbroken, restrained, and deeply pitiable without performance. No direct lens gaze during the emotional action, no comforting nod, therapist expression, warm smile, composed professional demeanor, glamour pose, melodrama, sobbing, visible tears, hostility, or dramatic collapse.`,
  },
] as const;

export const VIDEO_PROMPT_STYLES = [
  ...COMPANION_EMOTION_STYLES,
] as const;

export type VideoPromptStyleId = (typeof VIDEO_PROMPT_STYLES)[number]["id"];

export function composeVideoGenerationPrompt(
  presetId: Exclude<LtxPromptPresetId, "custom">,
  styleId: VideoPromptStyleId,
) {
  const preset = LTX_PROMPT_PRESETS.find((item) => item.id === presetId);
  const style = VIDEO_PROMPT_STYLES.find((item) => item.id === styleId);
  if (!preset || !style) throw new Error("视频生成提示词模块无效");
  return `${style.prompt} ${preset.prompt}`;
}

export function isVideoGenerationModelId(value: unknown): value is VideoGenerationModelId {
  return VIDEO_GENERATION_MODELS.some((model) => model.id === value);
}

export function isLtxModelId(value: unknown): value is LtxModelId {
  return typeof value === "string" && value.startsWith("ltx-") && isVideoGenerationModelId(value);
}

export function isMiniMaxModelId(value: unknown): value is MiniMaxModelId {
  return typeof value === "string" && value.startsWith("MiniMax-") && isVideoGenerationModelId(value);
}

export function videoGenerationModelsForProvider(provider: VideoGenerationProvider) {
  return VIDEO_GENERATION_MODELS.filter((model) => model.provider === provider);
}

export function videoGenerationProviderForModel(modelId: VideoGenerationModelId): VideoGenerationProvider {
  return VIDEO_GENERATION_MODELS.find((model) => model.id === modelId)?.provider ?? "ltx";
}

// Compatibility exports for modules outside the action-creation surface.
export const LTX_DEFAULT_MODEL = VIDEO_GENERATION_DEFAULT_MODEL;
export const LTX_MODELS = VIDEO_GENERATION_MODELS.filter((model) => model.provider === "ltx");
