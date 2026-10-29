# 真实样包验收记录（阶段 5）

日期：UTC 2026-10-29。范围：隔离实例 `127.0.0.1:18082`（项目 `innovation-ar-resource-platform-infra-check`，PostgreSQL 17.6，Java 21 后端 Jar sha256 `fa7eb0d4…ac7cc`，由 `check_java.py --module ruoyi-admin --package --offline` 产出，63 项测试 0 失败/错误/跳过；本轮未改后端/前端源码，未重建 Jar/dist）。这是单机回环结果，不是手机或公网性能，也不是 Android/iOS 真机验收。本记录不修改 `docs/06-validation.md`；原始报告留在本地 `.local/4dgs-check/evidence/stage5/`（`verify-4dgs.json`、`run.log`、`jfr/`、`playback/` 截图与逐次请求记录），不入库。

## 结论

| 项目 | 状态 |
|---|---|
| wedding、dance_color、shiku_dtwd 导入、发布、匿名目录/详情、全部文件字节与源 SHA-256 | 通过 |
| wedding 与 dance_color 的标准档完整下载（只含所选档位模型与去重后的公共文件，无高清/VR 字节） | 通过 |
| 上传、发布、列表/详情、HEAD、Range、完整下载、重启的服务端内容读取（JFR） | 通过 |
| 后台导入/继续上传在 1440 与 1024 宽的遮挡检查（`run_http_checks`，含真实 Chrome） | 通过（78 项） |
| 真实 Chrome 播放 wedding 标准、wedding 高清、dance_color 标准跨 5 秒（参考播放器真实构建 20261016/230726） | 通过（本轮新增，逐项见下） |
| shiku_dtwd 0–5 秒窗口播放 | 未播放：窗口是样例假设（原 timeOption 为空），不属于本轮验收集合 |
| 手机网络访问、原生解码、音画主观效果 | 未验收，留给用户真机 |

`verify_4dgs.py` 103 项检查全部通过，0 项阻塞，退出码 0（命令块见 `.local/PLAN.md` 真包命令块，`--source /data/前端4DGS调研/local-viewer/public`）。

## 参考播放器：对真实构建的核对与修正

上一版阶段 5 工具是在没有真实播放器时按文档写的；本轮用 `/data/前端4DGS调研/local-viewer/public`（只读，未编辑）逐项核对，发现并修正：

