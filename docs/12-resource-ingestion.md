# 资源入库闭环

2026-11-06 本地源码按管理员单场景单模型简化；不代表日常服务已部署。一个场景直接对应一套固定文件，换模型新建场景。名称和说明可编辑，文件上传校验完成后自动对外可用，启用/停用控制客户端访问，没有版本列表、独立发布或模型替换流程。

## 数据与状态

应用仅加载 `backend/ruoyi-admin/src/main/resources/db/demo` 下的 Flyway 迁移。V001–V017 保留原样；V018 将旧版本映射为独立场景，文件 UUID 与存储键不变，不搬运模型字节。旧当前发布模型保留原场景身份，其他模型停用保存；完整迁移规则及实测见[验证记录](06-validation.md)。升级任何真实数据库前须备份并获得单独授权。

| 数据 | 用途 |
|---|---|
| `ar_scene` | 名称、说明、启停、并发修订号、创建请求键和删除信息 |
| `ar_scene_file` | 直接关联场景的固定清单，保存相对路径、预期大小/SHA256、上传状态及验证结果 |
| 场景级删除记录 | 删除意图、失败原因和最小幂等回执 |
| `ar_audit` | 操作人、动作、对象和变更；历史版本动作保留为历史证据 |
| `ArtifactStorage` | 私有本地文件正文，不操作业务表 |

文件状态为 `PENDING`、`UPLOADING`、`AVAILABLE`、`FAILED`。只有服务端接收时核验大小、SHA256 并无覆盖提交后才记为 `AVAILABLE`。场景 `uploadStatus` 汇总为 `PENDING/UPLOADING/FAILED/READY`，删除处理中为 `DELETING/DELETE_FAILED`。

**客户端可见条件：启用、未删除/未进入删除、清单非空且所有文件 AVAILABLE。** 上传和恢复均不自动修改启停状态。管理员在上传期间停用，最后一个文件完成后仍不可公开。

## 固定文件清单

- 新建时一次登记目录或多个文件的完整清单（相对路径、字节数、SHA256），不能追加或替换；换模型使用新的场景 ID。
- 目录去掉所选顶层目录名，保留子目录；多文件以各自文件名登记。拒绝空选择、零字节、重复及大小写冲突、越界和非法路径；摘要或大小有误的文件上传拒绝。
- JSON 和 ZIP 均原样保存，ZIP 不解压。平台不解释 `resource.json` 或文件用途，档位、分段和加载顺序由已有播放器决定。
- 名称、说明和启停可编辑，内部修订号防止并发覆盖；它不是内容版本，不在管理列表展示。

## 管理接口

前缀 `/api/v1`，网关为 `/prod-api/api/v1`；管理员身份来自登录，不由请求体指定。完整字段见[生成 OpenAPI](../contracts/openapi.yaml)。

| 方法与路径 | 用途 |
|---|---|
| GET `/scenes/config` | 单文件和单场景限制：`maxBytes/sceneMaxFiles/sceneMaxBytes` |
| POST `/scenes` | `{requestKey,name,description,files}` 原子创建场景及固定清单；首次 201，相同请求重试 200 |
| GET `/scenes`、`/scenes/{sceneId}` | 列表汇总、详情与文件状态 |
| PUT `/scenes/{sceneId}` | `{name,description,expectedVersion}` 修改信息 |
| PUT `/scenes/{sceneId}/enabled` | `{enabled,expectedVersion,reason}` 启停并审计 |
| DELETE `/scenes/{sceneId}?expectedVersion=N` | 清理场景全部文件；成功 204，失败可重试 |
| GET `/scenes/{sceneId}/files/{fileId}` | 单文件结果核对 |
| PUT `/scenes/{sceneId}/files/{fileId}/content` | 原始字节流上传与校验 |
| GET / HEAD `/scenes/{sceneId}/files/{fileId}/content` | 管理员读取已完成文件，支持 Range |

业务错误为真实 HTTP 状态与 `code/message/traceId`，文件 416 无正文。重复创建的请求键对应不同信息/清单为 409，已删除或正在删除为 410；不恢复旧场景。

## 上传、访问与恢复

1. 管理页在一个详情面板填写名称、说明并选择文件，分块计算摘要，然后创建场景；名称草稿按账号保存。上传工具也使用相同接口。
2. 网页固定三路上传不同文件；单文件失败不阻断其余文件。发送进度与已确认入库数分别显示；结果不确定先查询单文件状态。
3. 已 `AVAILABLE` 文件不覆盖、不重传；`UPLOADING` 先核对，`PENDING/FAILED` 重传原文件。刷新页面后重新选择原始完整集合，路径、大小、摘要一致才续做。当前是按文件恢复，没有分片上传协议。
4. 服务端按“短事务登记 → 事务外文件 IO → 短事务确认并审计”处理。所有文件就绪后可见条件自然成立，不需要网页再请求发布；关闭网页不会留下“文件已入库但未发布”的步骤。
5. 停用后客户端列表隐藏，后续详情/文件请求 404；管理员仍可查看。已开始的文件流允许结束，本地已有文件无法通过停用撤回。
6. 删除先提交意图并停止公开，再删除各文件所有存储阶段，最后删文件行并完成回执。存储 IO 失败返回 503，显示删除失败；重试或启动恢复继续清理。活动上传期间删除 409，删除不截断已开始的下载。
7. 启动先续做删除，再盘点未完成文件。有完整遗留且验证通过则补记可用；中断且无完整字节的上传记失败。已确认文件不全量重算摘要，系统恢复记审计。

