# 录音与客户端播放回执关联

日期：2026-10-07。对应 [ADR0157](../adr/0157-recording-playback-receipt-correlation.md)。本批继续 OBS03，整个实施计划仍未完成。

## 已落实

原 Bridge 已验证的输出 epoch、speech、generation 与精确采样时钟，此前在规范播放事件中丢失，导致录音目录无法关联。现共享 SpeechLifecycle、Cascade 模型语音和 Native 模型语音均保留采样锚点；Native 同时保留 started/stopped 阶段。Observer 将锚点保存至既有遥测事件，不新增业务 actor、队列或恢复状态。

读取录音时，按原 tenant、user、Session、source thread、generation、turn、response、output epoch、speech、sample rate 精确匹配客户端前缀，与保存片段求采样交集。只有 Bridge 归一化为 speech-local stream 的音频可关联；旧格式、畸形、身份不符或缺少回执均保持未知。有效零回执可显示零；迟到的小前缀不会抹掉已报告的较大前缀。录音仍声明 `playback_confirmation=not-inferred`。

公共 API 只增加状态和采样计数白名单，保持原管理员及 Session 只读 Agent 权限。现有同主题播放器以数字显示“回执覆盖 0.050 / 0.100 秒”；悬停解释对应采样计数、匹配条件以及不能证明扬声器播出或用户听到。输入音轨不展示输出回执。旧后端没有字段时仍显示未知，不伪造零。

可选保留/回执查询共用原八个实际 IO 归属槽，每项最多等待250ms且不超过目录剩余截止时间；迟到任务实际退出前继续保护删除和关闭。审查复现可选查询自己取消会取消整个目录，两个正式回归先红后绿；现在仅对应源降级为不可用。慢/失败源不遮盖可读取录音。

## 验证

- 全量 Python：2677 passed、101 skipped、3 subtests，73.08s。
- 全量 Vitest：1426 passed、7 skipped，19.81s；本批路由/真实处理函数 hook/SSR 定向43项通过。
- 本机现有 PostgreSQL `/tmp`、随机隔离 schema：38项相关录音/Artifact测试通过，4.33s。新增两项验证精确及旧格式 JSON 持久化、Runtime 重建后正确回读；对象客户端为 Memory，非真实 S3。
- 隔离3029 Chrome：2项通过，13.1s。真实 PG 管理员身份、Memory Runtime、实际 Bridge 向受控 sink 发送1600 samples、真实规范协议接受800-sample精确回执；实际私有HTTP/Next白名单返回、数字/title、100ms原生WAV回放、保留2段刷新、手机布局、无Cookie Agent采样计数/摘要及拒写均通过。预览不请求私有音频。
- 五个相关源码/夹具 Mypy、限定 Ruff/ESLint、TSC、diff 检查通过；不是全项目 Python 类型基线通过。
- 复用 Python/代码审查员完成核心和最后 PG/夹具/E2E 增量限定 APPROVE。隔离进程已退出；查询确认所属 browser schema 已删除，Next自动生成配置变化已核实还原。

复跑浏览器：[隔离指南](../guides/recording-browser-integration.md)。正式红证据包括八个实际共享语音锚点用例、实际 Runtime 目录缺少回执投影，以及两个可选子查询取消用例。其余负向覆盖完整身份、畸形整数/采样率/时钟、零/部分/完整交集、旧回执、截断、慢源和实际任务归属。

## 仍待验收

目录目前读取一个最多5000条返回事件的既有诊断页。明确展示 next cursor 截断和采集健康，缺少回执始终未知；不会由“没有下一页”推出音频未播放。Memory适配器底层仍全量扫描/排序，5000不是底层CPU或内存总界。长会话定向检索、全部证据完整度和真实原 renderer/device oracle 未完成。本批截断回归是注入游标，不声称证明真实PG超5000事件的分页场景。

浏览器回放和受控原回执是两个不同证据；不证明生产通话用户实际听到。真实S3、管理员/外部Agent部署验收、录音完整性、OBS02完整输入聚合/因果异常去重/冷暖重连，以及全部原G0–G5真实标注oracle、JEV并发公平性与成对延迟准确率、持久未知动作、补充/手动/模型交付与非协作取消/renderer/断连矩阵、真实供应商负载仍保留原范围。未改生产迁移/密钥/功能开关，未重启用户服务，未 push。
