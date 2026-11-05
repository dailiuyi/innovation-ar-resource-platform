# 资源入库闭环

一个场景对应一个独立的 4DGS 重建成品。管理员私有入库流程：选择场景 → 导入资源目录或多个文件创建内容版本 → 逐文件上传并校验 → 正式存储确认 → 发布为场景当前版本 → 需要时整版删除。文件“可用”仅表示已可靠入库；匿名客户端只读取当前发布版本（见下文“匿名客户端读取与完整下载”）。

## 数据与状态

实际迁移随应用 Flyway 执行：`V014__remove_scene_geography.sql` 删除地址、经纬度和坐标系；`V015__scene_product_versions.sql` 是**破坏性清洁切换**，明确清空旧成品业务记录（`ar_audit`、旧草稿/文件/ZIP 表和 `ar_scene`）后删除旧表，不涉及任何 `sys_*` 账号和菜单表，也不能对日常库自动执行；`V017__remove_version_descriptor.sql` 删除 `ar_scene_version.descriptor` 列（该列数据不可恢复，执行前须备份并获批准；日常库 18081 已于 2026-10-29 经授权备份后执行，见 [验证记录](06-validation.md)）。根目录 `database/migrations` 仍是历史候选设计。

- `ar_scene`：只保留名称、启停、修订号及时间/删除信息，加当前发布指针 `published_version_id`、`published_at`、`published_by_*`（复合外键保证不跨场景发布）。
- `ar_scene_version`：文件清单与内容固定的版本，含场景内版本号、`request_key`、可编辑说明和说明修订号。同场景同请求键幂等。
- `ar_version_file`：每文件相对路径、预期大小/SHA256、服务端 UUID 加 `.bin` 的存储标识、状态、已验证大小/摘要、尝试次数、失败原因、创建人和最后操作人。同版本相对路径唯一。
- `ar_version_deletion`：整版删除意图、失败原因和最小幂等回执，不向已删除版本保留外键，也不复制文件内容。
- 文件内容只写入 `ArtifactStorage`，不进数据库。相对路径只用于清单和还原，不能指定服务器落盘路径。

| 文件状态 | 含义 |
|---|---|
| PENDING | 元数据已登记，尚未确认上传 |
| UPLOADING | 正在接收或校验，不能当作成功 |
| AVAILABLE | 接收时大小和 SHA256 校验通过并已无覆盖提交为正式文件，数据库确认可用 |
| FAILED | 校验、传输、存储或重启核对失败，原因可查，可用原文件重试 |

版本 `uploadStatus` 读时由文件状态推导，不另存状态机：未完成删除为 `DELETING`/`DELETE_FAILED`，否则有 `UPLOADING` 为 `UPLOADING`，有 `FAILED` 为 `FAILED`，全部 `AVAILABLE` 为 `READY`，其余 `PENDING`。`AVAILABLE` 的数据库约束要求已验证大小/摘要与登记值相等且无失败原因。

## 版本内容：固定文件清单

一个内容版本就是一次选择的固定文件清单（相对路径、字节数、SHA256）加可编辑说明 `description`。平台不保存或解释结构化 `descriptor` 字段（2026-10-29 删除）：档位、分段、时间、变换和媒体用途由 Unity 客户端按相对路径决定，服务端不解释文件用途、不解码模型。JSON（包括名为 `resource.json` 的普通文件）仍可上传下载，不获得特殊语义。

- “导入资源目录”登记目录下每个文件，去掉所选顶层目录名并保留子目录；“导入文件”允许选择任意类型的一个或多个文件，以文件名作为相对路径，一次选择创建一个版本。空选择、零字节文件和规范化后重名的文件拒绝。
- ZIP 与其他文件一样原样上传，不扫描包内清单、不在服务端解压。Unity 下载并校验文件后自行解压；平台清单只登记 ZIP 本身，不包含包内文件。本入口及续传支持于 2026-10-30，决定依据为用户确认的多文件/ZIP 导入需求。
- 路径必须为相对路径，不含 `..` 或绝对路径，已是 NFC 规范形式，文件名不含 `%`/`;`，大小写不敏感重复拒绝，并有长度限制；违反返回 400 并指出路径。文件大小或数量超配置返回 413。

