# Lip Forcing GPU 服务部署

OpenRealtime 将 Lip Forcing 14B 作为独立的单并发 GPU 服务运行。Web 进程提交动作视频和参考音频，轮询任务状态，再下载生成的视频。服务只监听 GPU 主机的 `127.0.0.1:8190`，通过 SSH 隧道访问；API Bearer Token 保存在 GPU 主机的 `/etc/openrealtime-lipforcing.env`。

## 前置条件

GPU 主机沿用此前部署，不重复下载模型：

- 代码：`/root/lipsync-eval/lipforcing-eval`
- 模型 Python：`/root/lipsync-eval/venv-lipforcing/bin/python`
- 14B 权重及 Wan VAE：位于代码目录的 `weights/` 下
- `ffmpeg`、`ffprobe`、`flock` 可用
- 登录路径：本机 `ssh beike`，再从 beike 的 `localhost:10022` 登录 GPU 主机 `dev`

管理脚本使用等价的 SSH `ProxyCommand` 直达 GPU。首次连接若仍要求密码，先配置 beike 到 GPU 的公钥登录；日常部署和 Web 服务运行不应依赖交互式密码。

## 部署与日常管理

在 OpenRealtime 仓库根目录运行：

```bash
scripts/lipforcing_service.sh deploy
scripts/lipforcing_service.sh status
scripts/lipforcing_service.sh smoke
```

常用操作：

```bash
scripts/lipforcing_service.sh restart
scripts/lipforcing_service.sh stop
scripts/lipforcing_service.sh start
scripts/lipforcing_service.sh logs
```

`deploy` 会把 API、固定版本依赖、systemd/s6 服务定义和推理脚本安装到 `/opt/openrealtime-lipforcing-service`，创建单独的轻量服务虚拟环境，保留现有模型虚拟环境，并自动选择宿主可用的进程管理器。任务与日志位于 `/var/lib/openrealtime-lipforcing/jobs/<job-id>/`；当前 GPU 容器由 s6 托管，服务日志同时写入 `/var/log/openrealtime-lipforcing.log`。

服务升级不会覆盖已有 `/etc/openrealtime-lipforcing.env`。模型路径变化时只需编辑该文件，然后执行 `restart`。

## Web 应用配置

先建立隧道（保持该进程运行，生产环境可将同一命令交给 systemd 管理）：

```bash
scripts/lipforcing_service.sh tunnel
```

读取 Token：

```bash
scripts/lipforcing_service.sh token
```

在 Web 进程的私有环境文件中配置：

```dotenv
LIPFORCING_API_URL=http://127.0.0.1:8190
LIPFORCING_API_TOKEN=<GPU 主机上的 Token>
LIPFORCING_JOB_ROOT=/var/lib/openrealtime/lipforcing-jobs
```

重启 Web 进程后，`/api/services/talking/status` 会把 Lip Forcing 标记为已配置。未设置 `LIPFORCING_API_URL` 时，代码仍保留原来的单次 SSH 执行作为回退路径。

## HTTP API

健康检查无需 Token：

```bash
curl --fail http://127.0.0.1:8190/health
```

提交任务：

```bash
curl --fail \
  -H "Authorization: Bearer $LIPFORCING_API_TOKEN" \
  -H "X-Job-Id: lipforcing-manual-001" \
  -F source_video=@source.mp4 \
  -F reference_audio=@reference.wav \
  http://127.0.0.1:8190/v1/jobs
```

查询和下载：

```bash
curl --fail -H "Authorization: Bearer $LIPFORCING_API_TOKEN" \
  http://127.0.0.1:8190/v1/jobs/lipforcing-manual-001

curl --fail -H "Authorization: Bearer $LIPFORCING_API_TOKEN" \
  -o output.mp4 \
  http://127.0.0.1:8190/v1/jobs/lipforcing-manual-001/result
```

同一个 `X-Job-Id` 重复提交会返回已有任务，避免 Web 重试时重复占用 GPU。服务内部只有一个 worker，保证 14B 模型任务串行执行。

## 故障排查

健康检查返回 `503` 时，响应的 `missing` 字段会列出缺少的运行时、Python、推理脚本或权重路径。推理失败时检查：

```bash
scripts/lipforcing_service.sh logs
```

并在 GPU 主机查看：

```bash
ls -la /var/lib/openrealtime-lipforcing/jobs/<job-id>/
tail -n 200 /var/lib/openrealtime-lipforcing/jobs/<job-id>/inference.log
```

任务输入、输出和日志默认保留，便于人工核对；确认无须追溯后再按具体 job-id 清理，不要批量删除整个任务目录。