- 已核对属实：`D8TV3hLS.js` 第 46 行是 `import("./Drq6wweV.js")`，取其 `default` 作为 `showdemo=4dv` 的场景表，场景键取 URL 路径最后一段，所以以 UUID 为键、`config_name` 用 UUID 可行；`__S4D_BENCH__` 一直存在（`testBenchRuntime` 只控制运行时统计），但它是带方法的对象：必须调用 `snapshot()`（含 `currentTime`、`playerCurrentTime`、`duration`、`timePaused`、`renderReady`、`appFrame`、`graphicsWidth`、`sortingEngine`…）和 `ready()`，对它做 JSON 序列化只得到空对象。旧驱动里按名字猜时间字段的 `find_time` 因此删除，改读 `snapshot().playerCurrentTime`。
- 不成立：来源目录里没有 `viewer/index.html`、`viewer/sw.js`、`viewer/manifest.json`、`4dvai.svg`、`super-4d.png` 和 `viewer-static/font/` 下的字体（研究仓库的静态清单记载过前几项，但本机副本里已不存在）。本轮为确认这一点只读取过一次上游公开页面 `https://www.4dv.ai/viewer/rocket`（结果存在 `/tmp`，未入库、未用于播放）：它现在引用更新构建 `20261026/153339`，与来源里的 `20261016/230726` 不是同一构建，不能用来补页面。处理：`prepare_reference_viewer.py` 不再要求这些文件，也不联网；用 `scripts/reference_viewer/index.html` 写出最小入口页（模块脚本、样式表、manifest 和主包渲染到的 `#dropArea`，结构取自上述当前页面和旧资源清单，不是上游原文件，没有预加载提示和统计脚本），不安装 Service Worker。后果：`/viewer/sw.js` 与 `/viewer-static/Gineso-ConMed.png` 在网关上 404（来源缺文件，验收脚本逐一列为允许的 404，其他 4xx 一律失败）；计划里“重算 Service Worker 修订”的步骤因来源没有 SW 而不适用，`serviceWorker: none` 记入准备目录的标记文件。
- CSP 需要 `'unsafe-eval'`：首版 CSP（无 `unsafe-eval`）实测页面 40 秒停在 0%，页面错误 `window is not defined`，模型未开始加载；加上 `unsafe-eval` 后正常加载。原因按代码推断：主包的自卫代码用 `Function(...)` 取全局对象并在失败时回退到 `window`，Worker 中没有 `window`（该推断由“加后消失”间接支持，未单独隔离）。研究仓库自己的服务器策略同样允许 `unsafe-eval`。外部访问仍由 `connect-src 'self'` 封死。CSP 同时写入准备目录标记文件，隔离网关把它作为响应头发给 `/viewer/`、`/viewer-static/`（meta 标签管不到 Worker）。
- 统计请求：主包会尝试连 Sentry（`o4511410060722176.ingest.us.sentry.io`）和 PostHog（`pd.4dv.ai`）。全部被 CSP 在浏览器内拦下，没有一个到达网络；验收脚本把“已发出且未被拦的外部请求”判失败，被拦的主机名写入报告。主包中另有 10 个第三方地址字符串（posthog、sentry、fonts.googleapis、`pd.4dv.ai` 等）留在代码里，同样由 CSP 封死。
- 隔离网关：旧版 `prepare` 在容器已运行时不会让网关看到重写后的 Nginx 配置/查看器目录（文件和目录换了 inode）。`prepare_4dgs_check.py` 现在在 `up` 后对网关做 `--no-deps --force-recreate`；网关无状态，后端和库不受影响。
- 参考播放器加载目录时对平台上的每个场景取详情（本库 36 个，含此前门禁留下的合成场景），并为其他场景请求少量文件（每次 8 个，来自 18082）。这些请求都在 `127.0.0.1:18082`，不影响当前场景档位的检查。
- 单元测试：`scripts/test_prepare_reference_viewer.py` 11 项（来源无入口页/SW 仍可准备、不安装 SW、CSP 来自标记文件）、`scripts/test_verify_4dgs.py` 6 项（循环回绕的连续时间段、网络分类、控制台允许项）、`node --test scripts/test_reference_catalog_adapter.mjs` 8 项，均通过。这些夹具不是 4DV 播放器，播放证明只来自下面的真实运行。
- 网关覆盖：`prepare_4dgs_check.py --reference-viewer` 生成的 Nginx 配置：`/viewer/<uuid>` 返回入口页，`/viewer/platform.html`、静态资源按真实路径返回且带 COOP/COEP/CORP 与 CSP 头，不存在的路径 404（`{36}` 正则加引号；`^~ /viewer/` 会遮蔽场景 ID 正则，故用普通前缀）。

## 真实浏览器播放

真实 Chrome 156（`/opt/google/chrome/chrome`，无头），每次新建 context（无旧 Service Worker、CacheStorage 或存储），启动参数 `--use-gl=angle --use-angle=gl-egl --ignore-gpu-blocklist`；渲染器 `ANGLE (NVIDIA Corporation, NVIDIA GeForce RTX 4060 Laptop GPU/PCIe/SSE2, OpenGL ES 3.2)`。同一脚本也记录了不带参数时的默认渲染器：SwiftShader（软件）。每次运行都从 `/viewer/platform.html` 选场景和档位并点“打开播放器”，进入 `/viewer/<sceneUUID>?showdemo=4dv&variant=<档位>`，不带 Authorization，不 mock 任何后台响应。

| 运行 | 就绪（`ready()`/`renderReady`） | 玩家时间 | 画面 | 所选档位模型请求 |
|---|---|---|---|---|
| wedding / standard_quality | 1.2 s，画布 1280 宽，`CPUSorter(tree)`，时长 8 s | 5.0 s 墙钟内玩家时间前进 5.1 s，到 8 s 循环 | 首帧与后续帧均为真实渲染（817→1568 种颜色，非黑），帧计数持续增加 | 2 个分段 200，30,863,971 与 23,503,730 B |
| wedding / high_quality | 1.7 s，时长 8 s | 5.0 s 墙钟内前进 5.0 s | 同上（1003→1657 种颜色） | 2 个分段 200，86,695,444 与 66,413,844 B；与标准档请求的文件互不相交 |
| dance_color / standard_quality | 1.0 s，时长 73 s | 5.0 s 墙钟内前进 5.0 s；越过第二分段起点 5 s（到 6.63 s），再 2 s 后 8.65 s 仍前进且仍在渲染 | 首帧/后续帧均非黑非单色 | 3 个分段 200（第二、三分段已被预取） |

