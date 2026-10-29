# 真实样包验收记录（阶段 5）

日期：UTC 2026-10-29。范围：隔离实例 `127.0.0.1:18082`（项目 `innovation-ar-resource-platform-infra-check`，PostgreSQL 17.6，Java 21 后端 Jar sha256 `fa7eb0d4…ac7cc`，由 `check_java.py --module ruoyi-admin --package --offline` 产出，63 项测试 0 失败/错误/跳过）。这是单机回环结果，不是手机或公网性能，也不是 Android/iOS 真机验收。本记录不修改 `docs/06-validation.md`；原始报告留在本地 `.local/4dgs-check/evidence/stage5/`（`verify-4dgs.json`、`run.log`、`jfr/`），不入库。

## 结论

| 项目 | 状态 |
|---|---|
| wedding、dance_color、shiku_dtwd 导入、发布、匿名目录/详情、全部文件字节与源 SHA-256 | 通过 |
| wedding 与 dance_color 的标准档完整下载（只含所选档位模型与去重后的公共文件，无高清/VR 字节） | 通过 |
| 上传、发布、列表/详情、HEAD、Range、完整下载、重启的服务端内容读取（JFR） | 通过 |
| 后台导入/继续上传在 1440 与 1024 宽的遮挡检查（`run_http_checks`，含真实 Chrome） | 通过（78 项） |
| 真实 Chrome 播放 wedding 标准/高清、dance_color 标准跨 5 秒 | 未执行：参考仓库在本机缺失（见下） |
| 手机网络访问、原生解码、音画主观效果 | 未验收，留给用户真机 |

`verify_4dgs.py` 68 项检查全部通过，4 项被阻塞，退出码 4。

## 被阻塞：参考播放器

计划中的参考目录 `/home/elma/文档/ChatGPT/前端4DGS调研/`（`local-viewer/public`、`D8TV3hLS.js`、`Drq6wweV.js`、`bundled-scenes.json`、`viewer-static/`）在本机不存在：全盘按文件名和目录名搜索 `D8TV3hLS.js`、`Drq6wweV.js`、`bundled-scenes.json`、`20261016`、`230726`、`viewer-static`、`local-viewer` 均无结果（`/home/elma/文档/ChatGPT/` 下只有无关目录 `炽变晶凯`）。按计划的应急条款，不联网重抓、不生成替身播放器，播放项标 blocked。

- 已执行：`prepare_reference_viewer.py --source '/home/elma/文档/ChatGPT/前端4DGS调研/local-viewer/public' ...` 明确失败并退出 2（`reference viewer source ... does not exist`），没有创建输出。
- 缺失路径：`/home/elma/文档/ChatGPT/前端4DGS调研/local-viewer/public/viewer/20261016/230726/js/D8TV3hLS.js`、`.../js/Drq6wweV.js`、`.../js/DfIBC3Nc.js`、`.../assets/main.D9zuS0dI.css`、`.../assets/worker-Cmdae1oK.js`、`.../assets/worker-Cn3mf7d7.js`、`.../viewer/index.html`、`.../viewer/sw.js`、`local-viewer/public/viewer-static/`，以及同构建下的 WASM。
- 适配模块和联调页已写好但没有对真实播放器运行过：目录适配 `scripts/reference_viewer/catalog-adapter.js` 用假平台客户端 API 做了行为测试（`node --test scripts/test_reference_catalog_adapter.mjs`，8 项通过：所选档位进所有设备入口且无 `highPlyPath`、逗号文件名保持编码、空目录为空、不存在的档位报错不回退、分页取全）；`prepare_reference_viewer.py`、样本描述和网关覆盖配置在结构夹具上通过 `scripts/test_prepare_reference_viewer.py` 的 10 项测试，夹具不是 4DV 播放器，不证明播放。`__S4D_BENCH__` 的时间字段名是按已有文档推断的，`verify_4dgs.py` 的 `playback()` 从未执行，找不到时间字段时会失败而非通过。
- 网关覆盖：`prepare_4dgs_check.py --reference-viewer` 生成的 Nginx 配置在夹具副本上经 `nginx -t` 和 curl 验证：`/viewer/<uuid>` 返回 `index.html`，`/viewer/platform.html`、静态资源按真实路径返回且带 COOP/COEP/CORP 头，不存在的路径 404（发现并修复：含 `{36}` 的正则需加引号；`^~ /viewer/` 会遮蔽场景 ID 正则，改为普通前缀）。

