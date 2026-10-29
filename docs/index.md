# 仓库知识入口

本页负责导航；具体行为以对应实现、迁移、契约和同版本验证证据共同确认。发现文档与代码不一致时先说明差异，不把旧设计直接变成当前需求。

| 要回答的问题 | 入口 | 使用边界 |
|---|---|---|
| 收到口头需求、准备 Issue、审查 PR 或接手任务时先做什么 | [Agent 工作流入口](17-agent-workflow.md) | 先判断职责和用户授权，再进入对应手册；不依赖旧聊天 |
| 当前后台实现了什么 | [资源入库闭环](12-resource-ingestion.md)、[项目介绍](../README.md) | 已有场景、账号、成品版本私有入库、场景发布指针、整版删除，以及匿名客户端读取当前发布版本和完整下载参考工具；预览未实现；参考播放器适配工具已有，真实播放未验收，见 [真实样包验收记录](20-4dgs-sample-validation.md) |
| 当前平台如何组成 | [当前架构](11-current-platform-architecture.md) | 结合现行实现核对；后续设计不等于已有能力 |
| 深圳试点大资源如何传输和存储 | [公网分发架构建议](19-public-resource-delivery-proposal.md) | 云主机挂盘与 CDN，预留对象存储；方案未实施 |
| 如何开发、启动、打包 | [开发工作流](development-workflow.md)、[本机手册](08-demo-runbook.md)、[容器手册](10-local-infrastructure.md) | 日常 Demo、隔离验收、LAN Compose 是不同环境 |
| 应该跑什么检查 | [Harness 使用说明](13-harness.md) | profile 通过只覆盖声明的范围 |
| 如何审查改动 | [Code Review 默认规则](14-code-review.md) | 短提示指定范围与重点，默认独立审查、不修改 |
| 如何快速验收并提供预览 | [专项检查与审查实例](16-fast-review.md) | 先需求专项，固定提交目录，独立审查后交付回环实例 |
| 以前验证过什么 | [验证记录](06-validation.md)、[证据索引](evidence/README.md) | 历史报告不证明当前未提交修改 |
| API 与数据库在哪里 | [OpenAPI](../contracts/openapi.yaml)、[数据库说明](../database/README.md) | OpenAPI 只描述当前实际接口；实际迁移在 backend 的 db/demo |
| 为什么作出某项决定 | [决策记录](decisions/README.md) | 记录原因、约束和重新考虑的条件 |
| 如何跨会话交接 | [任务管理](tasks/README.md)、[4DGS 成品重构任务](tasks/active/2026-10-29-4dgs-resource-refactor.md) | 任务记录进度，完成后归档 |
| 如何核对或恢复 Agent 环境 | [环境版本与自检](18-symphony-environment.md) | 镜像/控制器配套、轻量自检与构建并发；不替代宿主业务验收 |
| 如何运行开发任务调度 | [Symphony 本地安装](15-symphony.md) | GitHub Issue 标签入队；草稿 PR 等待人工审查，Windows 入库验收另行执行 |

`docs/01` 至 `docs/05`、`docs/07`、根目录 `database/migrations/` 和 `contracts/` 中的 runtime-manifest（不再由生成器生成）包含历史候选设计。它们的结构检查可以通过，但不表示当前 Spring Boot 已提供相应接口。

新增长期规则时指定对应文档和验证方式。优先补一个能发现实际错误的检查，避免反复追加大段提示词。尚不能自动检查的约束，明确由任务负责人审查。