## 接口

管理接口位于 `/api/v1`，类级 `ar_admin`，经网关为 `/prod-api/api/v1`。完整输入输出见生成的 [OpenAPI](../contracts/openapi.yaml)（`4DGS Scene Resource API` 0.5.0，仅描述当前实际接口）。创建版本 body 为 `{requestKey, description, files}`。

| 方法与路径 | 用途 |
|---|---|
| GET `/scene-versions/config` | 单文件、单版本文件数和字节上限 |
| GET / POST `/scenes/{sceneId}/versions` | 分页查询（含 `sceneLockVersion`、`published`）/ 创建版本 |
| GET / PUT `/scene-versions/{versionId}` | 版本信息和完整文件清单 / 仅编辑说明（`expectedVersion`） |
| DELETE `/scene-versions/{versionId}` | 整版物理删除；当前发布版本 409 |
| POST `/scene-versions/{versionId}/publish` | 发布，body `expectedSceneVersion` |
| GET `/scene-versions/{versionId}/files/{fileId}` | 单文件状态，用于结果未确认后核对 |
| PUT `/scene-versions/{versionId}/files/{fileId}/content` | `application/octet-stream` 原始文件流 |
| GET / HEAD `/scene-versions/{versionId}/files/{fileId}/content` | 管理员读取已完成文件，支持强 ETag、Range、If-Range |

操作人从登录身份取得。关键变更写入 `ar_audit`，动作为 `VERSION_CREATE`、`VERSION_EDIT`、`VERSION_PUBLISH`、`VERSION_DELETE_REQUEST`、`VERSION_DELETE`、`VERSION_DELETE_FAILED`，以及场景动作和上传结果动作，可在“场景操作记录”查看。业务 JSON 错误沿用 `AR_<status>`/`message`/`traceId`；文件 Range 416 无正文，不能要求所有失败都有 JSON。

## 创建、上传与恢复

1. 创建版本时一次登记全部文件。首次 201；同 `requestKey` 且说明和排序后的路径/大小/摘要完全相同返回 200 与原版本；任一不同返回 409；已整版删除的版本迟到重试返回 410，不复活。
2. 版本创建后文件清单固定，需要改变任何文件或路径时创建新版本。只有说明可编辑。
3. 服务端逐段读取文件，同一次读取中校验实际字节数与 SHA256，超过声明大小立即拒绝；只有校验通过才能无覆盖提交为正式 `.bin`，提交后直接标记 `AVAILABLE`，不再重读。
4. 同一文件并发处理返回 409。已 `AVAILABLE` 的文件重复上传只核对记录、文件存在和长度后返回原记录。大小或摘要不符返回 422，存储 IO 失败返回 503，均保存 `FAILED` 与原因，新尝试递增 `attempts`。
5. 上传按文件恢复：先查询状态，`AVAILABLE` 跳过，`UPLOADING` 显示处理中，`FAILED`/`PENDING` 重新完整上传该文件。该文件若留有校验不符的 `.ready` 或未确认 `.bin`，重新上传会先删除这份未确认遗留，再接收新正文；已确认可用的正式文件不覆盖。传输超时只表示结果未确认，不自动改成失败；没有自动重试、全量轮询或分片协议。
6. 启动先恢复未完成整版删除，再只对 `PENDING`/`UPLOADING`/`FAILED` 且有遗留数据的记录恢复：完整且校验通过的 `.ready` 或已落盘未确认的文件至多验证一次后补记可用。校验不符的遗留保持失败，不在启动时删除。中断的 `UPLOADING` 变 `FAILED`，没有遗留数据的 `PENDING` 保持不变。`AVAILABLE` 不全量重算摘要。恢复审计标明 `performedBy=SYSTEM_RECONCILIATION`。

文件列表、版本详情、发布和管理员 GET/HEAD 不读取其他文件内容，也不计算内容摘要。已可用文件的同长度磁盘损坏不会被服务端发现，由下载端校验 SHA256 发现。当前支持一个 Spring Boot 实例和一个私有本地存储卷。

## 发布与整版删除

