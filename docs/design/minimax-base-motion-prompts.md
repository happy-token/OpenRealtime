# MiniMax 静默动作底片提示词

## 已确认要求

- 同一条底片贯穿视频通话交互并循环播放，不按倾听和说话阶段切换。
- 底片不含说话动作或发声口型，供后续口型对齐使用。
- 保留参考图的外貌、发型、服装、背景和光照。职业与角色通过互动姿态体现。
- 正面为主，脸和嘴持续清晰可见，避免侧脸、低头和遮挡。
- 排除招手、指向、竖拇指等不适合重复循环的一次性动作，以及反复点头等明确回应动作。
- 通过姿态、动作节奏、眉眼神态和轻微身体重心变化区分风格；首尾自然衔接。
- 每套提示词提供语义对应的中文与英文，方便查看和修改。

## 第一批角色风格

| 角色风格 | 动作设计方向 |
| --- | --- |
| 温柔陪伴 | 柔和目光、舒展坐姿、缓慢动作 |
| 活泼朋友 | 明亮眉眼、轻盈姿态、稍快的动作节奏 |
| 专业顾问 | 挺拔坐姿、稳定目光、克制动作 |
| 耐心老师 | 亲切神态、开放肩姿、平稳动作 |
| 冷静学者 | 专注目光、沉静神态、较长静止间隔 |
| 自信搭档 | 从容目光、放松肩姿、轻微重心变化 |

## 全站语言设置（已确认）

- 主页 GitHub 图标旁新增语言切换图标。
- 设置页新增语言选择，与主页入口共享同一偏好。
- 默认跟随系统语言。

## 语言与生成参数（已确认）

- 全站语言选项为跟随系统、简体中文、English。
- 提示词默认跟随页面语言，可在编辑框独立切换；生成时提交编辑框当前选中的语言。
- 时长以高级选项的选择为准，不固定为 5 秒；预设动作节奏与首尾衔接须适配所选时长。
- 高级选项中的实际参数须传递到生成接口，再传递到供应商请求；界面可选值须与模型支持范围一致。

## 表情与翻译范围（已确认）

- 允许轻微闭嘴微笑，避免露齿笑、张嘴笑与频繁嘴角变化。
- 时长必须可选，选项由当前模型支持范围决定，不能统一限制为 6 秒。
- 全站现有页面的按钮、说明和提示信息支持中英文。
- 用户填写的角色名称、内容与自定义提示词保留原文。

## 提示词草案

每套完整提示词由同语种的「通用约束」与「角色动作」组成。使用片段相对时间，避免与高级选项中的时长冲突。

### 通用约束 · 中文

以所提供参考图中的人物为唯一主体，保留其身份、五官、发型、服装、配饰、背景和光照。生成适用于一对一视频通话、可重复循环播放的静默动作底片。沿用参考图构图，固定镜头，不推拉、不摇移、不切镜。人物主要正对镜头，视线自然朝向镜头附近，双眼、完整脸部和嘴部始终清晰可见。保持头部基本水平，不明显转成侧脸，不低头，不让头发、手或物体遮住脸和嘴。嘴唇自然轻闭，下颌放松，全程不说话、不做发音口型、不张嘴、不露齿；可有稳定、轻微的闭嘴微笑。嘴部随脸部自然运动，不僵硬冻结。只表现下述角色动作，配合轻微呼吸和稀疏、自然的眨眼；不招手、不指向、不竖拇指、不反复点头、不进行有明确开始结束含义的手势。手保持在参考图中的自然位置，不新增道具。动作在片段中段自然展开，在结尾平缓回到开头的姿态、头部位置和表情，运动速度也平滑衔接；不突然复位，不淡出，不制造停顿卡点。无说话声、无发声、无音乐。

### Shared constraints · English

Use the person in the supplied reference image as the sole subject. Preserve their identity, facial features, hairstyle, clothing, accessories, background, and lighting. Create a silent base-motion clip for continuous looping during a one-to-one video call. Retain the reference framing with a locked camera, no zoom, pan, or cuts. Keep the person predominantly frontal with natural attention near the lens. Both eyes, the full face, and the mouth remain clearly visible throughout. Keep the head approximately level: no pronounced profile turns, downward head movement, or face and mouth occlusion by hair, hands, or objects. Keep the lips naturally and gently closed and the jaw relaxed. No speaking, speech articulation, open mouth, or visible teeth. A subtle, steady closed-mouth smile is allowed. Let the mouth move naturally with the face rather than freezing it. Perform only the role motion below, accompanied by subtle breathing and sparse natural blinks. No waving, pointing, thumbs-up, repeated nodding, or gestures that imply a distinct greeting, response, or farewell. Keep the hands in their natural reference position and introduce no props. Let the motion unfold naturally through the middle of the clip, then ease back to the opening posture, head position, and expression, with smoothly compatible motion at the loop boundary. No abrupt reset, fade-out, or conspicuous pause. No speech, vocalization, or music.

