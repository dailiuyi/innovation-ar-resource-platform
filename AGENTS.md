# Repository Guidelines

## Start here

- Read the [knowledge index](docs/index.md) for current implementation, historical candidates, decisions and task handoffs.
- For verbal requirements, Issue preparation, Symphony work, PR review or retry/handoff, first use the [Agent workflow entrypoint](docs/17-agent-workflow.md). It defines roles, user-intent routing and stage outputs without relying on chat history.
- Use [resource ingestion](docs/12-resource-ingestion.md) for current business behavior and [development workflow](docs/development-workflow.md) for local processes, Docker and acceptance commands.
- Use [harness instructions](docs/13-harness.md) to choose checks and interpret evidence. A passing quick check is not end-to-end acceptance.
- For work spanning sessions, copy the [task template](docs/tasks/template.md) and follow the [handoff rules](docs/tasks/README.md).
- For review requests, follow the [review defaults](docs/14-code-review.md). A short request naming the changes is sufficient; review only unless the user also requests fixes.

## Select your role before acting

- Host preparation Agent: clarify missing business intent, record confirmed scope and acceptance, prepare an Issue and external task plan when authorized, validate model routing, and add ready last only when execution is authorized. A verbal idea alone does not authorize queueing or inventing requirements.
- Controlled Symphony coding Agent: the workflow/adapter identifies this role. Edit only in the isolated Issue workspace and end the turn; the controller owns checks, the single repair opportunity, file publication and terminal state. The general commands below are requirements for the controller/host, not instructions for this coding Agent to run installers, tests or GitHub writes. Never reset state or requeue yourself.
- Independent host reviewer: “审查 PR X” defaults to independent review, applicable host checks and a same-SHA local acceptance instance after no blocking findings. This permits isolated tooling and local evidence, not source fixes, merge or Demo deployment. Respect an explicit “code review only / 不启动实例”. The author cannot attest their own independent review.
- Ordinary local implementation stays local unless the user asks to use Symphony or enqueue an Issue. No role automatically creates another agent/task, changes models mid-run, merges or deploys.

## Review defaults

Review actual changes against the user's intent and accepted project constraints. For "current uncommitted changes", include staged, unstaged and relevant untracked files; the named feature is the focus, not permission to silently omit other changes. Let the reviewer choose investigation and necessary verification. Report actionable defects with location, trigger and impact; distinguish uncertainty, avoid style-only findings and do not invent issues to meet a quota. Do not edit source, tracked reports or task records during review, or deploy, unless separately requested. State the reviewed scope and verification limits; see the linked defaults for evidence and changing-worktree handling.

## V0.1 boundaries

One Spring Boot service, intranet local ArtifactStorage, manual content production, and separate accounts with equal administrator privileges. One scene is one independent 4DGS reconstruction product. Private ingestion implements immutable scene versions carrying a `resource.json` v1 descriptor and a fixed file list, per-file upload/verification and retry, startup recovery and administrator audit.

Version deletion is whole-version and physical: remove every stored payload and the rows, retain audit and a minimal idempotency receipt, and recover unfinished deletions at startup. Preserve the separation of scenes, content versions and deliverable files.

Administrator publication is one published version pointer per scene: the version's descriptor and files are fixed, its description stays editable, and the previous version stays viewable and deletable after a replacement. Anonymous client reads (catalogue, detail, Range file streams), the per-variant complete-download reference tool `scripts/download_scene.py`, and desktop-Chrome playback of the reference player are implemented and verified on the isolated instance (see [sample validation](docs/20-4dgs-sample-validation.md)). Phone/native playback, Unity loading and audio are not verified. Day/night variants, coordinates, scene addresses and catalog parsing are not part of the current model. Do not introduce task queues, Worker services, tenant isolation or approval roles without a new requirement.

## Repository map

- `backend/`: pinned RuoYi Spring Boot 3, MyBatis, Bearer authentication, fixed-role accounts and ruoyi-ar. Only `classpath:db/demo` migrations initialize the application.
- `frontend/`: pinned RuoYi Vue3; use `scripts/agent_check.py --profile frontend` for task-local dependency/build reuse. It installs with `npm ci` when needed; preserve the lockfile and do not repeat installs/builds outside the entrypoint.
- `database/migrations/`: historical candidate SQL, not current application migrations.
- `contracts/`: generated OpenAPI (admin scene-version API plus the three anonymous client routes) and resource.json v1 schema/example (the runtime-manifest files are static historical candidates, no longer generated). Edit `scripts/generate_contracts.py`, then regenerate; never fix drift only in generated files.
- `scripts/`: development, contract and acceptance tooling; `harness.py` is the common check entrypoint.
- `compose.yaml`, `deploy/`: single-host containers; container tests must use isolated `innovation-ar-resource-platform-infra-check` resources (`127.0.0.1:18082`, prepared by `scripts/prepare_4dgs_check.py`).
- `.local/`: ignored runtime, logs, harness evidence and secrets. Never commit or print credentials.
- Root images and notes are user references; preserve unrelated files and worktree changes.

