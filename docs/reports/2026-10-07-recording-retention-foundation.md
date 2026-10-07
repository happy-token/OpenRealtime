# 2026-10-07 录音保留与上传清理前置

继续“commit，继续未完成的”，分页批次已本地提交7b3bb6d；随后沿OBS03默认双路录音轨道核查既有AudioSink与ArtifactStore，发现retention_until只是提前删除保护，没有录音expiry intent。决定见[ADR0150](../adr/0150-recording-artifact-retention-and-upload-ownership.md)。

## 实际变化

voice_session_recording请求必须声明aware期限；PG复用既有cleanup_intents在创建同事务安排期限，pin同事务取消；Memory只选择到期未pin录音。维护batch严格1–1000，记录候选按尝试次数轮转，避免第一个永久失败阻塞另一条。已有avatar清理及其他Artifact的保留语义保留。

共用private ArtifactUploadOwner最多64项实际IO任务，caller取消不撤实际upload task，实际完成才释放容量/消费晚异常。Memory活跃上传/孤儿重试复用Store状态，不能把有上传归属的录音标DELETED；删除/失败校验/标记竞争保持明确状态。没有增加业务actor或worker queue。

新增0036 put_completed列：实际put返回后、crash hook之前持久记录；旧清理撤权不能恢复receipt CAS，late writer会重挂清理。未知put即使delete当前不存在的key成功仍保留cleanup_pending并继续复查，不能宣称未来不会写入；有完成证明且真实delete成功才cleaned。token失效的终态UPDATE0不计成功。过去旧cleaned行不自动伪造完成证据；部署时如存在旧孤儿需独立盘点。未知write清理元数据可能持续保留，详见ADR限制。

## 独立审查与正式回归

7项Memory、3项PG最初正式失败覆盖缺清理/无界batch/缺期限。审查又实际复现：Memory晚failed finalize把DELETED复活；Memory和PG的put在物理写前被清理后迟写留下对象；真实Boto3 to_thread在caller取消后仍写入；PG旧清理token撤销仍报成功。上述主要路径分别补正式red→green回归，复用旧Store和真实生产adapter；线程SDK为注入本地受控实现，无真实S3调用。独立probe还指出pin成功误标失败和跨批失败饥饿，均补正式受控竞争/轮转回归。

测试覆盖期限前/模拟7天后、无关Artifact、pin前/后删除准入、删除失败重建Store重试、late put orphan delete失败、put确认先于crash/restart、stale token计数、64个取消caller仍占真实容量。受控时钟与IO不能当作真实7天线上运行或供应商性能实验。

## 最终验证

- 全量Python：**2562 passed、84 skipped、3 subtests passed，59.20s**。
- artifacts+avatar_assets定向：**48 passed、1 skipped，4.60s**。
- 隔离本地PG16.13，两个文件：Artifact **21** + Journal **15** = **36 passed，4.04s**；fixture随机schema运行0036并finally删除，未动生产schema/未启动或重启DB。
- 4源Mypy、7文件限定Ruff、diffcheck通过。Memory_replace(**dict[str,object])的6项错误经HEAD临时shadow证实相同，未新增，也没有声称整个Memory类型检查绿。
- Python独立审查限定APPROVE，独立28项Memory/21项PG（最终孤儿轮转前）通过；代码审查最终限定APPROVE，独立29项Memory、64容量及孤儿轮转探针通过。最后代码审查又复现失败孤儿占据batch首位；两晚put正式回归先红后绿，失败孤儿锁内移至末尾，不更改归属。最后孤儿轮转修正之后重新执行全量Python，数字为最终结果；前端此次无新改动。

没有生产迁移、默认录音启用、3010/8765/8766重启、真实S3/语音模型调用或远端推送。

## 继续任务

这一批是录音存储前置。双路input/实际sent分段采集、默认7天策略的实际应用、Runtime Store及IO生命周期、维护调度、录音Session索引/只读音频接口、renderer confirmed_played映射及页面状态仍未完成。OBS02完整输入证据与音频引用、故障去重/冷暖建连指标及全部G0–G5保持开放。整个目标仍active。
