当前应用迁移位于 `backend/ruoyi-admin/src/main/resources/db/demo`；V018 将版本文件归到单场景，保留原模型文件与审计。现行行为见[资源入库说明](../docs/12-resource-ingestion.md)，生产迁移须另行备份和授权。本目录其余内容均为历史候选设计，不参与应用初始化。

# V0.1 候选数据库初始化

此目录不参与当前 Demo 初始化。应用使用 `backend/ruoyi-admin/src/main/resources/db/demo`，由 Flyway 执行；详见[启动说明](../docs/08-demo-runbook.md)。

文件管理粒度待成品交付格式确认。本文涉及的平台文件关联、入口和依赖处理属于当前候选方案，确认后再定稿实现。

当前数据库设计包含 7 张表，目标版本为 PostgreSQL 17，尚未部署。

Flyway 按顺序执行以下脚本，初始化空数据库：

1. [V001](migrations/V001__platform.sql)：创建数据表、索引和约束。
2. [V002](migrations/V002__publication_functions.sql)：创建冻结与发布函数。

旧候选方案的 JPA 配置使用 `ddl-auto=validate`，检查数据结构与实体定义是否一致。

## 数据库验证

在仓库根目录执行：

```powershell
python scripts/verify_database.py --pg-bin 'C:/Program Files/PostgreSQL/17/bin'
```

脚本使用独立临时目录、随机端口和随机密码，实例仅监听 `127.0.0.1`，结束后停止。测试目录保留，实际路径与数据库版本记录在[验证报告](../docs/validation-database.json)中。

检查覆盖冻结、文件约束、昼夜版本归属、并发冲突、回滚、撤销和审计。现有结果来自 PostgreSQL 18.4，目标版本 17 仍需复验。

对象存储内容校验、Session 鉴权和 HTTP 行为由应用实现，数据库检查不覆盖这些内容。
