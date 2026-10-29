# Symphony 本地安装

新接手的 Agent 先读 [工作流入口](17-agent-workflow.md)，确定自己负责需求准备、受控编码还是独立宿主审查。本页是执行与恢复手册；不要把宿主操作命令交给受控编码模型自行运行。

新增 [专项优先与固定审查入口](16-fast-review.md)。Java 执行镜像目标为 `innovation-symphony:0.0.3-java-v2`（JDK 21/Maven）；是否已切换运行容器以当前状态和验证记录为准。Java 变更须先运行实际测试再交付，宿主审查通过后交付同版人工实例。

Symphony 在独立 Docker 容器中运行，读取 GitHub Issues，使用 Codex 执行任务。它是开发工具，不是 Spring Boot 业务服务，也不改变入库系统的单服务边界。

## 当前配置

- 官方稳定版 v0.0.3；Linux x86_64 发行包已按官方 SHA256 校验。
- Codex CLI 0.154.0；基础镜像 `innovation-symphony:0.0.3`，当前执行镜像 `innovation-symphony:0.0.3-java-v2`，包含预装验证依赖、Temurin 21.0.9 和 Maven 3.9.11。
- 审批策略使用当前 App Server 支持的 `granular`，五类审批字段均设为 false，保留拒绝越权的含义；不要直接复制上游示例中的 `reject` 对象，该 CLI 会以 unknown variant 拒绝创建会话。
- 工作流模板使用 ASCII；v0.0.3 的换行解析使用未启用 Unicode 的正则，可能拆断中文 UTF-8 字节，导致 Jason.EncodeError。中文 Issue 正文在模板解析后注入，进展说明仍要求中文。App Server 握手等待为 60 秒，适应本机首次会话初始化。
- 看板仓库 `dailiuyi/innovation-ar-resource-platform`；配置见 [WORKFLOW.md](../WORKFLOW.md)。
- 最多同时运行 4 个任务，各自使用独立工作区；只领取带 `symphony:ready` 标签的 open Issue。
- 管理页面绑定宿主机回环地址 `http://127.0.0.1:43190/`。
- 安装文件、日志和独立工作区位于忽略目录 `.local/symphony/`，不会进入公开仓库。
- 默认交付 draft PR，等待独立审查；不自动合并或部署。
- 模型与思考深度由 Issue 标签传给独立 stdio 适配器，缺省为 `gpt-6-astra / low`；每次调度校验当前 Codex 模型目录。

