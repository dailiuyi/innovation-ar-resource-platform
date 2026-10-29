# 基础 Harness

先按 [专项优先流程](16-fast-review.md) 执行需求对应的最短检查，再按风险选择 profile。Java 专项使用 `scripts/check_java.py`；账号 HTTP 与同提交人工实例使用 `scripts/review.py`。通用 ingestion 不替代专项验收，也不是所有改动的默认门槛。

Harness 把仓库约束、验证脚本与交接记录组织成统一工作流。Harness 本身是验证入口，不调度模型、不修复、不合并、不部署。Symphony 的固定任务控制器调用该入口，并单独管理一次修复和持久化终止状态。

## Agent 安装与构建复用

受控 Symphony 任务由程序调用入口，编码模型不自行执行。人工使用 `python scripts/agent_check.py --profile frontend`（无前端变更用 `quick`）。它运行 harness，由前端构建控制器在同一文件锁内准备依赖和构建，并保存 `.local/frontend-control/handoff.json`：`container_checks_passed`、`code_check_failed` 或 `environment_blocked`。前端 profile 已包含 quick，不需重复执行两个 profile；专项业务验收仍由任务要求决定。

`frontend_control.py` 在每个工作区独立保存安装和构建记录，OS 文件锁避免并发重复操作，进程退出自动释放锁。第一次无可信记录时执行一次 `npm ci --prefer-offline --no-audit --no-fund --include=dev`，随后核对锁文件、npm 配置、Node/npm/平台、相关环境和已安装包内容再复用；不共享任务 node_modules。暖依赖的一次实际构建只做一次构建前依赖内容扫描，构建后再扫描一次验证输入稳定；外层 agent_check 不重复预扫描。缺少依赖由构建控制器安装，frontend doctor 只核对工具链可用性；ingestion 仍要求已有前端依赖。完整内容校验本身有 I/O 成本，但能发现依赖删除或损坏。Vite 开发缓存 `.vite`、`.vite-temp` 和 `.cache` 不参与依赖摘要。

构建键包括整个 frontend 输入（含未跟踪和忽略的 `.env`，排除 node_modules/dist/.git）、依赖内容、运行环境和控制器版本。仅成功记录、输入相同且 dist 内容完整一致时复用；报告 `mode=reused` 并引用原构建日志，不伪装为本轮重新构建。文档变更不强制重建前端，前端源码/配置/依赖变化会失效。构建过程中输入变化不算通过。

单次构建上限 900 秒，每 30 秒输出耗时和日志位置。相同输入失败、超时或中断后保留状态，不再自动重试；代码失败仍返回 failed，不能变成“仅环境待验收”。调查并修复后，使用 `python scripts/agent_check.py --profile frontend --retry-reason "具体修复条件"` 明确重试一次。不要绕过入口再次直接运行 npm 构建。历史无记录 dist 不自动采信。

quick、成品包解析测试、浏览器、数据库和真实业务验收不缓存；复用构建不是业务验收或合并批准。当前环境指纹针对本项目 Vite 配置使用的 VITE_/NODE_/NPM_CONFIG_/AR_/SASS_、CI、PATH、语言/时区和 SOURCE_DATE_EPOCH；以后新增其他构建环境输入或外部文件读取时须扩展指纹。记录保存在 `.local/`，不打印环境变量或 npm 配置值。

## 使用

在仓库根目录运行（入口也支持从其他目录调用）：

```powershell
python scripts/harness.py doctor --profile quick
python scripts/harness.py check --profile quick
python scripts/harness.py doctor --profile frontend
python scripts/harness.py check --profile frontend
python scripts/harness.py doctor --profile ingestion
python scripts/harness.py check --profile ingestion
```

| Profile | 检查范围 | 前置条件 |
|---|---|---|
| quick（默认） | Harness 故障回归、审查工具回归、Symphony 模型路由协议回归、OpenAPI/Schema/示例、生成源一致性、AGENTS/README/docs 递归本地链接 | Python 3.11+、Git、requirements-review 中的契约验证依赖 |
| frontend | quick + 成品包解析消费者行为测试（`scripts/test_scene_package.mjs`）+ Vue 生产构建 | Node、npm、已通过 npm ci 安装的前端依赖 |
| ingestion | quick + 成品包解析测试 + 已测试 Jar 上的 Windows 隔离入库 API/Edge 验收（版本导入、逐文件上传与恢复、发布、整版删除） | Windows、项目 .local 中 PostgreSQL 17/JDK 21、Redis、Node、前端依赖、psycopg、Playwright、Edge，以及同源码由 `scripts/check_java.py --module ruoyi-admin --package` 产出的 `backend/ruoyi-admin/target/ruoyi-admin.jar` |

`doctor` 只探测所选 profile 的必要环境，不安装依赖、不启动应用、不连接日常数据库。Python 同时搜索当前解释器和 `.local/python`；缺依赖时按输出提示准备。版本和路径沿用已有入库脚本的约定。Node 还会对现有回归脚本进行路径访问探测；如沙箱拒绝读取项目父目录，应申请对应命令的沙箱外权限，不修改业务代码绕过限制。

`ingestion` 不再自行构建后端：不复制源码，也不运行 Maven，只复用同一源码已由 `check_java.py --package` 执行并通过全部测试后产出的 Jar（缺失则 doctor 阻塞）。旧的 `export-path-migration`（只验证已完成的 V013 历史行为，脚本 `verify_export_path_migration.py` 保留为独立历史脚本）和 `backend-package` 步骤随旧 Windows 流程移除。测试使用随机回环端口、新数据库、新存储目录和合成账号。不会启动 Docker、重建网关或操作现有 Demo 账号。

