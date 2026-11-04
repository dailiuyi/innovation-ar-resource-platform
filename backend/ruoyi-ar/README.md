# ruoyi-ar 业务模块

2026-11-04 按职责分包，供开发和人工审查使用。业务阅读顺序与状态流转见 [代码 Review 导读](../../docs/23-code-review-guide.md)。本模块仍使用单 Spring Boot 实例和私有本地存储，不新增服务或数据库表。

```text
src/main/java/com/ruoyi/ar/
├── controller/  SceneController、SceneVersionController、ClientSceneController
├── dto/         场景、启停、版本创建/编辑/发布和文件清单请求
├── service/     SceneService、SceneVersionService、ClientSceneService
├── mapper/      SceneMapper（MyBatis）
├── storage/     ArtifactStorage、LocalArtifactStorage
├── config/      ArtifactStorageConfiguration
├── exception/   ArExceptionHandler
└── support/     RelativePath、HttpRange
```

| 包 | 职责与依赖边界 |
|---|---|
| controller | HTTP 参数与角色校验、响应状态；调用 service，使用 dto，不直接访问数据库 |
| dto | 请求数据、Bean Validation 和 OpenAPI 元数据；不依赖 controller/service；Java 类型使用业务全名 |
| service | 业务规则、事务、版本锁、状态变更、审计及启动对账；依赖 dto、mapper、storage、support，不依赖 controller |
| mapper | 现有场景/审计 MyBatis SQL；不反向依赖 service/controller |
| storage | 文件接收、校验、正式提交、读取、恢复及删除；不操作业务表、不决定场景是否发布 |
| config | 按 ar.storage.enabled 装配存储 Bean |
| exception | AR 控制器异常到 HTTP 响应的统一映射，advice 范围仍覆盖 com.ruoyi.ar 子包 |
| support | 路径规则与 Range 协议工具；不编排业务事务 |

版本与客户端查询原有的 JdbcTemplate SQL 仍保存在对应 service，事务和锁边界未拆分；这次完成包结构和 Controller/DTO 依赖整理，没有重写持久化实现。现有 Map 响应也保持原样，没有增加无实际用途的 Entity、Service 接口或 impl 层。

请求类型独立文件：SceneInput、SceneEnabledInput、SceneVersionFileInput、SceneVersionCreateInput、SceneVersionEditInput、SceneVersionPublishInput。由内部 record 提取出来的类型显式保留原 OpenAPI schema 名（EnabledInput、FileInput、CreateInput、EditInput、PublishInput），防止仅因 Java 重命名改变已有文档引用；HTTP 字段和校验规则不变。

测试在 `src/test/java/com/ruoyi/ar/` 下按 service/support/storage 对应分包。ClientSceneServiceTest 留在 service 包内测试包级可见辅助方法，没有扩大生产方法可见性。

MyBatis 使用项目已有的 `@MapperScan("com.ruoyi.**.mapper")`；移除 AR 根包额外扫描。Spring 组件扫描、Knife4j 的 packages-to-scan 和异常 advice 都继续覆盖 com.ruoyi.ar 子包，实际启动后检查这些配置，不仅以编译通过判断扫描成功。

验证入口：`python3 scripts/check_java.py --module ruoyi-admin --package`（从仓库根目录执行，需 Java 21+），随后执行 quick 与隔离 HTTP 检查。具体本轮命令、PostgreSQL 版本、结果和边界见 [验证记录](../../docs/06-validation.md)。

注释约定（2026-11-04）：类注释只说明职责，代码旁只解释业务约束、事务/文件边界和失败恢复。省略方法名已表达的含义及与 Knife4j 重复的说明；完整流程统一见 Review 导读。
