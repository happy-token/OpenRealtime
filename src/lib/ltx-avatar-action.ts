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

export type PromptLanguage = "zh-CN" | "en";

export const BASE_MOTION_CONSTRAINTS = {"zh-CN": "以所提供参考图中的人物为唯一主体，保留其身份、五官、发型、服装、配饰、背景和光照。生成适用于一对一视频通话、可重复循环播放的静默动作底片。沿用参考图构图，固定镜头，不推拉、不摇移、不切镜。人物主要正对镜头，视线自然朝向镜头附近，双眼、完整脸部和嘴部始终清晰可见。保持头部基本水平，不明显转成侧脸，不低头，不让头发、手或物体遮住脸和嘴。嘴唇自然轻闭，下颌放松，全程不说话、不做发音口型、不张嘴、不露齿；可有稳定、轻微的闭嘴微笑。嘴部随脸部自然运动，不僵硬冻结。只表现下述角色动作，配合轻微呼吸和稀疏、自然的眨眼；不招手、不指向、不竖拇指、不反复点头、不进行有明确开始结束含义的手势。手保持在参考图中的自然位置，不新增道具。动作在片段中段自然展开，在结尾平缓回到开头的姿态、头部位置和表情，运动速度也平滑衔接；不突然复位，不淡出，不制造停顿卡点。无说话声、无发声、无音乐。", "en": "Use the person in the supplied reference image as the sole subject. Preserve their identity, facial features, hairstyle, clothing, accessories, background, and lighting. Create a silent base-motion clip for continuous looping during a one-to-one video call. Retain the reference framing with a locked camera, no zoom, pan, or cuts. Keep the person predominantly frontal with natural attention near the lens. Both eyes, the full face, and the mouth remain clearly visible throughout. Keep the head approximately level: no pronounced profile turns, downward head movement, or face and mouth occlusion by hair, hands, or objects. Keep the lips naturally and gently closed and the jaw relaxed. No speaking, speech articulation, open mouth, or visible teeth. A subtle, steady closed-mouth smile is allowed. Let the mouth move naturally with the face rather than freezing it. Perform only the role motion below, accompanied by subtle breathing and sparse natural blinks. No waving, pointing, thumbs-up, repeated nodding, or gestures that imply a distinct greeting, response, or farewell. Keep the hands in their natural reference position and introduce no props. Let the motion unfold naturally through the middle of the clip, then ease back to the opening posture, head position, and expression, with smoothly compatible motion at the loop boundary. No abrupt reset, fade-out, or conspicuous pause. No speech, vocalization, or music."} as const;

export const LTX_PROMPT_PRESETS = [{
  id: "video-conversation", name: "视频对话", actionName: "视频对话 · 温柔陪伴",
  description: "视频通话静默循环底片，供后续口型对齐使用",
  prompt: BASE_MOTION_CONSTRAINTS.en,
}] as const;
export type LtxPromptPresetId = (typeof LTX_PROMPT_PRESETS)[number]["id"] | "custom";

