# PostgreSQL Demo 启动与维护

另有 [Docker Compose 部署与本地存储组件](10-local-infrastructure.md)，使用独立数据库卷和账号，不自动导入本文的本机 Demo。资源入库和场景发布指针已接入；预览、单独下线和客户端下载仍未接入，见 [资源入库说明](12-resource-ingestion.md)。

## 已实现范围

单个 Spring Boot 应用提供若依登录、固定同权账号、登录日志、操作日志、场景管理、成品版本、文件入库、场景发布指针和只读业务审计。Vue3 页面复用若依布局及 Element Plus。

本阶段没有对象存储、标记管理、资源预览、单独下线或游客接口。原七表 PostgreSQL 脚本仍是下一阶段候选材料，不参与 Demo 初始化。

## 当前本机入口

- 本机 Vite 前端：http://127.0.0.1:43174
- 局域网 Compose 网关：http://192.168.0.12:43174（使用独立容器后端和数据库）
- 后端：http://127.0.0.1:18080
- PostgreSQL 17.6：127.0.0.1:15432
- 独立 Redis 3.0.504（本机既有版本）：127.0.0.1:16379

当前仅保留 `superadmin`，原密码不变。`bootstrap`、`demo_a`、`demo_b` 已停用并逻辑删除，历史审计保留。早先测试账号文件不再作为登录凭证；依赖这些账号的自动化验收应在独立测试环境运行。

## 首次启动

要求 Java 21、Maven、Node.js、PostgreSQL 17 和 Redis。现有机器已在 `.local/java21`、`.local/postgresql17` 准备便携运行环境。换机器时自行准备对应运行环境，或设置 `AR_JAVA_HOME`、`AR_PG_BIN` 指向安装目录。

在项目根目录执行：

```powershell
python scripts/local_demo.py infra
python scripts/local_demo.py build
python scripts/local_demo.py backend
npm --prefix frontend ci
npm --prefix frontend run dev
```

`infra` 只初始化本项目 `.local/pgdata17`，使用固定本机独立端口。已有实例运行时不要重复执行。前端通过 Vite 代理访问本机后端。`npm --prefix frontend run dev` 按 Vite 配置绑定 `127.0.0.1:43174`，可与绑定 `192.168.0.12:43174` 的 Compose 网关并存。Compose 运行时不要执行 `python scripts/local_demo.py frontend`：该脚本读取 `AR_FRONTEND_HOST`，现有局域网绑定会与网关冲突。

首次运行生成 `.local/demo-secrets.json`，包含数据库密码、Token 密钥与引导密码；无共享默认密码。空库启动后用 `bootstrap` 登录，在账号管理中创建第一个日常管理员。创建成功后引导账号失效，重新使用新账号登录即可。

配置示例见 [demo.env.example](../config/demo.env.example)。应用环境变量：`AR_DATABASE_URL`、`AR_DATABASE_USER`、`AR_DATABASE_PASSWORD`、`AR_TOKEN_SECRET`、`AR_BOOTSTRAP_PASSWORD`、`AR_REDIS_HOST`、`AR_REDIS_PORT`、`AR_REDIS_DATABASE`、`AR_PORT`。启动辅助脚本读取本地秘密文件；直接运行 Jar 时由外部环境提供这些值。

所有本机日志与 PID 文件保存在 `.local/`。停止、重新编译后端：

```powershell
python scripts/local_demo.py stop-backend
python scripts/local_demo.py build
python scripts/local_demo.py backend
```

停止本项目全部本地进程可执行 `python scripts/local_demo.py stop`，脚本核对记录 PID 的命令行后再停止，不按进程名称批量终止其他服务。

## 数据与鉴权

- 应用只加载 `classpath:db/demo` 的 Flyway 迁移；不扫描根目录 `database/migrations`。
- 若依系统表沿用框架主键，场景 UUID、UTC 时间独立管理。`ar_audit` 使用追加式记录和数据库保护触发器。
- 所有日常账号固定关联角色 100。停用和删除最后一个有效管理员被事务锁保护；账号支持确认后逻辑删除，保留历史记录。不能删除当前登录账号，不提供修改角色的入口。
- 账号密码或状态改变时，数据库递增 `credential_epoch`；请求将登录时的版本与数据库比较，拒绝旧凭证。Redis TTL 负责登录会话过期。
- 密码长度 6–64 字符。页面不记住密码，也不把请求正文缓存到 sessionStorage。
- 框架接口保留若依 `code/msg` 语义；AR 接口使用真实 HTTP 状态和 `code/message/traceId` 错误。客户端不能仅靠 HTTP 200 判断框架业务成功。
- 本机数据库账号用于隔离 Demo 初始化和故障注入，具备较高权限。生产部署需要另行设计迁移账号、运行账号、HTTPS、Redis 认证与备份，不可直接照搬本地配置。

## 构建与验收

日常验证按 [专项优先流程](16-fast-review.md) 和 [Harness](13-harness.md) 选择范围：

```powershell
python scripts/harness.py doctor --profile quick
python scripts/harness.py check --profile quick
# 前端行为修改时追加：
python scripts/harness.py doctor --profile frontend
python scripts/harness.py check --profile frontend
```

入库、存储、发布及恢复变更追加 ingestion；账号变更使用专项账号验收。依赖缺失按 doctor 提示准备，修改契约时才运行生成器。报告保存在 `.local/harness/`，不得以旧 Jar 或历史报告代替当前源码验收。

旧 `verify_framework.py`、`verify_demo.py`、`verify_initialization.py` 和 `verify_browser.py` 是历史专项入口，部分会连接固定本机端口、创建场景或修改合成账号，并写入 docs 报告。不要把它们作为日常一键检查；确需复现时先核对连接目标、输出和清理方式，在隔离环境执行。旧初始化脚本会保留独立空库供复核；浏览器脚本使用 Microsoft Edge。

`scripts/adapt_ruoyi.py` 是首次移植的历史辅助脚本，已有应用上会拒绝重跑。日常开发直接修改工程，通过新增 Flyway 迁移演进。

## 升级与下一阶段

升级前先对照上游来源记录和修改清单，重点复核鉴权入口、账号策略、凭证失效和 SQL 方言。通过现有 HTTP、数据库、浏览器测试后再替换依赖；不要整体覆盖当前工程。

资源入库已实现带 resource.json 描述的成品版本、逐文件上传、发布指针和整版删除；匿名客户端读取和播放验收尚未实现。当前使用内网本地文件存储，Demo 不实现场景地址、坐标或昼夜变体。
# 侧栏分组

侧栏按业务分为两个板块：场景管理（场景列表、场景操作记录）和账号管理（账号列表、登录日志、操作日志）。首页继续保留。菜单变更通过 V005 迁移执行，固定角色权限不变；已有页面需刷新以重新加载菜单。

场景操作记录保存场景变更前后的业务内容，与场景修改同一事务提交；登录日志记录登录成功、失败等认证结果；操作日志记录创建账号、调整账号状态、重置密码及修改个人信息等已接入框架日志的管理动作，用于查看操作人、时间和执行结果，不代表所有 HTTP 请求，也不等同于场景变更历史。
