# Actor 精确 PCM 播放时钟

日期：2026-10-07。ADR0137 句末许可所需事实补强；阶段3/G3仍开放。

## 修复的缺口

renderer V2 给出采样位置，Bridge知道实际已发送 PCM 总样本数与采样率，原命令只带微秒值，actor没有精确PCM时钟。现在 ReportPlaybackProgress 和不可变 ReplyPlayback 都保留 played_position_samples / sample_rate_hz，经生产 Bridge → Cascade → InputPipeline → 同一actor/版本账本投影。没有新增actor、定时器、队列或存储表。

内部成对采样字段严格要求非bool整数、JS-safe位置和有效采样率；sample事实必须有完整pair，epoch/精度和微秒必须一致。没有pair的历史command仍兼容，但pipeline明确降级unknown并丢弃当前句。当前回复的采样率绑定独立于最新快照保存，legacy/unknown降级不忘记它；新回复重新绑定，历史恢复不恢复live时钟。

V2在实际已发送PCM范围内截取位置，不把provider声明duration当实际样本数。使用整数累计PCM换算、ties-to-even舍入，避免浮点大数或逐包舍入累积偏差。旧legacy微秒流程保持原兼容；这里不改变入站Pydantic的既有宽松字段，严格性是内部command/fact契约，不能称作整个wire已严格。

非终态退序位置被忽略，不用单调微秒前沿伪造新样本。stopped退序仍记录停止终态，保留已报告历史前沿，最终位置降级unknown并清pair/current_sentence。部分finished仅为暂时队列排空，不是整回复终态；只有生成终态且覆盖全部PCM的finished才completed，排空后后续实际playing仍合法。

真实持久停播写入屏障覆盖stop600和late650的两个投影顺序。未知停止位置不能因晚处理progress恢复sample精度，终态与原stop接收时刻保持锁定；可以保留更高的已报告历史前沿，但不能据此宣称实际最终停在650。后续回复衔接必须依据这种精度区分，不能将reported history当confirmed stop位置。

## 验证

- 实际生产链样本字段缺失先红后绿；stopped超范围位置按已发送2000样本截取。
- 独立审查发现exact→unknown→changed-rate被接受，新增失败回归后修复，并用same-rate正对照避免过度拒绝。
- 无pair的epoch/SEGMENT命令误升sample先红后绿；严格fact constructor也拒绝这种声明。
- 持久stop写入与更高late progress顺序回归先红后绿；原收件时钟不被晚投影改写。
- 两个旧V2测试用b'audio'却声称200ms，已改为相符4800采样PCM，未为通过测试保留虚构精确位置。
- 定向109 passed；最终全量Python1972 passed、69 skipped、3 subtests（41.40秒）。6核心模块Mypy、限定8文件Ruff与diff检查通过；独立审查通过。

## 未完成

本批让actor拥有真实PCM事实，尚不签发当前句许可。生产许可的输入/回复版本与deadline、Bridge传递/撤销及heard_frontier生成/交接重验仍待实现。数字人/G3、误打断恢复/G4、未归档动作恢复/G2、真实标注及共享JEV公平/配对负载/G0/G1/G5、录音/Agent只读身份/异常去重/冷暖指标继续按全量计划推进。

未重启用户3010/8765/8766、迁移用户数据库或push；本批没有前端改动，未以单元回归代替实际扬声器或模型实验。
