# 资源入库闭环

一个场景对应一个独立的 4DGS 重建成品。管理员私有入库流程：选择场景 → 导入带 `resource.json` 的资源目录创建内容版本 → 逐文件上传并校验 → 正式存储确认 → 发布为场景当前版本 → 需要时整版删除。文件“可用”仅表示已可靠入库；匿名客户端只读取当前发布版本（见下文“匿名客户端读取与完整下载”）。

## 数据与状态

实际迁移随应用 Flyway 执行：`V014__remove_scene_geography.sql` 删除地址、经纬度和坐标系；`V015__scene_product_versions.sql` 是**破坏性清洁切换**，明确清空旧成品业务记录（`ar_audit`、旧草稿/文件/ZIP 表和 `ar_scene`）后删除旧表，不涉及任何 `sys_*` 账号和菜单表，也不能对日常库自动执行。根目录 `database/migrations` 仍是历史候选设计。

- `ar_scene`：只保留名称、启停、修订号及时间/删除信息，加当前发布指针 `published_version_id`、`published_at`、`published_by_*`（复合外键保证不跨场景发布）。
- `ar_scene_version`：不可变版本，含场景内版本号、`request_key`、说明、`descriptor`（jsonb）、说明修订号。同场景同请求键幂等。
- `ar_version_file`：每文件相对路径、预期大小/SHA256、服务端 UUID 加 `.bin` 的存储标识、状态、已验证大小/摘要、尝试次数、失败原因、创建人和最后操作人。同版本相对路径唯一。
- `ar_version_deletion`：整版删除意图、失败原因和最小幂等回执，不向已删除版本保留外键，也不复制文件内容或完整描述。
- 文件内容只写入 `ArtifactStorage`，不进数据库。相对路径只用于清单和还原，不能指定服务器落盘路径。

| 文件状态 | 含义 |
|---|---|
| PENDING | 元数据已登记，尚未确认上传 |
| UPLOADING | 正在接收或校验，不能当作成功 |
| AVAILABLE | 接收时大小和 SHA256 校验通过并已无覆盖提交为正式文件，数据库确认可用 |
| FAILED | 校验、传输、存储或重启核对失败，原因可查，可用原文件重试 |

版本 `uploadStatus` 读时由文件状态推导，不另存状态机：未完成删除为 `DELETING`/`DELETE_FAILED`，否则有 `UPLOADING` 为 `UPLOADING`，有 `FAILED` 为 `FAILED`，全部 `AVAILABLE` 为 `READY`，其余 `PENDING`。`AVAILABLE` 的数据库约束要求已验证大小/摘要与登记值相等且无失败原因。

## resource.json v1

上传目录根必须有且只有一个 `resource.json`，浏览器以它所在目录为根，描述中的路径都相对这个根。内容作为创建版本请求的 `descriptor` 存入 jsonb，不作为模型文件传输。字段、约束和示例见 [Schema](../contracts/schemas/resource-descriptor.schema.json) 与 [wedding 示例](../contracts/examples/resource-descriptor.json)，同源于 `scripts/generate_contracts.py`。

- 固定 `formatVersion=1`；`defaultVariant` 指向真实档位；必须显式给出 `transform`；`settings` 必填，`poster`/`audio`/`preview` 可选，缺少就省略。
- 每个档位有 `id`、`name`、`format`（当前唯一值 `4dv-compressed-ply`）和非空有序 `segments`（`path`、`startSeconds`、`durationSeconds`）。时间不猜测，不按文件名推断顺序，不要求各档位段数一致。
- 引用路径去重后的集合必须与请求 `files` 的路径集合完全相等；重复路径、路径穿越、缺失引用、重复档位、未知默认档位、时间重叠返回 400 并指出字段或路径。文件大小或数量超配置返回 413。后端不解码模型。

## 接口

管理接口位于 `/api/v1`，类级 `ar_admin`，经网关为 `/prod-api/api/v1`。完整输入输出见生成的 [OpenAPI](../contracts/openapi.yaml)（`4DGS Scene Resource API` 0.4.0，仅描述当前实际接口）。

