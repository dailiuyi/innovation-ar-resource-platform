# 4DGS 成品管理与客户端分发重构

状态：进行中。负责人：Main。更新时间：UTC 2026-10-29。

## 目标与验收

一个场景对应一个独立 4DGS 重建成品；同一内容版本同时包含多个模型档位和公共配置、媒体文件。删除场景地址、经纬度和坐标系；保留 Spring Boot、Vue、PostgreSQL、本地 ArtifactStorage 和后台账号。内部 Demo 客户端最终匿名读取已发布资源，支持按段在线加载和按档位完整下载。旧业务数据不保留，干净切换，不做旧草稿迁移或旧 API 别名。

- 完整分阶段计划：本地工作树 `.local/PLAN.md`（不入库）。五阶段按顺序交付：1 删除地点模型和固定成品描述、2 合并正常入库校验、3 成品版本业务与后台调用方切换、4 匿名读取与完整下载参考工具、5 真实样包与 4DV 参考客户端闭环。
- 范围外：推送、合并、日常 Compose/数据库/LAN 部署、Android/iOS 真机验收。
- 分支 `codex/4dgs-resource-refactor`，独立工作树 `.local/worktrees/4dgs-resource-refactor`。

## 进度与决定

- [x] 阶段 1：删除地点模型，新增 `resource.json` v1 描述校验（提交 5f090d6）。隔离 PostgreSQL 17.6 空库与 V013 升级库门禁通过（`.local/stage1-gate/report.json`，40 项）。
- [x] 阶段 2：存储接口收敛为 `store`/`recover`（提交 530c877）。存储门禁通过（`.local/stage2-gate`/`.local/stage2_gate.py`，44 项）。
- [x] 阶段 3：成品版本业务、后台与调用方切换（后端 f2b09b1、前端 31ccec3、工具 92786e3，集成修复 f519283、faeafaa、fbe07da）。后端门禁（V015 空库/升级、HTTP 生命周期、删除失败 503 与启动恢复）58 项通过；经隔离网关的集成门禁、真实 Chrome 后台操作见下。`scripts/test_scene_package.mjs` 与 `agent_check.py --profile frontend` 的全量结果由主代理统一运行并记录。
- [x] 阶段 4：匿名成品读取、Range 补全与完整下载参考工具（提交 69dc9b0、8ee4725）。`ClientSceneController`/`ClientSceneService`、`SecurityConfig` 逐路由放行、网关 `/api/v1/client/`、后缀 Range 与 `HttpRangeTest`、`scripts/download_scene.py`、`artifact_transfer.py` 控制目录/边写边算/OS 锁。门禁 73 项通过，见下。
- [x] 阶段 5：真实样包与参考客户端闭环（提交 5e7d0e6 及后续）；三份真实样包导入/发布/匿名读取/完整下载/JFR 证据通过，真实 Chrome 对参考播放器（构建 20261016/230726）播放 wedding 标准、wedding 高清、dance_color 标准跨 5 秒通过，`verify_4dgs.py` 103 项通过、0 阻塞、退出码 0。手机/原生、音频和 shiku_dtwd 窗口未验收。验收记录见 [真实样包验收记录](../../20-4dgs-sample-validation.md)。

已确认决定：

- V015 迁移是破坏性清洁切换，只在隔离验收库执行，日常库另需授权。
- 当前 OpenAPI 描述保留或新增的管理接口和阶段 4 的三个匿名客户端只读操作（`listClientScenes`、`getClientScene`、`downloadClientFile`/`headClientFile`，无 security）。`runtime-manifest` 作为历史静态资料保留，不再由生成器生成。
- `scripts/verify_export_path_migration.py` 只验证已完成的 V013 历史行为，保留为独立历史脚本，不再是当前门禁。
- Linux 真实验收走 `scripts/prepare_4dgs_check.py` 启动的固定隔离 Compose 实例，不使用 Windows 专用 ingestion profile。

未解决问题：无。

## 验证证据