Linux 上的真实验收不走 Windows profile，而是用 `scripts/prepare_4dgs_check.py` 启动固定的隔离 Compose 实例（项目 `innovation-ar-resource-platform-infra-check`，`127.0.0.1:18082`，不使用日常 18081/43174 或 `config/compose.env`），再运行 `scripts/verify_ingestion.py --base-url http://127.0.0.1:18082 --admin-base-url http://127.0.0.1:18082/prod-api --credentials-file <runtime.json 中的 credentialsFile> [--browser-executable /opt/google/chrome/chrome]`（等价于 `run_http_checks`）。`prepare` 只用已有镜像、已测试 Jar 和已交付的前端 dist，凭据 0600 且不打印，`stop` 只 `compose stop` 并保留数据。quick 和合成 UI 检查都不是该全链验收。

真实样包与参考播放器闭环原由 `scripts/verify_4dgs.py --runtime <runtime.json> --samples-root <样本目录> --sample-descriptors <描述目录> --viewer-root <参考播放器副本> --browser-executable /opt/google/chrome/chrome --report-dir <.local 下目录>` 执行；该脚本与参考播放器适配仍读取已删除的 `descriptor`/`variants`，自 2026-10-29 起对 0.5.0 接口不可用，按用户决定保留原状、不维护。以下为原用法记录：只接受固定的隔离实例；退出码 0 全部通过、1 有检查失败、2 输入或运行时不可用、4 已执行项全部通过但有被阻塞项（报告 `verify-4dgs.json` 的 `blocked`）。`prepare_4dgs_check.py prepare` 同时给测试后端开启仅含文件读写事件的 JFR（`JAVA_TOOL_OPTIONS`，写入后端日志卷，正常停止时转储），可选 `--reference-viewer DIR` 只读挂入参考播放器副本。无头 Chrome 默认回退到 SwiftShader 软件渲染，需 `--use-gl=angle --use-angle=gl-egl --ignore-gpu-blocklist` 才使用本机 NVIDIA GPU，`verify_4dgs.py` 同时记录两种渲染器。详见 [真实样包验收记录](20-4dgs-sample-validation.md)。

## 报告与完成判定

每次调用创建独立 `.local/harness/<UTC时间>-<随机标识>/`，保存 `report.json`、逐步日志、专项证据和必要的构建产物。目录沿用 `.local/` 忽略规则，不自动清理。日志和测试目录可能包含运行时敏感信息，应留在本机；正式共享前检查脱敏。

- `passed` / 退出码 0：所选范围执行通过；doctor 的通过仅表示环境就绪。
- `failed` / 退出码 1：命令失败、契约漂移、断链或证据不完整/不通过。
- `blocked` / 退出码 2：缺环境、超时、中断、清理未完成，或检查过程中源码变化。
- `skipped`：前置检查阻塞或前一步未通过，后续没有执行；不能当成通过。

报告包含 UTC 时间、命令、工作目录、退出码、日志路径、Git HEAD 及包含未提交/未忽略新增文件的源码 SHA256。开始和结束指纹必须一致；恢复任务时需重新核对指纹，不能仅凭旧 HEAD 或旧绿色报告宣告完成。忽略的运行时文件和依赖不属于源码指纹；环境结果仅对应本次本机环境。

契约和入库步骤同时要求进程成功与非空、全部通过的结构化证据。除上述带输入和产物校验的前端构建外，不读取过去的报告补齐结果。每步有时限，遇错停止后续步骤；超时/中断尝试停止本次子进程树，并停止本次证据目录下遗留的 PostgreSQL。主机崩溃或直接强杀整个 harness 无法保证执行清理，应检查该运行目录和进程，不得扩大到日常 Demo。

`verify_design.py` 和 `verify_ingestion.py` 支持 `--report-dir`；未指定时保留写入 docs 的旧行为。入库脚本的 Windows 模式使用 `--backend-jar`，harness 只验收固定路径的已测试 Jar；单独运行仍需自行确认 Jar 与源码一致。`verify_design.py` 只验证当前 OpenAPI（`scripts/generate_contracts.py` 同源）和文档链接，数据库约束由真实 PostgreSQL 验收承担；`contracts/` 中的 runtime-manifest 是历史静态资料，不再生成也不是当前门禁。

## 怎么选检查

文档、契约、规则修改先跑 quick。纯文案/按钮还需按开发工作流检查引用该控件的选择器；frontend profile 不代替人工视觉检查，视口与列宽类布局可用 `scripts/verify_scene_list_ui.py`（Vite 加真实浏览器、Playwright 返回合成响应，不连后端）先做专项自查。前端行为改动跑 frontend；涉及入库、文件删除、恢复、审计或对应鉴权时跑 ingestion。账号等其他业务仍需对应专项验收，当前 harness 不宣称覆盖所有业务。

入库 profile 不运行历史候选七表数据库验收，也不再运行 V013 历史迁移验证；候选结构校验不属于已实现业务的数据库证明。Docker Nginx 路由、LAN、真实客户端加载仍需独立验收。

正式证据的保存和引用遵循 [证据索引](evidence/README.md)。将真实验收摘要加入 [验证记录](06-validation.md)；需要提交专项 JSON 时只提升人工核对后的证据，避免把本机绝对路径或敏感日志一起提交。扩展入口时先明确测试环境、副作用和完成证据，再加入 profile。以后是否接 CI 或 Agent 调度，见 [基础决策](decisions/0001-harness-baseline.md)。

任务控制、字节发布和构建复用的回归测试由只读执行工具提供；旧 PR 缺少新工具测试时仍执行中央工具测试，不将零测试视为成功。源码中的业务测试仍按该提交执行。新任务计划、停止和恢复规则见 [Symphony](15-symphony.md)。
