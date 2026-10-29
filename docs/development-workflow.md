# Development and acceptance workflow

当前日常应用运行在开发机 Docker Compose，通过 nginx 中继与反向 SSH 隧道提供公网 HTTPS；新功能先在本地开发或隔离实例验证，不因文档中的启动示例自动更新日常实例。Windows 原生 Demo 命令仍保留，适用范围见下文。

## Development loop


Work locally. Docker is a packaging step after the change is settled, not part of the edit cycle.

1. Inner loop: edit source, use Vite and the appropriate isolated backend/runtime, check the result, repeat.
2. Package Docker only when the UI and APIs are stable, the LAN demo must show the new build, or a container-shaped acceptance is required.
3. Do not rebuild images, `docker cp` into a container, or recreate Compose services for copy, button, layout, or other small edits.

前端内循环使用 Vite（`npm --prefix frontend run dev`）。`local_demo.py` 的数据库和进程管理依赖 Windows `.exe`/PowerShell，仅在相应原生环境使用；Java 修改先由 `scripts/check_java.py` 产出已测试 Jar，再重启对应隔离后端，不为每次编辑重建日常镜像。Linux 入库与真实样包流程见 [Harness](13-harness.md) 的 `prepare_4dgs_check.py` 入口。

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

日常 Compose 网关为 `http://192.168.0.12:18081`，公网 `https://4dgs.elma-gohan.xyz` 经 `elma-gohan.xyz` 的 nginx 与反向 SSH 隧道转入；开发机或隧道离线时不可用。Vite 为 `127.0.0.1:43174`，Linux 隔离验收为 `127.0.0.1:18082`，三者不能混用数据库、账号与配置。Compose 前端在镜像构建时固化；Redis 使用 tmpfs，仅 Redis 重启会丢失其中的登录会话，重建 backend/gateway 本身不等于清空 Redis。

For copy, button, or layout-only changes: edit `frontend/src` and any Playwright selector that clicks the old control (`scripts/verify_browser.py`, `scripts/verify_ingestion.py`). Update the matching sentence in `docs/` if it names that control. A removed label is done when the source and selectors no longer name it. Full login-and-click checks are for behavior changes. `bootstrap` is retired on the LAN demo; do not enable it or mint sessions to satisfy a browser check. If you cannot log in, say so and stop.

When the user asks to publish a settled change to the LAN demo, rebuild only what changed. Frontend-only:

```powershell
docker compose --env-file config/compose.env build gateway
docker compose --env-file config/compose.env up -d gateway
```

Do not `up --build gateway` in a way that recreates `backend`.

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

Use JSON Schema/OpenAPI validators and psycopg with real PostgreSQL. For current business changes, check affected invariants such as immutable file lists, verified files, publication pointer replacement, physical deletion/recovery and audit consistency. Day/night variants remain historical candidates; republishing an intact old version uses the current publication API, not a separate rollback endpoint. No percentage coverage threshold exists. Record results and limitations in `docs/06-validation.md`; SQL tests do not verify HTTP, cloud storage, or client behavior.

## Commit & Pull Request Guidelines

Use imperative subjects, optionally prefixed `docs:`, `db:`, or `contracts:`. PRs should explain changed behavior, the reason for the change, validation commands, database version, and remaining assumptions.

## Security & Configuration

Never commit credentials or production connection strings. Keep examples synthetic and validate only against isolated databases. Treat unresolved client formats and server settings as explicit assumptions.