阶段 3 集成门禁（隔离实例 `127.0.0.1:18082`，项目 `innovation-ar-resource-platform-infra-check`，已测 Jar 由 `check_java.py --module ruoyi-admin --package` 产出：50 项测试，0 失败/错误/跳过；前端 dist 由 `frontend_control.py build` 构建；全部流量经 Nginx 网关）：

- `scripts/verify_ingestion.py` 外部模式（含 Chrome 1440/1024）78 项通过，含 21 MiB 文件经网关上传与物理删除；报告 `.local/4dgs-check/evidence/validation-ingestion.json`。
- 网关行门禁 `.local/stage3_gateway_gate.py` 20 项通过：上传中断后只有该文件 FAILED、同一 versionId 继续上传且已完成文件 attempts 不变、整版删除存储失败 503 后重试成功且保留回执、遗留删除意图经后端重启完成且字节不恢复、被删请求键迟到创建返回 410。报告 `.local/4dgs-check/evidence/stage3-gateway-gate.json`。
- 真实 Chrome（`/opt/google/chrome/chrome`）后台门禁 `.local/stage3_ui_gate.py` 19 项通过：1440x1000 与 1024 宽下导入目录、中断后继续、发布 V1、导入并替换发布 V2、删除非发布 V1，无遮挡/裁切/重叠/横向溢出，21 MiB 文件经网关成功；截图在 `.local/4dgs-check/evidence/ui-*.png`。
- 门禁发现并修复的缺陷：1024 宽版本列表固定列过宽导致操作列被裁切、发布卡片依赖接口未提供的文件数/大小（f519283）；`prepare_4dgs_check.py` 重复运行时容器 ID 为 bytes 导致所有权检查失败（faeafaa）；验证脚本将 V2 发布审计中的 `fromVersionId` 误计入 V1，并在滚动区外误判按钮遮挡（fbe07da）。
- 已清理本任务阶段 1/2/3 后端门禁遗留的已退出容器与对应网络（仅 `-stage1-`/`-stage2-`/`-s3be-` 后缀）。

阶段 4 门禁（同一隔离实例，新 Jar sha256 `fdd6dc6c…26d9` 由 `check_java.py --module ruoyi-admin --package --offline` 产出：63 项测试，0 失败/错误/跳过；前端未改动，复用阶段 3 构建的 dist；网关配置为含 `/api/v1/client/` 的当前 `deploy/nginx.conf`）。提交 69dc9b0（后端、网关、契约、文档）与 8ee4725（下载工具与 OS 锁）：