1. 同场景只有一个当前发布指针。发布只检验全部文件 `AVAILABLE`，不解析模型、不重算摘要；未完成返回 400，有处理中文件或删除意图返回 409。
2. 目标已是当前发布版本时直接返回 200，不更新修订号、发布时间、指针或审计。实际切换时比较 `expectedSceneVersion`，不符返回 409；成功后递增场景 `lock_version` 并写一条 `VERSION_PUBLISH` 审计。
3. 替换发布后旧版本可查看或整版删除；当前发布版本禁止删除，不保留历史分发快照。场景停用或逻辑删除后不递归删除模型。
4. 整版删除先持久化删除意图和 `VERSION_DELETE_REQUEST` 审计，再逐 UUID 删除存储内容；全部成功才在事务内删除文件行、版本行、完成回执并写 `VERSION_DELETE` 审计。IO 失败返回 503，版本保留并显示 `DELETE_FAILED`，再次 DELETE 重试；完成后重复 DELETE 为 204。文件处理中 409。

## 匿名客户端读取与完整下载

内部 Demo 客户端不登录，只读当前已发布版本。`ClientSceneController`/`ClientSceneService` 仅在 `ar.storage.enabled=true` 时注册，没有类级角色；`SecurityConfig` 对下面三个路由的 GET 和文件 HEAD 逐条放行，其余 `/api/v1/client/**` 路径及任何写方法仍要求登录或被拒绝（匿名得 401/403），不存在 `/access` 之类返回成功的占位接口。客户端路径直接访问网关，不带 `/prod-api` 前缀。

| 方法与路径 | 用途 |
|---|---|
| GET `/api/v1/client/scenes?name=&limit=20&offset=0` | `{items,total}`；每项 `id,name,versionId,versionNo`。只含启用、未删除且有完整当前发布版本的场景；limit 1–100；空目录返回 200 与空数组 |
| GET `/api/v1/client/scenes/{sceneId}` | `{sceneId,name,versionId,versionNo,files[{fileId,relativePath,bytes,sha256,contentType,downloadPath}],fileCount,totalBytes}`；`files` 是该版本的完整集合，客户端按自身逻辑以 `relativePath` 选择所需文件。无发布、停用、删除均 404；不返回 `storageKey` 或磁盘路径 |
| GET / HEAD `/api/v1/client/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}` | 文件字节，支持强 ETag、单段 Range（`a-b`、`a-`、后缀 `-n`）、If-Range |

- 目录和详情只读数据库，不打开模型文件，不计算摘要。`fileName` 是实际 basename 的 URI 编码，只用于保留文件后缀并与记录比对，不参与磁盘路径；不符 404。含 `%` 或 `;` 的文件名无法进入 URL，创建版本时直接返回 400。
- 判定顺序：场景可见、版本归属、文件 `AVAILABLE` 且无删除意图；`versionId` 不再等于当前发布指针返回 **409**，客户端须重新获取详情，不能混用新旧版本；错误归属或不存在 404；记录存在但存储缺失或长度不符 409。下载前不重算 SHA256，强 ETag 为登记摘要。已开始的旧版本字节流允许完成，其后的旧版本请求 409。
- 响应读锁持有到流结束，整版删除取写锁，不会截断正在读取的文件。`Content-Type` 只按扩展名：json 为 `application/json`，jpg/jpeg/png/webp、wav、webm 对应 MIME，模型和未知为 `application/octet-stream`，不嗅探内容。客户端响应不带 `attachment` 文件名，`Cache-Control: no-store, no-transform`；管理员下载保留 `attachment`。
- Range、If-Range、HEAD 和状态码处理统一见 [客户端接口](21-client-api.md)；合法但无法满足的 Range 返回 416 与 `Content-Range: bytes */size`，无正文；HEAD 忽略 Range 且不发送正文。永久回归为 `HttpRangeTest`。

