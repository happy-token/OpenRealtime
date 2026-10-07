# 2026-10-07 Agent 单会话诊断授权

根据“commit，继续未完成的”继续横向OBS02轨道。前置提交为`d03f726`，当前工作区起始干净。新增决定见[ADR0148](../adr/0148-session-scoped-agent-diagnostic-access.md)，使用方式见[操作说明](../guides/agent-session-diagnostics.md)。

## 实际交付

管理员同源POST签发独立Agent身份、15分钟绝对有效期、单Session只读凭据。既有diagnostics GET接受该凭据，保留独立日志游标、来源可用性和截断标记；无效Bearer不回退管理员Cookie。机器请求不读取全局采集health、不转发凭据到Control Plane。真实会话详情增加同主题下载按钮，预览禁用；普通诊断导出没有密钥。

配置示例中的`OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET`默认留空。没有生成或写入运行中服务的密钥，没有重启3010/8765/8766、执行生产迁移、调用真实提供商或推送远端。部署后管理员下载和外部Agent实际调用仍需验收。

## 独立审查发现及修复

原Session ID允许单独`.`/`..`，URL规范化会改变查询资源。两项正式红回归证实问题；签发、验证和GET统一使用排除dot-segment的校验后通过。

审查进一步实际复现共享thread会话A/B正文越界：旧reader仅按`thread_id=session_id`读全线程。5项真实ApplicationRuntime/Journal/Telemetry红回归覆盖共享thread、不同公开身份、相同generation、缺失metadata、身份歧义及1001条超限。修复后复用服务器记录的tenant/user/thread，按原始`context.voice_session_id`过滤，并返回来源字段。Next机器聚合还逐源拒绝外Session或缺失来源身份的正文。旧后台未经更新只能将对话源标不可用，不把不确定来源作为授权数据。

Python审查又复现第5001条遥测出现冲突身份未被第一页解析发现。第6项真实红回归复现后，既有resolver增加可选`require_complete`，仅本次reader设为true：身份页有后续则明确不可用，不重复查询/无限扫描，其他历史及删除调用保持原行为。大Session的独立身份查询仍待补齐。

传统对话数组接口没有分页。1000条线程扫描再探测一条，超限返回来源不可用，避免截断/续接晚段被标为完整；后续需要按Session分页查询，此项没有因安全修复而关闭。

## 验证

- 全量Python：**2537 passed，69 skipped，3 subtests passed，58.56s**。
- 全量前端Vitest：**1312 passed，7 skipped，18.49s**。
- 29项授权/路由定向测试和最终93项Python读取/装配/HTTP测试通过。
- `tsc --noEmit`、本批ESLint、Python定向Ruff和`git diff --check`通过。
- 独立代码审查复跑92项Python、30项前端，最终限定APPROVE；独立UI探针验证重复点击只发一次请求、无视abort的迟到回复在卸载后不下载、预览禁用、成功下载且状态文案不含token。这是组件探针，不是实际管理员浏览器下载验收。

Python审查最终93项通过、限定APPROVE。Runtime Mypy排除既有`asyncpg`缺少类型标记的import-untyped后通过；HEAD shadow同样有这1项。demo Mypy的19项错误与HEAD基线一致，本轮reader未新增，不能宣称全部Python类型检查绿。

密钥轮换撤销全部凭据；当前没有单凭据提前撤销或持久签发/使用审计，移除管理员不立即撤销其已签发的15分钟凭据。文件传递须使用安全渠道，生产调用HTTPS。机器subject是管理员指定的名字，不声称已验证外部工作负载身份。

## 仍开放

OBS02完整证据/对话分页/部署与真实Agent调用、OBS03默认双路录音存储和实际播放映射、故障因果去重/冷暖重连指标，以及G0标注录音、G1真实公平性和延迟、G2未知动作持久幂等、G3完整交接、G4完整真实renderer/供应商异常矩阵、G5综合负载继续保留。当前仅完成受限诊断授权增量，整个计划未完成。
