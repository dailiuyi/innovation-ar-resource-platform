# Docker 部署与本地成品存储基础设施

格式未定阶段的独立开发工具见 [资源传输参考框架](11-artifact-transfer-reference.md)：提供打包扩展接口和下载续传参考测试，尚未接入本页的 Spring Boot/Nginx 服务。

## 当前实现与交付边界

本阶段已提供四个服务的 Docker Compose 配置：Nginx、Spring Boot、PostgreSQL 17、Redis。业务能力包含账号、场景、成品版本、文件入库与审计。管理员可在后台导入资源目录并上传文件；匿名客户端可只读已发布版本。

`ArtifactStorage` 和 `LocalArtifactStorage` 已实现本地文件暂存、大小/SHA256 校验、不可覆盖确认、读取、校验及文件盘点。存储组件通过场景版本服务接入管理员 HTTP 上传和数据库登记，仍没有公开文件目录。文件确认入库不等于业务发布。

成品版本导入、逐文件上传、发布指针和整版删除已实现，详见 [资源入库闭环](12-resource-ingestion.md)；匿名客户端读取（网关 `/api/v1/client/`）已实现，下载授权不依赖令牌或签名地址。旧候选契约和七表脚本不会参与容器初始化。

## 启动

要求 Windows Docker Desktop 使用 WSL2/Linux 容器，或 Linux Docker Engine + Compose。准备阶段需要联网构建/获取镜像；运行时不依赖云存储。下面命令从仓库根目录执行，Linux 将 `python` 换成 `python3`。

```powershell
# 1 MiB 仅用于合成数据的基础设施验证，不是产品上传限制。
python scripts/prepare_compose.py --max-bytes 1048576 --bind-address 127.0.0.1 --http-port 18081
docker compose --env-file config/compose.env config --quiet
docker compose --env-file config/compose.env up -d --build
docker compose --env-file config/compose.env ps
```

准备脚本使用独占创建生成随机数据库密码、Token 密钥和引导密码，不打印密码，也不覆盖已有文件。`config/*.env` 已忽略且不进入 Docker 构建上下文。Windows 文件权限继承宿主目录权限，应将仓库置于自己的私有工作目录；Linux 新配置权限为 0600。

默认入口为 `http://127.0.0.1:18081`。首次使用 `bootstrap` 和私有配置内的引导密码登录，在账号管理中创建日常管理员；引导账号随即停用。容器数据库是新库，**不包含现有 Windows Demo 的账号和场景**。

内网开放时把 `AR_BIND_ADDRESS` 改成宿主机实际内网地址，再重新执行 `up -d`，并为该端口配置限定来源的 Windows 防火墙规则。客户端使用可配置的服务地址；前端通过同源 `/prod-api/` 代理，不写死机器 IP。当前提供内网 HTTP，未配置公网入口或 HTTPS。

`AR_STORAGE_MAX_BYTES`（单文件上限）是必填的正整数，应按最大模型文件设置；`AR_STORAGE_VERSION_MAX_FILES`（默认 1000）和 `AR_STORAGE_VERSION_MAX_BYTES`（默认 4294967296）限制单个版本。产物入口使用原始字节流，由服务端流式检查上限；Nginx 对精确的 `scene-versions/{versionId}/files/{fileId}/content` 路径关闭请求/响应缓冲和网关字节限制，其他接口继续使用 20m 限制。单服务启动后会对已有文件记录核对本地存储。

## 持久卷与权限

| 卷 | 用途 | 挂载位置 |
|---|---|---|
| `postgres_data` | 数据库 | PostgreSQL 数据目录 |
| `artifacts_data` | 成品存储 | 后端 `/data/artifacts` |
| `framework_uploads` | 与成品隔离的框架目录 | 后端 `/data/framework-uploads` |
| `backend_logs` | 应用滚动日志 | 后端 `/app/.local/logs` |

实际卷名含 Compose 项目前缀。项目名称保持稳定，否则会创建另一组卷。重建容器保留命名卷；`down -v` 会删除卷，不用于日常更新。

当前 Compose 项目名为 `innovation-ar-resource-platform`，数据库名为 `innovation_ar_resource_platform`。数据库登录角色沿用 `innovation`；已有部署改名时必须先备份并迁移原有四个命名卷，不能直接用新项目名启动空卷。本机 2026-09-25 的迁移与保留的旧卷见 [验证记录](06-validation.md)。

后端以 UID/GID 10001 运行。数据库和 Redis 不映射宿主端口，服务间使用 internal 网络；网关是唯一宿主入口。Nginx 不挂载成品卷，预留的成品路径直接返回 404，尚未提供 `X-Accel-Redirect` 或 Range 成品下载。Redis 的 `/data` 使用 tmpfs，不持久化登录会话，重启后重新登录。

PostgreSQL 当前延续 Demo 的初始化/运行同账号模式，该账号拥有较高权限。本阶段用于单机内网 MVP；后续权限拆分需另立迁移方案。健康检查用于确认进程/基础接口可用，不代表客户端业务验收。

镜像使用明确版本标签；应用镜像为 `innovation-ar-resource-platform-backend:infra-v1`、`innovation-ar-resource-platform-gateway:infra-v1`。迁移时应传输实际已验收的镜像并核对镜像 ID，不能把同名标签当作内容相同的证明。

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

Windows 单元测试使用 Java 21，并明确设置项目 Maven 缓存：

```powershell
mvn -f backend/pom.xml -Dmaven.repo.local=.local/m2 -pl ruoyi-ar -am test -B -ntp
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
6. 核对数据库记录和逐文件摘要，启动相同版本应用，检查登录、场景和审计。未来资源模块接入后，还必须核对文件引用、发布关系和真实客户端下载。
7. 验收后切换服务地址，源环境保持停止且保留数据。若回退，先停止目标写入，再切回源；目标已有新增数据时不能直接回退而丢弃它。

本轮验证容器重建持久性，不声称已完成上述跨物理主机迁移。
