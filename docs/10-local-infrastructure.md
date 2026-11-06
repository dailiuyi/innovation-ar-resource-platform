# Docker 部署与本地成品存储基础设施

单文件 Range 续传参考与通用打包扩展边界见 [资源传输参考](11-artifact-transfer-reference.md)；当前场景下载由 `scripts/download_scene.py` 通过匿名 HTTP 接口编排，不需要 ZIP 或解包步骤。

## 当前实现与交付边界

本地源码提供 Nginx、Spring Boot、PostgreSQL 17、Redis 四服务 Compose；场景直接关联固定模型文件，上传校验完成即对启用场景开放匿名读取，没有独立发布流程。日常部署版本以本页带日期记录为准。

`ArtifactStorage`/`LocalArtifactStorage` 处理流式大小与 SHA256 校验、无覆盖提交、读取、删除和未完成字节恢复。场景服务负责固定清单、可见性与审计，私有目录不公开。

2026-11-06 切换到单场景模型需要 V018 升级和新客户端路径，见[入库闭环](12-resource-ingestion.md)。旧数据库、模型与审计必须保留，日常迁移和重建服务需另行批准。

## 启动

要求 Windows Docker Desktop 使用 WSL2/Linux 容器，或 Linux Docker Engine + Compose。准备阶段需要联网构建/获取镜像；运行时不依赖云存储。下面命令从仓库根目录执行，Linux 将 `python` 换成 `python3`。

以下命令仅用于准备新环境，不是更新日常实例的指令。V015 会清空旧成品业务记录；现有数据库升级必须先备份并另行授权，不能直接执行。

```powershell
# 1 GiB 是示例单文件上限，按实际成品调整；已有配置不重复生成。
python scripts/prepare_compose.py --max-bytes 1073741824 --bind-address 192.168.0.12 --http-port 18081
docker compose --env-file config/compose.env config --quiet
docker compose --env-file config/compose.env up -d --build
docker compose --env-file config/compose.env ps
```

准备脚本使用独占创建生成随机数据库密码、Token 密钥和引导密码，不打印密码，也不覆盖已有文件。`config/*.env` 已忽略且不进入 Docker 构建上下文。Windows 文件权限继承宿主目录权限，应将仓库置于自己的私有工作目录；Linux 新配置权限为 0600。

当前日常入口为 `http://81.71.154.125:18081`，推荐使用 `https://4dgs.elma-gohan.xyz`；HTTPS 在 `elma-gohan.xyz` 的 nginx 终止，再经 HTTP 转发到云端 gateway。2026-10-30 经用户选择切换，已不依赖开发机和反向隧道。本机旧实例的四个容器、项目网络和应用镜像标签已按授权清理，四个原数据卷、私有配置和备份完整保留，隧道服务停用；本机模型未迁移，禁止清理原数据卷。对象存储、CDN 和自动备份未部署。

Compose/准备脚本在未覆盖参数时仍默认 `127.0.0.1:18081`；隔离验收固定用 `127.0.0.1:18082`，不能混用日常库和配置。首次空库使用 `bootstrap` 和私有配置内的引导密码登录，创建日常管理员后引导账号停用；新容器库不自动导入原生 Demo 数据。

内网开放时设置 `AR_BIND_ADDRESS` 为实际内网地址，并限定宿主防火墙来源。客户端服务地址可配置，管理前端使用同源 `/prod-api/`，匿名读取使用 `/api/v1/client/`；仓库内 gateway 提供 HTTP，公网 TLS 在中继终止。

新源码使用 `AR_STORAGE_MAX_BYTES` 限制单文件，`AR_STORAGE_SCENE_MAX_FILES`（默认 1000）和 `AR_STORAGE_SCENE_MAX_BYTES`（默认 4294967296）限制场景；替换旧版本命名配置时显式更新私有部署配置。Nginx 对 `/prod-api/api/v1/scenes/{sceneId}/files/{fileId}/content` 关闭请求/响应缓冲和字节限制，其余接口保持 20m。启动先恢复场景删除，再核对未完成上传，不全量重算可用文件。以上不构成已经升级日常实例的记录。

