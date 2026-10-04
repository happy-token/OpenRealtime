# 数据日志后台整体 Review

范围：管理员身份验证、总览与详情、遥测采集与汇总、打断回执、PostgreSQL 写入、统一诊断接口，以及已确认的录音/保留/Agent 需求。此次仅 review，没有修复业务代码或修改运行配置。

## 已确认的代码问题

### 1. [P1] 打断停播计时可能误报，也可能漏采

位置：[observability.py](/Users/forever/workspace/OpenRealtime/server/realtime/observability.py:223)、[终态处理](/Users/forever/workspace/OpenRealtime/server/realtime/observability.py:301)。

`SpeechPlaybackProgress.completed == false` 同时表示播放开始、播放中进度和停止，观察器却把任意未完成回执当成停播。另一方面，收到 ResponseCancelled 时会删除打断计时起点，随后客户端真正停止的回执无法计算耗时。引擎实际先发 AssistantYieldRequested 再取消响应，因此不是不可能的事件顺序。

实测：输入普通未完成播放进度，产生 `barge_in.time_to_client_stop`；输入打断请求然后取消，回执前 `_yield_requested_ns == {}`。

建议：明确 started/progress/stopped/finished 的回执类型，以目标 response/speech 关联打断；等待真正 stopped 回执再结束计时，服务端取消不清掉客户端计时起点。覆盖迟到回执与替换回复的测试。

### 2. [P1] 部分数据可用时详情仍会崩溃；不存在的 Session ID 也会触发

位置：[session-diagnostics.tsx](/Users/forever/workspace/OpenRealtime/src/components/admin/session-diagnostics.tsx:55)、[聚合接口](/Users/forever/workspace/OpenRealtime/src/app/api/observability/sessions/[sessionId]/diagnostics/route.ts:33)。

聚合接口允许 telemetry 为 null，但详情把缺失时间变成空字符串传入 `formatClock`，抛出 `RangeError: Invalid time value`。控制接口对不存在的会话返回 telemetry 404、conversation 200 空数组、debug-log 200 空数组；聚合接口认为有 available 来源就返回 200，进一步触发同一崩溃。

实测：调用真实 formatClock('') 抛出上述错误；不存在 ID 的三个实际上游状态为 404/200/200。

建议：空日期显示“—”；区分数据源能访问与会话有记录。所有来源空时返回未找到，部分来源有内容时展示可用内容，增加真实详情渲染回归测试。

### 3. [P1] LLM TTFT 已采集，但无法关联到每轮详情

位置：[LLM 采集](/Users/forever/workspace/OpenRealtime/server/brain/plugins/openai_compatible_llm_client.py:229)、[record](/Users/forever/workspace/OpenRealtime/server/observability/telemetry.py:619)、[详情过滤](/Users/forever/workspace/OpenRealtime/src/components/admin/session-diagnostics.tsx:34)。

LLM 首文本调用 record 时没有传 generation；record 不继承 telemetry_generation_scope，与 provider_call 的行为不同。因此 TTFT 的 generation 为 null，详情按轮次过滤会丢掉它；选中轮次后原始遥测视图也不会显示这些未关联事件。

实测：在 generation=7 scope 内调用实际 record('llm.request_to_first_text')，返回 generation=None。

建议：使用任务局部 scope 关联 generation，并尽可能携带 turn/response/call 标识；详情提供未关联事件区。不能用共享的 latest generation 推测并发请求归属。

### 4. [P2] 模块卡片的“错误 0”不代表该模块没有失败

位置：[聚合 SQL](/Users/forever/workspace/OpenRealtime/server/persistence/postgres/runtime_telemetry.py:155)、[内存聚合](/Users/forever/workspace/OpenRealtime/server/observability/telemetry.py:1443)。

仅 duration 非空的同名事件进入模块汇总。ASR/TTS 失败可能只产生无 duration 的 realtime.capability.* 事件，不会进入首包指标的 error_count。

实测：一条 TTS 首包成功样本和一条 TTS capability error，全局错误=1，但 TTS 模块错误=0。

建议：模块调用数/失败数按 capability 和 call_id 独立统计，耗时分位数按计时样本统计；分别说明两个分母。

### 5. [P2] 长会话日志只能拿前半段，没有分页续查

位置：[遥测详情](/Users/forever/workspace/OpenRealtime/server/persistence/postgres/runtime_telemetry.py:223)、[决策日志](/Users/forever/workspace/OpenRealtime/server/persistence/postgres/debug_log.py:84)。

遥测只取最早 5000 条，决策日志只取最早 2000 条。虽已提示可能截断，Agent 和页面仍无 cursor 或时间范围续查，发生在尾部的异常无法从统一接口拿到。详情 summary 也仅根据截断后的记录生成。

建议：独立全量 summary，事件/决策日志按稳定游标分页；Agent 导出遍历所有页，明确实际返回范围。

### 6. [P2] 写入失败和丢日志对后台不可见

位置：[队列满](/Users/forever/workspace/OpenRealtime/server/observability/telemetry.py:457)、[写入错误](/Users/forever/workspace/OpenRealtime/server/observability/telemetry.py:509)、[健康接口](/Users/forever/workspace/OpenRealtime/server/control_plane/http.py:312)。

