# Development and acceptance workflow

日常部署、Vite 开发和隔离验收是不同环境。日常拓扑、2026-10-30 云端切换与源端数据保留记录以 [基础设施手册](10-local-infrastructure.md) 为主；新功能先在本地开发或隔离实例验证，文档中的命令示例不构成更新日常实例的授权。Windows 原生 Demo 命令仍保留，适用范围见下文。

## Development loop


Work locally. Docker is a packaging step after the change is settled, not part of the edit cycle.

1. Inner loop: edit source, use Vite and the appropriate isolated backend/runtime, check the result, repeat.
2. Package Docker only when the UI and APIs are stable and an authorized deployment or container-shaped acceptance requires it.
3. Do not rebuild images, `docker cp` into a container, or recreate Compose services for copy, button, layout, or other small edits.

前端内循环使用 Vite（`npm --prefix frontend run dev`）。`local_demo.py` 的数据库和进程管理依赖 Windows `.exe`/PowerShell，仅在相应原生环境使用；Java 修改先由 `scripts/check_java.py` 产出已测试 Jar，再重启对应隔离后端，不为每次编辑重建日常镜像。Linux 入库的完整准备、验收与停止流程见 [Harness](13-harness.md)“使用”节；旧播放器的真实样包播放命令仅见 [历史记录](20-4dgs-sample-validation.md)，不是当前启动入口。

以下是 Windows 原生工具示例，不是 Linux 日常 Compose 启动命令：

```powershell
python scripts/local_demo.py infra
python scripts/local_demo.py backend
npm --prefix frontend run dev
```

Open `http://127.0.0.1:43174`. Local API is `http://127.0.0.1:18080`. Vue saves hot-reload; do not rebuild the gateway to see them.

Windows Agent 的 Job Object 可能在启动命令返回时终止子进程；这不是 Linux 的通用进程约束。原生工具打印 `started` 不代表服务仍存活。使用该运行方式时保持拥有进程的终端/会话，并确认端口与健康接口。

Windows 原生 Agent 可在一个长驻命令中启动 infra/backend 并保持父进程不退出：

```powershell
python scripts/local_demo.py infra
python scripts/local_demo.py backend
python -c "import time; time.sleep(10**9)"
```

Do not report the local demo as up merely because `local_demo.py` printed `started`. Confirm `http://127.0.0.1:18080/captchaImage` and `http://127.0.0.1:43174/` after the starter is still running. `python scripts/local_demo.py stop` remains the stop path.

环境地址与云端/源端状态统一查 [基础设施手册](10-local-infrastructure.md)，不得自行重启旧本机服务、恢复隧道或切回旧路由，也不得清理保留的数据卷。Vite 使用 `127.0.0.1:43174`，Linux 隔离验收使用 `127.0.0.1:18082`，不能混用日常数据库、账号与配置。Compose 前端在镜像构建时固化；Redis 使用 tmpfs，重启会丢失其中的登录会话，重建 backend/gateway 本身不等于清空 Redis。

Linux 隔离开发/验收实例的默认管理员账号为 `admin` / `123456`，由 `scripts/prepare_4dgs_check.py` 首次准备时通过正常账号接口创建。已有实例优先使用该账号；迁移旧随机账号时使用私有凭据中的有效管理员创建，首次空库使用 bootstrap。只有新账号实际登录成功后才更新 0600 凭据文件，不重置已有账号密码、不重新启用退役 bootstrap。仅限本机回环 `127.0.0.1` 的隔离实例；日常 18081、云端、局域网及任何真实数据环境不得使用该弱口令。

For copy, button, or layout-only changes: edit `frontend/src` and any Playwright selector that clicks the old control (`scripts/verify_browser.py`, `scripts/verify_ingestion.py`). Update the matching sentence in `docs/` if it names that control. A removed label is done when the source and selectors no longer name it. Full login-and-click checks are for behavior changes. `bootstrap` is retired on the daily instance; do not enable it or mint sessions to satisfy a browser check. If you cannot log in, report the blocker rather than bypassing authentication.

日常发布统一按 [基础设施手册](10-local-infrastructure.md) 核对目标配置、已验收镜像及校验结果，并取得明确部署授权；云端运行 Compose 不含构建步骤，不在部署主机照抄本地 build 命令。数据库迁移前先备份并获授权，不因小范围 UI 编辑重建日常实例。

## Build, Test, and Development Commands

Run the shortest requirement-specific check first; see [专项验收](16-fast-review.md). For documentation, repository rules and contracts, run from the repository root:

```powershell
python scripts/harness.py doctor --profile quick
python scripts/harness.py check --profile quick
```

Use [Harness profiles](13-harness.md) to add frontend or ingestion checks by risk. Reports stay under `.local/harness/`; quick does not establish HTTP or browser acceptance. Prepare missing dependencies according to doctor, then rerun it.

Only when changing contracts, edit `scripts/generate_contracts.py`, run `python scripts/generate_contracts.py`, then run quick. Validation must not regenerate contracts to hide drift.

`verify_design.py` and `verify_ingestion.py` retain legacy defaults that overwrite reports in docs; use harness for routine checks. `verify_database.py` checks the historical seven-table candidate and writes `docs/validation-database.json`; it is not the current application database acceptance entrypoint. Historical reproduction belongs in a separate checkout. Record the tested PostgreSQL version; PostgreSQL 18 results do not establish PostgreSQL 17 compatibility.

## Coding Style & Naming Conventions

Use four-space Python indentation, SQL/Python `snake_case`, API `camelCase`, UUIDs, and UTC timestamps. Keep Chinese design documentation concise. Update SQL, contracts, and documentation together. No formatter or linter is configured.

The V0.1 scripts initialize an empty database. Use descriptive Flyway names such as `V003__add_scene_field.sql` for subsequent changes. Keep initialization reproducible.

## Testing Guidelines

Use JSON Schema/OpenAPI validators and real isolated PostgreSQL. Current business checks cover fixed scene manifests, upload-completion visibility, enable/disable, verified files, physical scene deletion/recovery and audit. A new model requires a new scene; version replacement and republish are historical behaviors. No percentage coverage threshold exists. Record actual commands, versions, results and limitations in [validation records](06-validation.md); SQL alone does not verify HTTP or resource distribution.

## Commit & Pull Request Guidelines

Use imperative subjects, optionally prefixed `docs:`, `db:`, or `contracts:`. PRs should explain changed behavior, the reason for the change, validation commands, database version, and remaining assumptions.

## Security & Configuration

Never commit credentials or production connection strings. Keep examples synthetic and validate only against isolated databases. Treat unresolved client formats and server settings as explicit assumptions.
