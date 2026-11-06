# 若依来源与适配记录

## 固定来源

| 工程 | 上游 | 分支 | 提交 |
|---|---|---|---|
| 后端 | https://github.com/yangzongzhuan/RuoYi-Vue | springboot3 | `a51a838b71b446ea27256900efe7ed2faa2a02fd` |
| 前端 | https://github.com/yangzongzhuan/RuoYi-Vue3 | master | `838965c5a18d2c61b73ec30c6e288057aaa08b63` |

保留两个工程的 LICENSE。后端依赖版本由父 POM 固定，Spring Boot 3.5.16；前端使用 package-lock.json 和 npm ci。Java 21.0.12.1、PostgreSQL 17.6 用于本次本地验收，不表示已经完成生产部署评估。

## 后端修改

- Maven：Java 21，PostgreSQL 驱动、Flyway，增加 `ruoyi-ar`；移除 quartz、generator 及无入口的框架闭环与 POI/OSHI/Velocity 依赖。2026-11-05 MyBatis-Plus 3.5.18 Boot 3 starter 替换原 MyBatis starter，PageHelper 排除旧 starter 但保留原分页功能。
- 数据：独立 `db/demo` 迁移替代 MySQL 初始化；系统表保留框架结构，移除上游演示账号和密码种子，初始化单个固定管理角色。
- Mapper：时间函数、日期参数转换、反引号、字符状态比较、祖级列表匹配和分页方言适配 PostgreSQL。当前实际启用的账号、菜单、日志路径已执行验证，未声称上游所有闲置模块均已验证。
- Mapper 扫描：继续使用 `com.ruoyi.**.mapper`；MyBatis-Plus 自动配置加载 XML、别名和 UUID 类型处理器，删除手写 SqlSessionFactory。AR Mapper 均在模块 mapper 包，存储等普通接口不作为 Mapper 注册。基础 CRUD 与复杂 XML 共用同一事务资源。
- 账号：`DemoAccountService` 固定角色、统一密码规则，使用共享角色行锁防止并发停用最后一个管理员；首次日常账号创建后停用引导账号。
- 安全：SecurityConfig 采用方法与路径白名单；关闭注册、文件上传、部门角色配置、在线代码生成、任务调度等入口。凭证版本存入 LoginUser，并在请求中检查数据库状态。
- 响应：未登录返回 HTTP 401，禁止访问返回 HTTP 403。AR 模块独立错误处理及场景修改事务；其余业务响应沿用框架语义。
- 配置：数据库密码和 Token 密钥由环境提供；本地日志归入 `.local`，禁用开发热重载及管理监控公开入口。
- 2026-11-06：移除业务版本层，改为管理员场景直接关联固定文件；新建含完整清单，上传就绪自然可见，启停独立，删除统一清理。V018 保留模型 UUID 和审计，历史版本映射为停用场景，当前调用链见[业务导读](23-code-review-guide.md)。

## 前端修改

- 保留上游登录、布局、动态菜单及日志页面，增加场景、账号、业务审计和修改密码页面。
- 移除注册路由、角色授权等闲置动态路由；替换首页，停用通知组件及布局配置入口。
- 清除预填的演示凭证、记住密码与请求正文缓存；增加真实 HTTP 401 和 AR 错误信息处理。
- Vite 仅监听本机 43174，通过代理连接后端 18080。另增 Docker 内 Nginx 静态站点及同源 `/prod-api/` 反向代理，见 [基础设施说明](10-local-infrastructure.md)。

机器可读的来源及文件清单见 [upstream-lock.json](upstream-lock.json)。升级时应在隔离副本比较这些文件，不直接覆盖。