## Development and validation

Run the shortest requirement-specific business check first; trace actual callers before changing shared rules. Java changes must execute affected-module tests via `scripts/check_java.py` with nonzero executed tests. Then choose quick/frontend/ingestion by risk; account changes do not automatically require unrelated artifact-ingestion regression. See [fast review workflow](docs/16-fast-review.md).

For PR review use `scripts/review.py` to prepare a commit-scoped checkout, validate, and (after independent review) serve a loopback-only human acceptance instance. Include verified URL, SHA, credential-file location and stop command. This authorizes isolated local acceptance tooling, not merge or daily Demo/LAN deployment.

Work locally first. Use Vite on `127.0.0.1:43174` (point `AR_DEV_API_TARGET` at a backend; the default is `127.0.0.1:18080`, which `local_demo.py` uses). The daily Compose stack is the local Docker gateway on `192.168.0.12:18081` with its own database and accounts; its public face is `https://4dgs.elma-gohan.xyz`, an nginx relay on `elma-gohan.xyz` reached through a reverse SSH tunnel (`innovation-4dgs-relay.service`), so it is only reachable while this machine and the tunnel are up. The reference player is mounted onto the daily gateway only through a local, untracked compose override under `.local/`; it is not part of the production image. Changing the public address or the relay is a deployment and needs separate authorization.

Do not rebuild images, copy into containers or recreate Compose services for copy/button/layout edits; use the Vite dev server and update the corresponding browser selectors and documentation. Rebuilding the gateway or backend to ship a finished change to the daily instance needs explicit user approval, and back up the database before any migration. Use full login/click checks for behavior changes. The `bootstrap` account is retired on the daily instance: do not re-enable it or mint sessions to make checks pass. Report login blockers honestly.

On the Windows host, read the development workflow before starting/stopping processes: the agent's Job Object can kill descendants when a starter command exits. On Linux, long-lived processes such as Vite run as named services. Confirm health endpoints after startup; a printed `started` is insufficient. Never stop the daily instance just to validate a change. Harness ingestion builds a separate backend copy.

Run `python scripts/harness.py doctor --profile quick`, then `python scripts/harness.py check --profile quick` for repository rules and contracts. Choose `frontend` for frontend behavior/build checks or `ingestion` for the isolated current-source backend/HTTP/browser flow. Inspect the report's scope, source fingerprint and skipped/blocked checks before claiming completion.

Optional Symphony development-task orchestration is configured in `WORKFLOW.md`; see [its runbook](docs/15-symphony.md). Only explicitly labeled issues are eligible, and delivery stops at a draft PR for human review. No automatic merge, deployment or unscoped repair loop is enabled. A failed check must be understood; do not weaken a test or edit a report to make it green. Promote reviewed acceptance evidence to docs explicitly; routine checks keep reports under `.local/harness/`.

When preparing a Symphony issue, follow the runbook's model-selection procedure: inspect the container's model catalog (GPT plus the configured DeepSeek provider), respect the user's explicit choice, record the selection reason, validate the model/effort pair, set the two routing labels, and add `symphony:ready` last. Missing routing labels default independently to `gpt-6-astra` and `low`; do not infer execution parameters from issue prose or silently replace an unavailable model. DeepSeek uses the official `deepseek-flash` ID and a separately mounted API key; catalog/label validation alone does not prove authenticated inference.

## Conventions and security

Use four-space Python indentation, SQL/Python `snake_case`, API `camelCase`, UUIDs and UTC timestamps. Keep Chinese documentation concise. No global formatter/linter is configured. Update SQL, generated contracts and documentation together when their behavior changes.

Use descriptive incremental Flyway migrations for subsequent changes (currently through V016); keep empty-database initialization reproducible. V015 is a destructive clean cutover and must never run against the daily database without a backup and approval. Use real isolated PostgreSQL for changed data invariants; PostgreSQL 18 results do not establish PostgreSQL 17 compatibility. Verify applicable concurrency, audit, storage and authentication behavior. Client-loading invariants on phones and in Unity are not claimed until implemented and verified.

Record commands, tested versions, results and limitations in [validation records](docs/06-validation.md). SQL checks do not establish HTTP, cloud storage or client behavior. No percentage coverage threshold exists.

Use imperative commit subjects, optionally `docs:`, `db:` or `contracts:`. PRs explain changed behavior, reason, validation commands, database version and remaining assumptions. Never commit production connection strings; keep examples synthetic and unresolved client/server contracts explicit.

Controlled lifecycle and recovery details: [Symphony runbook](docs/15-symphony.md). Browser/system provisioning belongs to host preparation. Missing applicable checks must be resolved before queueing; existing scene checks do not prove unrelated pages work.
