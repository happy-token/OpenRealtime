export const DEFAULT_TTS_VOICE = "zh_male_yuanboxiaoshu_uranus_bigtts";
export const DIALECT_TTS_VOICE = "zh_female_vv_uranus_bigtts";

export type TtsProvider = "bailian" | "doubao";

export const TTS_PROVIDER_OPTIONS = [
  { value: "bailian", label: "阿里云百炼", description: "CosyVoice · 双流式" },
  { value: "doubao", label: "火山引擎", description: "豆包 Seed TTS 2.0" },
] as const;

export const BAILIAN_TTS_VOICE_OPTIONS = [
  { value: "longanhuan_v3", label: "龙安欢 V3", description: "内置音色 · 欢脱元气女" },
  { value: "longyingmu_v3", label: "龙应沐 V3", description: "内置音色 · 优雅知性女" },
  { value: "longhua_v3", label: "龙华 V3", description: "内置音色 · 元气甜美女" },
  { value: "longcheng_v3", label: "龙橙 V3", description: "内置音色 · 智慧青年男" },
] as const;

export const BAILIAN_CLONED_VOICE_OPTIONS = [
  { value: "__active_bailian_clone__", label: "傻妞", description: "默认克隆音色 · 当前工作区" },
] as const;

export const BAILIAN_DIALECT_OPTIONS = [
  { value: "", label: "普通话", description: "默认发音" },
  { value: "cantonese", label: "广东话", description: "龙安欢 V3" },
  { value: "dongbei", label: "东北话", description: "龙安欢 V3" },
  { value: "henan", label: "河南话", description: "龙安欢 V3" },
  { value: "hunan", label: "湖南话", description: "龙安欢 V3" },
  { value: "shaanxi", label: "陕西话", description: "龙安欢 V3" },
  { value: "shandong", label: "山东话", description: "龙安欢 V3" },
  { value: "sichuan", label: "四川话", description: "龙安欢 V3" },
  { value: "anhui", label: "安徽话", description: "龙安欢 V3" },
] as const;

export const TTS_VOICE_OPTIONS = [
  { value: "zh_male_yuanboxiaoshu_uranus_bigtts", label: "渊博小叔 2.0", description: "通用 · 沉稳对话" },
  { value: "zh_female_qingxinnvsheng_uranus_bigtts", label: "清新女声 2.0", description: "通用 · 自然助理" },
  { value: "zh_female_vv_uranus_bigtts", label: "Vivi 2.0", description: "通用 · 中英 / 方言" },
  { value: "zh_female_xiaohe_uranus_bigtts", label: "小何 2.0", description: "通用 · 甜美亲切" },
  { value: "zh_male_m191_uranus_bigtts", label: "云舟 2.0", description: "通用 · 清爽沉稳" },
  { value: "zh_female_qingchezizi_uranus_bigtts", label: "清澈梓梓 2.0", description: "通用 · 清澈年轻" },
  { value: "zh_female_tianmeitaozi_uranus_bigtts", label: "甜美桃子 2.0", description: "通用 · 轻快自然" },
  { value: "zh_male_qingshuangnanda_uranus_bigtts", label: "清爽男大 2.0", description: "通用 · 年轻活力" },
  { value: "zh_female_kefunvsheng_uranus_bigtts", label: "暖阳女声 2.0", description: "客服 · 服务沟通" },
  { value: "saturn_zh_female_qingyingduoduo_cs_tob", label: "轻盈朵朵 2.0", description: "客服 · 轻盈自然" },
  { value: "saturn_zh_male_qingxinmumu_cs_tob", label: "清新沐沐 2.0", description: "客服 · 专业耐心" },
  { value: "zh_female_yingyujiaoxue_uranus_bigtts", label: "Tina 老师 2.0", description: "教育 · 中英双语" },
  { value: "zh_female_shaoergushi_uranus_bigtts", label: "少儿故事 2.0", description: "有声阅读 · 故事讲述" },
  { value: "zh_female_xiaoxue_uranus_bigtts", label: "儿童绘本 2.0", description: "有声阅读 · 亲子阅读" },
  { value: "zh_male_cixingjieshuonan_uranus_bigtts", label: "磁性解说男声 2.0", description: "视频配音 · 专业解说" },
  { value: "zh_female_liuchangnv_uranus_bigtts", label: "流畅女声 2.0", description: "视频配音 · 内容口播" },
  { value: "zh_female_cancan_uranus_bigtts", label: "知性灿灿 2.0", description: "角色扮演 · 知性角色" },
  { value: "saturn_zh_female_nuanxinxuejie_tob", label: "暖心学姐 2.0", description: "角色扮演 · 温柔陪伴" },
  { value: "zh_female_xueayi_saturn_bigtts", label: "儿童绘本 · 新版", description: "有声阅读 · 亲子讲述" },
  { value: "zh_male_dayi_saturn_bigtts", label: "大壹", description: "视频配音 · 沉稳叙事" },
  { value: "zh_female_mizai_saturn_bigtts", label: "黑猫侦探社咪仔", description: "视频配音 · 角色感" },
  { value: "zh_female_jitangnv_saturn_bigtts", label: "鸡汤女声", description: "视频配音 · 情感口播" },
  { value: "zh_female_meilinvyou_saturn_bigtts", label: "魅力女友", description: "视频配音 · 亲密自然" },
  { value: "zh_female_santongyongns_saturn_bigtts", label: "流畅女声 · 新版", description: "视频配音 · 流畅口播" },
  { value: "zh_male_ruyayichen_saturn_bigtts", label: "儒雅逸辰", description: "视频配音 · 儒雅温和" },
] as const;

export const TTS_DIALECT_OPTIONS = [
  { value: "", label: "普通话", description: "默认发音" },
  { value: "dongbei", label: "东北话", description: "仅 Vivi 2.0" },
  { value: "shaanxi", label: "陕西话", description: "仅 Vivi 2.0" },
  { value: "sichuan", label: "四川话", description: "仅 Vivi 2.0" },
] as const;

export type TtsVoice = string;
export type TtsDialect = (typeof TTS_DIALECT_OPTIONS)[number]["value"];

export function isTtsVoice(value: unknown): value is TtsVoice {
  return typeof value === "string" && /^[A-Za-z0-9_-]{2,128}$/.test(value);
}

export function findTtsVoice(value: string) {
  return TTS_VOICE_OPTIONS.find((option) => option.value === value);
}

export function isTtsDialect(value: unknown): value is TtsDialect {
  return typeof value === "string" && TTS_DIALECT_OPTIONS.some((option) => option.value === value);
}
