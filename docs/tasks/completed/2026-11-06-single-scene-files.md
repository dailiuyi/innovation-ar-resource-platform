# 管理员单场景固定模型改造

状态：完成（本地实施与资源分发验收，待用户界面确认；未部署）。负责人：主会话集成；四个用户指定的 DeepSeek V4.1 Flash 子代理分别负责后端、前端、工具契约、验收脚本。日期：2026-11-06。

## 目标与已确认决定

- 一场景一套固定文件；用户明确选择“新模型新建场景”。名称、说明可编辑，模型文件不可替换。
- 管理员上传全部校验完成即对外可用，启停独立；合并场景信息与文件页面，去掉业务版本和发布流程。
- 用户进一步确认“只需要提供资源分发就行了，客户端可以完成解压与解码，已经跑通了”。本轮不改播放器、不做解包或训练。
- 使用现有本地存储，不引入 OSS/CDN、普通用户、审核、消息队列或 GPU 调度；千人容量是后续云分发验收目标。
- 已授权本地实施，未授权提交、推送、部署或日常数据库升级。

## 工作区与接口

原工作区的未提交更改保持原样，实施在 `/home/elma/文档/Code/innovation-ar-resource-platform/.local/worktrees/admin-scene-files`，分支 `feat/admin-scene-files`，基线 `fbf3c50c5c2f4d16caa9c61beb7f4cdea58252ee`。

POST `/api/v1/scenes` 原子登记 requestKey、名称、说明和非空固定清单，文件操作为 `/scenes/{sceneId}/files/{fileId}`。客户端去掉 versionId/versionNo，沿用固定文件 SHA256 和 Range。接口版本 0.6.0 为不兼容切换，日常接口尚未升级。

## 数据和验证计划

追加 V018，保留 V001–V017、文件 UUID、存储键与审计；原公开模型保留场景身份，其他历史模型迁为停用场景。先用 PostgreSQL 17.6 验证空库/非空升级和删除回执，再实际启动新 Jar，验证上传、启停、Range、删除及恢复；浏览器使用真实登录和上传。

当前 18082 隔离 Compose 已有其他任务持有，不接管、不重建。为本任务创建独立带标签的 PostgreSQL/Redis 临时容器，端口仅绑定回环；名称 `innovation-ar-resource-platform-infra-check-scene-files-pg` 和 `innovation-ar-resource-platform-infra-check-scene-files-redis`。API/前端将作为独立命名服务运行，绝不操作日常环境。

## 完成记录与交接

单场景固定文件、上传即发布、统一详情、启停及整场景清理已实现。旧文件 UUID/存储键和审计保留，V001–V017 字节不变；V018 已在隔离空库和非空 PostgreSQL 17.6 验证，未执行日常升级。

实际结果：Java57项、迁移20项、上传下载Python28项、最终场景包15项、真实网关HTTP/浏览器110项、合成API/真实浏览器112项，以及32项独立HTTP和19项真实重启/存储故障检查通过。两文件22,020,954字节经真实CLI上传、受控中断和Range206续传，最终SHA256逐项一致；重跑上传/下载复用已有完成文件。命令、报告、此前失败定位和警告见[验证记录](../../06-validation.md)。

隔离预览 `http://127.0.0.1:18085/admin/scenes`，人工登录使用[开发工作流](../../development-workflow.md)已约定的本地隔离默认账号，已实际验证登录和管理员场景读取；自动验收私有凭据仍在本 worktree `.local/scene-files-runtime/credentials.json`，不复制密码。API 命名服务 `scene-files-api-final`，启动脚本和隔离网关配置保留在同一运行目录。停止命令与归属要求见验证记录；旧18082和日常云端未操作。

本轮没有播放器/解压/解码改造、生产迁移、部署、提交或推送。原工作区未提交改动保留；本地分支仍为 `feat/admin-scene-files`，可在该 worktree 人工验收后决定提交。最终静态门禁及源码指纹引用 `.local/scene-files-runtime/final-gates.json`，不将较早门禁指纹替代后续文档修改。

2026-11-06 后续：用户验收后要求删除场景列表的「文件」列并部署。列已删除，详情汇总保留；前端 profile 与真实浏览器检查通过，随后用户授权上线日常云端。云端现为 backend/gateway `single-scene-20261106`，V018 已执行，备份与回退口径见[基础设施手册](../../10-local-infrastructure.md)和[验证记录](../../06-validation.md)。仓库仍未提交，代码仍需用户决定是否入库。

Symphony、Issue、PR、runId：不适用。本次使用会话原生子代理，不进入外部队列。后续 OSS/CDN、用户权限、审核、社交、GPU 调度保持独立需求与授权。
