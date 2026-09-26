# Turn-taking 文本初筛：TypeSafe Jev 与 DeepSeek V4 Flash

日期：2026-09-20。原 30 条基线容易暴露标签，本次固定提示词后新增 52 条挑战场景。
82 条独立合成文本场景，两个模型每条各调用 5 次，共 820 次真实请求。五次重复不是
410 条独立样本，不能把请求次数当作数据集规模。
命令：`uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py
--repeats 5 --output tmp/turn-taking-v2-challenge-five-runs.json`。逐次预测、耗时、
逐轮及分层统计在该 JSON 文件中（`tmp/` 不提交）。

## 接口验证

- TypeSafe Python SDK `typesafe-sdk` 的 `system_one` + `Choice` 使用
  `../open/.env` 中的 `JEV_API_KEY` 成功返回 `complete`，响应模型为 `jev-1.13.0`。
- 本项目已有 `OpenAiCompatibleLlmClient` 使用本项目 `.env` 的 `DEEPSEEK_API_KEY`，
  成功调用 `deepseek-v4-flash` 的 Responses 接口。这个模型 ID 是项目现有配置中的
  V4 Flash 路径；本次未发现单独名为 `deepseek-v4.1-flash` 的模型 ID。
- TypeSafe 调用形态经官方文档的 `Choice` / Python SDK 页面和已安装 SDK 类型核对。

## 分层结果

| 样本与指标（五轮合并） | TypeSafe Jev | DeepSeek V4 Flash |
| --- | ---: | ---: |
| 基线完整度准确率（8 条确定标签） | 40/40 (100%) | 40/40 (100%) |
| 挑战完整度准确率（24 条确定标签） | 105/120 (87.5%) | 119/120 (99.2%) |
| 挑战完整度宏精确率 / 宏召回率 / 宏 F1 | 90.0% / 87.5% / 87.3% | 99.2% / 99.2% / 99.2% |
| 基线打断准确率（18 条） | 90/90 (100%) | 90/90 (100%) |
| 挑战打断准确率（24 条） | 80/120 (66.7%) | 98/120 (81.7%) |
| 挑战打断宏精确率 / 宏召回率 / 宏 F1 | 56.8% / 80.0% / 66.1% | 87.0% / 88.0% / 85.2% |
| 挑战集 `ignore` 召回率（8 条各五次） | **0/40 (0%)** | **20/40 (50%)** |
| 全部请求平均 / P90 响应时间（各 410 次） | **340.8 / 401.6 ms** | **568.5 / 785.6 ms** |
| 请求或解析失败 | 0/410 | 0/410 |

挑战集完整度逐类召回率：`complete` 两模型均 60/60；`incomplete` Jev 45/60、
DeepSeek 59/60。打断逐类召回率：Jev 的 `backchannel/stop/correction/interrupt`
各 20/20，`ignore` 0/40；DeepSeek 的前两类 20/20，`correction` 20/20，
`interrupt` 19/20，`stop` 19/20，`ignore` 20/40。挑战集中 4 条 `review`
完整度样例各重复五次，不混入准确率；主动输出 `uncertain` 的次数为 Jev 0/20、
DeepSeek 1/20。原集四条 `review` 的 20 次也都没有被两模型弃判。

响应时间是客户端发起请求到**完整响应解析完毕**的 wall time；平均值是逐次算术平均，
P90 对排序后的 410 个耗时用 nearest-rank 计算。全量按任务拆分：完整度
Jev 平均/P90 为 346.1/400.6 ms，DeepSeek 为 567.3/785.6 ms；打断分别是
335.8/401.6 ms 与 569.7/773.3 ms。
异常请求也计入延迟，标签按失败预测计分。所有调用串行执行，两模型每轮交替；
这既不是首 token 延迟，也不包含 VAD、ASR、网络传音和实际停播动作。

## 稳定误判与波动

Jev 在完整度 `hc04/hc14/hc22` 三条句尾悬空样例均 5/5 判为 `complete`，
导致其挑战集 `incomplete` 召回率下降。打断 `hi17`–`hi24` 八条 `ignore`
全部 5/5 未判为 `ignore`：同样的“停一下”“查返程票”即使声源观察变成电视或旁人，
仍随词面判断停播/接管；回声中的“继续”被当成用户附和。

DeepSeek 在 `hi23` 回声“继续”5/5 判为 `backchannel`，`hi17/hi18/hi19/hi21/hi24`
则在五次重复中摇摆；另有 `hi07` 的 1 次 `stop→interrupt`、`hi15` 的 1 次
`interrupt→correction` 和 `hc04` 的 1 次 `incomplete→complete`。挑战集展示了
同一文本与声源观察冲突时的真实分类弱点，但声源字段仍是合成的，不是声学识别输出。

| 轮次 | Jev 平均 / P90 | DeepSeek 平均 / P90 |
| --- | ---: | ---: |
| 1 | 337.9 / 387.9 ms | 576.5 / 821.1 ms |
| 2 | 338.3 / 400.6 ms | 589.4 / 791.0 ms |
| 3 | 328.5 / 408.5 ms | 565.5 / 773.8 ms |
| 4 | 337.1 / 369.3 ms | 557.5 / 743.7 ms |
| 5 | 362.4 / 414.3 ms | 553.6 / 754.9 ms |

## 边界与下一步

这些背景噪声及声源观察仍是文字描述，不是可播放音频；不能证明说话人分离、
声学 VAD、ASR 抗噪能力。当前运行时还保留
`completed_interruption_creates_turn` 的 fail-open 规则：模型给出的 `ignore` 不必然
抑制已完成的用户 Turn。因此这份报告只评模型标签，不评真实停播或 Turn 准入。

下一轮应获取经许可、去标识的真实重叠音频与 ASR partial/revision、播放进度和最终
停播时间；双人复标边界案例，另留独立测试集后再选择阈值和供应商。两模型的置信度
含义不同，不应直接以自报数值横向比较。尤其不能针对这 52 条定向修改提示词后，
再把同一集当作独立最终测试集报告。