## 客户端与完整下载

匿名路由仅为列表 GET、详情 GET、文件 GET/HEAD。其余写请求不开放；管理员 Token 不发送到匿名读取接口。

| 路径 | 返回 |
|---|---|
| `/api/v1/client/scenes` | `{items:[{id,name}],total}` |
| `/api/v1/client/scenes/{sceneId}` | `{sceneId,name,files,fileCount,totalBytes}` |
| `/api/v1/client/scenes/{sceneId}/files/{fileId}/content/{fileName}` | 固定文件 GET/HEAD，使用详情中的 `downloadPath` |

文件大小、SHA256、MIME 和相对路径在清单返回。Range/If-Range/200/206/416 与下载端校验规则见[客户端接口](21-client-api.md)。文件缺失或长度不符为 409，不再有“版本替换”错误。响应仍为 `no-store, no-transform`，尚未接 CDN。

`scripts/download_scene.py --base-url URL --scene-id UUID --output DIR` 将全部文件下载至 `<DIR>/<sceneId>/payload/`，控制区和 `ready.json` 与正文分开；完整性通过才标记就绪。重复执行可续传，错误场景或清单不复用本地任务。已有播放器应消费详情文件清单；用户已确认有播放器，实际代码位置和播放接入证据另行核对。

## 历史记录（旧多版本基线）


以下带日期的检查与部署条目是历史记录，不代表本轮或当前日常实例已重新验收；部署状态与源端数据保护要求以 [基础设施手册](10-local-infrastructure.md) 为主。

2026-10-29 验证：`check_java.py --module ruoyi-admin --package` 在 JDK 21 容器执行 50 项测试，零失败、错误、跳过；frontend profile 通过；`verify_scene_list_ui.py` 的合成接口浏览器检查 89 项通过；隔离实例的 `verify_ingestion.py` HTTP/浏览器检查 81 项通过，包含旧分段锁同桶的不同文件并发、同文件在途 409、完成后幂等，以及目录导入 READY 和发布。证据在本地 `.local/harness/upload-ui`、`.local/harness/upload-lock-before`、`.local/harness/upload-lock-after`，不代表日常实例验收或真实服务端取消证明。

已知收尾限制：结果未确认的文件后来全部入库时，先点“刷新状态”会使版本成为 READY，并隐藏“继续上传”；客户端历史异常清单仍保留。当前浏览器检查直接点击继续，没有覆盖这一步刷新。此 P2 问题未随三路并发改动修复，不把现有检查解释为该路径已通过。

2026-10-29 日常发布（用户授权提交、合并、部署和推送）：代码提交 `69f8904` 已快进合并到 `main`。使用已验收的 Jar 与 dist 打包 runtime 镜像，只重建 backend/gateway，保留 PostgreSQL、Redis 和现有参考播放器挂载；未改变公网中继或执行新迁移。

- 部署前 `pg_dump -Fc` 备份到 `.local/releases/parallel-upload-20261029/daily-before-parallel-upload.dump`（0600，`pg_restore --list` 可读取 129 项）。`before-parallel-upload-20261029` 镜像已于 2026-10-29 按用户要求删除，不能再靠旧标签回退。
- 部署后 backend/gateway 均 healthy，Jar SHA256 为 `03ccb4e3cbdf095eb4636aae7ecfdc8c4c4269b3d7c328ecfa3fa49ef58de6d9`，网关全部 320 个文件与已测试 dist 一致。库中场景 4、版本 3、文件 134、发布指针 3、审计 282、账号 3，与部署前相同，Flyway 仍为 017。
- LAN `http://192.168.0.12:18081` 和公网 `https://4dgs.elma-gohan.xyz` 的 healthz、captchaImage、匿名目录/详情均返回 200，Range 返回 206 和 16 字节；下发的 `VersionPanel-CfGxw4dG.js` 与本地构建逐字节一致。
- 真实 Chrome 访问后台会跳到登录页；当前没有可用的已登录浏览器，未在日常库执行登录上传，没有启用 bootstrap 或生成会话。隔离实例的上传证据不能替代日常账号点击验收。

### 上传反馈修复（2026-10-29）