## 持久卷与权限

| 卷 | 用途 | 挂载位置 |
|---|---|---|
| `postgres_data` | 数据库 | PostgreSQL 数据目录 |
| `artifacts_data` | 成品存储 | 后端 `/data/artifacts` |
| `framework_uploads` | 与成品隔离的框架目录 | 后端 `/data/framework-uploads` |
| `backend_logs` | 应用滚动日志 | 后端 `/app/.local/logs` |

实际卷名含 Compose 项目前缀。项目名称保持稳定，否则会创建另一组卷。重建容器保留命名卷；`down -v` 会删除卷，不用于日常更新。

当前 Compose 项目名为 `innovation-ar-resource-platform`，数据库名为 `innovation_ar_resource_platform`。数据库登录角色沿用 `innovation`；已有部署改名时必须先备份并迁移原有四个命名卷，不能直接用新项目名启动空卷。本机 2026-09-25 的迁移与保留的旧卷见 [验证记录](06-validation.md)。

后端以 UID/GID 10001 运行。数据库和 Redis 不映射宿主端口，服务间使用 internal 网络；网关是唯一宿主入口。Nginx 不挂载成品卷，内部存储路径直接返回 404；Range 下载由后端流式输出，尚无 `X-Accel-Redirect` 静态交付。Redis 的 `/data` 使用 tmpfs，Redis 重启后登录会话丢失，需要重新登录。

PostgreSQL 当前延续 Demo 的初始化/运行同账号模式，该账号拥有较高权限。此开发机演示实例不是生产安全基线；后续权限拆分需另立迁移方案。健康检查只确认进程/基础接口可用，不代表客户端业务验收。

镜像使用明确版本标签；应用镜像为 `innovation-ar-resource-platform-backend:infra-v1`、`innovation-ar-resource-platform-gateway:infra-v1`。迁移时应传输实际已验收的镜像并核对镜像 ID，不能把同名标签当作内容相同的证明。

### 云端独立实例（2026-10-30）

用户授权在 `http://81.71.154.125:18081/` 新建独立部署，SSH 别名 `innovation`，运行用户 `daily`，目录 `/home/daily/innovation-ar-resource-platform`。运行 Compose 不含构建步骤，2026-10-30 初始镜像为 backend `parallel-upload-69f8904`、gateway `auto-publish-20261030t124437z`、PostgreSQL `17.6-bookworm`、Redis `7.4.5-alpine3.21`。本次 gateway 复用已验收 dist 打包，包含尚未提交的自动发布/Enter/草稿功能；来源指纹与实际镜像摘要见服务器 `releases/auto-publish-20261030t124437z/source.json`、`release.json`，不能将基线提交 `8ee5581` 当作完整功能源码提交。初次部署的 `manifest.json` 和 `multi-file-ebf930c` 镜像保留为历史/回退材料。

初次部署使用全新数据库和文件卷。用户随后将范围明确为**仅迁移账号**，并选择将旧域名切到云端：现已迁移完整 `sys_user`、用户角色/岗位关联，两个原日常账号继续启用且密码不变，退役 bootstrap 仍停用/删除，不能使用云端生成的引导密码登录。没有迁移源端场景、版本、文件、业务审计或登录会话；云端原验收审计保留。HTTP IP 入口是明文，推荐 HTTPS 域名；中继到云端的上游仍是 HTTP，尚未配置端到端 TLS、自动备份或 CDN。

服务器上查看状态、启动与停止（停止保留命名卷，禁止 `down -v`）：

```bash
cd /home/daily/innovation-ar-resource-platform
docker compose --env-file config/compose.env ps
docker compose --env-file config/compose.env up -d --no-build --pull never --wait --wait-timeout 240
docker compose --env-file config/compose.env stop
```

单文件上限 1 GiB，每场景最多 1000 文件 / 4 GiB；ZIP 原样上传，由 Unity 下载后解压。该服务器已实测多文件真实入库与管理员完整/Range 下载，未验证 Unity 解压、手机播放或大文件带宽。部署及验收证据见 [验证记录](06-validation.md)「云端独立 Docker 部署」。

