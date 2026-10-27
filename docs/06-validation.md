# V0.1 验证记录

## 2026-09-20 新 Agent 的流程识别与交接文档

- 本轮仅补充仓库说明，不修改程序、不更新运行容器。AGENTS、README、知识索引共同链接 [Agent 工作流入口](17-agent-workflow.md)，明确口头需求、Issue 准备、受控编码、PR 审查和显式重试的职责与阶段产物。
- 消除受控模型“自行运行通用检查”和“由控制器检查”的职责冲突；统一“审查 PR X”默认交付同 SHA 本机实例，保留用户明确要求只审代码的例外。补充 Issue 正文模板、外置程序计划与 Markdown 任务记录的区别，以及交接/恢复字段。
- 入口人工走查覆盖需求澄清、仅准备 Issue、授权入队、受控编码、PR 审查、只审代码、查询阻塞和显式恢复。命令验证使用 `harness.py doctor --profile quick` 与 `check --profile quick`；本轮报告和最终源码指纹登记在 `.local/agent-workflow-docs-validation.json`，不沿用上一轮源码的绿色记录。
- 没有调用另一模型进行理解测试，因此不宣称所有 Agent 都能正确遵循。另机、远端或旧检出需先获得这些文档；本机未提交内容、外置合同和凭据不会随旧仓库自动出现。

## 2026-09-20 程序控制编码检查与本机验收

