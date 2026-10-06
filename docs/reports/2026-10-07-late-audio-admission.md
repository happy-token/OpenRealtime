# 替换后迟到音频的入队屏障

日期：2026-10-07。续`d334fbf`，阶段3前置交付，G3未关闭。

## 失败与修复

5项新失败回归复现：旧speech在同代或跨代替换后仍可重新入队，待播旧PCM未清理，同一speech可跨generation复用。DeviceAudioOutputRuntime现维护同epoch内单调generation和speech绑定，替换后旧身份禁止再入队，清除内部复制的旧PCM，不修改调用者原数组。换epoch后身份屏障复位；既有已完成speech后同代新speech仍可播放。

真实Chrome主页面追加“新音频后迟到旧包”，发现仅在播放器拒绝还不够：hook先enterSpeaking旧generation，随后拒绝物理播放，导致新音频ended无法发送finished。该用例已红后修复。接纳纯查询由同一runtime提供，Browser.play与主hook的assistant_audio_chunk均先校验，拒绝前不修改AudioContext、时钟、speaking或timer。实际enqueue再次校验，没有新增决策actor或输出队列。

## 验证与限制

新增5项单测先红后绿；限定3文件23 passed，独立审核4文件31 passed。前端全量1259 passed / 7 skipped，17.17秒。限定ESLint通过。后端未改变，上一批Python1783 passed / 62 skipped / 3 subtests为本批基线。

跨代Chrome场景加旧包后先失败（只有新playing而无finished），修复后与输入失败清理3轮共6项通过。扩展同代后首次组合运行8 passed / 1 failed，首个同代用例未在3秒内收到finished；未将其归因于已验证的代码错误。加入真实AudioContext状态/时钟到失败断言观测，保持3秒阈值，再跑同代/跨代各5轮共10项全部通过（31.6秒）。该间歇首次运行现象仍应持续观察，不能据此关闭真实renderer验收。

TSC与Next测试服务同时运行曾因测试目录文件被重建产生TS6053；测试服务退出、还原自动修改的next-env/tsconfig后单独重新检查通过。最终TSC、限定ESLint及diff检查通过，不把并发构建的中间错误当作生产类型缺陷。

结论仅覆盖已接入的assistant_audio_chunk浏览器路径。旧版assistant_audio入口、数字人媒体身份、精确句段/停播命令、STOP_CONFIRMED/UNKNOWN、限时当前句许可、heard_frontier交接与误打断恢复仍待实施。会话metadata与上层音频队列完整界限未关闭。真实模型/实体设备未测试，用户服务未重启，未push。
