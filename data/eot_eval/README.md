# 中文语义完整度评测集

`zh_semantic_completeness_v1.jsonl` 是 OpenRealtime 自建的首版文本语义 EoT 评测集，
用于比较可替换的 Turn Manager / EoT evidence adapter，而不是训练模型。

## v1 口径

- 100 条中文口语样例，`complete` / `incomplete` 各 50 条。
- 10 个类别各 10 条，并在每个类别内保持标签平衡。
- `complete` 表示当前文本结合已提交历史，已经表达了可识别、可响应的意图。
- `incomplete` 表示表达仍在条件、连接、列举、纠正或槽位上明显悬空。
- 不以标点、ASR final 或信息是否足够执行任务作为标签依据。
- 短确认、拒绝和附和在上下文中可以是完整表达。

每行字段：

- `id`：稳定且唯一的样例标识。
- `text`：当前累计 ASR 文本。
- `label`：`complete` 或 `incomplete`。
- `history`：判定前已经提交的用户/助手消息。
- `category`：场景分类。
- `difficulty`：人工标注的 `easy` / `medium` / `hard`。
- `tags`：便于后续切片分析的非权威标签。

## 本地运行

```bash
uv run --extra firered python scripts/evaluate_semantic_eot.py \
  --output tmp/eot-eval/firered-zh-v1.json
```

评测当前运行时的“保守 FireRed 快速完成 + LLM 兜底”策略：

```bash
set -a; source .env; set +a
uv run --extra firered python scripts/evaluate_semantic_eot.py --runtime \
  --output tmp/eot-eval/runtime-zh-v1.json
```

核心指标：

- `false_cutoff_rate`：实际不完整却判为完整，代表抢断用户。
- `complete_precision`：所有“已完整”判定里真正完整的比例，是快速提交的首要安全指标。
- `missed_endpoint_rate`：实际完整却未判为完整，代表不必要等待。
- `accuracy`：整体二分类准确率。
- `latency_p50_ms` / `latency_p95_ms`：模型推理延迟，不含 VAD 静音窗和网络。

## 限制

v1 是人工构建的文本级起始基线，不包含真实录音、ASR 错字、时间对齐或真实用户停顿。
后续应从获准留存的真实会话中抽取匿名困难样例，经过双人复核后建立 v2；测试集不得用于调参后
重复报告最终效果，应另保留独立验证集。

## v2 小规模模型对照

`turn_taking_v2.jsonl` 是 30 条**人工构造的文本场景**，作为易样例基线；
`turn_taking_challenge_v2.jsonl` 另有 52 条困难挑战样例：完整度 12 组完整/不完整
最小对照和 4 条待复核样例，打断 24 条包含否定、口语改口、同一转写但不同声源的对照。
两者均不覆盖原有的 100 条语义 EoT v1 数据。
12 条语义完整度包含 `complete` / `incomplete` 各 4 条，以及 4 条边界 `review` 样例；模型
仍可输出 `uncertain`，但 `review` 不当作确定真值参与准确率。18 条语义打断
覆盖附和、停止、纠正、新任务各 3 条，以及背景人声和背景噪声各 3 条。背景两类的
预期输出均为运行时的 `ignore`。`uncertain` 是谨慎弃判，不等同于执行新动作。

```bash
uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py
```

脚本从 `../open/.env` 读取 `JEV_API_KEY`，从本项目 `.env` 读取 `DEEPSEEK_API_KEY`；
环境变量可覆盖对应值。默认合并 30 条基线与 52 条挑战样例比较 TypeSafe Jev 和
DeepSeek `deepseek-v4-flash`，每条样例对两个模型分别推理 5 次（可用 `--repeats`
调整）。逐例/逐轮及 `baseline` / `challenge` 分层结果写到
忽略版本控制的 `tmp/turn-taking-v2.json`。脚本统计确定性标签的准确率、
宏平均精确率/召回率/F1、逐类精确率/召回率/F1，以及完整响应耗时的平均值和
nearest-rank P90；`review` 样例只统计模型弃判率，不混入准确率。请求/解析
错误算作错误预测，耗时仍计入延迟分布。

挑战集的 `rationale` 和 `pair` 仅供人工审阅，不传给模型。数据完全是合成的文本和
文字化声源观察，没有真实音频、说话人分离或 ASR 时序。声源观察属于提供给模型的
模拟输入；生产系统未必拥有这些条件，尤其不能从这组结果证明声学归因能力。
仅可用于检查标签契约和发现误判案例，不能作为真实背景噪声抵抗率或线上效果；
模型自报 `confidence` 与 TypeSafe 的选择分布置信度也不可直接校准比较。

## Jev 提示词实验

`turn_taking_prompt_holdout.jsonl` 是另外 20 条合成文本样例（完整度 8、打断 12）。
`--typesafe-prompt source-aware` 启用声源优先和句尾悬空的候选提示词；不带参数仍是原版。
可用 `--provider typesafe` 只调用 Jev，不需要 DeepSeek 的密钥。五轮同条件对照：

```bash
uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py \
  --provider typesafe --dataset data/eot_eval/turn_taking_prompt_holdout.jsonl \
  --repeats 5 --output tmp/turn-taking-prompt-holdout-baseline.json
uv run --with typesafe-sdk python scripts/evaluate_turn_taking_models.py \
  --provider typesafe --typesafe-prompt source-aware \
  --dataset data/eot_eval/turn_taking_prompt_holdout.jsonl --repeats 5 \
  --output tmp/turn-taking-prompt-holdout-source-aware.json
```

结果和逐例错误见 `docs/reports/2026-09-20-turn-taking-prompt-optimization.md`。
这个保留集未用于选择候选提示词，但和开发集一样由人工模拟，仍需真实音频验证。