### 1. 温柔陪伴 / Gentle Companion

**中文角色动作：** 呈现温柔、放松且始终在场的陪伴感。肩部舒展，目光柔和，保持淡淡的闭嘴微笑。片段前半段，上身缓慢、轻微地向镜头靠近，头部仍水平正面，像自然调整坐姿；后半段缓慢回到初始位置。眉眼保持舒缓，不挑眉强调，不点头，不做安慰手势。整个动作连贯、柔和，避免反复前后摇摆。

**English role motion:** Convey a warm, relaxed, consistently present companion. Keep the shoulders open, the gaze soft, and a faint closed-mouth smile steady. During the first half, let the upper body ease slightly closer to the camera as a natural posture adjustment, keeping the head level and frontal. During the second half, gently return to the opening position. Keep the eyes and brows relaxed, without eyebrow emphasis, nodding, or comforting gestures. Use one smooth, gentle posture arc rather than repeated rocking.

### 2. 活泼朋友 / Lively Friend

**中文角色动作：** 呈现明朗、有精神但不过度兴奋的朋友感。眼神明亮，眉部略舒展，闭嘴微笑自然稳定。片段中段，肩部与上身一起做一次轻盈、幅度很小的横向重心调整，再自然回到中心；头部保持水平朝向镜头。动作节奏比温柔陪伴稍轻快，但不抖肩、不左右连续摇摆、不挑眉双拍，不出现惊喜或打招呼的表演。

**English role motion:** Convey a bright, engaged friend without excessive excitement. Keep the eyes alert, the brows slightly open, and a natural closed-mouth smile steady. Through the middle of the clip, let the shoulders and upper body make one light, very small lateral weight adjustment, then naturally return to center. Keep the head level and facing the camera. Use a slightly livelier pace than the gentle companion, without shoulder bouncing, repeated swaying, double eyebrow beats, surprise reactions, or greetings.

### 3. 专业顾问 / Professional Advisor

**中文角色动作：** 呈现稳重、可靠的专业顾问。坐姿挺拔、肩部平衡，视线稳定朝向镜头，表情平和，可保留极轻微闭嘴微笑。片段中段缓慢调整上身的挺拔程度，像舒适地坐稳，随后恢复开头姿态；头部位置变化极小。动作克制、均匀，不做认可点头、不皱眉思考、不作陈述手势。

**English role motion:** Convey a composed, dependable professional advisor. Sit upright with balanced shoulders, steady attention toward the lens, and a calm expression; a very faint closed-mouth smile is acceptable. Through the middle, subtly adjust the uprightness of the torso as if settling comfortably into the seat, then restore the opening posture. Keep head displacement minimal. Motion is restrained and even, without approving nods, thoughtful frowns, or explanatory gestures.

### 4. 耐心老师 / Patient Teacher

**中文角色动作：** 呈现亲切、耐心且容易接近的老师。肩姿开放，眼神专注而柔和，保持轻微闭嘴微笑。片段中段，双肩缓慢放松并略微展开，胸口姿态随之自然舒展，随后平缓回到开头状态。身体保持居中正面，节奏平稳；不抬手讲解、不看向画面外的教材、不低头、不用反复点头表示鼓励。

**English role motion:** Convey an approachable, kind, patient teacher. Keep an open shoulder posture, attentive yet gentle eyes, and a slight closed-mouth smile. Through the middle, slowly relax and open both shoulders a little, allowing the upper chest posture to ease naturally, then smoothly return to the opening state. Stay centered and frontal with an even pace. No instructional hand gestures, glances toward off-screen materials, looking down, or repeated encouraging nods.

### 5. 冷静学者 / Calm Scholar

**中文角色动作：** 呈现安静、专注、沉着的学者。上身稳定，肩部自然，嘴唇轻闭，表情中性而不冷漠。大部分时间保持安定姿态，以轻微呼吸、自然眼部变化和稀疏眨眼体现生命感。片段中段只做一次非常轻微的坐姿重心松弛，随后缓慢回到原位。比其他风格保留更长的安定间隔，但不僵硬、不凝视表演、不低头阅读、不摸下巴。

**English role motion:** Convey a quiet, focused, composed scholar. Keep the torso steady, the shoulders natural, the lips gently closed, and the expression neutral but approachable. Maintain a settled posture for most of the clip, with subtle breathing, natural eye activity, and sparse blinks. Through the middle, make only one very slight relaxation of seated weight, then slowly return. Allow longer settled intervals than the other styles without appearing frozen, theatrically staring, looking down to read, or touching the chin.

### 6. 自信搭档 / Confident Partner

**中文角色动作：** 呈现从容、平等、可靠的搭档。目光稳定而放松，肩部松弛，嘴角保持极轻微的闭嘴微笑。片段前半段，上身缓慢做一次小幅侧向重心转移，肩线随之轻微调整；后半段以从容的节奏回到起始重心。头部保持水平正面，不随肩部转向侧脸。动作比活泼朋友更沉稳、幅度略清晰，但不摆造型、不耸肩、不做挑眉挑衅。