### 2026-11-06 单场景固定文件上线

用户在该日验收本地实现后要求“去掉列表的文件列后部署”，授权把 `feat/admin-scene-files` 的成果上线日常云端。当前镜像为 backend `single-scene-20261106`（镜像 ID `d71dbe848133`）、gateway `single-scene-20261106`（`6cd1108b3c66`），归档 `releases/single-scene-20261106/images.tar.gz`，SHA256 `ad88f6e8d2af3b828042c9917c9d675f8428ce46c86b74ed9e7e109ebadfc9e8`，来源为本机 worktree 的同一构建产物。`compose.yaml` 与 `config/compose.env` 同时把 `AR_STORAGE_VERSION_MAX_*` 改名为 `AR_STORAGE_SCENE_MAX_*`，值不变；改动前副本保存在同一 `releases/single-scene-20261106/` 目录。

上线前备份：`backups/single-scene-20261106/before-v018.dump`（`pg_dump -Fc`，SHA256 `a0f9d2ca712efa2f079aa5e2f1e0b0190348d57827ec01cf6ec808999be967a3`），含账号数据，不外发。V018 只搬移业务行，不改写 payload 文件；云端实测 13 场景（7 启用）、7 文件、73 审计、0 孤儿文件、4 条删除回执，`flyway_schema_history` 记为成功。Redis 重启会丢登录会话，已登录用户需重新登录。

回退：V018 是破坏式切换，不能只把应用标签改回旧版。获准回退时先停止写入，把镜像标签改回 `knife4j-20261104`，并用上述 dump 还原数据库（会丢弃上线后的新数据）；未执行过回退演练。

账号迁移备份：源端 `.local/migrations/accounts-cloud-20261030/source-before.dump`，云端 `/home/daily/innovation-ar-resource-platform/backups/accounts-20261030/target-before.dump`（均含敏感账号数据，不外发）；nginx 原配置位于 `root@elma-gohan.xyz:/root/4dgs-before-cloud-accounts-20261030.conf`。本机旧容器与应用镜像已清理，但卷仍在；获准回退时先停止云端写入并保全新增数据，核对 `.local/releases/cloud-81.71.154.125-20261030/images.tar.gz.sha256` 后 `docker image load --input .local/releases/cloud-81.71.154.125-20261030/images.tar.gz`，再将 backend `parallel-upload-69f8904` 和 gateway `multi-file-ebf930c` 打回本机 Compose 所用的 `infra-v1` 标签，重建服务以挂回原卷。随后恢复隧道及中继原配置，`nginx -t`、reload。云端已有新增写入时，不能直接恢复旧快照或切回本机丢弃它们；回退恢复演练未执行。


## 存储组件约定

`ar.storage.enabled` 默认关闭，保留现有本机 Demo 启动方式。Compose 显式启用并配置根目录和大小限制。组件只接受 UUID 及小写 SHA256；存储标识为 `<uuid>.bin`，不接受用户文件名、绝对路径或下载 URL。

1. `store(descriptor, input)`：同一文件锁内流式写 `staging/<uuid>.part`，一次读取同时计算大小与 SHA256，刷新后原子重命名为 `.ready`，再创建 `committed/<uuid>.bin` 的硬链接并清理 `.ready`。硬链接让完整文件一次可见，且目标存在时不能覆盖；大小或摘要不符、输入中断时不产生正式文件。正常成功后不再重读内容。调用方负责关闭输入流。
2. 重试：同一 UUID 已有完整且校验通过的 `.bin` 或 `.ready` 时，`store` 只验证一次后复用，不覆盖也不读取新输入。内容不符时 `store` 抛出未确认遗留错误且不删除正式文件；上传服务仅对尚未 `AVAILABLE` 的文件删除这份遗留后再接收。锁冲突返回可重试的 I/O 错误，由应用服务映射 HTTP 状态。
3. `recover(descriptor)`：只处理已有的 `.bin`/`.ready`，至多对保留字节验证一次。正式文件匹配时直接清理遗留 `.ready` 并返回 true；仅有 `.ready` 时验证后提交；只有 `.part` 或没有文件返回 false，不把不完整数据当成功；内容不符抛出 I/O 错误。不以修改时间代替内容验证。
4. `open`/`size` 只负责读取，业务层必须先完成访问授权；读取路径不计算摘要。
5. `inventory`：列出可识别的 `.part`、`.ready`、`.bin` 文件、大小、时间和阶段。重启后可见遗留状态；下次同 ID 上传可替换中断的 `.part`。不自动删除正式文件，不自动推定它是否已登记或发布。