- 每次运行：所有到达网络的请求都发往 `http://127.0.0.1:18082`（目录分页、场景详情、设置、海报/预览/音频、所选档位模型、查看器静态文件、WASM）；被拦的外部主机只有 `o4511410060722176.ingest.us.sentry.io` 和 `pd.4dv.ai`（未发出）；没有 `/4dgs/demo` 或 `/api/v1/viewer` 路径的请求，即没有内置清单或研究服务；没有请求其他档位的文件；4xx 只有来源缺文件的 `/viewer/sw.js`、`/viewer-static/Gineso-ConMed.png`；控制台错误只有被 CSP 拦下的外部主机和这两个 404。
- 档位切换：wedding 标准与高清的模型请求文件集合互不相交，字节不同；平台目录页（launcher）列出的档位与描述完全一致。
- 截图：`.local/4dgs-check/evidence/stage5/playback/playback-<场景>-<档位>-{first,later}.png`；逐次请求（URL、状态、Range、Content-Length、ETag）和 `snapshot()` 采样在同目录 `.json`。浏览器证明不等于手机证明：手机上的 WebGL/WASM 解码、网络访问与音画主观效果仍待真机。
- 备注：Chrome 无头模式下 AudioContext 因无用户手势未启动（控制台警告），音频播放未被本轮验证。

## 真实样包

样本目录只读，描述由 `prepare_4dgs_samples.py` 写入 `.local/4dgs-check/sample-descriptors/`。引用字节：wedding 10 文件 267,533,112 B；dance_color 49 文件 1,534,783,789 B；shiku_dtwd 5 文件 136,446,400 B；无关的报告 .md 未上传。导入前按“引用字节 + 下载字节 + 2 GiB”检查磁盘（本次开始时约 29.2 GB 可用，全部满足）。每次运行都是全新导入（新请求键、新版本），随后删除被取代的旧版本。

- 每份描述的所有引用文件在版本内均 AVAILABLE，匿名详情的 `descriptor` 与上传的完全相同，文件清单大小/摘要与源一致，响应中无 storageKey、磁盘路径；所有文件经网关下载后的 SHA-256 等于源文件，带强 ETag，无 attachment 头。
- shiku_dtwd 的 0–5 秒窗口与 1.4 缩放是样例演示选择（原配置 timeOption 为空），不是重建出的生产时间契约。
- 下载：`download_scene.py` 对 wedding/standard_quality 取 6 个文件 68,553,739 B，对 dance_color/standard_quality 取 19 个文件 354,532,956 B；负载目录恰为所选档位加公共文件；无 high_quality/vr_foreground 文件落盘；网关日志中 GET 的文件 ID 集合等于计划集合且全部 200，发送字节等于所选模型 + 去重公共文件之和。

## 耗时（本机回环，首轮；括号为重复）

| 场景 | 预哈希 | 创建版本 | 全部上传（含预哈希） | 发布（重复） | 目录 | 详情 | 整套文件读取 |
|---|---|---|---|---|---|---|---|
| wedding | 0.134 s | 18 ms | 0.67 s | 11.8 ms（5.5 ms） | 2.6 ms（2.7 ms） | 1.2 ms（1.3 ms） | 267.5 MB / 0.32 s |
| dance_color | 0.767 s | 20 ms | 3.59 s | 8.3 ms（3.4 ms） | 2.9 ms（1.7 ms） | 1.7 ms（1.3 ms） | 1534.8 MB / 1.74 s |
| shiku_dtwd | 0.067 s | 11 ms | 0.34 s | 6.4 ms（2.1 ms） | 1.9 ms（2.0 ms） | 1.1 ms（1.2 ms） | 136.4 MB / 0.21 s |

完整下载：wedding 标准档 0.19 s，dance_color 标准档 0.69 s（含逐文件校验）。文件处于系统页缓存，不能代表磁盘或网络吞吐。浏览器首次就绪（含目录取全、详情、首个分段下载和解码）1.0–1.7 s，同样是回环数字。

## JFR 文件读写证据

