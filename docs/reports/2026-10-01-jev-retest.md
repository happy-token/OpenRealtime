# Jev 判停与打断复测

日期：2026-10-01。找到本地历史评测脚本和服务器端凭据，无需 SSH。
独立 smoke 请求实测返回模型 `jev-1.13.0`；凭据没有写入报告或提交文件。

## 实测

复用已有合成文本集，每种配置每例请求一次，共 122 次评测请求，零请求／解析失败。
共有 102 条不同样例：82 条原基线与挑战样例，20 条旧保留样例；后者在两种提示词下重复调用。
这些都是以前用过的样例，不能当作新的独立验收集。

| 配置与样例 | 完整度正确数 | 打断标签正确数 | 平均请求耗时 | P90 |
| --- | --- | --- | --- | --- |
| 原提示词，基线＋挑战 82 条 | 29/32（90.6%） | 34/42（81.0%） | 318.5ms | 356.8ms |
| 原提示词，旧保留 20 条 | 6/8（75%） | 9/12（75%） | 338.4ms | 332.9ms |
| 声源优先提示词，同一旧保留 20 条 | 6/8（75%） | 12/12（100%） | 333.7ms | 337.1ms |

82 条中有 8 条完整度真值为 review，不计入完整度准确率；这些请求仍计入耗时。
耗时是请求开始至完整响应解析结束，百分位采用 nearest rank；少量冷请求会使平均值高于 P90。

## 主要问题

- 原提示词挑战完整度：21/24；12 条不完整表达中有 3 条被提前判为完整。
- 原提示词挑战打断：16/24；8 条背景音／旁人声均未正确归为 ignore。
- 声源优先提示词在旧保留集改善了打断分类，但 4 条不完整表达仍有 2 条误判为完整。
- 优化提示词的声源信息来自合成文字观察，不能证明真实录音中的声源区分有效。
- 没有复测 DeepSeek，不能把今天的 Jev 结果和旧报告的 DeepSeek 耗时当作同条件对照。

## 如何重跑

凭据由已有脚本在服务器端读取 `JEV_API_KEY`，默认文件位置为工作区同级 `open/.env`。
SDK 通过 `uv run --with` 临时提供，无需修改项目依赖。

```bash
uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py \
  --provider typesafe --repeats 1 \
  --output tmp/jev-2026-10-01-baseline.json

uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py \
  --provider typesafe --dataset data/eot_eval/turn_taking_prompt_holdout.jsonl \
  --repeats 1 --output tmp/jev-2026-10-01-holdout-baseline.json

uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py \
  --provider typesafe --typesafe-prompt source-aware \
  --dataset data/eot_eval/turn_taking_prompt_holdout.jsonl \
  --repeats 1 --output tmp/jev-2026-10-01-source-aware.json
```

逐次标签、置信度、耗时和错误类型保存在上述本地 JSON；不包含密钥。
评测脚本里的模型名称是历史标记，本次实际模型版本另经 smoke 返回字段核实。

## 接入判断

Jev API 可用，可以作为现有语义插件的实验提供者。优先尝试声源优先的打断判断，
完整度仍需谨慎：本次数据中提前提交风险没有消失，因此本次未切换默认运行模型。
当前只验证分类 API，没有验证新协调器与 Jev 的端到端停播、ASR final 或真实麦克风交互。

接入时，`Choice` 的标签和置信度映射到现有 `EotClassification`／
`InterruptionClassification`；运行时继续控制等待、取消和输入准入。
需要另外记录选项概率，并验证阈值，不能把分类准确率直接视为停播动作准确率。

官方说明：[Jev 与结构化判断](https://docs.typesafe.ai/introduction)、
[置信度与概率](https://docs.typesafe.ai/confidence)。
后续接口与评估要求参见 [Jev 接入 PRD](../JEV-TURN-TAKING-PRD.md)。
