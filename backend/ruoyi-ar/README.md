# ruoyi-ar 业务模块

2026-11-06：单场景固定模型切换。业务包为 `module/scene` 和 `module/client`，旧版本业务模块移除。一个场景直接拥有一套固定文件，名称和说明可编辑；文件校验完成且场景启用时自动可读，换模型新建场景。用户已确认客户端自行解压、解码已跑通，后端只提供资源分发。

## 阅读入口

| 位置 | 职责 |
|---|---|
| `module/scene/controller/SceneController` | 管理员场景、文件、配置、启停、删除及审计 HTTP 接口 |
| `module/scene/service/SceneService` | 固定清单创建、幂等重试、查询、信息编辑、启停与场景物理清理 |
| `module/scene/service/SceneFileService` | 上传短事务、存储 IO、结果确认、Range 读取及未完成文件恢复 |
| `module/scene/service/SceneRecovery` | 数据库初始化后先续做删除，再恢复文件 |
| `module/scene/manager/SceneManager` | 组合场景、文件、删除和审计持久化，不决定事务与 HTTP 错误 |
| `module/scene/manager/SceneConcurrency` | 单进程场景读写锁及活动上传集合 |
| `module/scene/mapper` | `SceneMapper/SceneFileMapper/SceneDeletionMapper`，SQL 在对应 XML |
| `module/scene/model` | 创建、编辑、启停请求及场景/文件查询 record，不保留版本参数 |
| `module/client` | 匿名目录、详情和直接场景文件路由；文件下载跨模块只调用 SceneFileService |
| `storage` | `ArtifactStorage/LocalArtifactStorage` 的流式校验、暂存、无覆盖提交、恢复、删除和盘点 |
| `support` | `RelativePath/HttpRange/FileContentType` 等路径、MIME 和 HTTP 规则 |

模块内部 Controller → Service → Manager → Mapper，模块间只调用 Service。Service 控制事务、操作者和审计，不拼 SQL；自定义 SQL 统一位于 `resources/mapper/{scene,client}/` 的 XML。继续使用项目 MyBatis-Plus/MyBatis 配置与 UUID 类型处理器，不增加通用 DAO、空接口或双层实体。当前查询 record 不为继承 BaseMapper 强造可写实体。

旧 SceneConvert 及仅供它使用的 MapStruct 依赖和处理器已随本次切换移除；当前查询直接映射 record，不保留旧实体转换链。

## 关键边界

- 创建一次性写入场景与非空固定清单；请求键唯一，相同内容复用，不同内容 409，删除键 410。不存在后续注册另一套文件或替换接口。
- 上传按“事务登记 → 事务外存储 → 事务确认”执行。AVAILABLE 不覆盖，失败按原清单重试；完成上传和启动恢复均不修改 enabled。
- 客户端可见条件是启用、非空全部 AVAILABLE、未删除且无删除意图。服务端自然可见，不依赖网页补发发布。
- 上传和下载持场景读锁，文件在途集合阻止同文件重复上传；删除取写锁，不能截断活动传输。锁是单实例范围，不声称集群安全。
- 删除先记意图，事务外清理所有存储阶段，成功删文件行、软删除场景并完成回执；失败可重试，启动删除优先于上传恢复。
- V018 保留当前模型场景 ID，将历史模型分离为停用场景；文件 UUID 和 storage_key 不变。旧审计保留，不通过升级清空历史文件。

## 存储与协议复用

范围流使用 Commons IO `BoundedInputStream` 并关闭传播；`IOUtils.copyLarge` 限长且检查短读，附件名由 Spring `ContentDisposition` 编码。相对路径拒绝越界、非法段和规范化冲突，不能用操作系统 normalize 替代验证。MIME 保留明确白名单。

HTTP Range 保留单区间 200/206/416、HEAD 无正文、If-Range 强验证及非法/多区间忽略规则。`LocalArtifactStorage` 保留 SHA256、文件锁、原子暂存和硬链接不覆盖提交；盘点不是完整性扫描或归属证明，当前进程恢复不等于断电保证。

详细流程和真实检查见[资源入库](../../docs/12-resource-ingestion.md)、[业务导读](../../docs/23-code-review-guide.md)、[验证记录](../../docs/06-validation.md)。Java 使用 `scripts/check_java.py --module ruoyi-admin --package`，之后检查当前源码的 HTTP、数据库和浏览器行为，编译通过不构成完整验收。