已有 last_error/dropped_records，但健康接口恒定 status=ok，统一报告的完整度只检查查询上限。数据库故障或队列过载后，即使采集已丢数据，后台仍可能把可查询到的部分记录标成 available。

建议：增加采集健康信息：存储后端、最后成功写入、积压、丢失数、失败状态；将采集缺口纳入报告完整度。不能用“可读取数据库”证明“日志采集完整”。

### 7. [P2] 多来源删除不是原子操作

位置：[delete_session_history](/Users/forever/workspace/OpenRealtime/server/application/runtime.py:266)。

依次删除决策日志、会话 journal、遥测，跨来源没有共同事务。如果中途失败，接口提示删除失败，但部分来源已永久删除；活跃会话后续还可以追加新记录。

建议：PostgreSQL 路径使用同一事务；对活跃会话建立保留/删除状态，或明确只允许删除结束会话；返回每个来源的完成状态并保证重试语义。

## 已确认需求尚未完成

- **用户体验整体延迟**：停说到实际首播、有效开口打断到实际停播仍未完整采集，端点/确认到客户端回执仅是代理值。需要客户端音频时间轴锚点及明确回执事件，不能简单相加模块耗时替代。
- **录音与保留**：[报告 audio 字段](/Users/forever/workspace/OpenRealtime/src/lib/session-diagnostics-report.ts:11) 仍为 not-configured，没有默认双向录音、同步回放、7 天清理、标记长期保留。
- **Agent 自动查询**：[接口授权](/Users/forever/workspace/OpenRealtime/src/app/api/observability/sessions/[sessionId]/diagnostics/route.ts:8) 只有浏览器管理员 Cookie，没有独立、只读、可过期、按 Session 限定的 Agent 凭据。仅给 Session ID 还不能自动查询。
- **逐 Token 延迟**：现有 TTFT 是首个非空文本增量，不包含 Token 间隔/生成吞吐；不要将文本 chunk 当作单 Token。
- **延迟历史趋势**：总览图是会话活动数量，还不能看首播/停播或各模块延迟随时间的变化。

## 已验证的有效部分与验证限制

- 管理员授权按 issuer+subject 查询，页面/API 复用应用会话；无需第二次登录。
- 本地环境已显式配置 PostgreSQL，上一轮真实写入、跨服务重启、查询的持久化检查通过。其它环境仍需显式配置，默认配置仍为 memory。
- 首包/首文本与含编排的总耗时已分开描述；缺少样本不填零。
- 本轮使用内存隔离的真实观察器和聚合器复现问题，未写业务记录、未重启服务。
- 现有测试即便全部通过，也没有覆盖详情缺失遥测渲染、实际取消到停播回执顺序和 TTFT 逐轮归属；不能据此认定功能完整。

修复顺序：停播回执与 TTFT 关联、详情容错 → 模块失败汇总与采集健康 → 分页和 Agent 只读访问 → 整体延迟锚点、录音及保留。

## 本轮修复与验证（2026-10-04）

上述七个代码缺陷已修复：

1. 播放协议明确区分 started、progress、stopped、completed；仅 stopped 计算停播回执耗时。取消回复不会清掉待确认计时，按响应标识匹配并保留原轮次归属。
2. 缺失遥测时详情仍能渲染其它日志；三个来源没有会话内容时返回 404，失效时间戳显示占位符。
3. 直接记录的 TTFT 等事件继承任务内 generation；历史未关联事件另行展示。
4. 总览增加 capability_failures，包含没有 duration 的能力失败。页面分开说明计时样本错误与能力失败事件，避免混用分母。
5. 遥测及决策日志支持按 event ID 的稳定游标续查；遥测 summary 独立统计全会话。统一 API 接受 telemetry_cursor、debug_cursor，页面加载更多并按 event_id 去重。决策日志满页会提供游标，最后一页恰好满页时可能需一次空页确认结束。
6. /observability/health 提供存储后端、待写入数、丢弃数、写入失败和最后成功写入时间。报告保留进程级采集健康；查询可用不代表日志完整。旧服务不提供健康信息时，页面明确提示无法确认完整性。
7. PostgreSQL 删除在同一连接、同一事务执行，任一来源失败则整体回滚。更正原 review：HTTP 入口原先已有活跃会话删除保护，本轮保留该保护。

验证：Python 主要回归 147 passed / 1 skipped；控制平面新增健康接口测试后 21 passed。前端定向回归 50 passed。独立临时 PostgreSQL schema 的真实集成测试 3 passed，包含 5002 条遥测分页、决策游标、注入第三个删除源失败后的三来源回滚；测试 schema 已清理。Ruff 和 git diff --check 通过。TypeScript 全量检查仍被原有 model-services route 导出 isPersonalModelKind 的类型错误阻挡，本轮未引入新报错。

完成回归后读取 /sessions 确认为空，才优雅加载新后端。真实 /observability/health 返回 postgres、零积压、零丢弃、无写入错误；既有业务数据没有被删除。

已确认需求中的整体体验时间锚点、录音存储/保留、独立 Agent 只读凭据、逐 Token 间隔、延迟历史趋势仍是后续实现项；本轮修复没有将代理指标冒充整体体验指标，也没有将这些功能标为已完成。
