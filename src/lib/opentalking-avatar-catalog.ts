export interface OpenTalkingAvatarAsset {
  id: string;
  name: string;
  width: number;
  height: number;
  previewImageUrl: string;
  sourceImageUrl: string;
  motionVideoUrl?: string;
}

const asset = (
  id: string,
  name: string,
  width: number,
  height: number,
  hasMotionVideo = false,
): OpenTalkingAvatarAsset => ({
  id,
  name,
  width,
  height,
  previewImageUrl: `/digital-human/opentalking/${id}/preview.png`,
  sourceImageUrl: `/digital-human/opentalking/${id}/reference.png`,
  ...(hasMotionVideo ? { motionVideoUrl: `/digital-human/opentalking/${id}/motion.mp4` } : {}),
});

export const OPENTALKING_AVATAR_CATALOG: OpenTalkingAvatarAsset[] = [
  asset("anchor", "主播", 512, 512, true),
  asset("ancient-beauty", "古装美女", 720, 900, true),
  asset("ancient-young-man", "古风小生", 720, 1280, true),
  asset("anime-handsome-guy", "动漫帅哥", 720, 900, true),
  asset("companion", "陪伴", 538, 878, true),
  asset("video-call", "视频通话", 720, 540, true),
  asset("news-duo", "新闻双人主播", 960, 720, true),
  asset("dogo-light2d", "DOGO 博士小狗", 561, 1024, true),
  asset("female-host-transparent", "女主持（透明背景）", 1024, 1024, true),
  asset("fitness-coach", "健身教练", 506, 776, true),
  asset("immortal-man", "修仙帅哥", 720, 1280, true),
  asset("laozi", "老子", 430, 700, true),
  asset("live-broadcast", "带货主播", 720, 1280, true),
  asset("liveportrait-musetalk", "LivePortrait + MuseTalk", 720, 928, true),
  asset("new-year", "新年", 720, 1280, true),
  asset("newscaster", "新闻主播", 790, 1166, true),
  asset("office-woman", "职场女", 540, 900, true),
  asset("singer", "歌手", 830, 1108, true),
  asset("virtual-idol", "虚拟偶像", 720, 1280, true),
  asset("woman", "职场女（动态）", 858, 1072, true),
];
