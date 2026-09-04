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
