# Unity / 已有播放器资源接入

更新：2026-11-06。用户已确认已有客户端能够完成解压、解码并已跑通；本轮后端只负责资源分发，不新增播放器、解包或渲染模块。路由、状态码与响应结构以[客户端接口 0.6.0](21-client-api.md)和[OpenAPI](../contracts/openapi.yaml)为准。本地源码更新不等于日常公网接口已经部署。

## 1. 管理端操作

管理员在场景管理中新建：填写名称和说明，选择资源目录或多个文件，开始上传。非空固定清单的全部文件经服务端确认后，启用场景自动可读；没有版本选择或另一次发布操作。失败后重新选择完整原始集合继续，已经成功的文件跳过。

文件清单固定；改名称、说明不产生新模型，换模型新建场景。启用/停用控制新客户端请求，删除场景清理所有模型文件。JSON、ZIP、PLY 等均按普通文件原样保存；ZIP 内部文件不出现在平台清单中。

## 2. 客户端流程

1. `GET /api/v1/client/scenes` 获取 `{items:[{id,name}],total}`。
2. `GET /api/v1/client/scenes/{sceneId}` 获取完整 `files`、文件数和字节总量。
3. 按已有客户端约定，以 `relativePath` 选择所需文件。
4. 请求各自 `downloadPath`，完整性通过后交给已有解压/解码逻辑。

接口不再返回 `versionId/versionNo`，文件路由也无版本段。客户端不拼文件 URL，不对返回路径二次编码。用基础 URL 解析相对 downloadPath；日常基础 URL 和隔离验收地址以当前目标环境为准。

## 3. C# 数据结构

```csharp
public class SceneList {
    public List<SceneItem> items;
    public int total;
}
public class SceneItem {
    public string id, name;
}
public class SceneDetail {
    public string sceneId, name;
    public int fileCount;
    public long totalBytes;
    public List<FileEntry> files;
}
public class FileEntry {
    public string fileId, relativePath, sha256, contentType, downloadPath;
    public long bytes;
}
```

继续使用已有 JSON 解析方式；这组类型是接口映射，不是要求重写客户端。Unity 2022.3 的普通 class 可避免 C# record/IsExternalInit 兼容问题。

## 4. 本地缓存和续传

以 `sceneId` 和固定清单识别任务，目录可为 `persistentDataPath/<sceneId>/`；不再以业务版本分目录。保留旧目录，不自动清除已有资产。

使用流式下载到 `.part`，保存强 ETag。续传发 Range 与 If-Range；206 核对范围及总量再追加，200 从头写入。下载完成验证大小与 SHA256，再交付正式文件或进行解压。已经采用其他等价方式的客户端无需照搬参考目录结构。

404 表示场景不可访问或路径错误，停止该请求并刷新目录。409 表示资源存储异常，不再表示新版本替换；保持本地状态并向管理员报告。416 不能单独作为完成依据。超时后保留临时字节，不直接删除已确认文件。

参考工具为 `scripts/download_scene.py`，完整下载至 `<output>/<sceneId>/payload/`；底层 `artifact_transfer.py` 展示 Range/If-Range 和摘要处理。它们是联调参考，不是强制替换既有 SDK。

## 5. 启停和模型身份

停用后新列表、详情和文件请求均不可访问；正在传输的文件允许完成。重新启用时相同场景和文件继续可读。换模型使用新场景 ID，旧文件 URL 不变成另一份内容；名称、说明编辑不改变缓存身份。

已有缓存不会因服务端停用而从设备消失。若产品要求客户端主动隐藏本地模型，应由客户端自己的目录刷新策略处理，不把服务端拒绝新请求当作远程删除设备数据。

## 6. 资源分发验收

本轮检查：创建并上传、匿名清单、完整文件字节和 SHA256、HEAD/Range/If-Range、下载中断后续传、停用拒绝新读取、启用恢复、场景删除。

已有客户端解压和解码按用户已跑通的事实记录，本轮不重复验收、不推定新设备表现。首帧、显存、音频、手机网络等仍由对应客户端或专项测试说明；历史参考播放器记录见[旧样包验收](20-4dgs-sample-validation.md)，后端本轮执行证据见[验证记录](06-validation.md)。