export const VIDEO_PROMPT_STYLES = [
  {"id": "gentle-companion", "name": "温柔陪伴", "nameEn": "Gentle Companion", "description": "呈现温柔、放松且始终在场的陪伴感", "descriptionEn": "Convey a warm, relaxed, consistently present companion.", "speechCompatible": true, "prompt": "Convey a warm, relaxed, consistently present companion. Keep the shoulders open, the gaze soft, and a faint closed-mouth smile steady. During the first half, let the upper body ease slightly closer to the camera as a natural posture adjustment, keeping the head level and frontal. During the second half, gently return to the opening position. Keep the eyes and brows relaxed, without eyebrow emphasis, nodding, or comforting gestures. Use one smooth, gentle posture arc rather than repeated rocking.", "promptZh": "呈现温柔、放松且始终在场的陪伴感。肩部舒展，目光柔和，保持淡淡的闭嘴微笑。片段前半段，上身缓慢、轻微地向镜头靠近，头部仍水平正面，像自然调整坐姿；后半段缓慢回到初始位置。眉眼保持舒缓，不挑眉强调，不点头，不做安慰手势。整个动作连贯、柔和，避免反复前后摇摆。"},
  {"id": "lively-friend", "name": "活泼朋友", "nameEn": "Lively Friend", "description": "呈现明朗、有精神但不过度兴奋的朋友感", "descriptionEn": "Convey a bright, engaged friend without excessive excitement.", "speechCompatible": true, "prompt": "Convey a bright, engaged friend without excessive excitement. Keep the eyes alert, the brows slightly open, and a natural closed-mouth smile steady. Through the middle of the clip, let the shoulders and upper body make one light, very small lateral weight adjustment, then naturally return to center. Keep the head level and facing the camera. Use a slightly livelier pace than the gentle companion, without shoulder bouncing, repeated swaying, double eyebrow beats, surprise reactions, or greetings.", "promptZh": "呈现明朗、有精神但不过度兴奋的朋友感。眼神明亮，眉部略舒展，闭嘴微笑自然稳定。片段中段，肩部与上身一起做一次轻盈、幅度很小的横向重心调整，再自然回到中心；头部保持水平朝向镜头。动作节奏比温柔陪伴稍轻快，但不抖肩、不左右连续摇摆、不挑眉双拍，不出现惊喜或打招呼的表演。"},
  {"id": "professional-advisor", "name": "专业顾问", "nameEn": "Professional Advisor", "description": "呈现稳重、可靠的专业顾问", "descriptionEn": "Convey a composed, dependable professional advisor.", "speechCompatible": true, "prompt": "Convey a composed, dependable professional advisor. Sit upright with balanced shoulders, steady attention toward the lens, and a calm expression; a very faint closed-mouth smile is acceptable. Through the middle, subtly adjust the uprightness of the torso as if settling comfortably into the seat, then restore the opening posture. Keep head displacement minimal. Motion is restrained and even, without approving nods, thoughtful frowns, or explanatory gestures.", "promptZh": "呈现稳重、可靠的专业顾问。坐姿挺拔、肩部平衡，视线稳定朝向镜头，表情平和，可保留极轻微闭嘴微笑。片段中段缓慢调整上身的挺拔程度，像舒适地坐稳，随后恢复开头姿态；头部位置变化极小。动作克制、均匀，不做认可点头、不皱眉思考、不作陈述手势。"},
  {"id": "patient-teacher", "name": "耐心老师", "nameEn": "Patient Teacher", "description": "呈现亲切、耐心且容易接近的老师", "descriptionEn": "Convey an approachable, kind, patient teacher.", "speechCompatible": true, "prompt": "Convey an approachable, kind, patient teacher. Keep an open shoulder posture, attentive yet gentle eyes, and a slight closed-mouth smile. Through the middle, slowly relax and open both shoulders a little, allowing the upper chest posture to ease naturally, then smoothly return to the opening state. Stay centered and frontal with an even pace. No instructional hand gestures, glances toward off-screen materials, looking down, or repeated encouraging nods.", "promptZh": "呈现亲切、耐心且容易接近的老师。肩姿开放，眼神专注而柔和，保持轻微闭嘴微笑。片段中段，双肩缓慢放松并略微展开，胸口姿态随之自然舒展，随后平缓回到开头状态。身体保持居中正面，节奏平稳；不抬手讲解、不看向画面外的教材、不低头、不用反复点头表示鼓励。"},
  {"id": "calm-scholar", "name": "冷静学者", "nameEn": "Calm Scholar", "description": "呈现安静、专注、沉着的学者", "descriptionEn": "Convey a quiet, focused, composed scholar.", "speechCompatible": true, "prompt": "Convey a quiet, focused, composed scholar. Keep the torso steady, the shoulders natural, the lips gently closed, and the expression neutral but approachable. Maintain a settled posture for most of the clip, with subtle breathing, natural eye activity, and sparse blinks. Through the middle, make only one very slight relaxation of seated weight, then slowly return. Allow longer settled intervals than the other styles without appearing frozen, theatrically staring, looking down to read, or touching the chin.", "promptZh": "呈现安静、专注、沉着的学者。上身稳定，肩部自然，嘴唇轻闭，表情中性而不冷漠。大部分时间保持安定姿态，以轻微呼吸、自然眼部变化和稀疏眨眼体现生命感。片段中段只做一次非常轻微的坐姿重心松弛，随后缓慢回到原位。比其他风格保留更长的安定间隔，但不僵硬、不凝视表演、不低头阅读、不摸下巴。"},
  {"id": "confident-partner", "name": "自信搭档", "nameEn": "Confident Partner", "description": "呈现从容、平等、可靠的搭档", "descriptionEn": "Convey an assured, equal, dependable partner.", "speechCompatible": true, "prompt": "Convey an assured, equal, dependable partner. Keep the gaze steady yet relaxed, the shoulders loose, and a very slight closed-mouth smile stable. During the first half, slowly shift seated weight a small distance to one side, with a subtle adjustment of the shoulder line. During the second half, return to the opening balance at an unhurried pace. Keep the head level and frontal rather than turning with the shoulders. Motion is more grounded than the lively friend, with slightly clearer displacement, without posing, shrugging, or provocative eyebrow raises.", "promptZh": "呈现从容、平等、可靠的搭档。目光稳定而放松，肩部松弛，嘴角保持极轻微的闭嘴微笑。片段前半段，上身缓慢做一次小幅侧向重心转移，肩线随之轻微调整；后半段以从容的节奏回到起始重心。头部保持水平正面，不随肩部转向侧脸。动作比活泼朋友更沉稳、幅度略清晰，但不摆造型、不耸肩、不做挑眉挑衅。"},
 ] as const;
// Kept as an export alias for consumers of the previous catalog.
export const COMPANION_EMOTION_STYLES = VIDEO_PROMPT_STYLES;
export type VideoPromptStyleId = (typeof VIDEO_PROMPT_STYLES)[number]["id"];

export function composeVideoGenerationPrompt(
  presetId: Exclude<LtxPromptPresetId, "custom">,
  styleId: VideoPromptStyleId,
  language: PromptLanguage = "en",
) {
  const preset = LTX_PROMPT_PRESETS.find((item) => item.id === presetId);
  const style = VIDEO_PROMPT_STYLES.find((item) => item.id === styleId);
  if (!preset || !style) throw new Error("视频生成提示词模块无效");
  return `${BASE_MOTION_CONSTRAINTS[language]} ${language === "zh-CN" ? style.promptZh : style.prompt}`;
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