完整下载参考工具 `scripts/download_scene.py --base-url URL --scene-id UUID --output DIR`（Python 标准库，匿名）下载当前发布版本的全部文件，目录为 `<DIR>/<sceneId>/<versionId>/`：`payload/` 是相对路径的根，`.download-state.json` 在写任何字节之前原子建立并记录固定清单与已完成集合，`.transfer/` 存放 `.part`、验证器和锁，`ready.json` 在全部文件校验后才原子写入。同名 `.tmp` 只有带本次任务状态时才接管；非空且无法确认归属的临时目录直接拒绝，不删除。同命令可在被杀或断网后继续：已完成且长度匹配的文件不再请求、不重哈希；其余沿用 `artifact_transfer.download` 的 Range + If-Range，206 校验起点后追加，200 截断重写，摘要不符删除该 `.part`、不就绪、下次只重下该文件。锁为操作系统文件锁（`fcntl`/`msvcrt`），残留的空锁文件不会阻塞。遇 409 工具停止（退出码 3）、不自动重试并保留旧目录；该退出码/提示沿用“版本变化”的命名，但服务端也可能因文件不可用返回 409。重新取详情后只有 `versionId` 改变才进入新版本目录，未改变不能假定重跑即可恢复，见 [客户端接口](21-client-api.md)。它是联调参考，不是 Android/iOS 下载 SDK；按需选择文件由客户端实现。

## 后台

新建场景：输入非空名称后可按 Enter 或点“保存”，提交时去掉首尾空白，提交期间不会重复创建；中文输入法的确认 Enter 不触发提交。未提交名称按账号保存在当前浏览器 localStorage，关闭弹窗、离开页面或刷新后再点“新建场景”会恢复；只有创建接口确认成功才清空，失败保留原文。编辑已有场景不会覆盖或清空新建草稿。清除浏览器站点数据会清除该草稿。

入口：场景列表每行的 **版本与文件**，地址栏参数为 `sceneId`、`versionId`。面板顶部固定当前发布卡片，下方是版本列表和所选版本详情（平铺文件清单）；点击“导入资源目录”选择目录，或点击“导入文件”多选任意文件，随后填写版本说明并“开始导入”。两种入口共用流程：登记全部所选文件 → 每个文件用 `hash.worker.js` 按 2 MiB 块计算一次 SHA256 → 创建一个版本 → 固定三路并发上传缺失文件。单个文件请求失败不阻断其余文件，完成后完整列出“请求失败”和“结果未确认”；发送字节百分比与已入库数分开显示。停止会中止全部在途 PUT，等待这些请求的一次状态核对结束后退出传输状态。已存在版本可点击“重新选择目录”或“重新选择文件”继续：必须选择完整原始集合，路径、大小和摘要都必须一致，每轮重新查询状态，只发送 `FAILED`/`PENDING`，跳过 `AVAILABLE`/`UPLOADING`。未刷新页面且仍保留原文件时可直接“继续上传”。服务端只登记正在处理的文件 UUID，同一文件在途返回 409，不同文件不因分段锁碰撞互相拒绝；SHA256 仍随每个请求流式校验，命令行导入工具不改。

2026-10-30 操作更新：目录导入和任意多文件导入（包括续传）全部确认入库后，页面再次读取版本状态；只有后端返回 READY 且所有文件 AVAILABLE，才无确认弹窗地调用现有发布接口，自动替换当前发布指针，原版本保留为历史。发送进度 100%、失败、处理中、结果未确认或取消都不触发自动发布。采用本轮上传开始时的场景修订号；发布 409 或其他失败不自动重试、不重新上传，保留就绪文件并提示用户确认当前指针后手动发布。历史版本手动发布入口保留。

“版本名”经用户澄清即现有“版本说明”，未新增字段；导入前可填，发布后仍可修改，不改变版本号、固定文件清单或发布指针。自动发布由后台页面衔接，后端创建、上传、发布 API 契约保持分离；关闭页面不构成服务端自动发布承诺。


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

## 配置与运行