| 方法与路径 | 用途 |
|---|---|
| GET `/scene-versions/config` | 单文件、单版本文件数和字节上限 |
| GET / POST `/scenes/{sceneId}/versions` | 分页查询（含 `sceneLockVersion`、`published`）/ 创建版本 |
| GET / PUT `/scene-versions/{versionId}` | 描述和完整文件清单 / 仅编辑说明（`expectedVersion`） |
| DELETE `/scene-versions/{versionId}` | 整版物理删除；当前发布版本 409 |
| POST `/scene-versions/{versionId}/publish` | 发布，body `expectedSceneVersion` |
| GET `/scene-versions/{versionId}/files/{fileId}` | 单文件状态，用于结果未确认后核对 |
| PUT `/scene-versions/{versionId}/files/{fileId}/content` | `application/octet-stream` 原始文件流 |
| GET / HEAD `/scene-versions/{versionId}/files/{fileId}/content` | 管理员读取已完成文件，支持强 ETag、Range、If-Range |

操作人从登录身份取得。关键变更写入 `ar_audit`，动作为 `VERSION_CREATE`、`VERSION_EDIT`、`VERSION_PUBLISH`、`VERSION_DELETE_REQUEST`、`VERSION_DELETE`、`VERSION_DELETE_FAILED`，以及场景动作和上传结果动作，可在“场景操作记录”查看。错误沿用 `AR_<status>`/`message`/`traceId`。

## 创建、上传与恢复

1. 创建版本时一次登记全部文件。首次 201；同 `requestKey` 且说明、描述和排序后的路径/大小/摘要完全相同返回 200 与原版本；任一不同返回 409；已整版删除的版本迟到重试返回 410，不复活。
2. 版本创建后描述和文件清单固定，需要改变模型、配置、路径或档位时创建新版本。只有说明可编辑。
3. 服务端逐段读取文件，同一次读取中校验实际字节数与 SHA256，超过声明大小立即拒绝；只有校验通过才能无覆盖提交为正式 `.bin`，提交后直接标记 `AVAILABLE`，不再重读。
4. 同一文件并发处理返回 409。已 `AVAILABLE` 的文件重复上传只核对记录、文件存在和长度后返回原记录。大小或摘要不符返回 422，存储 IO 失败返回 503，均保存 `FAILED` 与原因，新尝试递增 `attempts`。
5. 上传按文件恢复：先查询状态，`AVAILABLE` 跳过，`UPLOADING` 显示处理中，`FAILED`/`PENDING` 重新完整上传该文件。传输超时只表示结果未确认，不自动改成失败；没有自动重试、全量轮询或分片协议。
6. 启动先恢复未完成整版删除，再只对 `PENDING`/`UPLOADING`/`FAILED` 且有遗留数据的记录恢复：完整 `.ready` 或已落盘未确认的文件至多验证一次后补记可用，中断的 `UPLOADING` 变 `FAILED`，没有遗留数据的 `PENDING` 保持不变。`AVAILABLE` 不全量重算摘要。恢复审计标明 `performedBy=SYSTEM_RECONCILIATION`。

文件列表、版本详情、发布和管理员 GET/HEAD 不读取其他文件内容，也不计算内容摘要。已可用文件的同长度磁盘损坏不会被服务端发现，由下载端校验 SHA256 发现。当前支持一个 Spring Boot 实例和一个私有本地存储卷。

## 发布与整版删除

1. 同场景只有一个当前发布指针。发布只检验描述引用及全部文件 `AVAILABLE`，不解析模型、不重算摘要；未完成返回 400，有处理中文件或删除意图返回 409。
2. 目标已是当前发布版本时直接返回 200，不更新修订号、发布时间、指针或审计。实际切换时比较 `expectedSceneVersion`，不符返回 409；成功后递增场景 `lock_version` 并写一条 `VERSION_PUBLISH` 审计。
3. 替换发布后旧版本可查看或整版删除；当前发布版本禁止删除，不保留历史分发快照。场景停用或逻辑删除后不递归删除模型。
4. 整版删除先持久化删除意图和 `VERSION_DELETE_REQUEST` 审计，再逐 UUID 删除存储内容；全部成功才在事务内删除文件行、版本行、完成回执并写 `VERSION_DELETE` 审计。IO 失败返回 503，版本保留并显示 `DELETE_FAILED`，再次 DELETE 重试；完成后重复 DELETE 为 204。文件处理中 409。

