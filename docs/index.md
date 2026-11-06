# 仓库知识入口

本页负责导航；具体行为以对应实现、迁移、契约和同版本验证证据共同确认。发现文档与代码不一致时先说明差异，不把旧设计直接变成当前需求。

## 现行手册

| 要回答的问题 | 入口 | 使用边界 |
|---|---|---|
| 收到口头需求、准备 Issue、审查 PR 或接手任务时先做什么 | [Agent 工作流入口](17-agent-workflow.md) | 先判断职责和用户授权，再进入对应手册；不依赖旧聊天 |
| 当前平台实现了什么 | [资源入库闭环](12-resource-ingestion.md)、[项目介绍](../README.md) | 管理员单场景单模型、固定文件清单、上传即发布、启停、场景级物理清理与匿名下载；本地源码不代表日常环境已升级 |
| 客户端如何对接接口 | [客户端接口对接文件](21-client-api.md)、[Unity 对接技术文档](22-unity-integration.md) | 0.6.0 场景/文件身份，无版本字段；用户确认既有客户端已解压解码跑通，本次只做资源分发 |
| 当前平台如何组成 | [当前架构](11-current-platform-architecture.md) | 结合现行实现核对；后续设计不等于已有能力 |
| 如何开发、启动、打包，并查看部署记录 | [开发工作流](development-workflow.md)、[Windows 原生手册](08-demo-runbook.md)、[容器与环境手册](10-local-infrastructure.md) | 环境分工和带日期部署记录以 10 为主体；其他入口只导航，不复制当前实例状态 |
| 下载参考工具如何工作 | [资源传输参考](11-artifact-transfer-reference.md) | 场景下载使用 download_scene.py，复用单文件 Range/If-Range；通用打包扩展不是当前业务流程 |
| 上游来源与本地适配 | [若依来源与适配记录](09-upstream-adaptation.md) | 固定上游提交、后端/前端改动与升级边界；本地验收不等于生产部署评估 |
| 应该跑什么检查 | [Harness 使用说明](13-harness.md) | profile 通过只覆盖声明的范围 |
| 人工阅读业务代码，从哪里开始 | [业务代码 Review 导读](23-code-review-guide.md)、[ruoyi-ar 分包说明](../backend/ruoyi-ar/README.md) | 源码调用链、状态与事务/文件边界；不替代独立审查 |
| 如何审查改动 | [Code Review 默认规则](14-code-review.md) | 短提示指定范围与重点，默认独立审查、不修改 |
| 如何快速验收并提供预览 | [专项检查与审查实例](16-fast-review.md) | 先需求专项，固定提交目录，独立审查后交付回环实例 |
| API 与数据库在哪里 | [OpenAPI](../contracts/openapi.yaml)、[数据库说明](../database/README.md) | OpenAPI 只描述当前实际接口；实际迁移在 backend 的 db/demo |
| 为什么作出某项决定 | [决策记录](decisions/README.md) | 记录原因、约束和重新考虑的条件 |
| 如何核对或恢复 Agent 环境 | [环境版本与自检](18-symphony-environment.md) | 镜像/控制器配套、轻量自检与构建并发；不替代宿主业务验收 |
| 如何运行开发任务调度 | [Symphony 本地安装](15-symphony.md) | GitHub Issue 标签入队，草稿 PR 等待人工审查；Windows review/ingestion 与 Linux 隔离 Compose 验收分别按手册执行 |

## 待实施方案

| 要回答的问题 | 入口 | 使用边界 |
|---|---|---|
| 当前简化业务与后续云架构的关系是什么 | [管理员单场景方案与长期调研](24-4dgs-content-platform-proposal.md) | 当前已授权管理员单模型、上传即发布和启停；普通用户、OSS/CDN、审核与 GPU 是后续范围 |
| 深圳试点大资源如何传输和存储 | [公网分发架构建议](19-public-resource-delivery-proposal.md) | 云主机挂盘、CDN 回源与对象存储预留等仍待批准实施；不代表所有部署都未实施，实际部署记录见[容器与环境手册](10-local-infrastructure.md) |

## 历史证据与任务

| 要回答的问题 | 入口 | 使用边界 |
|---|---|---|
| 以前验证过什么 | [验证记录](06-validation.md)、[证据索引](evidence/README.md) | 历史报告只对应所记日期与基线，不证明当前未提交修改或后续业务通过 |
| 如何跨会话交接 | [任务管理](tasks/README.md)、[4DGS 成品重构任务](tasks/active/2026-10-29-4dgs-resource-refactor.md)、[任务控制](tasks/active/2026-09-20-task-control.md)、[4DGS 格式核查](tasks/active/2026-10-23-4dgs-format-discovery.md) | 任务记录进度和当时边界，完成后归档 |
| 4DGS 真实样包验收（旧基线） | [真实样包记录](20-4dgs-sample-validation.md) | 对应旧描述与参考播放器基线；现行接口见 21，资源清单见 12 |

`docs/01` 至 `docs/05`、`docs/07`、[历史汇报页](presentation.html)、`docs/images/`、根目录 `database/migrations/` 与 runtime-manifest 保留历史候选设计。旧任务、决策及验收中的“当前”只对应所记基线，不沿用草稿、昼夜、ZIP 或多版本流程。现行单场景固定文件与读取链路由 12 与 21 承接，`resource.json` 普通文件无特殊语义。

新增长期规则时指定对应文档和验证方式。优先补一个能发现实际错误的检查，避免反复追加大段提示词。尚不能自动检查的约束，明确由任务负责人审查。