- `AR_STORAGE_ENABLED=true` 开启入库接口；关闭时路由不注册。`AR_STORAGE_ROOT` 指向私有目录或容器持久卷。
- `AR_STORAGE_MAX_BYTES`：单文件上限，必填正整数，后端登记和实际流式写入共同检查。本机 `scripts/local_demo.py` 默认 256 MiB；真实样包验收设 1073741824。
- `AR_STORAGE_VERSION_MAX_FILES`（默认 1000）和 `AR_STORAGE_VERSION_MAX_BYTES`（默认 4294967296）：单版本文件数与总字节上限，Compose 与 `config/compose.env.example` 提供。旧 `AR_STORAGE_COLLECTION_*`、ZIP 缓存配置已删除。
- Nginx 对 `/prod-api/api/v1/scene-versions/{versionId}/files/{fileId}/content` 关闭请求/响应缓冲和网关字节限制，超时 300s；其余业务接口保持 20m 限制。管理员下载必须携带登录身份，令牌不放进 URL。`/api/v1/client/` 以同源、路径不改写、关闭响应缓冲、超时 300s 代理到后端；不开放任何磁盘目录，不增加 CORS 配置。

## 验收

- 契约与链接：按 [Harness](13-harness.md) 运行 quick；只有契约本身变化时才修改生成源并重新生成，不以验证时重生成掩盖漂移。
- 隔离实例：Linux 的完整 prepare、HTTP/浏览器 verify 与 stop 命令集中在 [Harness](13-harness.md)“使用”节，必须提供 `.local/` 下的 `--report-dir` 和同源码已测试 Jar、有效 frontend dist；核对缺镜像时的构建副作用与授权。不要将本页导入示例用于日常实例。Windows 原生运行时（`review.py`、harness ingestion）继续提供数据库和私有存储故障注入。
- 无需服务的永久回归为 `scripts/test_download_scene.py`、`scripts/test_artifact_transfer.py`；`HttpRangeTest`、`ClientSceneServiceTest` 在 `ruoyi-ar` 中。阶段 4 的 `.local/stage4_gate.py` 仅是当时隔离实例门禁记录，不是 clone 后保证存在的仓库入口。
- 真实样包导入联调：`scripts/import_scene_package.py --base-url http://127.0.0.1:18082 --scene-id UUID --package-root DIR --state-file FILE --credentials-file FILE [--version-id UUID] [--report FILE]`。该脚本只支持**隔离 HTTP 网关根 URL**，不带 `/prod-api`（脚本自动追加），不支持 HTTPS；这不是允许将公网凭据改用明文传输。凭据使用本任务隔离实例的私有文件，状态与报告放 `.local/` 且位于包根之外，不打印口令或令牌。
- 导入脚本复用创建/上传 API，导入包根下的每个普通文件，拒绝符号链接和空目录。每文件预哈希一次，状态记录 `requestKey` 与 `versionId`（不是 `versionNo`）；同命令或 `--version-id` 续传时重新哈希核对同一清单，跳过 AVAILABLE、不重发 UPLOADING、重传 FAILED/PENDING。口令和令牌只在内存；脚本不自动发布，页面自动发布行为见“后台”节。
- 旧 `prepare_reference_viewer.py`、`verify_4dgs.py` 与参考播放器目录当前不在 `scripts/` 中，不能作为可执行验收入口。其旧描述基线上的准备、播放、JFR 与真实样包结果统一见 [真实样包验收记录](20-4dgs-sample-validation.md)；这些历史命令不适用当前 0.5.0，不在本轮恢复或维护。
- 合成模型字节不是可渲染 4DGS 内容，只验证管理与传输契约；浏览器播放、Android/iOS 真机、手机网络和音画主观效果不在这些检查内。

阶段与证据见 [任务记录](tasks/active/2026-10-29-4dgs-resource-refactor.md)。[保留证据索引](evidence/README.md)中的旧入库 JSON 是历史快照，不代表当前代码。

## 明确未实现

后台内嵌场景预览、单独下线、对象存储、CDN、共享依赖与 catalog 解析未实现；版本中的视频文件可经匿名接口读取，不代表后台已有预览界面。参考播放器适配自 2026-10-29 去掉描述后不可用，此前桌面 Chrome 播放结果见 [验收记录](20-4dgs-sample-validation.md)（历史记录），不等于手机或 Unity 原生加载验收。Android/iOS 下载 SDK 尚未提供（`scripts/download_scene.py` 只是下载联调参考）；手机真机播放与音频同步未验证。空目录不保留。