## 匿名客户端读取与完整下载

内部 Demo 客户端不登录，只读当前已发布版本。`ClientSceneController`/`ClientSceneService` 仅在 `ar.storage.enabled=true` 时注册，没有类级角色；`SecurityConfig` 对下面三个路由的 GET 和文件 HEAD 逐条放行，其余 `/api/v1/client/**` 路径及任何写方法仍要求登录或被拒绝（匿名得 401/403），不存在 `/access` 之类返回成功的占位接口。客户端路径直接访问网关，不带 `/prod-api` 前缀。

| 方法与路径 | 用途 |
|---|---|
| GET `/api/v1/client/scenes?name=&limit=20&offset=0` | `{items,total}`；每项 `id,name,versionId,versionNo,defaultVariant,variants[{id,name,segmentCount,durationSeconds}],posterUrl?`。只含启用、未删除且有完整当前发布版本的场景；limit 1–100；空目录返回 200 与空数组 |
| GET `/api/v1/client/scenes/{sceneId}` | `{sceneId,name,versionId,versionNo,descriptor,files[{fileId,relativePath,bytes,sha256,contentType,downloadPath}],fileCount,totalBytes}`；`files` 是该版本去重后的完整集合，客户端按选定档位和公共 `settings/poster/audio/preview` 过滤。无发布、停用、删除均 404；不返回 `storageKey` 或磁盘路径 |
| GET / HEAD `/api/v1/client/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}` | 文件字节，支持强 ETag、单段 Range（`a-b`、`a-`、后缀 `-n`）、If-Range |

- 目录和详情只读数据库与已保存的描述，不打开模型文件，不计算摘要。`fileName` 是实际 basename 的 URI 编码，只用于保留 `.ply/.4dv/.json/.wav` 后缀（播放器按 URL 后缀选加载器）并与记录比对，不参与磁盘路径；不符 404。含 `%` 或 `;` 的文件名无法进入 URL，创建版本时直接返回 400。
- 判定顺序：场景可见、版本归属、文件 `AVAILABLE` 且无删除意图；`versionId` 不再等于当前发布指针返回 **409**，客户端须重新获取描述，不能混用新旧版本；错误归属或不存在 404；记录存在但存储缺失或长度不符 409。下载前不重算 SHA256，强 ETag 为登记摘要。已开始的旧版本字节流允许完成，其后的旧版本请求 409。
- 响应读锁持有到流结束，整版删除取写锁，不会截断正在读取的文件。`Content-Type` 按声明角色与扩展名：模型 `application/octet-stream`、settings `application/json`、jpg/png/webp、wav、webm 对应 MIME，未知为 `application/octet-stream`，不嗅探内容。客户端响应不带 `attachment` 文件名，`Cache-Control: no-store, no-transform`；管理员下载保留 `attachment`。
- Range：合法但越界返回 416 与 `Content-Range: bytes */size`（超大数字不抛 500）；无效、`end<start` 或多段 Range 忽略并返回完整 200；If-Range 不匹配返回完整 200；HEAD 不发送正文，长度为完整长度。永久回归为 `HttpRangeTest`。

