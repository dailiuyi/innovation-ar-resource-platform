# ruoyi-ar 业务模块

2026-11-04 业务统一按 `module/scene`、`module/version`、`module/client` 集中阅读完整调用链；跨模块通用的存储、配置、异常和协议工具保留在根包，不为目录对称增加空层。当前开发和 IDEA 审查都在原主目录的 `codex/ar-layers-idea-review` 分支，不再新建 worktree；已有 worktree 保留为此前源码和证据快照，不作为本轮编辑入口。业务流程见 [代码 Review 导读](../../docs/23-code-review-guide.md)。

```text
src/main/java/com/ruoyi/ar/
├── module/scene/
│   ├── controller/  SceneController
│   ├── service/     SceneService
│   ├── manager/     SceneManager
│   ├── mapper/      SceneMapper extends BaseMapper<SceneDO>
│   ├── model/       SceneReq、SceneEnabledReq、SceneDO、SceneVO、AuditVO、Page
│   └── convert/     SceneConvert（MapStruct）
├── module/version/
│   ├── controller/  SceneVersionController
│   ├── service/     SceneVersionService、SceneVersionFileService、SceneVersionRecovery、VersionChecks
│   ├── manager/     SceneVersionManager、VersionConcurrency
│   ├── mapper/      SceneVersionMapper、VersionFileMapper、VersionDeletionMapper（同名 XML）
│   └── model/       四个版本 Req、VersionRows
├── module/client/
│   ├── controller/  ClientSceneController
│   ├── service/     ClientSceneService
│   ├── manager/     ClientSceneManager
│   ├── mapper/      ClientSceneMapper（SQL 在 resources/mapper/client/ClientSceneMapper.xml）
│   └── model/       ClientSceneRow、ClientSceneFileRow
├── storage/     ArtifactStorage、LocalArtifactStorage
├── config/      ArtifactStorageConfiguration
├── exception/   ArExceptionHandler
└── support/     RelativePath、HttpRange、FileContentType
```

| 包 | 职责与依赖边界 |
|---|---|
| module/scene/controller | 收参、校验、HTTP 状态；只调用 Service，返回 VO 或 Page&lt;VO&gt; |
| module/scene/service | 业务判断、事务、操作者和审计动作；经 Manager 访问持久化，在此转换 DO→VO |
| module/scene/manager | 组合分页、写后读取和审计序列化，不控制业务事务或决定 HTTP 错误 |
| module/scene/mapper | 基础 insert/selectById 复用 MyBatis-Plus；修订号更新、软删除、分页和审计 SQL 留在 XML |
| module/scene/model、convert | 必要的 Req、DO、VO 和分页结果；MapStruct 生成实际需要的场景转换 |
| module/version/service | SceneVersionService 管生命周期与版本查询；SceneVersionFileService 管上传、下载、文件状态；二者分别控制原分段事务 |
| module/version/service/SceneVersionRecovery | 数据库初始化后的同步恢复入口，只顺序调用两个业务 Service，不再复制恢复实现 |
| module/version/manager | SceneVersionManager 组合创建、回执完成及审计持久化；VersionConcurrency 是两个 Service 共用的唯一版本锁/在途上传状态 |
| module/version/model、mapper | 复用原查询 record；Mapper 分别负责版本/发布、文件和删除回执，复杂 SQL 仍在 XML，不为使用 BaseMapper 再造实体 |
| module/client | Controller 收参；Service 判断可见性错误并组装响应；Manager 组合分页和详情查询；Mapper 只读持久化。下载跨模块只调用版本文件 Service |
| storage | 文件接收、校验、正式提交、读取、恢复及删除；不操作业务表、不决定场景是否发布 |
| config | 按 ar.storage.enabled 装配存储 Bean |
| exception | AR 控制器异常到 HTTP 响应的统一映射，advice 范围仍覆盖 com.ruoyi.ar 子包 |
| support | 路径规则与 Range 协议工具；不编排业务事务 |

模块依赖向下：Controller → Service → Manager → Mapper；模块间只调对方 Service，不引用其 Manager/Mapper/DO。Service 负责业务与事务，不写 SQL 或 Wrapper；Manager 调用 Mapper。自定义 SQL 只写 XML，基础 CRUD 可由 MyBatis-Plus 生成。只为场景保留 SceneDO/SceneVO 边界；审计直接查询只读 AuditVO，不重复建立 AuditDO。创建与重命名共用 SceneReq，场景及审计分页共用 Page，MapStruct 1.6.3 只承担实际的 SceneDO→SceneVO 映射。不增加 IService/impl、通用 DAO、空壳父类或无用转换器。

保留现有响应 JSON、Timestamp 类型、可空字段和 201/204，不新增 Result 信封。自定义 SQL 位于 `resources/mapper/{scene,version,client}/` 的同名 XML；Java Mapper 只继承基础方法、声明自定义方法和参数，不包含方法实现、SQL 或结果映射注解。版本锁查询在 XML 保留 `useCache=false`、`flushCache=true`。

