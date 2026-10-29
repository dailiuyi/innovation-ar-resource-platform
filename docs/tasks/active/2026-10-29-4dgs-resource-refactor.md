# 4DGS 成品管理与客户端分发重构

状态：进行中。负责人：Main。更新时间：UTC 2026-10-29。

## 目标与验收

一个场景对应一个独立 4DGS 重建成品；同一内容版本同时包含多个模型档位和公共配置、媒体文件。删除场景地址、经纬度和坐标系；保留 Spring Boot、Vue、PostgreSQL、本地 ArtifactStorage 和后台账号。内部 Demo 客户端最终匿名读取已发布资源，支持按段在线加载和按档位完整下载。旧业务数据不保留，干净切换，不做旧草稿迁移或旧 API 别名。

- 完整分阶段计划：本地工作树 `.local/PLAN.md`（不入库）。五阶段按顺序交付：1 删除地点模型和固定成品描述、2 合并正常入库校验、3 成品版本业务与后台调用方切换、4 匿名读取与完整下载参考工具、5 真实样包与 4DV 参考客户端闭环。
- 范围外：推送、合并、日常 Compose/数据库/LAN 部署、Android/iOS 真机验收。
- 分支 `codex/4dgs-resource-refactor`，独立工作树 `.local/worktrees/4dgs-resource-refactor`。

## 进度与决定

- [x] 阶段 1：删除地点模型，新增 `resource.json` v1 描述校验（提交 5f090d6）。
- [x] 阶段 2：存储接口收敛为 `store`/`recover`（提交 530c877）。
- [ ] 阶段 3：成品版本业务、后台与调用方切换。工具侧已完成：OpenAPI 0.4.0 仅描述实际接口、`verify_design.py` 改验当前契约、harness 改用 `scripts/test_scene_package.mjs` 并移除 Windows 专用 `export-path-migration`/`backend-package`、`verify_ingestion.py` 改为新版本导入/上传/发布/删除并提供 `run_http_checks`、Nginx 管理员 scene-versions 流式 location、Compose 与示例配置改为 `AR_STORAGE_VERSION_MAX_FILES/BYTES` 并移除 ZIP 配置、新增 `scripts/prepare_4dgs_check.py`、删除 `scripts/benchmark_zip_write.py`。后端、前端与隔离集成门禁见各自提交和后续记录。
- [ ] 阶段 4、5。

已确认决定：

- V015 迁移是破坏性清洁切换，只在隔离验收库执行，日常库另需授权。
- 当前 OpenAPI 只含保留或新增的管理接口；匿名客户端接口到阶段 4 才加入。`runtime-manifest` 作为历史静态资料保留，不再由生成器生成。
- `scripts/verify_export_path_migration.py` 只验证已完成的 V013 历史行为，保留为独立历史脚本，不再是当前门禁。
- Linux 真实验收走 `scripts/prepare_4dgs_check.py` 启动的固定隔离 Compose 实例，不使用 Windows 专用 ingestion profile。

未解决问题：无。

## 验证证据

阶段 3 工具侧已执行：`scripts/generate_contracts.py` 重新生成后无漂移，`scripts/verify_design.py` 通过，`harness.py doctor --profile quick` 通过，相关脚本 `py_compile` 通过，`docker compose config` 对示例环境有效。集成门禁（隔离 PostgreSQL 17.6 实例、真实浏览器、JFR）是后续步骤，**尚未执行**，不能以上述静态检查代替。具体命令与结果以本阶段提交说明及后续验收报告为准。

结果：工具侧静态检查通过；集成验收待执行。

## 交接与恢复

工作模式与当前阶段：普通本地开发，阶段 3。用户已授权：本地独立分支与隔离验收；不推送、不合并、不更新日常实例。

下一步：集成门禁——构建已测 Jar（`scripts/check_java.py --module ruoyi-admin --package`）、前端构建（`scripts/agent_check.py --profile frontend`）后，用 `scripts/prepare_4dgs_check.py prepare` 启动 `127.0.0.1:18082`，再运行 `scripts/verify_ingestion.py --base-url http://127.0.0.1:18082 --admin-base-url http://127.0.0.1:18082/prod-api --credentials-file <runtime.json 中的 credentialsFile>`；删除 IO 失败、遗留文件恢复和重启场景需要隔离 driver 控制 backend 与存储，由集成步骤提供。

本任务可能保留的运行资源：固定项目 `innovation-ar-resource-platform-infra-check` 的容器和卷；用 `scripts/prepare_4dgs_check.py stop --report-dir <目录>` 停止，不执行 `down -v`。

## 完成记录

完成时填写。