完整下载参考工具 `scripts/download_scene.py --base-url URL --scene-id UUID --variant ID --output DIR`（Python 标准库，匿名）只下载选定档位的分段加公共文件，目录为 `<DIR>/<sceneId>/<versionId>/<variantId>/`：`payload/` 是描述路径的根，`.download-state.json` 在写任何字节之前原子建立并记录固定清单与已完成集合，`.transfer/` 存放 `.part`、验证器和锁，`ready.json` 在全部文件校验后才原子写入。同命令可在被杀或断网后继续：已完成且长度匹配的文件不再请求、不重哈希；其余沿用 `artifact_transfer.download` 的 Range + If-Range，206 校验起点后追加，200 截断重写，摘要不符删除该 `.part`、不就绪、下次只重下该文件。锁为操作系统文件锁（`fcntl`/`msvcrt`），残留的空锁文件不会阻塞。409 表示发布版本已变化：工具停止（退出码 3）、不自动重试、保留旧目录，重新运行才会把新描述取到新的版本目录。没有该档位退出码 2，不自动换档。它是联调参考，不是 Android/iOS 下载 SDK。

## 后台

入口：场景列表每行的 **版本与文件**，地址栏参数为 `sceneId`、`versionId`。面板顶部固定当前发布卡片，下方是版本列表和所选版本详情；唯一新增动作是“导入资源目录”：读取根 `resource.json` → 展示档位、段数和文件总量 → 每个引用文件用 `hash.worker.js` 按 2 MiB 块计算一次 SHA256 → 创建版本 → 顺序上传缺失文件。已存在版本可重新选择同一目录“继续上传”，已入库文件不重传。

## 配置与运行

- `AR_STORAGE_ENABLED=true` 开启入库接口；关闭时路由不注册。`AR_STORAGE_ROOT` 指向私有目录或容器持久卷。
- `AR_STORAGE_MAX_BYTES`：单文件上限，必填正整数，后端登记和实际流式写入共同检查。本机 `scripts/local_demo.py` 默认 256 MiB；真实样包验收设 1073741824。
- `AR_STORAGE_VERSION_MAX_FILES`（默认 1000）和 `AR_STORAGE_VERSION_MAX_BYTES`（默认 4294967296）：单版本文件数与总字节上限，Compose 与 `config/compose.env.example` 提供。旧 `AR_STORAGE_COLLECTION_*`、ZIP 缓存配置已删除。
- Nginx 对 `/prod-api/api/v1/scene-versions/{versionId}/files/{fileId}/content` 关闭请求/响应缓冲和网关字节限制，超时 300s；其余业务接口保持 20m 限制。管理员下载必须携带登录身份，令牌不放进 URL。`/api/v1/client/` 以同源、路径不改写、关闭响应缓冲、超时 300s 代理到后端；不开放任何磁盘目录，不增加 CORS 配置。

## 验收

- 契约与链接：`python scripts/generate_contracts.py` 后 `python scripts/harness.py check --profile quick`。
- 隔离实例：`scripts/prepare_4dgs_check.py prepare` 启动固定 `innovation-ar-resource-platform-infra-check` 项目的 `127.0.0.1:18082`，再以 `scripts/verify_ingestion.py --base-url ... --admin-base-url ... --credentials-file ...` 运行 HTTP（可选浏览器）检查；用法和限制见 [Harness](13-harness.md)。Windows 原生运行时（`review.py`、harness ingestion）继续提供数据库和私有存储故障注入。
- 阶段 4 隔离实例门禁：`.local/stage4_gate.py`（匿名读写边界、Range、`download_scene.py` 的中断/续传/409 行，不入库）；`scripts/test_download_scene.py`、`scripts/test_artifact_transfer.py` 是无需服务的永久回归，`HttpRangeTest`、`ClientSceneServiceTest` 在 `ruoyi-ar` 中。
- 合成模型字节不是可渲染 4DGS 内容，只验证管理与传输契约；浏览器播放、Android/iOS 真机、手机网络和音画主观效果不在这些检查内。

阶段与证据见 [任务记录](tasks/active/2026-10-29-4dgs-resource-refactor.md)。[保留证据索引](evidence/README.md)中的旧入库 JSON 是历史快照，不代表当前代码。

## 明确未实现

场景预览、单独下线、对象存储、CDN、共享依赖与 catalog 解析；Android/iOS 下载 SDK（`scripts/download_scene.py` 只是联调参考）；4DV 参考播放器接入与真实样包验收（阶段 5）。客户端加载规则以真实播放验收后的结论为准。空目录不保留。