版本创建仍在同一场景行锁下检查幂等键、分配版本号并写入；清单用 FileSpec record 集合按字段比较，不再拼接字符串 key。上传保持“事务登记 → 事务外文件 IO → 事务提交结果”，删除保持“提交意图 → 事务外删文件 → 删行并完成回执”。SceneVersionRecovery 先调用生命周期 Service 的 recoverDeletions，再调用文件 Service 的 recoverFiles。所有发布、删除、上传和下载共用一个 VersionConcurrency；流式响应结束才释放读锁，不引入锁回收或新的并发机制。

场景请求位于 module/scene/model，版本请求位于 module/version/model：SceneVersionCreateReq、SceneVersionFileReq、SceneVersionEditReq、SceneVersionPublishReq 分别保留 CreateInput、FileInput、EditInput、PublishInput schema 名。请求字段、校验及 HTTP 状态不因 Java 类型或目录改名而改变。公共 MIME 规则位于 FileContentType，文件 Service 不依赖客户端业务 Service。

版本创建边界测试同步迁到 module/version/service，客户端 URL 测试迁到 module/client/service；原断言保留。原 MIME 用例位于 support/FileContentTypeTest，不以复制字段或转发调用测试替代真实 HTTP 验收。

MyBatis 使用项目已有的 `@MapperScan("com.ruoyi.**.mapper")`；移除 AR 根包额外扫描。Spring 组件扫描、Knife4j 的 packages-to-scan 和异常 advice 都继续覆盖 com.ruoyi.ar 子包，实际启动后检查这些配置，不仅以编译通过判断扫描成功。

2026-11-05 使用 MyBatis-Plus 3.5.18 的 Boot 3 starter，移除原 MyBatis starter 和手写 SqlSessionFactory 扫描配置，由自动配置加载 `mybatis-plus` 属性、原 XML 和 `UuidTypeHandler`；PageHelper 继续服务若依分页，排除其带入的旧 starter，不额外启用 Plus 分页插件。来源：[官方安装说明](https://baomidou.com/en/getting-started/install/)。

SceneDO 是已有持久化类型，改为可写 Bean 以支持基础插入和结果映射；主键为原生 UUID，数据库生成 enabled、lockVersion、时间默认值，DO 不出 Service，MapStruct 保持 VO 的字符串 ID。`@TableLogic` 使基础按 ID 查询排除软删除；实际改名、启停、删除仍使用带 expectedVersion 的 XML，不能以通用 updateById/deleteById 替代。版本/客户端的 record 是跨表或裁剪投影，不继承 BaseMapper。版本的 39 条 SQL 原样拆入三个 XML，Manager 在同一 Service 事务内组合它们，不新增 Service 或切分事务。

验证入口：`python3 scripts/check_java.py --module ruoyi-admin --package`（从仓库根目录执行，需 Java 21+），随后执行 quick 与隔离 HTTP 检查。具体本轮命令、PostgreSQL 版本、结果和边界见 [验证记录](../../docs/06-validation.md)。

注释约定（2026-11-04）：类注释只说明职责，代码旁只解释业务约束、事务/文件边界和失败恢复。省略方法名已表达的含义及与 Knife4j 重复的说明；完整流程统一见 Review 导读。

## support / storage 的复用边界（2026-11-05）

通用机制复用现有依赖：范围流使用 Commons IO `BoundedInputStream`，显式开启关闭传播；HTTP 正文使用 `IOUtils.copyLarge` 限长复制并检查短读；附件头使用 Spring `ContentDisposition` 生成 UTF-8 文件名，不再手写编码。没有新增依赖或工具抽象。

项目规则保留在本模块：

- `RelativePath` 负责 NFC、Windows 保留名、大小写与文件/目录冲突；不能用当前操作系统的 `Path.normalize()` 替代拒绝越界。去掉拆分后重新拼接和两份排序副本，以目录前缀查集合判断冲突；删除无业务调用的 `safeExportPath`，不静默改名。
- `HttpRange` 保留单区间 200/206/416、HEAD 不读正文、If-Range 强 ETag 匹配、忽略多区间和超大数字处理。附件头的 ASCII 备用名现在由 Spring 编码，`filename*` 解码后的中文、空格、加号保持不变；不保证头字符串与旧实现逐字一致。
- `FileContentType` 保留白名单，避免通用 MIME 映射改变 `audio/wav` 或将未知 HTML/SVG 当作可显示内容返回。
- `LocalArtifactStorage` 保留流式 SHA256、文件锁、原子暂存与硬链接不覆盖提交。这些是本地存储恢复协议，不能替换成普通文件上传/复制工具。范围校验用 `length > size - offset`，拒绝 long 加法溢出的请求。

调用方持有业务读锁至响应结束；范围流关闭底层文件，构造失败也关闭已打开的通道。盘点不等于数据库对账或并发一致快照；当前恢复保证面向进程中断，不声称已解决掉电和目录项持久化。验证命令与范围见 [验证记录](../../docs/06-validation.md)。