容器采用非 root 用户、移除所有宿主 capabilities 并启用 no-new-privileges。[seccomp 配置](../deploy/symphony-seccomp.json) 基于 [Docker 官方默认配置](https://github.com/moby/profiles/blob/main/seccomp/default.json)（源文件 blob：77df9d19e844f4403e41e401aca25ab28861e317，保留 [Apache-2.0 许可证](../deploy/symphony-seccomp.LICENSE)），本项目补充允许 clone、unshare、mount、umount2、pivot_root、setns、chroot、mount_setattr，以便 Codex 的 bubblewrap 在容器内建立用户命名空间与文件系统沙箱。其余默认系统调用限制保留；不使用 privileged、seccomp=unconfined 或 danger-full-access。该放行增加容器可用的命名空间调用面，适用范围仅此开发容器，用户已明确授权其在持有凭据的容器中持续使用。

## 操作

### 管理页面简体中文

本地 v0.0.3 页面补丁入口为 `python scripts/prepare_symphony_zh_cn.py --verify`：校验本机上游模板 SHA256，在 `.local/symphony/data/ui-zh-CN/` 生成中文模板，使用现有发行包的独立 Elixir VM 编译并渲染合成状态。命令不更新运行模块、不重启服务；需先有运行中的 `innovation-symphony` 容器和本机官方源码。

翻译范围包含标题、指标、状态、表格、按钮反馈、空状态、快照错误和页面 `lang=zh-CN`。原始 Agent 消息、错误诊断、JSON 字段、任务编号与模型名保留原文。HTTP API 与调度逻辑不变。

用户已于 2026-09-20 授权本次文案更新例外：仅在 running/retrying/blocked 与 GitHub open ready 队列均为空后，备份并替换 `SymphonyElixirWeb.Layouts`、`SymphonyElixirWeb.DashboardLive` 两个 BEAM 模块，再重启 Symphony；不重建镜像、不操作日常 Demo。本次已应用并在原地址验证中文页面及实时连接，启动清理阻塞时保留归档了四个已关闭任务的剩余工作区；具体证据和备份位置见验证记录。后续重建容器会恢复镜像内英文页面，须重新审查、授权应用；上游版本或源文件指纹变化时脚本拒绝生成，需核对新模板。

本次原模块备份在 `.local/symphony/ui-zh-CN-backup-20260920/`。需要回退时先确认上述空闲条件，停止 `innovation-symphony`，将备份中的两个 `.beam` 文件复制回 `/opt/symphony/.burrito/symphony_erts-16.4_0.0.3/lib/symphony_elixir-0.0.3/ebin/`，再启动同一容器并检查页面及 `/api/v1/state`。不要删除 data 或任务工作区。

### 实时会话详情（只读）

在另一个终端运行 `python scripts/symphony_viewer.py`，打开 `http://127.0.0.1:43191/`。
页面每两秒读取独立 Codex 会话日志，可切换会话、搜索已加载记录、展开工具调用及返回结果、跟随最新记录和暂停刷新。
页面暂停只影响显示，不暂停 Agent。历史记录分批加载；调度状态单独读取 43190 的只读接口，调度离线时仍可浏览日志。
服务仅绑定本机回环地址，不提供控制任务或修改文件的接口，也不需要重启 Symphony。
工具输出以日志实际保存的内容为准，已截断内容无法还原；不展示模型内部推理。
终端关闭或按 Ctrl+C 即停止详情服务；下次需要时重新运行上述命令。会话日志不会删除。

在仓库根目录用 PowerShell 运行：

```powershell
./scripts/symphony.ps1 Status
./scripts/symphony.ps1 Logs
./scripts/symphony.ps1 Stop
```

首次安装的镜像与 `.local/symphony/smoke.md` 已准备好。无凭据、无任务的运行方式：

```powershell
./scripts/symphony.ps1 StartOffline
```

已存在同名容器时不覆盖。升级时先停止并重命名保留旧容器，再启动；独立工作区和日志保留在 `.local/symphony/data/`。不要删除该目录，也不要操作日常 Demo 容器。

```powershell
./scripts/symphony.ps1 Stop
docker rename innovation-symphony innovation-symphony-before-update
./scripts/symphony.ps1 Start -UseHostCredentials
```

`-UseHostCredentials` 明确授权将当前 GitHub CLI Token 交给 Symphony，以及把宿主机 Codex `auth.json` 只读挂载到容器。它不会把凭据写进仓库或命令参数，但 Docker 管理员仍能读取容器环境。不要导出完整 `docker inspect` 输出。不挂载整个用户目录、Docker socket、日常数据库或项目原工作区。

GitHub Token 不传给 Codex 子进程；Agent 通过 Symphony 的 `github_api` 工具操作指定仓库。仓库范围在工作流中约束，Token 本身的权限仍由 GitHub 授权决定。可在后续改用仅授权此仓库的凭据。

宿主机 Codex 登录刷新后通常会映射到容器；若只读登录文件导致刷新失败，停止任务并重新登录、重建容器。不要把 Token 或登录文件提交到 GitHub。

## 领取与交付

### 准备任务合同

Issue 正文从 [Issue 模板](examples/symphony-issue-template.md) 整理；外置计划是程序控制输入，两者必须对应同一份已确认需求。只有正文或 ready 标签不足以执行。正文、JSON 的编写与命令操作由准备 Agent 完成，不要求用户手动转换口头需求。用户已明确授权准备或执行时沿用授权，不为每条命令重复确认。

需求准备者先复制 [任务计划示例](examples/symphony-task-plan.json)，明确可改路径、容器 quick/frontend、Java 模块、宿主专项和人工验收目标。当前宿主支持 smoke、scene-ui、accounts、ingestion；不适用的业务必须先补充检查器，不能让编码模型临场安装环境或自行扩展验收。完成模型目录检查和标签校验后，登记计划，最后才加 ready：

```powershell
./scripts/symphony.ps1 PrepareTask -Issue 11 -PlanFile .local/task-11.json
./scripts/symphony.ps1 TaskStatus -Issue 11
# 设置 model/effort 标签并校验之后，再添加 symphony:ready。
```

计划与状态位于 `.local/symphony/data/task-control/GH-编号/`，不属于模型可写工作区。已有计划不能被 prepare 覆盖。模型运行期间不换模型。

### 固定检查与一次修复

适配器读取已登记计划后启动编码会话。模型只提交代码和必要测试的修改，然后结束 turn；不提交 Git commit，不运行安装、构建、浏览器、Maven 或 GitHub 写入。程序接管固定检查，模型不需要轮询进程。

程序使用只读 `/opt/symphony-execution` 工具，先执行约定 Java 模块（非零测试），再运行 agent_check 的 quick/frontend。frontend 包含 quick，不重复执行两套。安装和构建复用仍由 frontend_control 校验输入、依赖内容与产物哈希；新代码不能引用旧证据。日志完整留在本地，交给模型的结果包含分类、证据路径、源码指纹和下一步。

- 通过：进入待审查，程序发布草稿 PR，列出宿主待验收项。
- 第一次代码失败：允许一次修复和复验；相同源码再次提交直接停止。
- 第二次代码失败、环境/权限阻塞或执行中断：持久化 blocked，保存补丁和证据，尽可能发布标有“未通过／待验收”的草稿。

不限制任务总时间或 token。受控模式的 App Server 等待为 infinity，stall 检测关闭；握手、单条检查和 GitHub 请求仍有超时。没有固定分钟数完成的承诺；尚未结束编码 turn 的模型也不会被总时长规则强制停止。

首次启动、调度重启和新模型会话都读取同一状态。`review`/`blocked` 在 GitHub 标签失败时仍阻止再次领取和推理。调度器补丁由 `prepare_symphony_blocking_fix.py --verify` 针对固定上游源码生成，在独立 VM 验证，不自动安装。受控执行必须同时安装 Orchestrator 与 Codex.AppServer 两个模块，不能仅修改 WORKFLOW。

### 程序交付与恢复

固定程序调用现有 symphony_publish，读取普通文件原始字节，经 Git Data 上传、核对 blob SHA、核对远端 head，再以 force=false 更新分支并回读。不让模型复制整文件或编码 base64；模型直接发布和 GitHub 写入会被适配器拒绝。Token 不传给模型 shell，认证仍由 Symphony github_api 传输。

发布仅允许显式源码路径、codex 分支，拒绝越界、符号链接、忽略文件和运行时文件。每文件最大 1 MiB、每批最大 100 文件/8 MiB；删除和符号链接暂不支持，按阻塞交接。更新已有草稿，不创建重复 PR；遇非草稿 PR 或远端冲突停止。超时先只读核对分支和 PR，不自动重发不确定写入；部分上传不标记完整交付。

每轮保留 `runs/<runId>/changes.patch`、文件副本、检查日志和 handoff；源码快照失败时保留整个工作区并明确记录不完整。只有用户明确要求重新执行后才允许：

```powershell
./scripts/symphony.ps1 ResumeTask -Issue 11 -Reason "用户要求重试，已补齐指定环境"
# 合同变化时追加 -PlanFile；旧合同和状态仍保留在 history。
# 核对远端发布结果，移除阻塞标签，再按原定模型重新加入 ready。
```

单独恢复 ready 标签不会清除本地终止状态。不得删除状态文件来重置修复次数。发布通道故障先读本地证据、远端分支和草稿状态，必要时人工使用已有 symphony_publish CLI 恢复，不自动反复上传。

### 宿主验收与执行环境更新

用户提出“审查 PR X”后，按 [本机审查入口](16-fast-review.md) 完成独立代码审查、同 SHA 专项检查和合成数据实例；通过草稿交付不表示人工验收通过，不合并、不部署。

升级前检查 running/retrying 为空且 GitHub open ready 队列为空，保存旧容器、WORKFLOW、所有只读挂载脚本和被替换模块，提供回退清单。Start 要求 `.local/symphony/data/blocking-fix/manifest.json` 与当前生成器和已验证模块的哈希相同，缺少验证即拒绝启动。补丁输入只读挂载在独立目录；symphony_entrypoint 先用 --help 完成 Burrito 解包，再校验并安装模块，最后才启动真实工作流，避免首次解包被只读模块阻塞。已安装中文模块可按清单 preservedModules 一并保留，禁止加载清单之外的模块。不要删除 data、任务工作区或操作日常 Demo。

## 模型与思考深度

准备 Issue 的 Agent 先运行以下命令读取当前容器账号可用的 GPT 模型和已配置的 DeepSeek 模型及各自支持的思考深度，按用户明确选择或任务复杂度选定组合，在正文写一句选择理由，并校验后设置标签。选择流程发生在需求准备阶段，Symphony 执行阶段不再调用模型评估器。DeepSeek 条目来自官方提供商配置，目录查询和 ValidateModel 仅校验组合，不证明密钥有效或真实请求成功。

```powershell
./scripts/symphony.ps1 Models
./scripts/symphony.ps1 ValidateModel -Model gpt-6-astra -Effort low
```

简单文案、样式和局部修改优先轻量模型及低深度；常规交互和接口任务使用均衡组合；权限、迁移、并发及复杂重构提高能力与思考深度。实际候选以目录为准，不维护另一份静态可用模型清单。目录暂时不可读时先记录默认组合，等执行前校验通过再入队，不猜测替代模型。

标签格式（严格按下列小写前缀）：

- `symphony:model:gpt-6-astra`
- `symphony:effort:low`

用户明确指定优先于 Agent 判断。每种前缀最多一个标签；变更时替换旧标签，不叠加。缺少模型标签时使用 `gpt-6-astra`，缺少深度标签时使用 `low`。重复、空值、未配置的模型、不支持的深度均阻止推理调用，不静默回退。正文中的模型示例不是配置。确认目标、验收与组合后，最后添加 `symphony:ready`；该文档不授权自行创建或修改远端任务。

适配器只解析工作流开头的 `SYMPHONY_ROUTING_V1` 元数据区；标识符和每个标签由 Solid `url_encode` 编码。它在 App Server 初始化后读取完整分页 `model/list`，首轮解析并校验标签，将 `model` 和 `effort` 写入每次 `turn/start`。同一会话的后续轮次固定复用组合，修改标签要到下一次调度才生效。目录失败或 30 秒内未完成读取会明确失败，沿用 Symphony 自身退避，不增加自动换模型重试。

`scripts/symphony_codex_adapter.py` 和查询脚本通过独立只读挂载运行在 `/opt/symphony-routing/`；任务工作区中的同名文件不参与执行。协议输出只走 stdout，结构化审计追加到 `.local/symphony/data/logs/model-routing.jsonl`，记录 Issue、线程、请求组合、默认来源、接受/拒绝和完成状态，不写提示正文或凭据。`turn_accepted` 只证明请求被接受；实际模型/深度应核对对应 Codex rollout 的 `turn_context`，实际业务完成仍需任务验收。

### 路由验证与恢复

#### DeepSeek 官方 API

继续使用 Codex App Server，通过 Responses API 调用 `https://api.deepseek.com`，不使用协议转换代理。官方 `deepseek-flash` 当前对应 DeepSeek-V4.1-Flash；不自行创造 `deepseek-flash4.1` 别名。配置依据：[DeepSeek Codex 接入](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)。支持深度 `low`、`high`、`max`，例如设置 `symphony:model:deepseek-flash` 和 `symphony:effort:high`，最后再设置 ready。

密钥只保存于忽略目录 `.local/symphony/secrets/deepseek-api-key`（单行纯密钥），启动脚本自动只读挂载到 `/run/secrets/symphony-deepseek`；也可用 `Start -UseHostCredentials -DeepSeekKeyFile <本地路径>` 指定。密钥不进入 Docker 环境配置、命令参数或审计日志，仅由适配器读入 Codex 子进程环境；所有线程的 shell 环境排除 `DEEPSEEK_API_KEY`。此文件不放进任务工作区或 `/data`，不要提交或打印。宿主及 Docker 管理员仍可读取挂载文件。

提供商只能在线程创建时选择。Symphony 首次 turn 才提供 Issue 标签，所以适配器在识别 DeepSeek 后创建一个尚无提示正文的新线程，完整保留原线程的沙箱、审批和动态工具定义，并在协议边界映射线程 ID。后续轮次沿用同一真实线程，不再创建；审计的 `threadId` 是真实执行线程，`parentThreadId` 是 Symphony 跟踪的初始空线程。排查或查看 rollout 时使用真实执行线程。缺密钥或创建失败明确停止，不回退 GPT；GPT 默认路由不变。

真实验收可在无 GitHub 凭据、独立 home/工作目录的容器中执行 `symphony_model_probe.py exercise --model deepseek-flash --effort high --output <证据路径>`：两轮连续请求、沙箱文件读写、合成动态工具回调，并核对 rollout 的模型、深度和提供商。此命令会创建 `routing-seed.txt` / `routing-result.txt`，只在合成工作目录运行。真实 Issue 到 draft PR 仍需单独验收。

首次增加密钥挂载需确认 running/retrying 与 ready 队列均为空，再停止并改名保留旧容器、用启动脚本新建同名容器。回退时也先确认空闲，停止并改名保留新容器，然后将旧容器恢复原名并启动；保留 data、密钥和证据。旧容器没有密钥挂载，恢复后仅 GPT 路由可用。2026-09-20 的回退容器名称和当前接入证据见验证记录。

quick profile 包含无网络、无凭据的假 App Server 协议测试；Linux 另验证 SIGTERM 后子进程树清理。真实短请求可在独立 home/工作区的同版本容器中运行 `symphony_model_probe.py smoke --output <证据路径>`；无标签验证默认组合，加 `--model` 和 `--effort` 验证显式组合。脚本核对真实 rollout 的模型和深度，不能仅凭回复文本判断通过。`catalog` 与 `validate` 子命令只查询目录，不发起推理请求。

首次从旧版本接入需在 running/retrying 均为 0 且 ready 队列为空时重建 Symphony 容器以增加挂载；以后只读挂载的脚本更新只影响新进程。保留旧容器、原工作流及 data，不操作 Demo/LAN Compose。

2026-09-19 本机回退点：旧容器 `innovation-symphony-before-routing`（已停止），原工作流与启动脚本在 `.local/symphony/routing-validation/rollback/`。回退时先确认空队列，停止新容器并改名保留，将备份工作流恢复到根目录，再将旧容器改回 `innovation-symphony` 并启动，检查 43190 健康。旧容器绑定根目录工作流，所以必须先恢复工作流；两个容器不能同时运行。不要删除 data，也不要直接用备份目录里的启动脚本启动（其相对路径以 scripts 目录为基础）。

## 验收限制

容器提供 Git、Node、Python、Codex、JDK 21 和 Maven。Java 依赖使用任务自己的 `.local/m2`，首次下载仍有冷启动成本；禁止用“镜像有 Java”代替实际执行测试。Python 验证依赖预装在镜像的只读 venv 中，各任务仍拥有自己的轻量 venv；前端任务按需执行 `npm ci --prefer-offline --no-audit --no-fund`，node_modules 不共享。

`ingestion` profile 与 `review.py` 原生运行时仍依赖 Windows、PostgreSQL 17、JDK 21、Edge 和 `.local` 环境，Linux 容器不能据此声称该 profile 通过。Linux 宿主的入库/真实样包验收使用 [Harness 的固定隔离 Compose 流程](13-harness.md)（`127.0.0.1:18082`）；两条路径都不能用 quick/frontend 代替真实业务验收，也不得操作日常实例。

管理页面 HTTP 200 只证明服务启动；Codex 登录状态不证明模型请求成功；二者都不等同于真实 Issue 到 PR 的验收。当前安装结果见 [验证记录](06-validation.md)。

## 安装来源与恢复

官方发行包：[Symphony v0.0.3](https://github.com/openai/symphony/releases/tag/v0.0.3)。基础镜像配方保存在 `.local/symphony/Dockerfile`，验证依赖扩展配方见 [symphony.Dockerfile](../deploy/symphony.Dockerfile)，官方源码在 `.local/symphony/source/`，下载文件在 `.local/symphony/downloads/`。这是一份本机安装，新的机器需要重新准备基础镜像和登录，不能仅 clone 仓库就直接启动。

### 预装验证依赖与下载缓存

运行 `./scripts/symphony.ps1 Build` 构建验证镜像；只向 Docker 发送配方、`scripts/requirements-review.txt` 和环境准备脚本，不发送仓库、登录或任务日志。基础镜像必须已存在。依赖变更后重新 Build，空闲时切换容器，不重建业务镜像。

2026-09-20 首次接入时 GH-3/GH-4 正在执行，先从已验收的新镜像同步两个新增只读 `/opt` 目录，未中断任务。两个任务结束且 ready 队列、running/retrying 均为空后，正式切换到验证镜像，健康与默认模型校验通过。旧容器 `innovation-symphony-before-cache` 停止保留；工作流备份在 `.local/symphony/environment-validation/rollback/`。回退需先确认空闲，停止新容器并改名保留，再将此旧容器恢复原名称并启动；data 和缓存不删除。

同日完成 Java 镜像切换，直接回退容器为 `innovation-symphony-before-java-v2`（停止保留）；当前容器健康与默认模型校验通过。上游在启动时同步清理已关闭 Issue 的目录，Windows 挂载盘上的大量小文件可使健康接口长时间未开放。GH-7 被部分清理后的剩余目录已保留至 `.local/symphony/data/archived-workspaces/GH-7-20260920-startup-recovery`，停止清理、归档后重启约 6 秒内恢复健康。不要盲目重复启动或直接删除工作区；先核对关闭状态、备份证据并在调度停止时处理。上游自动清理机制本次未修改。

依赖和 pip 安装在 `/opt/symphony-validation/venv`，由 root 所有，任务不可修改；实际安装版本记录在 `/opt/symphony-validation/installed.txt`。每次执行前，`before_run` 创建或检查工作区 `.local/venv`，用 `.pth` 引用镜像依赖，不复制 pip，不再次下载同一依赖。依赖清单与镜像一致时直接使用；清单变化时在任务自己的 venv 中补装，保留镜像和其他任务环境。旧镜像没有准备脚本时保留原安装方式作为过渡，不能把过渡路径当成已启用预装环境。

共享下载缓存随现有 `/data` 挂载持久化：宿主 `.local/symphony/data/cache/pip` 和 `cache/npm` 对应 `/data/cache/pip`、`/data/cache/npm`，通过 `PIP_CACHE_DIR`、`NPM_CONFIG_CACHE` 指定，容器重建后保留。沙箱仅额外放行这两个缓存目录；任务 venv、node_modules 和锁文件仍各自独立。缓存命中减少下载，首次遇到的新包仍需联网，仓库克隆和 npm 解包也仍需执行。

镜像验收在无网络、无凭据的临时容器运行 `python3 -m unittest discover -s /tests -p test_symphony_environment.py -v`，只读挂载 scripts 为 `/tests`，挂载隔离数据目录为 `/data`，使用本仓库 Symphony seccomp 配置。该检查验证离线初始化、任务依赖隔离、缓存路径及 Codex CLI 沙箱可写范围；Windows quick 不替代该 Linux 镜像验收。

停止 Symphony 不停止日常 Demo。容器重启策略为 `unless-stopped`，Docker 启动后会恢复未手动停止的容器；宿主机休眠或 Docker 停止期间不会领取任务。


### Linux 原生工作区卷

`symphony.ps1 Start` 默认把 Docker 命名卷 `innovation-symphony-workspaces` 挂载到 `/data/workspaces`，可用 `-WorkspaceVolume` 指定另一个已准备的卷。每个 Issue 的源码、`.local/m2`、venv、`frontend/node_modules` 和 dist 仍属于自己的工作区，不共享已安装依赖。`/data` 其余目录仍绑定宿主，task-control、日志、Codex 会话和 pip/npm 下载缓存的位置不变，Codex Trace 不需迁移。

已有 Windows 工作区不能直接被空卷遮蔽。迁移前确认 running/retrying 与 open ready 队列为空，停止并改名保留旧容器；源目录只读挂载到 `/legacy`，空原生卷挂载到 `/native`，以 uid 1000 运行 `scripts/migrate_symphony_workspaces.py --source /legacy --destination /native`。脚本拒绝非空目标、重叠路径、源文件变化与特殊文件，保留文件模式和符号链接，逐文件核对 SHA-256，成功后写入 `.migration-verified.json` 和清单。启动脚本遇到旧工作区但卷无验证标记时拒绝启动。失败时保留不完整副本供检查，不自动删除或覆盖。

本机旧路径 `.local/symphony/data/workspaces/` 在切换后仅是迁移时的回退副本，不再表示当前任务。读取当前源码和工作区证据使用 `docker exec innovation-symphony ...`；需要宿主文件时用 `docker cp innovation-symphony:/data/workspaces/GH-13/具体文件 <本地目标>` 导出。PR 宿主审查仍由 `review.py prepare` 按远端固定 SHA 创建独立目录。任务状态与发布保留副本仍可从宿主 task-control 读取。

回退前再次确认队列空闲，停止并改名保留新容器，再将迁移前旧容器改回 `innovation-symphony` 并启动。原宿主工作区和原生卷都保留。若新卷已有后续任务修改，先导出这些修改及证据，不能假定旧工作区包含它们。不停止或重建日常 Demo。


### 环境版本与轻量自检

当前镜像、控制器与补丁由 `deploy/symphony-environment.lock.json` 配套核对。`scripts/symphony.ps1 Doctor -Issue N` 按计划检查已有工作区；受控任务在开始编码前自动检查，失败持久化阻塞。默认 4 个 Agent 编码、1 路重构建；版本更新、离线恢复与并发实测见 [环境手册](18-symphony-environment.md)。