- 范围：外置任务合同/状态、最多一次修复、程序字节交付、调度重启终止守卫、按改动选择的 Windows 验收。没有任务总时长或 token 上限；单命令保留超时。不接 GitHub Actions，不合并或部署业务应用。实现基线 `c4b4879882a5f1317ea864d150577d8c84da106e`，隔离工作树 `.local/task-control-worktree`。
- 故障验证：Windows 任务控制及启动模块校验 13 项通过；适配器 Linux 19 项全部通过，覆盖权限阻塞、一次修复、第二次失败及进程清理。字节发布回归覆盖中文大文件、哈希冲突、远端并发、已有草稿更新；不确定写入只读核对，不自动重发。独立 Elixir VM 验证六组人工阻塞序列、持久化终态在 ready 未删除时阻止新领取/重试，以及受控会话等待 infinity、普通模式保留原时限。
- 调度补丁：Orchestrator 上游 SHA256 `a3cc9c67338e097eee9167e3ec88839a49850f8cf09f4c0529f05ca4e0b5d985`；AppServer 上游 `e51dd1af6f58883ebcea208f2786debb208363f6303d8b9bb00da2125a528cef`。已编译模块与验证清单保留在 `.local/symphony/data/task-control-validation/blocking-fix/`；安装状态另见下方上线记录。
- DeepSeek 实跑 [Issue #11](https://github.com/dailiuyi/innovation/issues/11)：deepseek-flash/high，模型编码约 16 秒、5 次工具调用（4 次读取/差异命令和 1 次补丁），无模型安装、检查轮询、浏览器安装或文件内容发布。程序一次 frontend 检查通过：检查命令 1105.586 秒，其中首次 npm ci 147.285 秒；仅一次安装和一次生产构建。完整流程 1176.44 秒，冷启动及 Windows 绑定磁盘 I/O 仍慢，不能宣称简单任务可固定分钟数完成。
- 程序创建 [草稿 PR #12](https://github.com/dailiuyi/innovation/pull/12)，提交 `45a560aa664808eb7aa6073197120774152372a1`，只改场景说明。交付状态 review，检查轮次 1，源码指纹 `54d0bcd1dbe923a9c127bd5b1d593cbc2bd3bdce2cd5b137ef633f6a77a12c81`，文件 blob `3e170d89be1be8c8678721120d84b5204725dee8`，远端标签更新通过。模型与检查、发布阶段时间及工具记录在 `.local/symphony/control-smoke-11-v3/`。实跑使用该目录 bundle.json 对应的冻结工具版本；后续中断保存、网络回读等补强由最终故障回归覆盖。
- 早期实跑失败记录保留：v1 在推理前遇 Linux/Windows Git 所有权；v2 使用宿主克隆导致跨平台 Git 快照超时，未完成检查/发布。修复为与 Symphony 相同的容器内克隆后才进行 v3，没有把失败记录算作通过或隐藏重试。
- Windows PR 10 完整 SHA `5b8ff6636f60472771777e5bc8fc5b75376f7157`：frontend、64 项场景 UI/视口检查、独立 PostgreSQL 17.6 真实登录与场景/草稿点击全部通过。后端构建执行 23 项 Java 测试且无跳过，Jar SHA256 `dde4d8316e82da226379a08e354881858b1e6909cf5217ea49be8bba0104c87a`，后续实例复用该产物。新 preview 合成数据、代理登录、健康查询、定向停止和端口关闭均验证；实例已停止，日常 Demo 容器仍健康。证据在 `.local/task-control-worktree/.local/reviews/pr-10/<完整SHA>/`。
- 修复验收器的实际问题：停用后等待文字误匹配旧操作按钮，改为等待“启用”按钮；合成 API 接受合法 201；直接浏览器调用复用宿主 Playwright。旧 PR 缺少新工具测试时执行中央工具回归，不跳过或伪造零测试。Windows Git 发布子进程设置 stdin=DEVNULL，避免继承协议管道而阻塞。
- 人工观感仍待用户确认；PR 12 未执行其自己的宿主验收，PR 10 的结果不能替代 PR 12。当前并未进行本次改动的 ingestion 全链、LAN、客户端加载或部署验证。所有凭据、完整日志与合成数据留在本地。
- 运行切换已完成：切换前后 running/retrying/blocked 均为 0，GitHub open ready 队列为空。保留旧容器 `innovation-symphony-before-task-control-20260920`，新容器 `378a743c1af574e902e7e9c37a7876f028932e90acc34acec3be35f099fd9a3a` 的调度器/AppServer/两份中文模块哈希全部匹配，43190 API 与中文页面健康，日常四个应用容器仍健康。回退清单与入口：`.local/symphony/task-control-rollout-20260920/manifest.json`、`rollback.py --apply`；回退先核对空闲和部署文件未被后续修改，不删除数据。
- 首次切换暴露 Burrito 解包与只读最终模块目录冲突，失败容器保留为 `innovation-symphony-startup-failure-20260920`，没有启动任务。修复为独立只读补丁目录和启动包装器：仅用 --help 解包（上游正常打印 Usage 并退出 1），校验模块后安装，再执行真实工作流。已在无网络无凭据容器验证，再切换并验证健康。升级未重建镜像、未改业务容器。
- 集成后的最终 quick 报告、源码指纹及运行模块核对结果统一索引在 `.local/symphony/task-control-rollout-20260920/validation.json`；该忽略目录索引不改变受检源码。源码尚未提交，保留与此任务无关的同期文档更新。

## 2026-09-20 拉取 main 并更新 LAN 网关

- 用户明确要求拉取最新代码并部署 Docker；main 从 `5806c68` 快进到 `8119b854e87b3a6fd7c2b251086b0c0f04b8b2e4`。原有未提交修改保留，验证记录的自动暂存冲突按独立段落合并，恢复备份仍留在 Git stash。
- `python scripts/harness.py doctor --profile quick`、`check --profile quick`、`python scripts/agent_check.py --profile frontend` 通过；frontend 报告 `.local/harness/20260920T084420Z-31rgtn15/report.json` 的 `sourceUnchanged=true`，对应写入本段之前的源码。
- `verify_scene_list_ui.py --channel msedge` 首次在停用状态断言失败：等待“停用”文字会匹配刷新前的操作按钮。仅在 `.local/deploy-8119b85/ui-wait-diagnostic.py` 诊断副本改为等待“启用”按钮，原有断言全部保留，64 项通过。仓库测试脚本未修改；这些检查使用合成响应，不证明真实业务闭环。
- 执行 `docker compose --env-file config/compose.env build gateway` 和 `up -d --no-deps --wait gateway`。新网关镜像 `sha256:c2ab0401e15385e65f1f245b5dded78a65b1a69c5537b3aa1e6037ff7b86a36f`；回退标签 `innovation-gateway:rollback-20260920-8119b85`。后端、PostgreSQL 17.6 和 Redis 未重建，数据库未迁移。
- 四服务 healthy，`nginx -t` 通过；本机访问 `http://192.168.0.12:43174/` 返回 HTTP 200，`/prod-api/captchaImage` code=200。Edge 登录页可见且无页面脚本错误，证据 `.local/deploy-8119b85/browser.json`。未验证其他局域网设备访问，未执行真实账号登录后的业务流程。

## 2026-09-20 GH-9 发布通道与草稿交付

- GH-9 已移除 `symphony:ready` 并停止当前会话，保留 `/data/workspaces/GH-9`、原始补丁及草稿 PR #10；Symphony 容器未重启，Demo/LAN 未操作。Issue 改为 `symphony:review`。
- 新增按路径文件发布工具：程序读取字节，复用 tracker 的 `github_api` 认证通道上传并校验 blob SHA；绑定 Issue 工作区、拒绝越界/链接/忽略与运行时文件、限制大小，检查源文件及远端 head 变化、不 force push，不自动重试或回退手工搬运内容。旧适配器与 WORKFLOW 备份保留于 `.local/symphony/publish-fix-20260920/`。
- Windows 发布回归 12 项（符号链接测试因权限跳过 1 项）；Linux 发布回归 12 项全部通过、路由协议 18 项全部通过。测试夹具显式隔离生产 DeepSeek 密钥挂载，未进行真实模型推理。大二进制字节、远端并发变化、错误 blob、输入变化、重复请求、认证失败不重试、禁止手工 blob 回退及线程映射均有覆盖。
- 实际通过同一发布器的宿主 gh 传输补交 `scripts/verify_ingestion.py` 与 `docs/06-validation.md`，提交 `5b8ff6636f60472771777e5bc8fc5b75376f7157`；远端 13 个 PR 文件的 Git blob SHA 均与保留工作区相同。证据：`.local/symphony/publish-fix-20260920/receipt.json`、`file-verification.json`。新增系统工具留在宿主工作区，不混入 GH-9 的界面功能 PR。
- 宿主 Windows ingestion、真实后端/数据库、Edge 登录点击、三视口人工观感、独立审查和同提交 preview 均待完成；PR 保持 draft，未合并或部署。本轮没有重装前端依赖或重跑构建。系统工具测试与上传哈希不代表 GH-9 业务验收通过。

本文按阶段保留历史结论；各段“当前”“未完成”只对应所记日期与源码。后续记录可能补充验收，但不追改当时结果。正式证据与保留快照的区别见 [证据索引](evidence/README.md)。本机 `.local` 路径仅是查证线索，不保证其他检出环境可访问。


## GH-9 场景列表入口拆分与列宽（2026-09-20）

- 行为：场景列表每行直接提供“场景信息”（名称、地址、坐标）和“版本与文件”两个入口；编辑弹窗底部只保留“关闭、保存”；资源面板标题与首行显示所属场景名称和编号，进入面板不再依赖编辑弹窗。列宽为状态 80、修订号 80、操作 300 且固定在右侧，名称与地址按 min-width 180/320 分配剩余空间、省略显示并悬停看完整值。版本列表与文件列表布局、发布/上传/下载/删除规则未改。
- 选择器与文档同步更新：`scripts/verify_ingestion.py`（行内两个入口、场景信息弹窗底部按钮、资源面板场景名，并追加 1280/1440/1920 列宽与按钮单行/间距断言）、`scripts/verify_browser.py`、`scripts/verify_draft_panel.mjs`（场景名加载与迟到响应失效）、`docs/12-resource-ingestion.md`、`docs/13-harness.md` 的专项入口说明和首页入口/步骤说明。
- 新增 `scripts/verify_scene_list_ui.py`：只启动 Vite 与真实浏览器、由 Playwright 返回合成接口响应，不连后端。本容器用 `/tmp` 下自行解包的 Debian 运行库启动 Chrome for Testing 153.0.8010.12 实跑，64 项全部通过：两个入口、四按钮不截断/不换行/不重叠、状态与修订号紧凑、地址宽于名称且随窗口变宽、超长名称与地址省略且悬停显示完整值、1024px 横向滚动时操作列固定在右侧、场景信息弹窗只留关闭与保存、版本与文件直接打开对应场景面板、发布后列表刷新修订号、停用原因填写与删除确认。它使用合成响应，不证明真实发布/上传/下载/删除。结果 [`validation-scene-list-ui.json`](evidence/issue-9/validation-scene-list-ui.json)；截图与逐项日志留在本机 `.local/scene-list-ui/`，未随仓库提交。
- Linux（Python 3.11.2、Node 22.23.2、npm 10.9.8）：`doctor --profile quick` 与 `check --profile quick` 通过且 `sourceUnchanged=true`，报告 `.local/harness/20260920T075839Z-iplkgd57/report.json`（HEAD `5806c68`，`dirty=true`，源码指纹 `280ee8af2bc0e88c6633c816d253e2ba8f1e6db75cf3954316d4f826d936040f`）。该报告对应写入本段说明之前的树；写入说明后的最终 quick 复核报告路径记在 Issue #9 唯一进展评论。
- `check --profile frontend`：contracts-and-links 与 draft-panel 通过；`frontend-build` 步骤在 harness 固定的 300 秒超时内未完成，该 profile 记为 blocked，不能算通过。同一命令直接执行 `npm --prefix frontend run build:prod` 退出码 0（墙钟 6 分 56 秒，user 28 秒），产物含 `"min-width":"180"`、`"min-width":"320"`、`width:"80"`、`label:"操作",width:"300",fixed:"right"` 与资源面板场景名文案。
- 未执行：Windows ingestion、Edge 真实后端登录点击、真实发布/上传/下载/删除业务闭环、数据库、Docker/LAN、部署与客户端加载。详见 [GH-9 证据记录](evidence/issue-9/README.md)。

## 2026-09-20 Symphony 管理页面简体中文补丁（已应用）

- 新增 `scripts/prepare_symphony_zh_cn.py`，固定校验本机 v0.0.3 上游模板指纹，生成并独立编译两个页面模块。翻译页面标题、指标、状态、表头、按钮反馈、空状态、快照错误、时长单位及 HTML 语言；保留原始日志、错误诊断与 JSON API。
- `python scripts/prepare_symphony_zh_cn.py --verify` 通过：独立 Elixir VM 编译成功，合成 empty/running/blocked/retry/error 状态渲染通过，诊断与会话 ID 保持原值。编译输出位于 `.local/symphony/data/ui-zh-CN/ebin/`，源文件指纹见同目录上一层 `manifest.json`。
- 用户再次明确要求更新并重启后，确认原容器已正常停止、GitHub ready 队列为空。核对原模块与 `.local/symphony/ui-zh-CN-backup-20260920/` 备份一致，只替换两个页面 BEAM 并核验副本。应用指纹与原容器 ID 记录在 `.local/symphony/ui-zh-CN-apply-20260920/applied.json`；未重建镜像或容器。
- 首次启动健康接口未开放；启动代码在 HTTP 服务启动前同步清理已关闭任务工作区，复现 Windows 挂载盘清理延迟。确认 GH-1、GH-3、GH-4、GH-9 均已关闭、ready 队列为空后停止容器，将四个剩余目录移动至 `.local/symphony/data/archived-workspaces/ui-zh-CN-startup-20260920/` 原样保留，再启动同一容器，健康恢复。未手动删除工作区、未更改调度器或日常 Demo。
- 原地址 `http://127.0.0.1:43190/` 返回 HTTP 200，标题为“Symphony 运行监控”，HTML 为 `lang=zh-CN`。实际浏览器验证标题、指标、中文空状态及“实时更新”连接状态，截图检查排版正常。`/api/v1/state` 返回原字段结构，running/retrying/blocked 均为 0。当前无执行任务，因此真实任务行及复制按钮沿用前述合成渲染验证，未派发任务进行测试。
- Windows quick 的首轮 doctor/check 通过（`.local/harness/20260920T064753Z-akgydp23/report.json`），后续最终源码检查另存 `.local/harness/`。该检查不证明当前运行页面已经切换，也不涉及业务 Java、数据库、ingestion 或日常 Demo。

## 2026-09-20 Symphony 接入 DeepSeek 官方 API

- 保留 Codex CLI 0.154.0 / Symphony v0.0.3 / `innovation-symphony:0.0.3-java-v2`，增加显式 `deepseek-flash` 路由及 `low/high/max` 深度。GPT 默认 `gpt-6-astra/low` 不变。提供商在线程创建时切换，原沙箱、审批、动态工具保留；异常不换模型。密钥仅在忽略的 secrets 目录及只读容器挂载中，未进入源码或报告。
- 官方 `/models` 认证查询返回 `deepseek-flash` 和 `deepseek-v4-pro`；此次只接入用户指定的 Flash。独立、无 GitHub 凭据容器的 `symphony_model_probe.py exercise --model deepseek-flash --effort high` 通过：真实两轮、沙箱文件读写、1 次合成动态工具回调，rollout 两轮均为 `deepseek-flash/high`，session provider 为 `deepseek`。证据 `.local/symphony/deepseek-validation/exercise.json`。首次 smoke 因隔离 home 目录尚未创建而失败，修正后通过；失败不计入验收。
- 路由回归 Windows 18 项中通过 17 项、跳过 Linux 进程组项；相同镜像无网络、无凭据 Linux 回归 18 项全通过，包括缺密钥、提供商失败/超时、工具线程 ID 映射、连续轮次、原 GPT 目录和进程树清理。quick doctor/check 通过，阶段报告 `.local/harness/20260920T055641Z-ncz8c_34/report.json`；文档补写后的最终报告保存在 `.local/harness/`，以交付列出的路径为准。没有数据库变更或 PostgreSQL 验收，不运行无关 frontend/ingestion。
- 确认 ready 队列和 running/retrying 均为空后，新建带只读密钥挂载的 `innovation-symphony`，健康接口通过；原容器 `innovation-symphony-before-deepseek` 停止保留。新容器真实 DeepSeek smoke 和无标签 GPT smoke 均通过，分别核对 `deepseek-flash/high/deepseek` 与 `gpt-6-astra/low/openai`；证据 `.local/symphony/data/logs/deepseek-live-smoke.json`、`gpt-after-deepseek-smoke.json`。
- 本次未创建/修改远端 Issue、提交 PR 或派发业务任务；真实 Issue 到 draft PR 尚未验收。日常 Demo/LAN 未变更。回退方法见 [Symphony 手册](15-symphony.md)。


## 2026-09-20 文档状态与证据引用整理

- 将旧候选文档标为历史状态，现行手册统一通过 Harness 执行日常检查；归档协作讨论并保留后续验收入口。新增 [证据索引](evidence/README.md)，记录保留 JSON 的 SHA256 和重复引用限制；没有改写报告内容，也没有恢复或补造旧批次证据。
- Windows / Python 3.12.5：`python scripts/harness.py doctor --profile quick` 和 `python scripts/harness.py check --profile quick` 通过，首轮报告 `.local/harness/20260920T035236Z-pq3min13/report.json`，`sourceUnchanged=true`。该报告对应补写本段前的快照；最终文档复核报告另存 `.local/harness/`，以本次交付所列路径为准。
- 范围为 Harness、审查工具、模型路由回归及契约/文档链接。Windows 路由测试明确跳过 1 项 Linux 进程组清理测试；未执行 frontend、ingestion、数据库或浏览器业务验收。未修改业务代码、脚本默认值或运行服务。

## 2026-09-20 需求专项优先与固定审查实例

- 新增 `scripts/check_java.py` 和 `scripts/review.py`，流程见 [固定审查入口](16-fast-review.md)。先验证需求实际路径，再按风险追加 quick/frontend/ingestion；零测试或跳过不得作为 Java 交付通过。
- Java 镜像 `innovation-symphony:0.0.3-java-v2`（Temurin 21.0.9/Maven 3.9.11）构建成功；无网络、无凭据环境测试 5 项通过。只读挂载 PR #8 后端并复制到隔离容器目录，执行 `mvn -f /tmp/backend/pom.xml -pl ruoyi-framework -am -Dmaven.repo.local=/cache test -B -ntp`，实际 6 项通过、零跳过。初次离线尝试因宿主缓存仓库标识及 Maven 默认插件差异失败；最终采用独立 Linux 缓存在线补齐，耗时约 4 分 27 秒，没有把失败记录视为通过。
- PR #8 提交 `78c147e54276f0caf8c28e298c69b4b88b1e77ac` 的 `review.py check --suite accounts --online` 通过（约 48 秒）：23 项 Java 测试、48 项账号 HTTP 断言，包含六位 bootstrap 登录、创建/重置/个人改密边界和两份旧 Token 失效；PostgreSQL 17.6。证据在 `.local/reviews/pr-8/78c147e54276f0caf8c28e298c69b4b88b1e77ac/check-522f3f79efa9/report.json`。首次 offline 因缺 maven-clean-plugin 失败；显式 online 补齐后重跑。
- 同版 `check --suite frontend` 通过（约 62 秒），证据 `check-de025cb9408b/report.json`；两项 sourceUnchanged=true。`test_review.py` 六项通过；root quick 增加该测试步骤，doctor/quick 检查通过。
- 审查后启动同版隔离实例，`http://127.0.0.1:9584` 页面、API 代理、真实登录及独立 status 健康通过。凭据仅存实例目录，未写入本文。已验证前一实例正常 stop，保留证据和数据。实际用户浏览器点击、其他设备访问和完整 ingestion 未验收；没有合并、推送或改变日常 Demo。
- Symphony 在空闲及 ready 队列为空时完成运行镜像切换，健康与模型选择校验通过；旧容器 `innovation-symphony-before-java-v2` 保留。首次启动的上游关闭任务自动清理阻塞健康接口，GH-7 残余目录已停止清理后归档；详情、限制与回退见 [任务交接](tasks/completed/2026-09-20-fast-review.md)。

## 2026-09-20 Symphony 验证依赖预装与共享缓存

- 扩展镜像 `innovation-symphony:0.0.3-validation-v1` 构建通过，image ID `sha256:4098208ef5fc0d57a5292ea610ee91ed6a0e57d8e3311fa8cf77461416b1ba8f`；保留 Symphony v0.0.3、Codex CLI 0.154.0、原基础镜像及并发上限 4。实际 Python 依赖版本记录在镜像 `/opt/symphony-validation/installed.txt`，`pip check` 通过。
- 最终 Linux 镜像在无网络无凭据容器中通过 4 项环境检查：离线初始化、只读镜像依赖与独立 venv、变更依赖只安装到本任务、共享缓存路径与沙箱隔离。轻量 venv 不复制 pip；Linux 临时目录初始化约 0.3 秒，Windows 挂载目录实测 1.425 秒，当前常驻容器合成工作区实测 1.703 秒。这些时间只包含 Python 环境准备，不包含克隆仓库或 npm 安装。
- 两个隔离任务的 pip 安装均命中共享下载缓存；另一个 `--network none` 容器通过 `npm ci --offline` 从持久缓存安装相同锁文件依赖，保持独立 node_modules。证据 `.local/symphony/environment-validation/warm.json`、`offline.json`，覆盖小型合成包，不声称完整前端依赖已预热。
- 实际 App Server 使用与 WORKFLOW 相同的 `workspaceWrite` 和两个缓存 writableRoots，模型执行合成脚本确认当前工作区及缓存可写、另一任务工作区被拒绝；结果 `.local/symphony/environment-validation/appserver-cache.json`。测试仅使用 Codex 登录，不带 GitHub 凭据，不操作业务数据。
- 未中断 GH-3/GH-4：先将已验收镜像中的两个新增 `/opt` 目录同步到原容器，校验只读权限、`pip check` 和脚本 SHA256 一致。任务全部结束，ready 队列及 running/retrying 均为空后正式切到验证镜像；健康和 Astra low 模型校验通过。原容器 `innovation-symphony-before-cache` 停止保留，缓存随 `/data` 挂载持久化到 `.local/symphony/data/cache/`。
- quick doctor/check 通过，阶段报告 `.local/harness/20260919T160018Z-igi1txta/report.json`；最终文档及测试准备项整理后的复核报告保存在 `.local/harness/`。未运行业务 ingestion 或修改前端锁文件、任务 node_modules；未重建业务镜像。

## 2026-09-19 Symphony 模型与思考深度路由

- 保留官方 Symphony v0.0.3 / Codex CLI 0.154.0；新增 stdio 适配器，将 Issue 的 `symphony:model:` 与 `symphony:effort:` 标签校验后写入 `turn/start`，缺省为 `gpt-6-astra / low`。同一会话保持组合，配置错误在推理前失败。
- 无网络无凭据 Linux 镜像中 `python3 -m unittest discover -s /opt/routing -p test_symphony_codex_adapter.py -v`：14 项全部通过；Windows Python 3.12.5 的 quick 中 13 项通过、Linux 进程组清理 1 项明确跳过（已由 Linux 补验）。覆盖分页、目录错误/超时、重复/未知/不支持组合、正文伪造、后续轮次、独立任务、工具请求转发及退出清理。
- 使用发行包实际 Solid 1.2.2 引擎加载当前 WORKFLOW，以合成 Issue 渲染完整模板；换行标签经编码后保持单条元数据，正文示例没有覆盖标签。结果 `.local/symphony/routing-validation/template.json`。
- 两个无 GitHub 凭据的一次性隔离容器完成真实短请求：无标签得到 `gpt-6-astra / low`，显式标签得到 `gpt-5.6-luna / medium`。均为 `turnStatus=completed`，实际 rollout 的 `turn_context` 与预期一致；证据为 `.local/symphony/routing-validation/default.json`、`explicit.json` 及对应审计文件。原始 rollout 随临时容器移除，保留的证据包含线程 ID 和实际参数，不含原始提示。
- quick doctor/check 通过，报告 `.local/harness/20260919T152334Z-pd4k03tt/report.json`；HEAD `a0df970d5c191c4c6ce001a4c3c50cbf1ce0e70e`，源码指纹 `f5bd5da00cfff7c8b15181e0fb3403bcb030124a2eba2bef6a294997bebf972c`，`sourceUnchanged=true`。该快照在补写本段记录之前；文档整理后的最终复核报告仍保存在 `.local/harness/`。
- 确认 ready 队列、running/retrying 均为空后切换常驻容器；43190 健康，`Models` 和 `ValidateModel` 通过，两个脚本挂载均为只读。旧容器 `innovation-symphony-before-routing` 已停止保留，工作流备份在 `.local/symphony/routing-validation/rollback/`，data 未删除。
- 未执行：新建或修改远端验收 Issue、真实 Issue 到执行/PR 的本次路由验收、独立代码审查及业务 ingestion。未重建业务镜像或操作 Demo/LAN Compose；既有会话查看器改动保留。

## 2026-09-19 Symphony 只读会话详情页

- Windows / Python 3.12.5：新增 `scripts/symphony_viewer.py` 与独立 HTML 页面，仅监听 `127.0.0.1:43191`，读取 Symphony 的持久化会话目录和本机调度状态；不接管任务，不重启容器。
- `python scripts/test_symphony_viewer.py` 通过：验证半行写入后的增量续读、不重复返回、中文内容及内部推理过滤。
- `python scripts/harness.py doctor --profile quick` 与 `check --profile quick` 通过；后续页面调整后再次执行 quick，以最终报告为准。未涉及数据库，未运行 ingestion 或业务前端构建。
- 在应用内浏览器确认真实会话记录增量更新、搜索、暂停/继续刷新及切换历史会话。详情仅覆盖实际落盘记录；工具自身截断的内容无法恢复，不展示内部推理。长工具返回使用展开式呈现。

## 2026-09-19 Symphony 首个真实任务启动修复

- GH-1 暴露安装冒烟检查未覆盖的 App Server 协议问题：`reject` 审批对象被 Codex CLI 0.154.0 拒绝。根据该二进制导出的 schema 改为 `granular`，五类字段均为 false，保留 workspace-write 与拒绝越权的规则。
- 随后发现工作流换行解析 `~r/\R/` 可能拆断中文 UTF-8 字节，使发送 turn 时出现 Jason.EncodeError；将内部模板改为等义 ASCII，中文任务正文继续由模板变量注入。握手 read_timeout_ms 从默认 5 秒调到 60 秒。
- 只重启 Symphony，保留 GH-1 工作区。2026-09-19T14:17:39Z 状态 API 显示 running、第 1 轮、有效 session_id、总 Token 16686、retry=null、last_error=null，证明实际 Issue 已进入模型执行。
- 此记录只确认真实任务成功启动，不代表首页功能完成、PR 交付或业务验收通过。

## 2026-09-19 Symphony 安装验证

- 官方 Symphony v0.0.3 Linux x86_64 发行包 SHA256 校验通过；运行镜像包含 Codex CLI 0.154.0。仅新建开发工具镜像，未重建业务镜像。
- 无凭据 memory tracker 启动成功，本机 `http://127.0.0.1:43190/` 与 `/api/v1/state` 返回 200，运行、重试与阻塞任务均为 0。
- `python scripts/harness.py doctor --profile quick` 与 `check --profile quick` 通过，检查报告在 `.local/harness/20260919T134505Z-jvxhrkrn/report.json`。此次范围为工作流、脚本和文档集成；未执行 ingestion、浏览器业务验收或数据库迁移。
- 公开发布前扫描可达历史中的 846 个 blob，检查常见凭据格式与当前本地环境配置中的秘密值，未发现匹配；这不构成任意秘密均不存在的保证。
- 用户明确授权复用本机 GitHub 和 Codex 登录后，容器 `codex login status` 确认 ChatGPT 登录，最小模型请求返回 `SYMPHONY_READY`，容器内 GitHub Issues 读取返回 HTTP 200，当前 open 条目为 0。
- 首次实际 shell 检查发现 Docker 默认 seccomp 阻止创建用户命名空间。基于官方默认配置补充 8 个嵌套沙箱所需调用后，无凭据临时容器内 bubblewrap 只读沙箱执行 Python 成功；仍保留非 root、cap-drop ALL 和 no-new-privileges。
- 用户明确授权将该 seccomp 配置应用到持有凭据的常驻容器后，Codex 在 workspace-write 沙箱中通过 shell 实际执行 `python3 -c "print(731942)"`，输出正确且退出码为 0。
- 真实 Issue 到 draft PR 尚未执行。服务启动、登录与最小模型请求不代替真实任务验收。

## 2026-09-18 Docker 内网更新

- 本次 quick doctor/check 与 ingestion profile 通过，164 项隔离 HTTP/Edge 检查通过；PostgreSQL 17.6 路径迁移回归通过。报告位于 `.local/harness/20260918T075547Z-bheby8t8/report.json`，源码指纹 `5f81da05afdf8a7b2686aa5be61ab073927f0c26bab517a05631d7602656a68f`，sourceUnchanged=true。浏览器退出时出现 Playwright CancelledError 回调日志，进程退出码 0，结构化检查全部通过。
- `docker compose --env-file config/compose.env build backend gateway` 成功，Linux Java 21 构建含 17 项测试通过，Vue 生产构建通过。随后执行 `up -d --no-deps backend gateway --wait --wait-timeout 180`，四个服务均 healthy；保留原 PostgreSQL、Redis 与命名卷。
- 后端镜像 ID：`sha256:d70abbab5d9821f95928a919029673d0c6bf8883afbb7cfc044cdcdd30958f3b`；网关镜像 ID：`sha256:90817d9152903894dcc9f2f80933ecf32f1864f29e2b619ca15916f112479f6d`。
- LAN PostgreSQL 的 V012/V013 均成功；升级前数据库备份保存在忽略目录 `.local/deployment-20260918/database.dump`。Nginx 配置检查通过。本机不经代理访问 `http://192.168.0.12:43174/` 返回 200，`/prod-api/captchaImage` 返回 code 200。
- 未重启 Windows Demo，未推送远程仓库。未执行 LAN 账号登录与另一台设备访问验证；系统拒绝读取防火墙端口规则，不能据本机 HTTP 成功宣称跨设备验收通过。

## 2026-09-18 V013 LIKE 通配符与日常库升级

前缀冲突三处改为 `starts_with`，避免路径中的 `_`、`%` 被 LIKE 当成通配符。独立 PostgreSQL 17.6 升级回归通过：`safe/asset_1` 与 `safe/assetA1/data.bin`、`dir%/x.bin` 与 `dirX/y.bin` 均保留。本机 Demo 已执行 V013，Flyway 现为 v013，`/captchaImage` 返回 200。

## 2026-09-18 V013 导出路径迁移修正

V013 未应用于日常 Demo（仍为 V012），因此直接改写未应用的 V013，未增加 V014、未改 Flyway 历史。迁移只保留已有合法相对路径，改写不安全或冲突路径；先删除唯一索引再写回，避免中间态 23505。

- 独立 PostgreSQL 17.6 带旧数据升级 15 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。覆盖嵌套目录保持、不同目录同名、CON.txt、冒号/问号清洗碰撞、已有 `report_2026-22222222.txt` 不被覆盖、file_name 与 storage_key 不变。
- 隔离 ingestion 164 项通过，含浏览器取消后重选同一目录。Harness `.local/harness/20260918T073111Z-wiqycldx/report.json`，源码指纹 `6a99f7c8dd5128ed67f0ca57759553a90ea5cbaeec2d5b4245aadf44ab0842cf`，`sourceUnchanged=true`。
- `python scripts/harness.py doctor --profile quick` 与 `check --profile quick`、`check --profile ingestion` 通过。未操作日常 Demo、未重启日常服务。日常库没有被压平的目录需要恢复。

## 2026-09-18 文件夹上传审查修复

修复五项：启动恢复使用集合创建人并标明 SYSTEM_RECONCILIATION；删除持有草稿写锁；取消后新批次使用新 requestKey；路径前缀冲突按大小写折叠；V013 改写不安全导出路径且不改 V012 历史。

- 隔离 PostgreSQL 17.6、HTTP 与 Edge 验收 164 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。Harness `.local/harness/20260918T070751Z-mxe5zmb4/report.json`。源码指纹 `1c0a772ae672a8ff14ce875140411bb52779afcd290493f3691c72d6d9cbb7a1`，`sourceUnchanged=true`。
- 新增覆盖：启动时完成未切换替换、系统恢复审计、下载/打包期间删除 409、取消批次键不能重开、大小写前缀冲突、`ar_safe_export_path`、浏览器取消后重选同一目录。
- `python scripts/harness.py doctor --profile quick`、`check --profile quick`、`check --profile frontend`、`check --profile ingestion` 通过。未操作日常 Demo、未重启日常服务。

## 2026-09-18 文件夹上传与双下载

管理员草稿支持选择文件夹替换全部文件，以及 ZIP 整包和完整清单逐文件下载。V012 增加文件集合、相对路径和 ZIP 缓存。发布与所有下载共用完整性门槛：集合非空、无未完成替换/上传/删除、全部 AVAILABLE 且存储校验通过。

- 隔离 PostgreSQL 17.6、HTTP 与 Edge 验收 149 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。Harness 报告 `.local/harness/20260918T041339Z-fdjg783q/report.json`。HEAD `b2e11821cce03f20400fcb98e04f9e4b82713cd8`，源码指纹 `05d7182833ceb228e36bbdaed1496e9df30957b1b19ceaf899d166eca53f3cf8`（工作区有未提交修改），构建 Jar SHA256 `1a3711e085cf26e840f4af17829461658e7d5f3a14a185052d22fd33c1a543e4`。
- 覆盖：失败文件拒绝发布和下载、路径穿越拒绝、文件夹替换开始/续传/清单变化 409、替换期间禁止发布下载追加、取消后恢复旧集合、切换后旧文件删除、清单还原目录、单文件与 ZIP 的 206/416/HEAD、ZIP 复用、匿名拒绝、浏览器文件夹上传与 ZIP 下载。
- `python scripts/harness.py doctor --profile quick` 与 `check --profile quick`、`check --profile frontend`、`check --profile ingestion` 均通过。契约 57 个操作、358 项设计检查。`RelativePathTest` 3 项、存储测试 13 项。
- 未执行：日常 Demo 迁移/重启、Docker 网关、磁盘写满、物理断电、客户端加载认证。空目录不保留。集合默认 200 个文件 / 500 MiB、ZIP 缓存 24 小时 / 2 GiB 为配置默认值。

## 2026-09-18 Review 默认规则

将独立 Code Review 的范围、缺陷标准、验证边界与输出约定写入 `docs/14-code-review.md`，由 AGENTS 和知识入口链接。简短的“review 当前未提交改动”默认包含暂存、未暂存及相关新增文件；功能名称作为重点，不静默忽略其他改动。默认只审查，具体调查和必要验证由 Agent 决定。

`python scripts/harness.py check --profile quick` 通过，覆盖 Harness 回归、契约一致性及本地文档链接。本轮只更新规则和文档，未执行场景发布功能审查或业务验收，未修改已有业务代码和正式 JSON 报告。

## 2026-09-18 场景发布审查修复

针对发布审查三项：刷新后重取当前草稿以同步 `published`；发布成功后通知场景列表刷新修订号；未发布时列表省略 `published` 字段（不再输出 `null`）。删除文件后的浏览器步骤改为点「刷新」并先等抽屉标题，避免整页重载时 Vite 代理 `/getInfo` 连不上后端导致登出、发布流程未执行。

- `node scripts/verify_draft_panel.mjs` 增加刷新后选中草稿发布状态同步。
- 隔离入库 115 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)：未发布列表无 `published` 字段、发布递增场景修订号、父表修订号更新、删除后刷新仍隐藏已删文件、发布/替换按钮流程跑完。

## 2026-09-17 场景发布指针

同一场景一份当前发布版本：发布后文件冻结、说明可改；替换后原版本回到草稿；当前发布禁止删除。V011 增加 `ar_scene` 发布指针。入口仍是场景编辑 → 版本与文件。

- 隔离 PostgreSQL 17.6、HTTP 与 Edge 验收 113 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。覆盖空草稿拒绝发布、过期场景版本 409、重复发布幂等、已发布文件冻结、当前发布不能删、说明可改、替换后解冻可删、发布审计、浏览器首次发布/替换确认与取消。
- 契约检查 313 项、48 个操作；草稿面板乱序回归与 Vue 生产构建通过。Maven package 含 12 项存储测试。
- 本机 Demo 已执行 V011 并重启后端；未重建 Docker 网关。客户端加载、预览、单独下线仍未实现。

## 2026-09-17 基础 Harness

新增统一 doctor/check 入口、quick/frontend/ingestion 三种检查范围、独立运行证据和包含未提交修改的源码指纹。AGENTS 改为导航与关键约束，原开发/部署操作移入开发工作流；新增知识索引、决策记录与跨会话任务模板。

- quick：9 个 Harness 回归用例、契约生成源一致性及递归文档链接检查通过。故障用例覆盖命令失败后跳过后续步骤、缺失/失败/空/错误结构的报告、缺失命令、超时、未提交/新增/删除源码的指纹，以及临时副本中故意引入的 OpenAPI 漂移。
- frontend：草稿面板异步乱序回归与 Vue 生产构建通过。首次沙箱执行遇到 Node 读取项目父目录的 EPERM，经授权在沙箱外运行后通过；已将路径访问探测加入预检，不将该环境错误解释成产品故障。
- ingestion：独立后端源码副本 Maven package（含存储测试）、真实 PostgreSQL 17/Redis/Spring Boot/Vite/Edge 的 88 项入库验收通过。验证使用本次构建的 Jar，原日常 Demo Jar 的 SHA256 前后相同。

运行证据按次保存在忽略的 `.local/harness/` 中；没有覆盖已有 `docs/validation-*.json`，没有重启日常 Demo 或操作 LAN Compose。上述结果不证明 Docker Nginx、客户端加载、发布、回滚或生产部署。入口用法和退出码见 [Harness 说明](13-harness.md)。

## 2026-09-17 未提交修改审查与小修复

逐项检查草稿接口鉴权、数据库约束、上传校验、物理删除及启动恢复，并核对前端请求与文档。修正草稿选择、文件列表和草稿分页的旧响应覆盖新状态问题，拒绝在当前场景下展示其他场景的草稿；同步修正 README 与本机运行手册的 Vite/Compose 入口及启动命令。

- `node scripts/verify_draft_panel.mjs` 通过：模拟请求乱序，覆盖草稿选择、文件响应、草稿列表响应、场景归属和关闭后迟到响应。
- `npm --prefix frontend run build:prod` 通过。

本次未重跑隔离后端/浏览器全链路，未重启 Demo 或重建 Docker；下列历史验收记录不作为本次全链路验证结果。

## 2026-09-17 草稿整份删除验收

草稿列表增加删除入口，确认后永久删除草稿行及其全部实际文件。V010 去掉文件删除回执对草稿行的外键。隔离 PostgreSQL 17.6、HTTP 与 Edge 验收 88 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。覆盖空草稿、含文件草稿、取消确认、上传中拒绝、匿名/非管理员拒绝、重复删除 204，以及文件物理消失。Maven package 与契约检查通过。未重建 Docker 网关。

## 2026-09-17 草稿文件物理删除验收（后续需求）

运行环境更新后，V009 迁移通过、4 个 Docker 服务健康。按用户明确授权清理此前已逻辑移除的 5 个文件，共 31,450,659 字节：逐 UUID 核对 `.bin`/`.part`/`.ready` 均不存在、草稿文件行均删除，5 条完成回执和5条成功审计保留。清理仅限事先记录的5个ID，其他文件摘要核对不变；零字节互斥锁保留。精确 ID 与执行证据存于忽略目录 `.local/physical-deletion-cleanup-*.json`。

按用户后续要求，将上一节所述逻辑移除改为物理删除：删除 UUID 对应的临时/正式文件和 `ar_draft_file` 行，保留审计及 `ar_file_deletion` 幂等回执。原先“不做正式文件物理删除”的边界在草稿文件范围内被本次要求替代。

- 隔离 PostgreSQL 17.6、HTTP 与 Edge 验收 73 项通过，见 [保留快照说明，非该批次独立证据](evidence/README.md)。新增验证实际文件/数据库行均消失、存储删除失败返回503并可重试、旧登记键无法恢复、删除前/磁盘删除后两种持久状态下的启动恢复、历史逻辑移除不自动清理、明确指定旧记录时可以物理删除，以及浏览器确认/取消与重新上传。
- 存储单元测试 12 项通过，其中新增仅删除指定 UUID 的 `.part`/`.ready`/`.bin`、其他文件保留、非普通文件路径及并发锁拒绝删除、重复删除安全。Maven package 通过。
- OpenAPI 生成与检查通过：276 项检查、46 个接口操作。

删除恢复测试在隔离目录注入两种中断后的持久状态；不声称已经验证物理断电和磁盘硬件故障。

## 2026-09-17 草稿文件移除验收

新增 V008 逻辑移除迁移、管理员 DELETE 接口、文件行“移除”按钮和确认框。正式文件与历史元数据保留，不执行物理删除。隔离 PostgreSQL 17.6、HTTP 和 Edge 浏览器入库验收共 65 项通过，包含取消/确认、刷新后保持移除、重新添加、上传中拒绝移除、旧幂等键不能恢复、重启不会恢复、匿名/非管理员拒绝与审计只记一次；详见 [保留快照说明，非该批次独立证据](evidence/README.md)。Maven package 和 Docker 前端构建通过；契约检查 275 项、46 个操作通过。

## 2026-09-17 资源入库闭环验收

本轮新增场景下的版本草稿、多个文件登记与上传、大小/SHA256 校验、失败重试、重启对账和后台文件明细。实现边界见 [资源入库说明](12-resource-ingestion.md)，完整证据见 [保留快照说明，非该批次独立证据](evidence/README.md)。

- `scripts/verify_ingestion.py`：47 项通过。使用新建私有目录和随机回环端口的 PostgreSQL 17.6、Redis、Spring Boot、Vite、Edge，不修改现有 Demo。覆盖双文件与刷新持久化、正式文件读取校验、大小/摘要错误、请求幂等与并发、真实网络中断、上传中强制终止后重启、`.ready`/已正式落盘但数据库未确认的恢复、匿名/非管理员鉴权及操作审计。浏览器另验证跨 2 MiB 分块的 SHA256、失败原因和重试入口。
- Maven 完整 `package` 成功，`LocalArtifactStorageTest` 10 项通过；Vue 生产构建通过。
- `scripts/generate_contracts.py` 与 `scripts/verify_design.py` 通过；OpenAPI 0.3.0 区分本轮已实现草稿入库接口与历史候选发布接口。

本轮 Docker 引擎不可用，未对修改后的 Nginx 上传转发路径执行容器验收；本轮结果不替代 9 月 16 日容器验收，也不证明物理断电、磁盘写满、真实 Addressables 加载或生产部署。下文保留各阶段的历史结果，涉及“尚未实现上传”的描述指当时状态。

## 2026-09-17 通用资源传输参考框架

运行 `python scripts/test_artifact_transfer.py`，15 项隔离测试通过。使用临时合成二进制文件和回环 HTTP 服务，覆盖整文件下载、缓存复用、真实连接中断后的续传、强 ETag 变化时从头下载、缺失/弱 ETag 与损坏检查点、Content-Range 异常、HEAD/206/416、503 保留部分文件、错误摘要拒绝交付、完整部分文件恢复、已有目标保护及同目标写入锁。

打包格式尚未确定，只有 `PackageCodec` 扩展接口，没有 ZIP 或其他打包/解包实现。测试不涉及真实 AR 包、手机 SDK、生产 Nginx、Spring Boot 下载接口、上传续传或并发容量。既有服务和数据库未修改。边界与运行方式见 [资源传输框架](11-artifact-transfer-reference.md)。

## 2026-09-17 账号删除验收

在 `innovation-infra-check` 隔离容器内执行 `scripts/verify_account_delete.py`，Edge 无头浏览器与实际接口的 18 项检查全部通过。覆盖删除确认和取消、未登录拒绝、禁止删除当前账号和最后一个有效管理员、删除后登录及旧凭证失效、禁止启用和重置已删除账号、账号名保留、历史场景审计保留、已停用引导账号删除，以及系统操作日志记录。测试后恢复隔离引导账号并逻辑删除生成的测试账号，没有修改日常环境的账号数据。结果见 [账号删除验证报告](validation-account-delete.json)。前后端镜像构建通过。

## 2026-09-16 场景删除验收

场景列表新增删除按钮和包含场景名称的确认窗口。后端使用 V006 增量迁移增加逻辑删除字段，删除与审计写入处于同一事务。

在 `innovation-infra-check` 隔离容器中执行 `scripts/verify_scene_delete.py`，使用 Edge 无头浏览器与实际 HTTP 接口完成 17 项检查，全部通过。覆盖取消不发请求、取消保留场景、确认只提交一次、未登录拒绝、缺少或过期修订号拒绝、删除后列表与详情隐藏、禁止再次编辑和启用、保留操作人和历史审计，以及并发删除只有一个成功请求。结果见 [场景删除验证报告](validation-scene-delete.json)。本次未运行依赖旧本机测试账号的 `verify_demo.py`，其中已补充删除时审计失败的事务回滚用例，尚待该隔离环境复验。

前端生产构建、后端 Maven 打包及已有 10 项存储单元测试通过。

## 2026-09-16 Docker 与本地存储基础设施验收

本次新增单机 Docker Compose 和本地 `ArtifactStorage` 基础组件，使用 Windows Docker Desktop 的 Linux 引擎完成隔离验收。测试项目固定为 `innovation-infra-check`、入口固定为 `127.0.0.1:18082`，使用独立配置、容器和命名卷，没有连接现有本机 Demo 数据库。详细运行边界见 [基础设施说明](10-local-infrastructure.md)。

- 本地存储单元测试 10 项通过：覆盖暂存与正式文件隔离、大小和 SHA256 校验、配置上限、传输中断清理、服务重启后的遗留暂存识别、重复提交不覆盖、确认阶段崩溃恢复、同长度损坏识别、并发锁及非法路径/非普通文件拒绝。
- Linux 容器内完整 Maven 打包及上述 10 项测试通过，Vue3 生产构建通过，前后端镜像构建成功。宿主机再次完整打包时，所有模块编译与测试通过，最后因本机后端正在使用目标 Jar，Spring Boot 插件无法重命名产物；未停止现有 Demo，也未清理或覆盖其运行产物。
- [基础设施报告](validation-infrastructure.json)记录 24 项通过：只有网关映射宿主端口，数据库与 Redis 位于 internal 网络，Redis 会话数据使用临时文件系统；后端使用 UID 10001；Nginx 配置有效；前端、登录和场景写入可用；现有上传入口仍关闭；暂存、正式文件及内部路径均不能通过网关读取。
- 强制重建四个容器后，隔离库中的合成场景和成品卷中的合成文件及其摘要保持不变。这个结果验证命名卷跨容器重建持久性，不等于备份恢复、断电恢复或跨物理主机迁移。
- 生成契约与设计检查通过，共 225 项、37 个操作；所有资源和发布接口继续标记为“候选：尚未实现”，顶层说明已明确旧云存储/昼夜契约等待真实成品与客户端加载约定。

当前没有真实成品、上传/版本/发布/下载 API、客户端渲染、磁盘写满、断电、物理 Linux 主机迁移或内网多设备测试。`AR_STORAGE_MAX_BYTES` 当前仅为基础设施测试值，不构成产品上传限制。Redis 7.4.5、PostgreSQL 17.6 和应用容器已共同启动验证，但尚未形成生产运维与高可用承诺。

## 2026-09-16 管理后台 Demo 验收

本次使用项目隔离的 Java 21.0.12.1、PostgreSQL 17.6、Redis 3.0.504 和 Microsoft Edge；后端 Spring Boot 3.5.16，前端 Vue3。服务只在本机验证，未部署服务器。

- [框架 HTTP 报告](validation-framework.json)：23 项复验通过，覆盖登录、同权账号、菜单分页、日志日期筛选、接口关闭、最后管理员保护、改密/禁用/退出/过期失效及密码哈希不外泄。首次引导账号创建与自动停用也已在初始验收中通过。
- [场景及数据库报告](validation-demo.json)：18 项通过，包括并发更新冲突、审计操作人、审计失败的业务回滚、审计追加约束和数据校验。
- [浏览器报告](validation-browser.json)：登录、新建、编辑、停用、查看审计与退出全部通过，未捕获页面脚本错误。截图保存在本机 `.local/scenes-browser.png`。
- [初始化报告](validation-initialization.json)：独立空库初始化后再次启动，迁移、账号、菜单、角色及场景数量一致，没有重复灌入。
- 当时记载契约检查通过，37 个操作按已实现/候选区分，管理接口使用 Bearer；生成源、OpenAPI、Schema 与示例一致。该批次独立报告本次未恢复，不能从 [保留快照](evidence/README.md) 推定其检查数量。
- Java 21 Maven 打包和前端生产构建通过。没有把 Maven 无测试类的构建结果当成业务测试，业务依据上述 HTTP/真实数据库/浏览器检查。

一万条合成场景数据下，单次 `EXPLAIN ANALYZE` 执行时间：列表 0.018 ms、名称筛选 0.458 ms、主键详情 0.007 ms。完整计划见数据库报告。测试数据事务回滚；这是本机查询采样，不是并发压测或端到端响应时间，不用于承诺生产吞吐。

运行环境与命令见 [启动说明](08-demo-runbook.md)，维护差异见 [上游适配记录](09-upstream-adaptation.md)。这一段记录的是管理后台 Demo 当时的状态；后续 Docker 和本地存储基础设施结果见本文上一节。资源上传、版本发布和客户端仍未验收。

## 以下为原云存储与昼夜候选设计的历史记录

## 已完成的检查

[数据库检查报告](validation-database.json)记录了 7 张表和 31 项检查的通过结果，覆盖版本冻结、文件约束、场景及昼夜归属、双连接发布互斥、并发版本冲突、回滚、撤销和审计。

这些检查在独立临时 PostgreSQL 18.4 实例上执行，实例已停止。设计目标为 PostgreSQL 17，仍需在目标版本上复验。

当时记载契约检查覆盖 OpenAPI、运行清单 Schema 与示例、生成源一致性、Session 和 CSRF 声明、数据表及本地链接，共 23 个操作。该批次独立报告本次未恢复，不能从 [保留快照](evidence/README.md) 推定其检查数量。

检查结果验证当前候选结构的一致性，不表示成品格式或文件管理粒度已经确认。

## 验证限制

当前尚未部署，Spring Boot 应用尚未实现。HTTP 登录、对象存储实际读写与校验、内容制作工具、客户端渲染、现场定位、服务器容量和备份恢复均未验收。系统结构图和数据库关系图已生成 PNG 和 SVG，并检查 PNG 的文字、连线与布局。数据库关系已对照 SQL 外键核对；其余 Mermaid 图尚未进行图形渲染检查。

本次文档重写不改变 SQL 行为，沿用现有数据库验证记录；接口元数据与文档链接通过设计检查重新验证。

## 历史复现命令（非日常验证入口）

以下保留历史命令，仅用于独立检出的候选设计复现。旧脚本会覆盖该检出目录的 docs 报告；日常检查使用 [Harness](13-harness.md)，不要在主工作区直接执行本段命令：

```powershell
python -m pip install -r scripts/requirements-review.txt
python scripts/generate_contracts.py
python scripts/verify_design.py
python scripts/verify_database.py --pg-bin 'C:/Program Files/PostgreSQL/17/bin'
```

按实际安装位置调整 PostgreSQL 路径，并在报告中保留实际测试版本。依赖位于其他目录时，执行前配置 `PYTHONPATH`。

数据库脚本只启动自身的临时实例，结束后停止，不连接业务数据库。

## 架构与工作流补充审查

[补充审查](07-design-review.md)核对了架构、数据库、工作流、接口和防御措施的实现成本。[审查证据](design-review-evidence.json)来自新的独立临时 PostgreSQL 18.4 实例，原有 31 项检查通过，额外 5 项检查确认了空并发版本号、普通表写权限绕过发布入口、审计写入影响历史访问资格，以及撤销时递增版本号被拒绝的边界行为。实例已停止，原有数据库验证报告保持不变。

补充报告的通过状态表示成功复现所描述的行为，不表示这些风险已经修复。运行角色的权限由测试构造，不能视为实际部署配置；应用、目标 PostgreSQL 17、对象存储及客户端仍未验证。

本轮另行核对三份生成产物与生成源一致、接口共 23 个、36 个本地文档链接有效，并通过文风检查。当前 Python 环境缺少完整 Schema 校验依赖，未重新执行完整的 OpenAPI 和 JSON Schema 验证。

## GH-1 首页操作指引（2026-09-19）

首页新增平台用途、四步操作路径、按已有权限与动态路由展示的常用入口和发布提示。核对了当前页面名称与菜单迁移。Linux 实现自查及 Windows 待验收步骤见 [首页验收说明](evidence/issue-1/README.md)。真实登录、目标页面、浏览器菜单 150% 缩放及 Windows ingestion 尚未验收；本次未部署，未操作日常 Demo 或真实账号/存储。

## 2026-09-19 PR #2 简单审查、构建与内网部署

- 用户明确授权 review、构建、合并和部署。审查 head 062a1493a88ff3d4d5c64b97e21fb26e8aaf75d4，与当时 main a0df970 的合并候选；未发现实质缺陷。核对首页三个权限及路由、动态路由加载时机、四步操作名称及发布边界。主工作区其他未提交修改未纳入。
- Windows 隔离目录 .local/pr2-release：npm ci 成功；使用 PYTHONPATH 指向已有 .local/python 依赖后 doctor quick、check quick、check frontend 均通过。frontend 报告 .local/harness/20260919T145118Z-2kgfytra/report.json，sourceUnchanged=true，包含 draft-panel 和生产构建。首次 doctor 因隔离目录缺 Python 依赖阻塞，未作为通过证据。
- Docker gateway 生产构建通过，镜像 innovation-gateway:pr2-062a149。PR 合并提交 e92ceed746b5c1ee485fae850a6449cd5ecb1ad9；部署用 frontend/deploy/compose 与合并主分支无差异。
- 保留原镜像 innovation-gateway:before-pr2，以新镜像更新 infra-v1，仅执行 compose up -d --no-deps --no-build gateway。后端、数据库、Redis 未重建。网关 healthy，/healthz 与 /index HTTP 200；实际 HTTP 获取 index-BYBCSCSi.js 含操作步骤、发布前请留意。
- 地址 http://192.168.0.12:43174/index 。已有 Chrome 页刷新后进入登录页；未绕过登录，登录后真实点击、权限差异及第二台 LAN 设备访问仍未验证。此前人工确认的是隔离组件视觉效果，不等同完整业务验收。本次没有数据库改动或数据库版本验收。

## GH-4 默认展示发布版本文件（2026-09-19）

新增默认发布版本选择、发布成功后的文件切换及场景初始化过期响应防护；保留手动选择和发布冻结规则。[自查范围与 Windows 验收步骤](evidence/issue-4/README.md)记录命令和限制。组件模拟回归已通过；最终 harness 结果见本任务 PR/Issue 进展记录。真实登录点击、Windows ingestion 与独立审查待完成，不代表业务验收通过。无数据库变更，未部署。
## GH-3 场景操作记录中文动作（2026-09-19）

核对当前后端全部 21 种动作，前端集中映射中文，未知代码保留原文；不修改接口、数据库、刷新或详情处理。实现自查、合成记录组件截图、完整映射和 Windows 待验收步骤见 [GH-3 验证说明](evidence/issue-3/README.md)。真实登录页面、Windows ingestion 和独立审查仍待完成；未合并、未部署。

## GH-7 管理员密码长度与登录返工（2026-09-20）

密码设置与实际登录入口统一使用 6–64 长度常量，补充真实登录服务路径的边界回归。Linux quick 检查已通过；Java 测试、Windows 专项账号矩阵、旧 Token 失效与独立审查仍待完成。[本次证据及隔离验收步骤](evidence/issue-7/README.md)区分原提交历史结果和返工证据；前端最终结果见现有 PR #8。未部署，无数据库迁移。

## 2026-09-20 最新主线 LAN 网关部署

- 当前分支快进至 `origin/main` 的 `b2b0200`，原有未提交修改经 autostash 恢复；部署输入 frontend 与网关配置没有本地差异。
- `python scripts/harness.py doctor --profile quick`、`check --profile quick`、`check --profile frontend`、`doctor --profile ingestion`、`check --profile ingestion` 均通过。frontend 与 ingestion 报告均为 `sourceUnchanged=true`；报告分别保留在 `.local/harness/20260919T161707Z-1apjlois/`、`.local/harness/20260919T161810Z-iilcbd4k/`。
- 隔离 PostgreSQL 17.6 / Redis / Spring Boot / Vite / Edge 验证通过，包含真实登录、默认展示发布文件、替换发布后展示新文件、手动选择与刷新保持。浏览器收尾日志有 CancelledError；进程退出码为 0，结构化业务检查全部通过。
- 执行 `docker compose --env-file config/compose.env build gateway` 及 `up -d --no-deps --wait gateway`，仅更新网关；后端容器 ID 与启动时间未变，数据库和 Redis 未重建。
- 新网关镜像 ID：`sha256:7488cd88d8ce15398becfdc545965acd1926f7153f8806b202abaa87301d5ca2`。旧网关镜像保留为 `innovation-gateway:rollback-20260920-b2b0200`。
- 四个服务 healthy；本机访问 `http://192.168.0.12:43174/` 返回 HTTP 200，`/prod-api/captchaImage` 返回 code 200。未做另一台 LAN 设备访问或线上日常账号登录验证；不包含真实客户端加载验收。

## 2026-09-20 最新 main 局域网部署（c604236）

- 从 origin/main 获取 c604236b1e6b617fcbb3dcd64dcbf3dabe948906，在 `.local/deploy-c604236` 独立 worktree 构建；主工作区分支及已有未提交修改保留。
- 最新 worktree 执行 `python scripts/harness.py doctor --profile quick`、`python scripts/harness.py check --profile quick` 通过；复用主工作区 `.local/python` 依赖。报告 `.local/deploy-c604236/.local/harness/20260920T023206Z-7nd3vhx4/report.json`，sourceUnchanged=true，SHA256=c6a197c7dd11406af6e03e6c8543d995d9f4a2286249723bd338a5b4815b5f20。
- `node scripts/verify_draft_panel.mjs` 通过；`docker compose --env-file E:/code/java/innovation/config/compose.env build backend gateway` 通过。Maven 3.9.11/JDK 21 构建实际执行 23 项测试，零失败/错误/跳过，包含 DemoAccountServiceTest 1 项、SysLoginServiceTest 5 项；Node 22.18.0 前端生产构建通过。
- 数据库 PostgreSQL 17.6；备份 `.local/deployment-20260920-c604236/database.dump`（79419 字节），pg_restore --list 可读取。旧后端保留为 innovation-backend:rollback-20260920；旧网关镜像底层内容缺失，无法 tag/commit，已备份 gateway-html 和 gateway-default.conf，可据此重建回退网关。
- `docker compose --env-file E:/code/java/innovation/config/compose.env up -d --no-deps --wait --wait-timeout 180 backend gateway` 成功；四服务 healthy，数据库/Redis 未重建，Nginx 配置检查通过。实际后端镜像 sha256:4238e50071aee2fac320e980fb88829cb6d2939893ed1629636e3eef81276bf5，网关 sha256:a009766600e0110511630f8fb4586767da3a98b4750010d0713e19b7e4d087e1，均与新构建一致。
- 本机访问 http://192.168.0.12:43174/ 与 /prod-api/captchaImage 均 HTTP 200，后者业务 code=200；Flyway 最新 013 成功。
- 范围限制：本次未执行完整 ingestion、真实账号登录/改密浏览器流程、第二台 LAN 设备访问或客户端加载验收；单元测试及健康检查不替代这些验收。


## 2026-09-20 Symphony 无人值守交付与人工阻塞修复

基线 HEAD `5806c68680212dccc3874b94a0ddd49dde080a5a`，工作区含先前 DeepSeek 接入及文档修改，本次保留。GH-9 在 06:40:37Z、07:11:58Z 调用 Apps GitHub 评论工具触发人工授权；`turn_ended_with_error` 覆盖阻塞事件，调度器随后重试。

- 适配器固定线程配置 `features.apps=false`，保留注入的 `github_api`。WORKFLOW 明确所有 GitHub 操作使用该动态工具，宿主验收待完成可以交付草稿 PR，并禁止为宿主专属检查反复补系统/浏览器依赖。
- `python scripts/prepare_symphony_blocking_fix.py --verify`：固定上游 SHA256 后生成调度器补丁；独立 Elixir VM 执行 6 组实际回调序列全部通过，覆盖输入/审批事件被结束错误与通知覆盖、仅结束错误携带阻塞原因、普通错误仍重试。保留阻塞只限同一 worker 生命周期。
- Windows `python -m unittest discover -s scripts -p test_symphony_codex_adapter.py -v`：18 项中 17 通过，Linux 进程树项跳过。无网络、无凭据的 `innovation-symphony:0.0.3-java-v2` 临时容器执行同套测试：18 项全部通过。首次误在挂密钥的运行容器测试，缺密钥案例无法成立；改到无凭据容器后验证，未放宽断言。
- `python scripts/harness.py doctor --profile quick` 与 `check --profile quick` 通过，初次报告 `.local/harness/20260920T072640Z-d0wgcptm/report.json`，`sourceUnchanged=true`；后续文档记录不属于该指纹，最终检查见本次交付报告。
- 本次已应用：临时移除 GH-9 ready，等待 running/retrying/blocked 和 ready 队列全空，备份工作区源码、差异与原 BEAM 后停止原容器，只替换 Orchestrator 模块并启动。已安装模块与测试产物 SHA256 同为 `27f8d1caa4c92c24f1b5d52a7044c4849a285a67d9483133cdcdbcc2cb0eaae3`；HTTP API 健康后恢复 GH-9 ready。未重建镜像、未操作 Demo。
- 回退备份：`.local/symphony/blocking-fix-20260920/`；补丁及编译产物：`.local/symphony/data/blocking-fix/`。回退前先暂停调度至空闲，将备份 `Elixir.SymphonyElixir.Orchestrator.beam` 恢复到原容器同名 ebin 路径，再启动并检查健康；源码与 data 不删除。重建容器后补丁需重新应用。
- 限制：协议/调度回归不证明 GH-9 功能、布局或真实后端验收完成；GH-9 继续执行，最终草稿 PR 和宿主验收分别核对。未运行数据库验收，本次不涉及数据库行为。


## 2026-09-20 安装与前端构建复用

- 基线 HEAD `5806c68680212dccc3874b94a0ddd49dde080a5a`，保留此前 DeepSeek/调度修复等未提交改动。新增 `agent_check.py`、`frontend_control.py`，接入 harness frontend build、WORKFLOW 和 Symphony 只读工具目录；不重启、不修改 GH-9 工作区、Demo 或 LAN。
- `python -m unittest discover -s scripts -p test_frontend_control.py`：Windows 15 项通过；无网络/无凭据 `innovation-symphony:0.0.3-java-v2` 临时容器同套 15 项通过。覆盖输入/环境/锁文件变化、包损坏、产物损坏、日志丢失、并发锁、超时/中断暂停、显式重试、构建期间源码变化。普通 quick 与业务检查不复用。
- Windows 独立副本 `.local/execution-reuse-validation` 实际 npm ci：14.4 秒，528 包；实际生产构建成功。连续两次 `agent_check.py --root <副本> --profile frontend` 全部通过，分别 56.5 秒和 25.8 秒，第二次安装及构建 `reused`，原日志引用保留、源码与 dist 重新校验；quick、契约、草稿面板检查仍执行。报告分别为该副本 `.local/harness/20260920T081319Z-9y_olpn4/report.json`、`20260920T081416Z-hgfroei5/report.json`，均 `sourceUnchanged=true`。计时汇总在副本 `integration-benchmark.json`。
- 测试环境首次缺少 Python 验证依赖，且沙箱创建的测试目录与宿主用户 Git 所有权不同，入口如实返回 blocked。随后以子进程级 safe.directory 和现有只读 `.local/python` 完成验证，未修改全局 Git 配置；同时收紧 harness --root 必须是实际 Git 根目录，避免嵌套目录误用外层仓库指纹。
- 当前工具安装至 `/opt/symphony-execution`，root 所有且文件只读；未来新容器由 symphony.ps1 逐文件只读挂载。运行中的旧会话不会自动获得新提示；新会话使用统一入口。构建上限 900 秒，失败同输入暂停而不是切换命令再次构建；明确修复后才带 `--retry-reason` 重试。
- 限制：完整依赖哈希有 I/O 成本；Windows 测速不证明 Docker 挂载盘相同速度。只有本项目已声明的文件/环境输入纳入构建键，新增外部输入须扩展。代码失败不降级为环境待验收；复用构建不证明 HTTP/浏览器/数据库/客户端验收。此次未运行数据库验收，无数据库版本结论。


## 2026-09-20 Symphony 原生工作区与构建前扫描去重

- 按用户要求把 `/data/workspaces` 切换到 Docker 命名卷 `innovation-symphony-workspaces`，各 Issue 的源码、node_modules、Maven 仓库和 venv 独立；其余 `/data`、共享下载缓存、任务状态与 Codex Trace 保持原挂载。先核对 running/retrying/blocked 和 open ready 为空，停止并保留旧容器，源工作区只读迁移。
- 迁移 GH-13 共 31,355 个条目、342,332,120 字节，逐文件 SHA-256 校验通过；与宿主独立枚举的条目数一致。一次性读取 Windows 旧目录耗时 1,062.344 秒。证据在 `.local/symphony/native-workspace-migration/migration.json`，完整清单在原生卷根目录 `.migration-inventory.json`。源目录未删除。
- `agent_check.py` 取消前置 deps 调用，统一由 harness 的 frontend-build 在同一把锁内检查依赖并构建；已安装依赖的真实构建仅保留一次构建前扫描与一次构建后变化检查。显式 retry reason 透传，冷工作区由该控制器安装依赖，失败暂停、输入/产物校验与任务隔离仍保留。
- Windows 前端控制测试 19 项通过；Linux 同套 19 项通过。迁移测试 Windows 3 项通过、1 项 Linux 专属跳过，Linux 4 项全部通过，覆盖拒绝覆盖/重叠路径、读取失败不生成成功标记、文件权限及符号链接。迁移回归已纳入 quick。PowerShell 语法检查与 git diff --check 通过。
- 原生卷中执行 `/data/workspaces/GH-13/.local/venv/bin/python /opt/symphony-execution/agent_check.py --root /data/workspaces/GH-13 --profile frontend`，全部通过。镜像保持 `innovation-symphony:0.0.3-java-v2`，2 核/4 GiB；源码指纹始终为 `974a523d2d69154dfbe6003d9bdad9b822c2d8b0e099f22ed62e4d0054023a5b`。检查总耗时由 1,149.850 秒降为 21.598 秒（本次计时包含 docker exec），实际构建由 465.019 秒降为 13.554 秒，mode=executed，依赖 reused。24,429 个依赖文件的构建前/后扫描分别 0.880/0.676 秒；311 个产物文件的内容指纹与迁移前一致。此次单次对比不是并发负载或所有任务的性能保证。
- 容器报告 `/data/workspaces/GH-13/.local/harness/20260920T130655Z-k5ahnh5j/report.json`，sourceUnchanged=true；宿主导出、构建日志与前后耗时保存在 `.local/symphony/native-workspace-migration/`。GH-13 仍处于 review，未重启模型执行、未更新 PR。43190 API 与 43191 Codex Trace HTTP 验证通过，deepseek-flash/high 目录校验通过（不代表此次发起过模型推理）。
- 回退容器 `innovation-symphony-before-native-workspaces` 已停止保留，原 `.local/symphony/data/workspaces` 仅为回退副本。回退前须确认空闲，保留当前卷的新修改，再停止并改名新容器，恢复旧容器名称并启动。工具变更前副本在 `.local/symphony/native-workspace-migration/rollback/before-*.py` 与 `before-symphony.ps1`；没有删除任何工作区、合并或修改 Demo/LAN。此次未改 Java/数据库行为，也未执行业务 HTTP/浏览器验收。


## 2026-09-20 Symphony 版本固化、自检与并发验收

- 新增环境清单与显式 freeze/只读 verify、Doctor，固定已接受的镜像 ID、运行工具和控制器/补丁摘要；保留原镜像，导出无凭据镜像归档和模块副本。基础 Dockerfile 纳入仓库，BuildBase 校验官方发行文件摘要；源码重建可能改变镜像 ID，不声称 apt/传递依赖逐字节可重复。
- 编码前按外置计划做轻量自检，失败持久化 blocked，不自动更换环境或重试。实测正常任务检查 0.537 秒，最终 Doctor 的容器探测 0.569 秒；在合成控制状态下移除 Java/Maven PATH，0.314 秒内在编码前阻塞。未修改 GH-13 的真实计划、状态或 PR，没有发起模型推理。
- 无网络、无凭据的同镜像 Linux 临时容器执行 46 项环境/版本/生命周期/路由测试全部通过。Windows 版本测试 6 项、生命周期测试 18 项通过；最终构建槽位调整后，Linux 生命周期 18 项再次通过，覆盖 quick 不占槽位及 frontend 释放槽位。覆盖脚本/镜像漂移拒绝、按 profile 选择工具、缺少 Maven、跨任务写入隔离、构建槽位等待/取消/释放。后续新增的计划选择与配置校验另由 Doctor 和真实 Task.begin 集成验证。
- 独立 2 核/4 GiB 容器、原生验证卷，以只读 GH-13 指纹 `974a523d2d69154dfbe6003d9bdad9b822c2d8b0e099f22ed62e4d0054023a5b` 复制三份源码和独立暖依赖。基线 Java/前端分别 15.280/12.857 秒，总计 28.138 秒；并发 A 26.745/21.000 秒，B 26.744/21.654 秒，共 48.438 秒。每个执行 22 项 Java 测试，全部通过；源码指纹不变，311 个前端产物内容指纹一致。匿名内存峰值 3,022,139,392 字节，含缓存峰值 4,171,456,512 字节；oom/oom_kill/max 计数增量均为 0。
- 两路吞吐约提升 16%，内存余量有限，因此仍允许 4 个编码 Agent，控制器默认最多 1 路重构建；等待不计入命令超时，可取消，文件锁随进程退出释放。不引入新 Worker/服务。
- 首次并发实验在卷权限阶段失败；随后发现复制夹具过度排除依赖包 dist，Java 通过但 Vite 缺文件。已修复空卷初始化与复制范围，增加回归与复制后依赖哈希校验，使用新空目录完成上述实验。失败记录保留，没有放宽业务断言。
- 证据 `.local/symphony/environment-lock-validation/`；成功实验 `concurrency-report.json`，轻量自检 `doctor-final.log`、`task-gate-integration.json`，Linux 测试 `linux-tests.log`。回退容器 `innovation-symphony-before-environment-lock`、原脚本 rollback 与镜像/补丁 recovery 保留。限制：没有四路压力、冷下载、HTTP/数据库/浏览器验收结论，未合并或部署 Demo。

## 2026-09-25 项目更名与 Compose 数据迁移

- 基线 HEAD 为 `360632e21e77b26e57ef82bab189bc66386d89fe`。根项目元数据、前端标题、文档及自动化引用改为 `innovation-ar-resource-platform`；GitHub 仓库已更名，`origin` 指向新地址，`git ls-remote origin HEAD` 与基线一致。GitLab 私有项目的名称与路径已在网页更名，本地 `gitlab` 远端地址同步更新。保留此前已有的未提交修改；本次源码提交和远端同步以 Git 历史为准。
- Compose 项目名与应用镜像名已更改，数据库由 `innovation` 改为 `innovation_ar_resource_platform`。数据库登录角色仍为 `innovation`。迁移前的 PostgreSQL 17.6 自定义格式备份保存在 `.local/rename-20260925/innovation-before-rename.dump`，SHA-256 为 `29FF5C2556A24FCCF0A16A2A1245172DB4917B3E8665292ACC918F1FE87649DB`；`pg_restore -l` 可读取。原 `innovation_` 四个命名卷未删除，新项目四个卷的文件清单与复制时源卷逐文件摘要一致。
- 在新命名卷的数据库中核对公共表 24 张，`ar_audit=199`、`ar_draft=4`、`ar_draft_file=57`、`ar_scene=4`、`sys_user=3`，与迁移前一致。执行 `docker compose -f compose.yaml --env-file config/compose.env build backend gateway` 和 `up -d --wait --wait-timeout 180` 成功；PostgreSQL、Redis、后端、网关四个服务均 healthy。`http://192.168.0.12:43174/` 返回 HTTP 200 且页面标题为新名称，`/prod-api/captchaImage` 返回业务码 200。
- `python scripts/check_java.py --module ruoyi-ar` 的 22 项测试通过，报告在 `.local/java-check/1d09cc3af862/report.json`。`python scripts/agent_check.py --profile frontend` 通过 quick、契约、专项前端检查及生产构建输入/产物复核，报告在 `.local/harness/20260925T065125Z-p8vme4sp/report.json`，该轮源码指纹 `118e6dd59ce86e33ce0ab359cb8c9c821f8ad4a949a38ed441c97dfbeaf3d03a`、`sourceUnchanged=true`；本条验证文档在该轮之后补记。
- 限制：未执行真实账号登录、第二台局域网设备或客户端加载验收。原卷与备份作为回退材料保留；若新库已有新增写入，回退前需先处理数据差异。数据库角色重命名未完成，本次不修改其登录凭据。本机目录已更名为 `E:\code\java\innovation-ar-resource-platform`；Codex 桌面应用保存的项目入口另行核对。

## 2026-10-27 公网分发方案文档提交检查

- 本轮仅提交公网分发建议、4DGS 样本任务记录与知识索引，保留原有 `README.md.bak`，没有业务源码变更。
- `git diff --check` 及两份新增文档的 `git diff --no-index --check /dev/null <文件>` 均无空白错误。
- `python3 scripts/harness.py doctor --profile quick` 与 `python3 scripts/harness.py check --profile quick` 均返回 blocked（退出码 2）：缺少 contract validators；报告分别为 `.local/harness/20261027T080034Z-9t5d_ybf/report.json`、`.local/harness/20261027T080044Z-8qz0vq69/report.json`。本机无 `python` 命令，使用 `python3`。未执行业务、浏览器或数据库验收。