- Java：`ruoyi-ar` 57 项（含新增 `HttpRangeTest` 10 项、`ClientSceneServiceTest`、版本创建对 `%`/`;` 文件名的 400 边界）、`ruoyi-framework` 6 项，均 0 失败/错误/跳过。
- Python（无需服务）：`scripts/test_artifact_transfer.py` 22 项（新增 OS 锁、残留锁文件不阻塞、控制目录、边写边算只哈希一次/续传校验一次、忽略 Range 回 200 截断）与 `scripts/test_download_scene.py` 14 项（假客户端 API：只下选定档位、杀/断后续传、已完成文件无再次 GET、损坏不就绪、409 不混版本、未知档位、非空无状态目录拒绝等）通过。`verify_design.py` 418 项通过（含三条匿名路由恰好只读、无 security、文件路由 200/206/416/409）；`agent_check.py --profile quick` 通过。
- 隔离实例门禁 `.local/stage4_gate.py` 73 项全部通过（经 Nginx 网关，合成包，无 Authorization；报告 `.local/4dgs-check/evidence/stage4-gate.json`）：
  - 匿名读写：未发布场景目录/详情/文件 404；发布后目录字段、详情（descriptor、去重文件、contentType、无 storageKey/磁盘路径）、全部文件 GET 精确字节与强 ETag、无 attachment、HEAD 空 body 完整长度；错误 basename/fileId/场景 404；停用/逻辑删除后全部读取 404；匿名 POST/PUT/DELETE、`/client` 其他路径、`HEAD /client/scenes`、全部管理接口均为 401/403（断言接受二者，原管理员登录和权限不变）；`/artifacts` 等内部路径 404。
  - Range（700 KB 合成模型）：`0-31`、`32-`、`-32` 的 206 与精确字节/Content-Range；越界与超大数字 416（`bytes */size`，不 500）；`-0` 416；If-Range 错回 200、对则 206；多段/无效范围回 200；后缀超长回整个文件 206；HEAD（含带 Range）空 body 且长度完整。
  - `download_scene.py`（经可注入故障的回环代理）：首个文件传输中途 SIGKILL，状态文件已先于任何字节建立、无 ready，残留空锁文件，同命令继续（OS 锁不卡）并以 `Range: bytes=<part 大小>-` 续传；首个文件完成后切断第二个文件，重跑无已完成文件的再次 GET，仅被切断文件 Range 续传，ready 仅在全部完成后出现；服务端忽略 Range 回 200 时截断重写且字节精确；损坏传输返回校验错误、无 ready、无该文件、`.part` 被删，重跑只重下该文件；中途发布 V2 后旧 V1 请求 409、工具退出码 3 且只有一次被拒请求、V1 目录原样未就绪，新运行取 V2 描述写入新版本目录、无 V1/V2 混合；已开始的 V1 字节流（40 MiB）在 V2 发布后仍完整，其后的 V1 请求 409；standard 与 high 档位下载的请求文件集合正好是各自模型加去重后的共用文件，不含另一档位字节，`ready.json` 总字节等于该集合大小。
  - 重复读取：10 轮目录+详情+两个 HEAD（共 40 HEAD + 10 目录 + 10 详情）使后端 JVM 的进程 `rchar` 仅增 82 KB，32 字节 Range 仅增 2.4 KB，而一次完整 12 MiB GET 增 12.6 MB，说明该方法可区分。这是进程级粗检，不是计划要求的 JFR 文件读取证据，JFR 留到阶段 5 `verify_4dgs.py`。
  - 耗时（本机回环，非手机或公网性能）：首次目录 2.4 ms、详情 1.5 ms；杀进程后续传 0.13 s。
- 门禁与实现中确认的行为：Spring Security 防火墙会拒绝路径中编码的 `%`（`%25`）和 `;`（`%3B`）（实测匿名得 401，`#`、`[`、`]` 可达控制器），因此版本创建对这类文件名直接返回 400，避免已入库文件客户端无法读取。
- 未执行：`ar.storage.enabled=false` 时路由不注册（只有一个启用存储的实例，由 `@ConditionalOnProperty` 保证，未单独实例验证）；Windows `msvcrt` 锁分支未在 Windows 运行（仅 Linux `fcntl` 实测）；JFR 与真实样包（阶段 5）。
- 门禁驱动自身的修正（非产品缺陷）：Range 行的“后缀超长”原用例误取小于文件的后缀；`urllib` 的 `read(64 KiB)` 会凑满整块才写 `.part`，因此首个文件改为 300 KB 并在 200 KB 处停顿。门禁没有发现后端或工具缺陷。

结果：阶段 1-4 门禁通过；浏览器证明不等于 Android/iOS 真机验收。

阶段 5（提交 5e7d0e6 与随后的文档提交；新 Jar sha256 `fa7eb0d4…ac7cc`，63 项测试 0 失败/错误/跳过；实例由 `prepare_4dgs_check.py prepare` 重启并给测试后端开 JFR）：