**English role motion:** Convey an assured, equal, dependable partner. Keep the gaze steady yet relaxed, the shoulders loose, and a very slight closed-mouth smile stable. During the first half, slowly shift seated weight a small distance to one side, with a subtle adjustment of the shoulder line. During the second half, return to the opening balance at an unhurried pace. Keep the head level and frontal rather than turning with the shoulders. Motion is more grounded than the lively friend, with slightly clearer displacement, without posing, shrugging, or provocative eyebrow raises.

## 实现与验收要求

- 主页语言图标和设置页共享同一语言偏好；推荐跨刷新保存选择，系统模式根据浏览器语言解析，未支持语言回退规则待实现时明确。
- 中英文预设语义对应；用户编辑内容独立保存，切换语言不覆盖已有编辑。
- 高级选项的时长、比例、分辨率、图片用途及参考视频（如适用）从界面传至接口，再传至供应商请求。
- 切换模型后只提供其支持的参数组合；不支持的旧参数需要调整并在界面体现。
- 检查接口实际请求中的参数值，而不只检查下拉菜单显示。
- 新提示词不保留旧预设中的固定秒数、说话能量、低头避视等冲突指令。
- 提示词只是生成约束，需用实际生成样片验证：无发音口型，正面与嘴部可见，循环边界自然，六种风格有可辨差异。未经样片验证不宣称已达到效果。

## 实现记录

- 已接入全站语言上下文与英文文案表。主页右上角 GitHub 入口旁、设置主页和外观设置均可选择语言，偏好在当前浏览器保存并跨标签页同步。
- 系统语言以浏览器首选语言为准：中文语言区域使用简体中文，其余语言回退英文。
- 已替换为六套中英文角色动作提示词。编辑按角色、语种、数字人分别保存至当前浏览器；页面切换语言不会自动翻译用户编辑内容。
- 已开放 H3 / Context IR 的现有 4–15 秒参数范围，H3 Max 为 5–15 秒。切换模型时修正不支持的分辨率、时长与参考素材组合。
- 已验证高级选项中时长、分辨率、画面比例、图片用途及当前提示词进入实际前端请求；接口测试验证供应商调用参数。
- 已修复制作窗口调整大小控件遮挡生成按钮，以及高级选项下拉内容被裁切的问题。
- 验证：全量 Vitest、语言与动作生成浏览器测试、TypeScript、修改区域 ESLint、生产构建。未调用真实付费视频生成，实际样片仍需验证循环自然度与风格辨识度。

## 主页入口调整

- GitHub 与语言图标仅在主页（`/conversation` 与根路径）显示；设置页保留文字形式的语言选择。
- GitHub 链接展示缓存接口返回的 Star 数量，采用紧凑格式；未知数量显示「—」。
- 全站语言选择及提示词语种选择使用主题化圆角下拉列表，背景、边框、选中态与页面主题一致。

### 未登录用户的基础设置入口

左下角未登录时显示齿轮与“设置”，展开与主题一致的圆角菜单，包含语言选择、外观和基本对话设置。登录入口位于分隔线下方；账户状态加载或服务不可用时仍可使用基础设置。登录后保持相同位置，显示账户信息并保留偏好入口、账户设置与退出登录。语言、外观及对话偏好沿用浏览器本地存储。

验证：侧边栏 18 项单元测试通过；新增浏览器测试以未登录状态验证菜单、切换语言、进入对话设置及音量刷新保留；TypeScript 检查通过。

### 设置界面精简

语言选择统一为单行标签与右侧选择框，固定 13px 字号，防止标签受挤压换行。菜单按钮样式只作用于直属选项，避免覆盖语言组件。账户菜单去掉个人资料、供应商重复快捷项，统一通过设置页进入。外观页移除重复语言标题与说明；Orb 预览和玻璃效果滑块默认折叠，保留语言、样式、主题、减少动态等常用选择。账户名采用省略显示。

左下角菜单进一步移除基本对话设置快捷项；菜单宽度跟随侧边栏可用宽度，语言选择框最大 132px，避免越过侧边栏边界。对话偏好仍可从完整设置页面进入。

### 动作列表创建入口

主页和角色详情复用的模式素材列表，在现有动作后追加“创建动作”卡片，携带当前数字人和角色返回位置进入动作制作流程。无角色的主页底部动作列表也添加同款入口；资产库原来的创建卡片移至列表末尾，保持顺序一致。

验证：主页预览相关 32 项测试通过，包含创建卡片在动作之后的顺序；TypeScript 检查通过。

离线数字人资源库右侧形象列表末尾新增“创建角色”卡片，进入 `/roles/new`。顶部创建形象入口继续用于上传源图；底部创建角色用于配置完整角色。相关测试覆盖末尾入口及动作创建入口顺序。