测试后端以 `JAVA_TOOL_OPTIONS=-XX:StartFlightRecording=settings=<最小 JFC>,dumponexit=true` 启动，JFC 只含 `jdk.FileRead/FileWrite`（阈值 0、含堆栈），不启用环境变量/属性事件；健康检查 JVM 清除该变量。正常停止后 `docker cp` 取出记录，在 Java 21 工具镜像里用 `jfr print` 导出并只统计 `/data/artifacts/staging`、`/committed` 路径（Jar、日志、配置读取不计）。本轮第一次后端生命周期共 289,042 个存储事件（含 48,587 次读取、240,455 次写入）。

- 三份样包导入窗口：staging/committed 内容读取事件 0；整份记录里没有任何一次存储读取的堆栈含 `verify` 帧；每个上传文件的 FileWrite 字节约等于一份文件（0.99–1.5 倍之间，提交为硬链接）。
- 10 轮目录 + 详情 + 重复发布 + HEAD：存储读取 0 字节。
- `Range: bytes=0-31` 与 `bytes=-32`：各只读目标文件 32 字节；完整 GET 只读目标文件且恰为其长度。
- 两次完整下载：存储读取恰为所选文件各一次（文件 ID 与长度逐一等于计划）；整份记录里存储读取的入口只有 `SceneVersionService.clientDownload`（匿名下载）和 `adminDownload`（管理员下载，6 次，来自 `run_http_checks`），都经 `HttpRange.write`。
- 全部文件 AVAILABLE 时重启后端：存储内容读取 0 事件、0 字节。
- 恢复夹具：1.5 MB 文件写完整但数据库行回滚为 UPLOADING，重启后恢复为 AVAILABLE，仅该文件被读取一次，恰 1,500,000 B，其他 AVAILABLE 文件不读。

## 门禁中发现并修复的问题

- JFR 导出：全量 `--json` 栈导出会产生约 8 GB 文件并写满磁盘（清理本任务的该文件和失控导出容器后恢复）；改为在工具容器内流式过滤到存储路径，字节数用深度 1 的 JSON、堆栈用文本导出。
- 下载核对：网关日志按整秒记录，首版窗口与前一次整套读取混在一起；验证脚本改为按场景和时间窗过滤。
- 无头 Chrome 默认使用 SwiftShader 软件 WebGL。加 `--use-gl=angle --use-angle=gl-egl --ignore-gpu-blocklist` 后渲染器为 NVIDIA GeForce RTX 4060 Laptop GPU（ANGLE、OpenGL ES 3.2），`verify_4dgs.py` 同时记录两者；该选择只对这次浏览器启动生效，未改系统设置。
- 其余为验收脚本自身的问题（过滤器解析、恢复夹具前先启动后端等），后端、存储和下载工具未发现缺陷。

## 未执行

- shiku_dtwd 窗口播放：不属于本轮验收集合（0–5 秒窗口是样例假设）。
- 音频：无头 Chrome 的 AudioContext 未启动，未验证音频播放；播放证据是画面、播放器自身时间和网络来源。
- 手机/原生：Android/iOS 解码、手机网络访问、音画主观效果。
- 阶段 3/4 已记录的未执行项不变（`ar.storage.enabled=false`、Windows `msvcrt` 锁分支）。

## 用户手动验收

1. 复现：按 `.local/PLAN.md` 真包命令块依次运行 `prepare_4dgs_samples.py`、`prepare_reference_viewer.py --source /data/前端4DGS调研/local-viewer/public --origin http://127.0.0.1:18082 --output .local/4dgs-check/reference-viewer`、`prepare_4dgs_check.py prepare ... --reference-viewer .local/4dgs-check/reference-viewer`、`verify_4dgs.py`。重新运行 `prepare_reference_viewer.py` 后必须再运行 `prepare_4dgs_check.py prepare`，让网关重建以挂载新目录。
2. 用真实 Chrome 打开 `http://127.0.0.1:18082/viewer/platform.html`，选 wedding + 标准/高清，确认首帧出现、时间推进；选 dance_color + 标准，播放越过 5 秒。浏览器开发者工具网络页应只有 `127.0.0.1:18082`。
3. 手机上通过局域网访问同一网关（需另行开放监听地址）并运行 `download_scene.py` 或原生客户端，核对解码和音画。浏览器证明不等于手机证明。
