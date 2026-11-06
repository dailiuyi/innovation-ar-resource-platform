# 业务代码阅读与人工 Review 导读

更新：2026-11-06。业务为管理员单场景固定文件，上传就绪自动可读；新模型新建场景。旧多版本导读不再描述当前代码。分层仍为 Controller → Service → Manager → Mapper，见[模块说明](../backend/ruoyi-ar/README.md)。本页是阅读导航，不是独立审查结论。

## 阅读顺序

| 顺序 | 入口 | 重点 |
|---|---|---|
| 1 | [scenes.vue](../frontend/src/views/demo/scenes.vue) | 列表、创建/详情入口、启停、删除，隐藏内部修订号 |
| 2 | [scenePackage.js](../frontend/src/utils/scenePackage.js)、[hash.worker.js](../frontend/src/views/demo/hash.worker.js) | 路径与大小检查、分块 SHA256、原文件匹配、有限并发上传 |
| 3 | [scene.js](../frontend/src/api/scene.js) | 创建、详情、文件流和状态核对，无发布请求 |
| 4 | [SceneController](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/scene/controller/SceneController.java) | 管理员角色、参数校验、201/200/204 和文件 HTTP 路由 |
| 5 | [SceneService](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/scene/service/SceneService.java) | 固定清单创建幂等、信息修改、启停、删除意图与恢复 |
| 6 | [SceneFileService](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/scene/service/SceneFileService.java) | 上传登记/IO/确认分段事务，错误恢复和下载可见性 |
| 7 | [SceneManager](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/scene/manager/SceneManager.java) 与 [SceneMapper.xml](../backend/ruoyi-ar/src/main/resources/mapper/scene/SceneMapper.xml) | 组合持久化和审计，汇总、请求键冲突与行锁 |
| 8 | [SceneFileMapper.xml](../backend/ruoyi-ar/src/main/resources/mapper/scene/SceneFileMapper.xml)、[SceneDeletionMapper.xml](../backend/ruoyi-ar/src/main/resources/mapper/scene/SceneDeletionMapper.xml) | 文件状态、验证值、删除记录和回执 |
| 9 | [LocalArtifactStorage](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/storage/LocalArtifactStorage.java) | SHA256、文件锁、无覆盖提交、大小/范围边界 |
| 10 | [ClientSceneService](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/client/service/ClientSceneService.java) 与 [ClientSceneMapper.xml](../backend/ruoyi-ar/src/main/resources/mapper/client/ClientSceneMapper.xml) | 非空全部完成且启用才匿名可见，文件不跨场景 |
| 11 | [SceneRecovery](../backend/ruoyi-ar/src/main/java/com/ruoyi/ar/module/scene/service/SceneRecovery.java) | 启动先删除再恢复上传，系统执行审计 |
| 12 | [V018](../backend/ruoyi-admin/src/main/resources/db/demo/V018__single_scene_fixed_files.sql) | 非空升级的原场景身份、历史模型隔离、文件不丢失及删除恢复 |

## 正常上传

创建前页面计算摘要并固定请求键。POST 原子登记场景和非空文件集合，响应丢失时同一请求键重试；不同内容拒绝，删除后的请求键不复活。每个文件 PUT 分三段：短事务标记 UPLOADING，事务外流式校验/落盘，短事务确认 AVAILABLE 与审计。

服务端公开条件直接查询启用、非空全部 AVAILABLE、未删除且没有删除意图；最后一个文件完成后不额外写发布指针。上传中停用会持续生效，网页取消只停止本轮传输，不能把结果未知直接视为失败。

## 删除与恢复

场景删除取得共享并发管理器的写锁，先提交删除意图，随后事务外按文件 UUID 清理 `.part/.ready/.bin`。全部成功才删文件行、标记场景删除并完成回执；失败保留可重试状态。活动上传/下载不得被强制截断。

启动先续做删除，随后仅恢复未完成上传。完整遗留验证后补记 AVAILABLE；只有部分字节的上传保留为可重试。已完成文件不在启动时全量哈希。停用与删除是独立动作；不存在先删除版本再删场景的操作。

## Review 检查点

- 请求键并发重试是否只创建一个场景；删除后是否仍拒绝复活。
- 改名称/说明是否修改了固定文件；空清单是否被误报 READY 或暴露到客户端。
- 服务端不依赖网页的发布请求；上传完成和重启是否错误覆盖停用决定。
- 文件 UUID、场景、URL 名称及就绪状态是否一并核验；管理员和匿名路由是否区分。
- 锁是否覆盖到正文传输结束；同文件冲突是否影响其他文件。
- 部分清理失败能否继续，是否仍可公开；回执是否晚于所有物理清理。
- V018 是否保留全部文件 UUID/存储键/归属、审计和旧可见性；历史资源是否停用。
- 206 追加与 200 截断、SHA256 不匹配、404 停用/删除与 409 存储异常是否被客户端工具正确处理。

实际命令与范围见[验证记录](06-validation.md)。本轮只验收资源分发，客户端解压/解码按用户已跑通的事实沿用，不以 HTTP 或合成文件证明新的设备播放或千人容量。
