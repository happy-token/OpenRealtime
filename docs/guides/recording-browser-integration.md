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