- 待导入版本说明使用独立响应式字段，不再把输入绑定到浅层引用的普通嵌套属性。输入、失焦后保留和创建请求中的说明一起验收。
- 准备校验阶段按整个目录累计已读取字节显示百分比，Worker 逐个 2 MiB 块报告实际读取字节；更换文件不归零，SHA256 算法和分块大小不变。传输阶段另标“传输进度”，显示字节数与“已入库”计数；发送完成不等于服务端校验入库。
- 每次 PUT 或既有单文件核对返回实际记录后，即时更新对应文件、详情计数和版本行；不等整轮结束，也不新增全量轮询。网络错误不会被本地直接写成服务端 FAILED。
- `verify_scene_list_ui.py --channel chrome --report-dir .local/harness/upload-panel-feedback` 的真实浏览器加合成 HTTP 检查 99 项通过。哈希使用真实 Worker 与不等大小文件，逐块核对目录字节进度，并与文件实际 SHA256 对照；持有其余请求时验证首个已入库文件已经出现在表格。截图保存在同目录 `scene-list-ui/`。这证明本地页面行为，不替代日常账号点击导入。取消检查仍会在 Playwright 退出时打印此前已有的三个 CancelledError，脚本退出码为 0，未捕获或屏蔽。
- `.local/ingestion-venv/bin/python scripts/agent_check.py --profile frontend` 通过，包含 14 项目录/调度测试、契约/链接门禁和本次重新构建的生产前端；报告 `.local/harness/20261029T115939Z-hj67ggr7/report.json`。未构建或改动已有脏工作区中的 Java 文件。
- 2026-10-29 日常发布：提交 `945d2fa` 已快进合并到 `main` 并推送 `origin/main`。只重建 gateway，backend 容器 `82f93f44c48b`、PostgreSQL `e4adcbb490e8`、Redis `1881b409f8cc` 未重建，参考播放器挂载保留。`before-upload-feedback-20261029` 及更早的 `before-v017`、`pre-4dgs` 应用镜像已删除；当前只保留正在运行的 `infra-v1`。回退需用对应 Git 提交重新构建，不能再改标签。
- 新网关 `99a2ae553ce0` healthy，镜像修订号即 `945d2fa`。容器内 320 个前端文件与本次 frontend profile 复用的 dist 一致。LAN `http://192.168.0.12:18081` 与公网 `https://4dgs.elma-gohan.xyz` 均下发 `VersionPanel-BXy_m6gc.js`，sha256 `d025068f30815addfb6f12fc7f757d18a948581a1cfab9b48b5ef356f0893aba`，包含“准备校验：已读取”和“传输进度：”。
- 未做数据库迁移，也未在日常账号上点击导入。审查指出的两处显示限制仍在：`size()` 舍入后文案可能与百分比不完全一致；普通 HTTP 失败要等整轮结束才写入文件行。

### 多网页并发策略

| 情况 | 当前行为 |
|---|---|
| 多个页面同时上传 | 每个页面独立最多三路；没有跨页面、跨账号或全站并发总上限，三个页面理论上可同时发出九个 PUT |
| 多个页面分别导入同一目录 | 各自产生新的 requestKey，创建不同版本，不按文件内容全局去重 |
| 多个页面续传同一版本 | 每轮各自获取状态快照，跳过 AVAILABLE/UPLOADING，只发送 FAILED/PENDING；快照之后仍可能争用同一文件，该文件在途请求由服务端立即返回 409，不排队或自动重试 |
| 一个页面完成文件，另一个页面仍打开 | 没有跨页面消息或后台全量轮询；只有本页请求/核对确认的记录会即时更新，其余变化需手动刷新 |

上述文件互斥是单 Spring Boot 进程内的活动文件集合，不是集群限流；多个页面会共同消耗本机网络、磁盘和计算资源。本轮只修复反馈显示，未新增全站调度或改变 409 策略。

## 配置与验证

- `AR_STORAGE_ENABLED=true` 开启场景文件接口，`AR_STORAGE_ROOT` 为私有根目录。
- `AR_STORAGE_MAX_BYTES` 限制单文件；`AR_STORAGE_SCENE_MAX_FILES` 与 `AR_STORAGE_SCENE_MAX_BYTES` 限制场景，替换旧版本命名配置，部署时显式迁移。
- Nginx 对 `/prod-api/api/v1/scenes/{sceneId}/files/{fileId}/content` 关闭请求/响应缓冲和网关字节限制，其他接口保持原限制；私有目录不公开。
- Java 由 `scripts/check_java.py --module ruoyi-admin --package` 检查，前端由 `scripts/agent_check.py --profile frontend` 检查。实际 HTTP/浏览器入库流程使用[隔离验收](13-harness.md)，不得操作日常实例。
- Python 上传参考 `scripts/import_scene_package.py`：首次以名称、说明和包根创建场景，或以 `--scene-id` 继续已有上传；状态文件放包外，避免把状态本身上传。参数以 `--help` 为准。
- 真实播放须使用已有播放器和真实产物验证；合成字节、SHA256 和 HTTP 200 不证明渲染。现阶段仍为单 Spring Boot 实例及本地存储；对象存储、CDN、用户审核和云端 GPU 不属于本轮。

旧浏览器播放器和旧描述接口验收见[历史样包记录](20-4dgs-sample-validation.md)。本次的测试、运行命令与未验证项只记录于[验证记录](06-validation.md)，不沿用旧测试数字。
