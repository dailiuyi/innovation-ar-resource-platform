# 需求专项优先与人工验收实例

“审查 PR X”默认执行本页完整流程；明确“只审代码”时不启动实例。先按 [Agent 工作流入口](17-agent-workflow.md) 核对独立审查身份、需求和用户范围。准备者从 Issue/任务计划读取 hostSuites，在 prepare 时用 `--require-suite` 补充，不能只依赖路径自动选择。

## 顺序

1. 先运行最短需求业务路径。密码策略先验证短密码设置后登录；发布功能先验证发布指针变更。实现前追踪实际调用方。
2. Java 修改先执行 `python scripts/check_java.py --module ruoyi-framework`（按风险选择模块），再执行 quick；UI 行为追加 frontend。零测试、跳过或未运行不能当通过。
3. 按改动选择 HTTP/数据库回归。账号变更不默认跑文件入库全套；迁移、存储、发布等相关变更才追加 ingestion。超时先定位原因，不盲目重复长构建。
4. 独立审查通过后启动同一提交的隔离实例，交付网址、凭据文件位置、版本、验证范围和停止命令。

## Windows 原生审查命令

`review.py` 的 HTTP/人工实例运行时目前只支持 Windows，以下命令统一用同一个 Windows 用户执行，必要时授权沙箱外运行，不在沙箱与宿主账号间反复建立 Git 快照。Linux 的入库/真实样包验证另用 [Harness 固定隔离 Compose 流程](13-harness.md)（`127.0.0.1:18082`），不把它当成 `review.py` 的跨平台实现，也不冒充同 SHA PR 人工审查通过。下列 Windows 路径按实际检出目录替换：

```powershell
python E:/code/java/innovation-ar-resource-platform/scripts/review.py prepare --pr 8
# SHA 替换为 prepare 返回的完整提交号。
# 在 check 前完成该 SHA 的独立代码审查；有阻断缺陷则报告，不启动验收实例。
python E:/code/java/innovation-ar-resource-platform/scripts/review.py check --pr 8 --sha SHA --suite auto
# 独立审查者确认无阻断问题后执行。
python E:/code/java/innovation-ar-resource-platform/scripts/review.py serve --pr 8 --sha SHA --reviewed-sha SHA
python E:/code/java/innovation-ar-resource-platform/scripts/review.py status --pr 8 --sha SHA
python E:/code/java/innovation-ar-resource-platform/scripts/review.py stop --pr 8 --sha SHA
```

工作区在 `.local/reviews/pr-编号/完整SHA/source`。每个提交独立检出，不覆盖脏目录、不切换主工作区。Python/JDK/PostgreSQL/Maven 来自宿主机 `.local`；npm 在审查目录独立安装并共享下载缓存。缺失 Maven 缓存时明确失败，确认后用 `check ... --online` 显式补齐依赖。预览运行期间拒绝重建，先停止再验证。

prepare 按完整 SHA 的改动路径选择专项，并写入 snapshot。所有实例要求 frontend 和 smoke；前端改动追加 scene-ui（当前覆盖场景页面），账号登录相关后端追加 accounts，入库/存储/迁移追加 ingestion。需求准备时选定的额外专项使用 `prepare --require-suite accounts` 等补充；重复 prepare 只增加、不删除原门槛。其他页面的业务操作尚无专项时应先补充检查器，不能把场景检查当作该页面通过。

`check --suite auto` 按 snapshot 执行。smoke 创建独立 PostgreSQL 17、Redis、存储和随机回环端口，自动创建 review_admin、长短名称场景、对应的合成成品版本（有效 resource.json 加合成小文件，不可渲染）；真实 Edge 登录后点击场景信息和对应版本面板。scene-ui 覆盖场景按钮及多视口布局，使用合成响应；accounts 覆盖密码边界和会话失效；ingestion 执行既有真实 HTTP/数据库/浏览器业务链。所有数据与日常 Demo 隔离。

依赖通过 frontend_control 复用；同 SHA 通过测试的后端 Jar 按哈希复用，记录 executed/reused。开始新检查先废止旧绿色记录。serve 按 snapshot 的全部专项检查证据，核对源码、Jar、独立审查 SHA 和远端 PR head。PR 更新后新 SHA 另建目录，旧实例始终保留旧 SHA，旧批准不能用于新版本。`--reviewed-sha` 是独立审查声明，不是自动批准。

serve 再创建一套独立合成数据，检查启动、API 代理和真实登录；交付网址、完整 SHA、credentialsFile、fixtures、已通过专项、待人工观感项与 stop 命令。凭据仅保存在本地，首个日常账号创建后 bootstrap 自动停用。

交付时说明网址只在当前 Windows 电脑可用，以及持有实例的前台进程/会话。给出凭据文件路径，不在报告中打印密码。若无法保持进程或缺少运行条件，明确交付“实例未就绪”及阻塞证据，不能提供未经健康验证的网址。用户验收结果另记对应 SHA；自动检查通过不代表人工确认。

`serve` 是长驻前台进程：人在终端保持它运行，Agent 使用持续终端会话，并从另一命令查询 `status`。`stop` 请求父进程关闭自己创建的 Java/Vite/Redis/PostgreSQL，保留证据及隔离数据。父进程被强杀可能留下锁或 PostgreSQL，须核对实例目录与进程身份后恢复，禁止按进程名批量终止服务。

## Symphony

`scripts/symphony.ps1 Build` 构建 `innovation-symphony:0.0.3-java-v2`，包含 JDK 21/Maven。修改配置不代表运行容器升级。只有 running/retrying=0 且 ready 队列为空时保留旧容器并切换，沿用 data 和既有认证流程。

Symphony 交付可审查代码、已运行的 Java 证据和宿主待验收项；宿主独立审查者负责真实 HTTP 和人工实例。实现者不得自我批准。未启动同版实例时写“人工实例待启动”，不写“全部完成”。独立实例不等于合并或日常 Demo/LAN 部署。
