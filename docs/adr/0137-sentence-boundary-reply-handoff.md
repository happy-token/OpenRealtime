# ADR 0137：按实际播放句末衔接纠正回复

日期：2026-10-05。状态：Proposed，待实施。

## 决策方向

一般补充保留当前句至实际句末，清除后续旧句；明确否定错误内容立即停止。新回复基于累计输入与已播放事实续答。句段完成必须由renderer回执确认，不能由TTS生成完成推断。

若现有renderer没有可靠位置，需要先扩展播放协议与音频队列，确认浏览器和数字人路径均支持。位置未知时不能保证无重复续播。

## 2026-10-06设计补充

播放能力审计前移到实施阶段0。现有yield_ack只确认服务端取消分支完成，不能当作客户端stopped；实际停播和句末完成使用精确输出epoch/句段回执。

作废版本禁止新增交付。一般补充仅冻结一个已实际开始句的限时许可，绑定回复版本/播放epoch/句段，未来音频清理；明确否定、结束或安全截止撤销许可。不能通过推进全generation误杀保留句，也不能以保留句为由放行全部旧音频。

预生成上下文区分confirmed_heard与permitted_current_sentence，绑定heard_frontier；句末放行时重验播放事实。许可句提前停止、回执缺失或语义前提改变时调整或重生成。

actor签发许可，版本账本保存引用，既有输出边界执行并上报事实；不新增独立衔接决策者。

## 依赖与验收

依赖0136及播放事实协议。需求AC05/06；句末竞争、迟到音频、回执超时、新旧音频不重叠。

## 2026-10-07前置实施

已补服务端签发并验证attach输出epoch、浏览器旧取消/ended隔离、独立speech样本时钟、引擎生成终态与实际PCM完成判定，以及同代旧失败/取消/yield/文本隔离。详见[播放事实报告](../reports/2026-10-07-playback-fact-isolation.md)。这只建立后续许可/交接所需事实边界；本ADR仍Proposed，精确句段许可、停播命令与确认、heard_frontier重验及真实数字人验收未完成。

同日继续补[精确停播操作](../reports/2026-10-07-precise-output-stop.md)：请求和回执绑定epoch/speech/generation/operation；浏览器本地队列确认与数字人未知结果分开；重复命令不停止替换speech，新音频在既有出队边界等待匹配回执和投影，失败有界并撤销交付许可。已观察的停止事实与后续交付许可分别维护。此为live桥接前置，尚未建立持久停止事实/actor句段许可，不能关闭本ADR或G3。

同日已补[停播诊断与正常关闭清理](../reports/2026-10-07-output-stop-diagnostics.md)：精确请求、回执、交接结果关联原回复并开放Session ID回读，成功三阶段计时与失败经过时间分离；正常关闭先结算再取消投影。诊断异步队列不等于actor持久确认，当前句许可与heard_frontier重验仍待实施。

已补[原播放目标上下文](../reports/2026-10-07-playback-target-context.md)：legacy/V2回执与精确停播投影使用PlaybackState绑定的原turn/response，避免合成turn-N及丢失response身份。后续仍需持久stop操作事实、稳定句段identity、actor精确许可和heard_frontier重验。


同日已补[持久停播操作账本](../reports/2026-10-07-output-stop-persistence.md)：SpeechDeliveryStore保存完整原目标和精确操作，终态不被重放降级；客户端停播不等待请求写入，交接等待请求/终态保存及原播放事实投影。生产Managed使用同一应用级存储，重配置切换不丢事实，普通关闭与重配置双失败保留未结算写入的删除保护；精确会话删除加入现有PG事务。本地队列确认和后续交付许可仍独立；Memory及外层事务未提交时不具有最终持久保证。迁移0034只在自建隔离测试库验证，未应用到用户服务。稳定句段身份、actor当前句许可、heard_frontier重验及真实renderer/G3仍未实现，本ADR保持Proposed。

同日已补[句子时间证据与精度分离](../reports/2026-10-07-sentence-playback-evidence.md)：完整provider字幕提供稳定原文/全speech时间区间，比例字符字幕标estimated，不进入exact已播前沿；重复句、残缺词、晚到证据及直接播报映射有回归。浏览器真实页面覆盖清屏后字幕、旧epoch以及同代/新代输出替换。该元数据不签发句段许可，字幕晚到也不能保证及时定位实际当前句；actor许可、队列切分/清理、heard_frontier重验及真实数字人/G3仍待实施，状态保持Proposed。