- `scripts/prepare_4dgs_samples.py`、`import_scene_package.py`、`prepare_reference_viewer.py`（含 `scripts/reference_viewer/` 适配模块、联调页和入口页模板）、`verify_4dgs.py` 已实现；`prepare_4dgs_check.py` 的参考播放器覆盖修复（正则加引号、前缀不遮蔽场景 ID 路由、跨源隔离头），新增 JFR 配置，并在对真实播放器核对后改为：网关带 CSP 响应头、每次 prepare 重建网关容器。永久回归：`scripts/test_prepare_reference_viewer.py`（11 项）、`scripts/test_verify_4dgs.py`（6 项）、`node --test scripts/test_reference_catalog_adapter.mjs`（8 项），均已在本轮运行通过。
- 第一次运行 `verify_4dgs.py`（无参考播放器）：68 项通过、4 项阻塞、退出码 4；其覆盖项在对真实播放器核对后的完整运行（计划命令块，`--source /data/前端4DGS调研/local-viewer/public`，`--viewer-root .local/4dgs-check/reference-viewer`）中重新执行：103 项通过、0 阻塞、退出码 0。覆盖：`run_http_checks` 78 项（含 1440/1024 宽真实 Chrome）；三份样包导入/发布/匿名读取与逐文件 SHA-256；Range/HEAD；wedding 与 dance_color 标准档完整下载（无高清/VR 字节）；JFR 证明上传、列表、详情、发布幂等、HEAD、Range、重启不读取存储内容，Range 32 字节只读 32 字节，恢复夹具只读该文件一次；真实 Chrome 播放三项（GPU 渲染器 RTX 4060，所有到达网络的请求只发往 127.0.0.1:18082，外部统计主机被 CSP 拦下未发出，播放器时间前进 ≥5 s，dance_color 越过 5 s 分段，标准/高清请求的模型文件互不相交）。耗时与明细见验收记录，截图与逐次请求在 `.local/4dgs-check/evidence/stage5/playback/`。
- 导入 CLI 实测：同命令重跑跳过全部 AVAILABLE；对 dance_color 导入中途 `SIGKILL` 后（11 个文件已完成、1 个中断），同命令继续，仅中断文件 attempts 为 2，其余不重传，最终 49 文件 AVAILABLE；错误的包根明确拒绝。该临时场景和版本已删除。
- 对真实播放器核对时修正的上一版假设：`/data/前端4DGS调研/local-viewer/public` 没有 `viewer/index.html`、`viewer/sw.js`（也没有 manifest.json、logo 和字体），上游当前页面已是更新构建，故入口页由模板写出、不装 Service Worker（`/viewer/sw.js`、`/viewer-static/Gineso-ConMed.png` 404 属来源缺文件，验收脚本逐一列为允许项）；`__S4D_BENCH__` 必须调用 `snapshot()` 取状态（对象本身序列化为空）；CSP 需要 `'unsafe-eval'` 否则解码阶段 `window is not defined`、停在 0%；主包的 Sentry/PostHog 请求被 CSP 拦下。无头 Chrome 默认软件渲染（SwiftShader），GPU 参数下为 RTX 4060，两者均已记录。详见验收记录。
- 发现并修复：JFR 全量 JSON 导出写满磁盘（改为容器内过滤）；网关日志整秒窗口混入前序流量（改为按场景和时间窗过滤）；网关覆盖配置的 `{36}` 正则未加引号导致 `nginx -t` 失败、`^~ /viewer/` 遮蔽场景 ID 路由。后端、存储、下载工具未发现缺陷。

## 交接与恢复

工作模式与当前阶段：普通本地开发，阶段 5 完成（桌面 Chrome 范围）。用户已授权：本地独立分支与隔离验收；不推送、不合并、不更新日常实例。

下一步：手机/原生部分由用户真机验收（解码、手机网络访问、音画主观效果；音频播放和 shiku_dtwd 窗口也未验证）。复现命令见 `.local/PLAN.md` 真包命令块；重新运行 `prepare_reference_viewer.py` 后需再运行 `prepare_4dgs_check.py prepare` 让网关挂载新目录。库中保留阶段 3/4/5 门禁留下的合成场景与 wedding、dance_color、shiku_dtwd 三个真实场景（当前发布版本）。

本任务可能保留的运行资源：固定项目 `innovation-ar-resource-platform-infra-check` 的容器和卷；用 `scripts/prepare_4dgs_check.py stop --report-dir <目录>` 停止，不执行 `down -v`。

## 完成记录

完成时填写。
