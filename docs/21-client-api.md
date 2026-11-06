# 客户端接口对接文件

本地接口版本：`4DGS Scene Resource API 0.6.0`。相对 0.5.0 不兼容：删除 `versionId/versionNo`，文件路径改为场景直接关联文件。没有旧版本路由兼容层；上传/下载工具和客户端应一起切换。**本地源码改变不代表公网日常服务已部署 0.6.0。** 目标环境先核对其 OpenAPI。

## 1. 访问与模型

- 日常 Base URL 为 `https://4dgs.elma-gohan.xyz`，部署情况见[基础设施记录](10-local-infrastructure.md)。隔离验收使用其实际回环地址。
- 前缀 `/api/v1/client/`，匿名读取，不发送管理员 Token 或 Cookie。只开放列表/详情 GET、文件 GET/HEAD。
- 一个场景对应一组固定文件。模型改变创建新场景；名称、说明、启停可变，文件不替换。
- 启用、未删除且全部文件校验完成的非空场景可见。上传完成即自动可用，无独立发布步骤。
- 客户端按 `relativePath` 判断档位、分段和配置用途；平台不解释 `resource.json`、不解包 ZIP、不解码模型。
- 当前文件响应为 `Cache-Control: no-store, no-transform`，客户端按场景 ID、文件 ID 和 SHA256 自行缓存；尚未接 CDN。

## 2. 接口

### 列表 `GET /api/v1/client/scenes`

查询参数：`name` 可选，最长 200 字；`limit` 默认 20、范围 1–100；`offset` 默认 0。

```json
{"items":[{"id":"UUID","name":"展厅模型"}],"total":1}
```

只返回满足可见条件的场景，无数据为 `200` 与空数组；不读取模型文件。

### 详情 `GET /api/v1/client/scenes/{sceneId}`

```json
{
  "sceneId":"UUID",
  "name":"展厅模型",
  "files":[{
    "fileId":"UUID",
    "relativePath":"standard/00.c.ply",
    "bytes":30900000,
    "sha256":"64位小写十六进制",
    "contentType":"application/octet-stream",
    "downloadPath":"/api/v1/client/scenes/<sceneId>/files/<fileId>/content/00.c.ply"
  }],
  "fileCount":1,
  "totalBytes":30900000
}
```

清单是场景全部文件，客户端可只选需要的文件。不存在、停用、未完成上传或删除中均为 404；不返回磁盘路径或 storageKey。文件列表、大小与摘要不因场景文字编辑而变化。

### 文件 `GET|HEAD /api/v1/client/scenes/{sceneId}/files/{fileId}/content/{fileName}`

直接使用 `downloadPath`，不要自己拼接或再次 URI 编码。`fileName` 是已编码的文件 basename，仅保留扩展名并用于核对，不能指定存储路径。

| 请求 | 响应 |
|---|---|
| 普通 GET | 200、完整文件，含 Content-Length、Accept-Ranges 与强 ETag |
| `Range: bytes=a-b`、`bytes=a-`、`bytes=-n` | 206，含准确 Content-Range 和返回长度 |
| 非法或多段 Range | 忽略 Range，返回 200 完整文件 |
| 合法但无法满足的 Range | 416，`Content-Range: bytes */<总长>`，空正文 |
| `If-Range: <ETag>` | 匹配才使用 Range，不匹配返回 200 完整文件 |
| HEAD | 200，完整长度，无正文；忽略 Range |

ETag 为登记 SHA256 的带引号值；下载时不重算摘要。MIME 按扩展名白名单确定：JSON、常见图片、WAV、WebM 使用对应类型，其余包括模型均为 `application/octet-stream`。客户端响应无附件 Content-Disposition。ZIP 原样下载，由客户端自行解压。

## 3. 下载与续传

1. 取列表和详情，保存场景 ID 与固定文件清单。
2. 按需要选择文件，流式写入 `.part`，保存响应 ETag。
3. 中断后请求 `Range: bytes=<已有长度>-` 与 `If-Range: <保存的ETag>`。
4. 206 先核对 Content-Range、总长和 ETag，再追加；200 清空临时文件从头写，避免重复追加。
5. 下载完成核对大小和 SHA256，通过后才交付正式文件；所需文件全部通过才写完成标记。
6. ZIP 等内容在完整性确认后交给既有客户端处理；后端不执行解压或模型解码。

参考命令：

```bash
python3 scripts/download_scene.py --base-url http://127.0.0.1:<验收端口> --scene-id <UUID> --output .local/downloads
```

输出为 `<output>/<sceneId>/payload/`，控制文件与正文分离。重复命令可继续；不同清单或来源不能直接复用同一本地下载目录。旧 `<sceneId>/<versionId>/` 目录不自动搬迁或删除。

## 4. 错误处理

| 状态 | 含义与处理 |
|---|---|
| 400 | 请求参数非法，修正后再请求 |
| 401/403 | 调用了管理路由或未允许方法，检查接口 |
| 404 | 场景不可访问、文件归属/名称错误；停止当前请求并刷新目录 |
| 409 | 文件存储缺失、长度不符或未就绪；保留下载状态，报告资源不可用，由管理员检查；不是版本变化 |
| 416 | 核对本地长度与 SHA256；状态本身不证明文件已完整 |
| 5xx/超时 | 保留临时文件和 ETag，有限退避后续传 |

AR 业务错误通常为 `{"code":"AR_<状态码>","message":"…","traceId":"…"}`。按 HTTP 状态处理，message 仅用于日志。HEAD、416、网关错误、传输中断不保证业务 JSON。

## 5. 启停与验证边界

停用后新列表不显示，后续详情和文件请求 404；已开始的文件流允许完成，客户端本地缓存无法撤回。重新启用恢复相同场景 ID 和固定清单。删除停止访问并清理模型，旧 URL 不会改指向另一模型。

用户已确认现有客户端解压与解码已跑通。本次后端工作验收资源清单、字节、续传、启停与删除，不重做播放器，不把合成 HTTP 检查解释成设备播放证据。实际运行记录见[验证记录](06-validation.md)，Unity 落地指导见[对接说明](22-unity-integration.md)。
