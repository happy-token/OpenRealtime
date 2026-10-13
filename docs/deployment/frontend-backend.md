# 前后端分离部署

OpenRealtime 由前端和后端组成。**后端包含会话管理服务与语音交互服务**，两者按职责划分，可以运行在同一台服务器，也可以在处理好依赖后分别部署。

- **前端**：用户看到的页面、文档和操作界面，以及浏览器端的麦克风采集与音频播放。
- **会话管理服务**：管理登录与权限、助手配置、供应商设置、产品资料、记忆和会话历史。例如，保存助手的声音或查阅一段历史会话，都通过会话管理服务 API 完成。
- **语音交互服务**：执行实时通话，连接语音识别、判停与打断、你的 Agent / LLM、语音合成。它接收麦克风音频，判断何时回应，并在用户插话时停止当前回复。

两者协作：会话管理服务为通话提供已授权的助手配置，语音交互服务按配置运行语音链路并保存会话记录。页面通过会话管理服务接口获取初始化数据；浏览器不连接数据库，也不获取长期供应商密钥。

| 所属层级 | 服务 / 运行部分 | 构建与位置 | 默认入口 |
| --- | --- | --- | --- |
| 前端 | 页面与浏览器交互 | 根目录 Next.js；OpenNext → Cloudflare | 页面与静态资源 |
| 后端 | 会话管理服务 | `apps/backend`；Node.js → 应用服务器 | `/api/*` |
| 后端 | 语音交互服务 | `server` / `demos/voice_web_server.py`；Python | `/voice/` |

公开域名保持统一，登录 Cookie、OIDC 回调、API 和 WebSocket 地址无需跨域迁移。个人接口禁止缓存。数字人大文件暂留源站。

## 本地运行

`pnpm dev` 会启动前端、会话管理服务 API、语音及已有可选数字人启动流程。也可以单独运行：

```sh
pnpm dev:api     # 127.0.0.1:3011；加载本地 .env / .env.local
pnpm dev:web    # 127.0.0.1:3010
pnpm dev:server # Python 语音与内部控制接口
```

前端默认连接 `http://127.0.0.1:3011`。通过 `OPENREALTIME_API_ORIGIN` 修改会话管理服务地址；它属于非敏感连接配置。后台密钥只注入 API / Python 进程。

## 构建和部署

```sh
pnpm build:api       # 仅构建会话管理服务
pnpm build:frontend  # 在隔离目录构建 Cloudflare 前端，检查依赖并排除后台环境文件
pnpm deploy:frontend
```

Cloudflare 生效配置是 `deploy/cloudflare/frontend/wrangler.jsonc`。
根目录旧 `wrangler.jsonc` 的语音代理属于旧部署示例，不能用于发布整个前端。
前端包不包含业务 route handlers；本地 `/api` transport adapter 仅作转发。
OpenNext 的已知 middleware manifest 加载差异由构建补丁处理，不改变中间件内容。

会话管理服务使用独立的 `openrealtime-api` 容器，监听 3012，部署在应用服务器上。
首次切换保留旧 Web，先验证新 API 再切 Cloudflare；完成检查后停止旧 Web。
回滚恢复旧 Worker、Caddy 配置及旧 Web 镜像；不要修改用户数据或回退数据库。

## 这一阶段的范围

前端不挂载业务数据、不持有数据库及供应商凭据，可以单独构建和发布。
会话管理服务与语音交互服务暂时保留现有共享目录和本机内部控制连接。将语音交互服务迁移到另一台服务器前，需要先处理共享存储和受限的跨机通信。内部控制接口只允许受信服务访问。
