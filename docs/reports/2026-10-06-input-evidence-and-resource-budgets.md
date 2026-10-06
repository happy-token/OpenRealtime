# 输入证据回读与逻辑输入资源预算

日期：2026-10-06。实施范围：ADR0135资源补强与ADR0136输入证据前置条件。正式回复版本纠正、句尾衔接与误打断恢复尚未实现。

## 行为与模块边界

CoordinatedTurnManager仍是唯一实时裁决actor。新增 `conversation_journal/input_evidence.py` 是存储适配器：单个有序写入worker，不判语义、不控制播放。复用Conversation Journal内部结构化内容；证据独立thread，不进入LLM主历史投影，不增加表或数据库迁移。

保存逻辑input_id、ASR版本与边界、替换位置/新增后缀/前序证据ID/校验摘要、封口块、合并/失效/请求与有效分类结果。边界变化即使文本和revision相同也记录。结果保留候选revision、当前ASR引用、候选范围、来源与有效标签，不能将其解释为提供商原始响应或实际停播事实。

捕获点是TurnManager收到的ASR文本：可能已经经过InputPipeline回声投影。纯回声早退、被上游拒绝的原始provider事件、旧token晚到结果仍主要在既有诊断路径；本批不是全部原始音频/ASR事件的完整oracle。未新增录音存储或机器身份认证。

写入返回匹配的item_id与digest才确认receipt。Postgres事务结束的确认可标durable；InMemory明确durable=false。正常输入证据异步写入，不要求每次模型调用等待数据库IO；异步失败须显式结束当前会话，包含输入已经提交或附和已经丢弃之后才失败的情况。

## 预算与退出

默认工程配置可通过环境变量调整，不是已验收延迟SLO：

|变量|默认|边界|
|---|---:|---|
|VOICEAGENT_INPUT_MAX_TEXT_BYTES|16384|单个接受的文本快照UTF-8字节|
|VOICEAGENT_INPUT_MAX_REVISIONS|2048|逻辑输入接受的文本/版本/边界变更|
|VOICEAGENT_INPUT_MAX_CHUNKS|2048|当前逻辑输入的候选历史|
|VOICEAGENT_INPUT_MAX_DURATION_MS|120000|从逻辑输入建立起的绝对时长，不随ASR更新重置|
|VOICEAGENT_INPUT_MAX_EVIDENCE_BYTES|2097152|逻辑输入累计证据序列化字节|
|VOICEAGENT_INPUT_EVIDENCE_TIMEOUT_MS|1000|单次证据写入等待|

writer还限制32个未确认记录（含正在写入的记录）、1MiB排队字节及64KiB单记录。封口块按128个批量记录，减少同步长快照产生的突发。候选历史/证据总预算在一次受限快照或记录完成构建后检查，可能短暂超出一个快照/记录；不宣称全进程或全部网络帧有硬内存界。

超额先冻结输入，取消语义任务与预生成，清除延迟观察队列。随后尝试保存完整拒绝快照；不截断文本交给模型。终态快照最多16Ki字符、32KiB UTF-8，超过此范围只记capture_complete=false和长度、缺失事实，保留收到的对象至会话关闭。

仅完整快照得到durable确认才允许请求ASRdiscard/清理本轮。写入失败、超时、排队溢出、内存journal或无法完整捕获均明确报告“未确认保存”。所有拒绝经 `semantic_input` 失败→WebSocket `voice_session_failed`、disposition=close结束会话；关闭负责释放未保存载荷和任务，不继续等待。不能承诺磁盘不可用或异常巨大载荷仍完整恢复。

普通/公开前端均停止麦克风、浏览器speechSynthesis和既有音频/数字人播放，清理回复计时器，保留已显示文字及具体安全错误。话筒按钮根据实际capture状态显示。

## 查询与保留

管理员应用登录后使用既有代理：

`GET /api/observability/sessions/{SessionID}/input-evidence?after_sequence=0&limit=100`

服务端loopback路径为 `/observability/sessions/{SessionID}/input-evidence`。limit为1..1000；游标为非负sequence。响应含schema、status、records、next_sequence、last_sequence、has_more、durable。未配置404；错误统一安全边界；非管理员代理401，不读取后端。

从已采集的服务端TelemetryRecord解析真实tenant/user/thread，不从管理员账户或SessionID猜用户线程。读取前flush本地待写telemetry；身份有歧义时失败，缺历史身份仅兼容旧本地默认scope。公开票据用户与已有线程续接均有回归。

删除会话时同时删除该Session专属输入证据；Postgres与已有日志/telemetry删除处于同一事务。主conversation thread只有全部Journal项属于所选Session、且当前进程没有已注册的活动/挂起引用时，才允许整线程删除；未知自定义存储缺原子归属删除能力时保留主线程。Memory在同一锁内检查/删除；Postgres锁定append更新version的线程行后检查其他Session项，再在事务内删除。同一事件循环内的thread_deletion_guard从筛选至全部删除await结束占用空闲线程，新续接register明确拒绝，成功/异常finally释放，避免检查后的注册竞态。原始Session被删除而恢复Session未选时保留共享历史；这不实现共享thread按Session逐item清除，也不是多进程会话活动目录。无主投影污染，无全局输入scope。

## 验证与限制

本地确定性回归覆盖证据顺序/不可变性/分页/隔离、队列和字节、失败/超时/非协作取消、错误确认、存储自行取消、内存与持久确认区别、UTF-8/版本/块数/绝对时长/证据预算、ASR改写回读、同revision边界、拒绝后旧final冻结、输入提交/附和丢弃后的晚到故障、后续话轮身份、删除原始Session保护恢复会话、原子共享归属检查。

完整模拟管线经过真实CoordinatedTurnManager、CascadedRealtimeEngine、ManagedRuntime与VoiceSessionEndpoint；已有阻塞Brain、双工TTS和语义分类被取消，输入/actor/writer退出。浏览器Chrome测试经过实际页面与hook，WebSocket/识别/语音合成均模拟，验证停止识别与播报、错误可见、文字保留和话筒状态。

最终完整Python：1671 passed / 62 skipped / 3 subtests（38.07s）。前端4组单元测试66 passed，Chrome失败退出E2E 1 passed（16.2s），全局TSC与限定ESLint通过；核心6个模块Mypy及注册器Mypy通过，限定Ruff通过，Postgres文件保留5个既有TRY004异常类型告警。独立Python及代码复核的本轮问题已闭环；删除期间续接注册竞争的独立定向回归4 passed。没有进行真实提供商、物理声卡/数字人端到端、真实Postgres故障注入或P95实验。用户3010/8765/8766服务未重启；后端新采集需要下次部署/重启才生效。未提交Git。

下一阶段继续ADR0136输入/回复版本账本和正式纠正关联；G1/G2尚未关闭。ASCII句点兼容路径CPU上界、真实语义标注/多会话公平性、机器只读身份与双路录音仍待处理。