每个 UUID 使用操作系统文件锁，锁文件长期保留，避免删除锁文件引入并发竞态。根目录只能由后端及受控维护工具写入；不支持其他进程直接修改正式文件。拒绝符号链接和非普通文件，目录必须位于同一个支持文件锁、原子重命名和硬链接的本地文件系统，不支持跨卷拼接或 NFS。没有针对断电或磁盘控制器缓存作持久性承诺。

这是独立存储组件，不是数据库一致性实现。应用服务先登记待处理记录，`store` 成功后再提交可用状态；重启时只对未完成记录用盘点结果调用 `recover`。不能因为 `store()` 成功就对客户端开放文件。

## 验证

Java 单元测试使用 Java 21，经项目入口执行，按风险选择模块：

```powershell
python scripts/check_java.py --module ruoyi-ar
```

容器验收只使用独立项目、端口和配置，会创建合成场景与文件：

```powershell
python scripts/prepare_compose.py --test --max-bytes 1048576
docker compose -p innovation-ar-resource-platform-infra-check --env-file config/compose-test.env up -d --build
python scripts/verify_infrastructure.py --recreate
docker compose -p innovation-ar-resource-platform-infra-check --env-file config/compose-test.env stop
```

准备脚本拒绝覆盖已存在的配置，重复验收时跳过第一行。不要在这个专用测试项目中创建日常管理员，测试脚本使用它的引导账号。`--recreate` 重建该项目的容器并验证场景记录及合成文件保留，不删除卷。

结果见 [验证记录](06-validation.md)。单元测试及 HTTP 检查不能代替真实包体、客户端渲染、磁盘写满、断电或物理 Linux 服务器迁移验收。

## 迁移到 Linux 的操作边界

允许维护窗口，暂不设置自动备份、RPO/RTO 或高可用目标。迁移准备仍需完成以下流程：

1. 记录代码、实际镜像 ID、数据库版本、Compose 配置和持久卷清单。通过 `docker image save`/`load` 传输已验收应用及依赖镜像，目标架构必须兼容；配置与密钥通过私有渠道传输。
2. 停止源环境网关与后端，保持 PostgreSQL 运行。确认没有其他文件写入者。
3. 在 PostgreSQL 容器中用 `pg_dump -U innovation -d innovation_ar_resource_platform -Fc -f /tmp/innovation-ar-resource-platform.dump` 导出，再用 `docker compose cp` 复制到宿主。避免 PowerShell 文本重定向处理二进制 dump。
4. 用一次性维护容器只读挂载成品卷，归档所有文件，并记录相对路径、大小、SHA256。保留暂存状态供后续排查；只迁移文件不改变其业务状态。框架文件及需保留的日志单独归档。
5. 目标启动新 PostgreSQL，在尚未启动后端的空库中执行 `pg_restore --exit-on-error --no-owner --no-privileges`；不要向已有业务库直接恢复。成品恢复到新命名卷，恢复后端 UID/GID 10001 的读写权限。
6. 核对数据库记录和逐文件摘要，启动相同版本应用，检查登录、场景、审计、文件引用、发布关系及真实客户端下载。
7. 验收后切换服务地址，源环境保持停止且保留数据。若回退，先停止目标写入，再切回源；目标已有新增数据时不能直接回退而丢弃它。

云端新部署与账号跨主机迁移已完成；上述整库及成品卷的完整跨主机迁移未执行，用户最终明确只迁移账号。不能将账号一致性核对当作文件迁移、真实日常账号密码登录或 Unity 客户端验收。
