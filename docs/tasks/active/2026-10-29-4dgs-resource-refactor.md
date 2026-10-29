# 4DGS 成品管理与客户端分发重构

状态：进行中。负责人：Main。更新时间：UTC 2026-10-29。

## 目标与验收

一个场景对应一个独立 4DGS 重建成品；同一内容版本同时包含多个模型档位和公共配置、媒体文件。删除场景地址、经纬度和坐标系；保留 Spring Boot、Vue、PostgreSQL、本地 ArtifactStorage 和后台账号。内部 Demo 客户端最终匿名读取已发布资源，支持按段在线加载和按档位完整下载。旧业务数据不保留，干净切换，不做旧草稿迁移或旧 API 别名。

- 完整分阶段计划：本地工作树 `.local/PLAN.md`（不入库）。五阶段按顺序交付：1 删除地点模型和固定成品描述、2 合并正常入库校验、3 成品版本业务与后台调用方切换、4 匿名读取与完整下载参考工具、5 真实样包与 4DV 参考客户端闭环。
- 范围外：推送、合并、日常 Compose/数据库/LAN 部署、Android/iOS 真机验收。
- 分支 `codex/4dgs-resource-refactor`，独立工作树 `.local/worktrees/4dgs-resource-refactor`。

## 进度与决定

- [x] 阶段 1：删除地点模型，新增 `resource.json` v1 描述校验（提交 5f090d6）。隔离 PostgreSQL 17.6 空库与 V013 升级库门禁通过（`.local/stage1-gate/report.json`，40 项）。
- [x] 阶段 2：存储接口收敛为 `store`/`recover`（提交 530c877）。存储门禁通过（`.local/stage2-gate`/`.local/stage2_gate.py`，44 项）。
- [x] 阶段 3：成品版本业务、后台与调用方切换（后端 f2b09b1、前端 31ccec3、工具 92786e3，集成修复 f519283、faeafaa、fbe07da）。后端门禁（V015 空库/升级、HTTP 生命周期、删除失败 503 与启动恢复）58 项通过；经隔离网关的集成门禁、真实 Chrome 后台操作见下。`scripts/test_scene_package.mjs` 与 `agent_check.py --profile frontend` 的全量结果由主代理统一运行并记录。
- [ ] 阶段 4、5。

已确认决定：

- V015 迁移是破坏性清洁切换，只在隔离验收库执行，日常库另需授权。
- 当前 OpenAPI 只含保留或新增的管理接口；匿名客户端接口到阶段 4 才加入。`runtime-manifest` 作为历史静态资料保留，不再由生成器生成。
- `scripts/verify_export_path_migration.py` 只验证已完成的 V013 历史行为，保留为独立历史脚本，不再是当前门禁。
- Linux 真实验收走 `scripts/prepare_4dgs_check.py` 启动的固定隔离 Compose 实例，不使用 Windows 专用 ingestion profile。

未解决问题：无。

## 验证证据

阶段 3 集成门禁（隔离实例 `127.0.0.1:18082`，项目 `innovation-ar-resource-platform-infra-check`，已测 Jar 由 `check_java.py --module ruoyi-admin --package` 产出：50 项测试，0 失败/错误/跳过；前端 dist 由 `frontend_control.py build` 构建；全部流量经 Nginx 网关）：

- `scripts/verify_ingestion.py` 外部模式（含 Chrome 1440/1024）78 项通过，含 21 MiB 文件经网关上传与物理删除；报告 `.local/4dgs-check/evidence/validation-ingestion.json`。
- 网关行门禁 `.local/stage3_gateway_gate.py` 20 项通过：上传中断后只有该文件 FAILED、同一 versionId 继续上传且已完成文件 attempts 不变、整版删除存储失败 503 后重试成功且保留回执、遗留删除意图经后端重启完成且字节不恢复、被删请求键迟到创建返回 410。报告 `.local/4dgs-check/evidence/stage3-gateway-gate.json`。
- 真实 Chrome（`/opt/google/chrome/chrome`）后台门禁 `.local/stage3_ui_gate.py` 19 项通过：1440x1000 与 1024 宽下导入目录、中断后继续、发布 V1、导入并替换发布 V2、删除非发布 V1，无遮挡/裁切/重叠/横向溢出，21 MiB 文件经网关成功；截图在 `.local/4dgs-check/evidence/ui-*.png`。
- 门禁发现并修复的缺陷：1024 宽版本列表固定列过宽导致操作列被裁切、发布卡片依赖接口未提供的文件数/大小（f519283）；`prepare_4dgs_check.py` 重复运行时容器 ID 为 bytes 导致所有权检查失败（faeafaa）；验证脚本将 V2 发布审计中的 `fromVersionId` 误计入 V1，并在滚动区外误判按钮遮挡（fbe07da）。
- 已清理本任务阶段 1/2/3 后端门禁遗留的已退出容器与对应网络（仅 `-stage1-`/`-stage2-`/`-s3be-` 后缀）。

结果：阶段 1-3 门禁通过。阶段 4、5 未开始；浏览器证明不等于 Android/iOS 真机验收。

## 交接与恢复

工作模式与当前阶段：普通本地开发，阶段 3 门禁完成，待进入阶段 4。用户已授权：本地独立分支与隔离验收；不推送、不合并、不更新日常实例。

下一步：阶段 4 匿名读取、Range 补全与 `scripts/download_scene.py`。隔离实例 `.local/4dgs-check` 仍在运行，阶段 4 以新 Jar 重新 `prepare`（`prepare` 可重入，复用卷与凭据）。

本任务可能保留的运行资源：固定项目 `innovation-ar-resource-platform-infra-check` 的容器和卷；用 `scripts/prepare_4dgs_check.py stop --report-dir <目录>` 停止，不执行 `down -v`。

## 完成记录

完成时填写。