## 真实样包

样本目录只读，描述由 `prepare_4dgs_samples.py` 写入 `.local/4dgs-check/sample-descriptors/`。引用字节：wedding 10 文件 267,533,112 B；dance_color 49 文件 1,534,783,789 B；shiku_dtwd 5 文件 136,446,400 B；无关的报告 .md 未上传。导入前按“引用字节 + 下载字节 + 2 GiB”检查磁盘（本次 30 GB 可用，全部满足）。

- 每份描述的所有引用文件在版本内均 AVAILABLE，匿名详情的 `descriptor` 与上传的完全相同，文件清单大小/摘要与源一致，响应中无 storageKey、磁盘路径；所有文件经网关下载后的 SHA-256 等于源文件，带强 ETag，无 attachment 头。
- shiku_dtwd 的 0–5 秒窗口与 1.4 缩放是样例演示选择（原配置 timeOption 为空），不是重建出的生产时间契约。
- 下载：`download_scene.py` 对 wedding/standard_quality 取 6 个文件 68,553,739 B，对 dance_color/standard_quality 取 19 个文件 354,532,956 B；负载目录恰为所选档位加公共文件；无 high_quality/vr_foreground 文件落盘；网关日志中 GET 的文件 ID 集合等于计划集合且全部 200，发送字节等于所选模型 + 去重公共文件之和。

## 耗时（本机回环，首轮；括号为重复）

| 场景 | 预哈希 | 创建版本 | 全部上传（含预哈希） | 发布（重复） | 目录 | 详情 | 整套文件读取 |
|---|---|---|---|---|---|---|---|
| wedding | 0.134 s | 18 ms | 0.68 s | 8.0 ms（4.3 ms） | 4.2 ms（2.7 ms） | 3.3 ms（2.2 ms） | 267.5 MB / 0.31 s |
| dance_color | 0.754 s | 20 ms | 3.55 s | 7.7 ms（3.2 ms） | 3.4 ms（2.5 ms） | 2.5 ms（2.2 ms） | 1534.8 MB / 1.70 s |
| shiku_dtwd | 0.067 s | 14 ms | 0.34 s | 8.6 ms（3.0 ms） | 3.2 ms（1.7 ms） | 1.9 ms（1.9 ms） | 136.4 MB / 0.15 s |

完整下载：wedding 标准档 0.23 s，dance_color 标准档 0.73 s（含逐文件校验）。文件处于系统页缓存，不能代表磁盘或网络吞吐。

## JFR 文件读写证据

测试后端以 `JAVA_TOOL_OPTIONS=-XX:StartFlightRecording=settings=<最小 JFC>,dumponexit=true` 启动，JFC 只含 `jdk.FileRead/FileWrite`（阈值 0、含堆栈），不启用环境变量/属性事件；健康检查 JVM 清除该变量。正常停止后 `docker cp` 取出记录，在 Java 21 工具镜像里用 `jfr print` 导出并只统计 `/data/artifacts/staging`、`/committed` 路径（Jar、日志、配置读取不计）。第一次后端生命周期共 468,790 个存储事件（含 36,570 次读取）。

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

- 参考播放器真实播放（wedding 标准/高清、dance_color 标准跨 5 秒、shiku_dtwd 窗口）：阻塞，原因见上。
- 手机/原生：Android/iOS 解码、手机网络访问、音画主观效果。
- 阶段 3/4 已记录的未执行项不变（`ar.storage.enabled=false`、Windows `msvcrt` 锁分支）。

## 用户手动验收

1. 把参考仓库的 `local-viewer/public` 放到 `/home/elma/文档/ChatGPT/前端4DGS调研/local-viewer/public`（或改 `--source`），在工作树运行 `prepare_reference_viewer.py`，以 `prepare_4dgs_check.py prepare --reference-viewer <输出目录>` 重启隔离实例，再运行 `verify_4dgs.py`（命令见任务记录）。
2. 用真实 Chrome 打开 `http://127.0.0.1:18082/viewer/platform.html`，选 wedding + 标准/高清，确认首帧出现、时间推进；选 dance_color + 标准，播放越过 5 秒。浏览器开发者工具网络页应只有 `127.0.0.1:18082`。
3. 手机上通过局域网访问同一网关（需另行开放监听地址）并运行 `download_scene.py` 或原生客户端，核对解码和音画。浏览器证明不等于手机证明。
