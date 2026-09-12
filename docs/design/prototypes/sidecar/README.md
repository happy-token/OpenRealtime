# Sidecar 边界融合预览

同一会话、同一布局下的两个交界方案：

| 方案 | 预览 | 说明 |
| --- | --- | --- |
| A 无边框同色 | [查看](/docs/design/prototypes/sidecar/sidecar-unframed-preview.png) | 去掉相邻侧边框和间距，让两个区块直接连续；人物素材原貌最完整。 |
| B 共享背景＋羽化（推荐） | [查看](/docs/design/prototypes/sidecar/sidecar-feather-preview.png) | 在交界处加入约 88px 的背景渐隐，弱化人物舞台和文字面的分割，文本与控件保持清晰。 |

窄屏预览：[共享背景＋垂直羽化](/docs/design/prototypes/sidecar/sidecar-feather-mobile-preview.png)。

本目录的图片为本地界面预览；B 已作为工作区预览样式接入，等待确认后才将 S02 标记为完成。

## V2：动作环境色扩展

A、B 均未采用。问题是数字人舞台的固定深色与对话区的表面色反差过大。

当前预览版本从动作图片、待机视频或讲话视频的**画面边缘**采样背景色，避开中心人物后把环境色写入 Sidecar 容器：人物区以该色作外围底色，对话区只混入低比例同色。这样换动作、换场景时，交界会跟随真实素材变化；文字面仍保持足够亮度和对比度。跨域视频不能读取像素时自动使用中性色，不阻断画面或会话。
