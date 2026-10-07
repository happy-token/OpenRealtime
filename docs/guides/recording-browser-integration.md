# 隔离录音保留浏览器测试

此测试使用本机 `/tmp` PostgreSQL、真实管理员Cookie、真实Next/私有HTTP和Memory Runtime录音。夹具通过实际Bridge向受控sink发送100ms音频，再通过规范播放协议接受50ms精确回执；浏览器验证该投影并独立回放WAV。不调用麦克风、外部模型或S3。需要项目既有 `.venv`、pnpm和Chrome。它不会自动启动Python夹具，不应指向运行中的用户服务。

在第一个终端，用新随机schema启动夹具：

```sh
export RUN_RECORDING_BROWSER_INTEGRATION=1
export VOICEAGENT_POSTGRES_SCHEMA="voiceagent_recording_browser_$(.venv/bin/python -c 'import uuid; print(uuid.uuid4().hex)')"
# 固定测试数据，不是生产密钥。
export VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY=a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s
.venv/bin/python tests-e2e/fixtures/recording_preservation_runtime.py
```

记下schema和夹具输出的 `control_plane_url`。第二个终端设置相同测试值及输出URL；Playwright独立启动并关闭3029的Next，端口已有服务时应拒绝启动：

```sh
export RUN_RECORDING_BROWSER_INTEGRATION=1
export VOICEAGENT_POSTGRES_SCHEMA=voiceagent_recording_browser_替换为第一个终端的32位随机后缀
export VOICEAGENT_CREDENTIAL_ENCRYPTION_KEY=a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s
export VOICEAGENT_POSTGRES_DSN='postgresql:///postgres?host=/tmp'
export VOICEAGENT_CONTROL_PLANE_URL=http://127.0.0.1:替换为夹具端口
export OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET=recording-fixture-only-read-secret-32
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:3029
export PLAYWRIGHT_EXECUTABLE_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
pnpm exec playwright test tests-e2e/session-recordings-integration.spec.ts tests-e2e/session-recordings-preview.spec.ts
```

完成后在第一个终端按Ctrl-C并等待退出；夹具只删除自己原子认领的随机schema。重复运行集成用例时重建夹具，避免第一次标记政策影响“未标记→标记”断言。Next可能改写`next-env.d.ts`和`tsconfig.json`的生成类型路径；只还原核实为本次生成的变化，不提交或覆盖其他编辑。

通过标准包括精确800/1600采样交集及说明、媒体解码/100ms播放完成、合法Range、目录刷新后两段真实immutable状态、无Cookie机器凭据读取计数与摘要、Agent/匿名/跨站拒写和手机布局。这不是原生产renderer播放确认、真实用户听到、持久S3或供应商延迟验收。

## 生产 WebAudio 回执与录音关联

使用新随机 schema 重新启动夹具，并在第一个终端额外设置：

```sh
export RECORDING_BROWSER_RENDERER=1
```

此模式不预先生成已发送录音或播放回执。记下输出中的 `renderer_port`，在第二个终端沿用以上隔离环境，同时设置：

```sh
export RECORDING_BROWSER_RENDERER=1
export RECORDING_BROWSER_RENDERER_PORT=替换为输出的renderer_port
pnpm exec playwright test tests-e2e/recording-renderer-integration.spec.ts
```

不要在此模式运行要求800/1600受控回执的旧集成用例；两种模式各自使用新夹具/schema。新用例实际打开`/conversation`，重定向真实WebSocket到测试端口，让生产WebAudio播放两段200ms音频并自行产生6400采样结束回执，离开对话后读取实际Settings录音投影，再用无Cookie Agent读取并比对WAV/真实wire PCM。测试保留原始失败，收尾取证有独立超时，附件`recording-renderer.json`包含实际前端、canonical和目录证据。

这个增量覆盖正常WebAudio链路；输入PCM仍预先生成，不证明端到端麦克风、物理扬声器/用户听到、所有数字人renderer、打断/断连、真实供应商或S3。参见[报告](../reports/2026-10-07-browser-recording-renderer.md)和[ADR0159](../adr/0159-browser-recording-renderer-sample-clock.md)。按上述方法停止夹具并等待owned schema删除，不修改运行中的用户服务。
