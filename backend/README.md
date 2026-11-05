# 场景资源平台后端

基于 [RuoYi-Vue Spring Boot 3](https://gitee.com/y_project/RuoYi-Vue/tree/springboot3) 3.9.2，使用 Java 21、Spring Boot、MyBatis-Plus、PostgreSQL 和 Redis。上游许可证保留在 [LICENSE](LICENSE)。这里是本项目的后端，不是完整若依功能演示站。

## 从模块读起

| 模块 | 当前职责 |
|---|---|
| `ruoyi-admin` | Spring Boot 入口、运行配置、数据库迁移、账号和日志 HTTP 接口 |
| `ruoyi-framework` | Spring Security、Token、Web/MyBatis/Redis 配置、审计与请求拦截 |
| `ruoyi-system` | 账号、固定管理员角色、菜单、字典、登录和操作日志的现有依赖 |
| `ruoyi-common` | 框架实际使用的公共模型、异常与工具 |
| `ruoyi-ar` | 场景、版本与匿名客户端模块，以及文件存储和协议工具 |

AR 代码从 [分层目录](ruoyi-ar/README.md) 或 [业务代码导读](../docs/23-code-review-guide.md) 开始。业务模块内部按 Controller → Service → Manager → Mapper，跨模块只调用 Service；基础 CRUD 复用 MyBatis-Plus，自定义 SQL 留在 Mapper XML。不要为层数增加空接口、无用实体或转换器。

框架保留登录、账号、固定角色、菜单、日志、验证码和字典读取依赖。当前不提供上游的代码生成器、任务调度、服务器监控或部门/角色管理页面；不能根据上游 README 推断本项目开放了这些能力。是否可访问由 SecurityConfig 的显式路由白名单决定，其他请求默认拒绝。

## 框架清理边界（2026-11-04）

按实际入口、Java/XML 引用和安全路由白名单清理，不按类名或“若依自带”判断冗余：

- 删除已被 `denyAll` 拒绝的通用上传下载、配置管理、字典维护和日志导出/删除/清空/解锁入口。日志列表、字典按类型读取仍保留；前端同步删除原来无权限的动作、废弃 API 和未使用的上传/富文本/Excel 导入组件。
- 删除 Excel 工具及实体上的导出注解、服务器监控模型、无入口的公告/已读/在线用户/注册服务，以及生成器、调度器残留常量。移除 POI、OSHI、Velocity 声明；前端移除 vue-quill、file-saver 及相应锁文件依赖。
- 删除未被安全配置消费的 `Anonymous` 注解扫描器和注入；显式放行规则、角色检查、Token 失效机制不变。
- 保留配置、部门、岗位、角色的现有底层依赖；它们仍被登录、账号和菜单调用。保留历史迁移、数据库表、许可证及当前文件存储协议，不把源码裁剪变成删数据。

AR 按 Controller → Service → Manager → Mapper 分层；根包 `storage/config/exception/support` 是共享基础能力，不再套一层无用途的 `common` 或 Manager。

## Mapper 整理（2026-11-05）

MyBatis-Plus 3.5.18 Boot 3 starter 替换原 starter；自动配置统一构建 SqlSessionFactory，删除原手工扫描工厂，注册 PostgreSQL UUID 类型处理器。原 XML 和若依 PageHelper 保留，不同时启用两套分页拦截器。

场景 Mapper 基于已有 SceneDO 复用 insert/selectById；修订号更新、启停和软删除仍为显式 XML，避免通用写操作漏掉版本检查、停用与审计。版本 Mapper 按版本元数据/发布、文件、删除回执拆分，39 条自定义 SQL 语义和 Service 事务边界不变。客户端与版本查询投影不为了继承 BaseMapper 再增加实体或通用 Service。

## 验证与运行

从仓库根目录执行：

```bash
python3 scripts/check_java.py --module ruoyi-admin --package
python3 scripts/harness.py doctor --profile quick
python3 scripts/harness.py check --profile quick
```

Java 检查产出 `backend/ruoyi-admin/target/ruoyi-admin.jar`。测试与 quick 不等于 HTTP 或浏览器验收；隔离运行流程见 [开发工作流](../docs/development-workflow.md) 和 [Harness](../docs/13-harness.md)。账号变更需账号专项，场景/文件变更需对应入库、发布、下载和恢复检查。

应用仅加载 `ruoyi-admin/src/main/resources/db/demo` 下的 Flyway 迁移。框架清理不删除历史迁移、生产表或数据，不重置账号/权限。登录凭据、Token 密钥、数据库密码通过私密环境配置提供，不写入源码。

本地整理不包含部署；云端日常服务、旧本机数据卷及用户工作区文件不得顺带清理。当前行为、清理范围与验收结果见 [架构说明](../docs/11-current-platform-architecture.md) 和 [验证记录](../docs/06-validation.md)。
