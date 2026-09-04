# “AI 赛博女友”风格素材筛选与试跑包

调研日期：2026-08-20

## 结论

Bilibili 上较接近当前目标的案例是[【开源实测】我用 OpenTalking 做了个实时对话美女数字人，效果有点治愈](https://www.bilibili.com/video/BV1t7L86TEGt/)。它的核心并不是传统“霓虹赛博朋克”，而是**暖系真人陪伴感**：年轻亚洲女性、丸子头或简洁发型、米白针织、暖色住宅背景、正面中近景、柔光、轻微眨眼和呼吸。

因此素材分成两条视觉路线：

1. **产品主形象：暖系陪伴型。** 适合长期实时交互，脸部纹理清楚，口型模型更容易稳定。
2. **宣传片副形象：霓虹赛博型。** 第一眼更有“赛博”标签，但投影会污染唇部和肤色，不适合做主力 MuseTalk 底片。

## 已处理素材

所有 `ready/` 文件都已转为 720×1280、25 fps、H.264、`yuv420p`、无音轨，并通过 FFmpeg 完整解码检查。

| 文件 | 定位 | 口部/姿态检查 | 建议 |
|---|---|---|---|
| `ready/musetalk_ready_cozy_asian_companion_6p7s.mp4` | 暖客厅亚洲女性，最接近“治愈陪伴”空间感 | 基本闭嘴，正面偏轻微 3/4，眨眼自然，无手部遮挡 | **优先试跑 MuseTalk** |
| `ready/musetalk_ready_clean_asian_portrait_9p7s.mp4` | 米白服装、干净背景、亚洲女性 | 嘴唇闭合或自然贴合，持续正视，头部缓慢小幅倾斜 | **技术基线最稳**，但服装略偏商务 |
| `ready/musetalk_ready_cyberpunk_projection_4p2s.mp4` | 绿色代码投影、亚洲女性、科幻视觉 | 前 4.2 秒人物保持画内，嘴部基本不动 | 仅作“赛博”宣传方向 A/B 测试；投影可能降低口型融合稳定性 |
| `ready/style_reference_cardigan_warm_home_6p2s.mp4` | 丸子头、米色针织、暖客厅，视觉上最像 B 站案例 | 嘴唇持续轻微分开，镜头推进明显 | **只作风格参考**，不列为严格闭嘴底片 |

## 来源与许可

### 1. 暖客厅陪伴型

- 来源：[Mixkit — Young girl looking at the camera in her loungeroom](https://mixkit.co/free-stock-video/young-girl-looking-at-the-camera-in-her-loungeroom-48688/)
- 本地使用版本：页面提供的 720p 版本。
- 页面标注：免费 720p 仅限个人用途；4K 商业用途需要 Envato 订阅及对应商业许可。
- 当前包仅用于内部调研和模型试跑，若进入商业产品，应购买商业版本或重新拍摄。

### 2. 干净人像技术基线

- 来源：[Pexels — Serious Woman Looking at Camera](https://www.pexels.com/video/serious-woman-looking-at-camera-8478630/)
- 作者：Sasha Kim。
- 许可：[Pexels License](https://www.pexels.com/license/)允许免费使用和修改，通常无需署名；不得暗示人物为产品背书，也不得把未修改素材原样转售或作为素材库重新分发。

### 3. 霓虹赛博方向

- 来源：[Mixkit — Female cyborg model portrait](https://mixkit.co/free-stock-video/female-cyborg-model-portrait-40210/)
- 页面标注：可按 Mixkit Stock Video Free License 用于商业或个人项目。
- 风险：动态投影穿过嘴部，MuseTalk 重绘区域可能出现色块跳变。

### 4. 米色针织暖家居参考

- 来源：[Pexels — Stressed Woman Looking at Camera](https://www.pexels.com/video/stressed-woman-looking-at-camera-9841385/)
- 作者：Ron Lach。
- 许可同上。该片不是严格闭嘴动作底片，保留它是因为人物发型、服装、光线和空间风格最接近参考案例。

## 商业素材候选（尚未购买，未做逐帧验收）

- [Vecteezy Pro — Asian woman looking at camera in home living room](https://www.vecteezy.com/video/68439785-ethnic-beautiful-woman-asian-korean-chinese-japanese-female-girl-looking-at-camera-portrait-face-expression-home-living-room-indoor-lady-smiling-businesswoman-business-homeowner-tenant-wife-girlfriend)：4K、14 秒、25 fps，描述最贴近目标；需 Pro/试用许可。
- [Storyblocks — Pensive serious Asian woman sitting at home](https://www.storyblocks.com/video/stock/pensive-serious-asian-woman-sitting-at-home-looking-at-camera-calm-focused-expression-portrait-korean-japanese-chinese-female-girl-indoors-353762430)：11 秒，4K/HD，订阅制。
- [Depositphotos — Young Asian woman sitting on sofa in living room](https://depositphotos.com/video/portrait-young-smiling-asian-woman-sitting-sofa-living-room-home-769806740.html)：15 秒、25 fps、最高 4K，需购买授权；“smiling”意味着必须确认是否露齿。

## MuseTalk 使用建议

先用 `musetalk_ready_clean_asian_portrait_9p7s.mp4` 排除技术链路问题，再用 `musetalk_ready_cozy_asian_companion_6p7s.mp4` 判断目标风格的融合效果。不要先用赛博投影片判断 MuseTalk 质量，因为动态光斑本身就会增加唇部区域的颜色变化。

验收重点：

- 嘴型结束后能否稳定回到原始闭嘴状态；
- 下巴边缘、牙齿和肤色是否闪烁；
- 循环首尾是否跳帧；
- 原片轻微头动时，嘴部掩码是否漂移；
- 720×1280 下实时帧率是否达到 25 fps。

## 文件校验

```text
6094f6354c53e18e6926f364b5dd38e3ef4aa4f14e05461d99fd6b46e356cac1  musetalk_ready_clean_asian_portrait_9p7s.mp4
b7234852f8db7ef0d21f4dc756a783730fe0688017399c3dee507710044584ae  musetalk_ready_cozy_asian_companion_6p7s.mp4
e3ace8fbc79ecee1b07b1b35fef92734b83f9983524c6e154a4a8b0e00eb9c95  musetalk_ready_cyberpunk_projection_4p2s.mp4
e8185ecfdced268bc08a0d1c27d89a986e20a0536b171619035fbc43a699abc2  style_reference_cardigan_warm_home_6p2s.mp4
```
