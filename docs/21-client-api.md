# 客户端接口对接文件

适用：Unity / 任何 HTTP 客户端读取已发布的 4DGS 场景。版本 `4DGS Scene Resource API 0.5.0`（相对 0.4.0 为不兼容变更：去掉 `descriptor`、`defaultVariant`、`variants`、`posterUrl`）；机器可读定义见 [OpenAPI](../contracts/openapi.yaml)（只看带 `客户端` 标签的三个操作）。本文只描述已实现的行为。

## 1. 基本信息

| 项 | 值 |
|---|---|
| Base URL | `https://4dgs.elma-gohan.xyz`。链路是 elma-gohan 的 nginx（HTTPS）经反向 SSH 隧道到开发机 gateway；开发机离线或隧道断开时该地址不可用 |
| 前缀 | `/api/v1/client/`，与管理后台同源 |
| 认证 | 无。不要发送 `Authorization`、Cookie。三个路由只开放 GET，文件路由另开放 HEAD |
| 传输 | HTTPS（Let's Encrypt 证书）；JSON 为 UTF-8，文件为二进制流。不需要为 Android/iOS 放行明文流量 |
| 错误体 | 所有错误统一为 `{"code":"AR_<状态码>","message":"…","traceId":"…"}`，按 HTTP 状态码判断，`message` 仅用于日志 |
| 缓存 | 文件响应为 `Cache-Control: no-store, no-transform`；客户端自行缓存，用版本号和 SHA256 判断 |

## 2. 数据模型

- **场景（scene）**：一个独立 4DGS 重建成品，有 `id`（UUID）、`name`。
- **版本（version）**：场景在任一时刻只有一个“当前发布版本”，不可变。发布新版本后旧版本即不可经客户端读取。
- **文件**：每个文件有 `fileId`、相对路径、字节数、SHA256、`contentType`、可直接请求的 `downloadPath`。一个版本就是上传目录的完整文件清单。
- 平台没有场景描述：档位、分段、时间、变换、封面/音频/配置等文件用途由 Unity 客户端按 `relativePath` 决定，服务端不解释、不解码文件。

## 3. 接口

### 3.1 列表 `GET /api/v1/client/scenes`

查询参数：`name`（可选，名称筛选，≤200 字符）、`limit`（默认 20，1–100）、`offset`（默认 0）。

```json
{
  "items": [
    {"id": "UUID", "name": "wedding", "versionId": "UUID", "versionNo": 2}
  ],
  "total": 1
}
```

- 只返回已启用、未删除且有完整当前发布版本的场景。没有数据时返回 `200` 与 `{"items":[],"total":0}`。
- 列表不返回文件；封面等需要时由客户端从详情的 `files` 中按路径选取。
- 列表不打开任何模型文件，可频繁调用。

### 3.2 详情 `GET /api/v1/client/scenes/{sceneId}`

```json
{
  "sceneId": "UUID", "name": "wedding", "versionId": "UUID", "versionNo": 2,
  "files": [
    {
      "fileId": "UUID",
      "relativePath": "standard_quality/00.c.ply",
      "bytes": 30900000,
      "sha256": "64 位小写十六进制",
      "contentType": "application/octet-stream",
      "downloadPath": "/api/v1/client/scenes/<sceneId>/versions/<versionId>/files/<fileId>/content/00.c.ply"
    }
  ],
  "fileCount": 14,
  "totalBytes": 123456789
}
```

- `files` 是该版本的**全部**文件。客户端按自身逻辑以 `relativePath` 选出需要的文件，不必全部下载。
- 场景不存在、停用、已删除或无发布版本：`404`。

### 3.3 文件 `GET|HEAD /api/v1/client/scenes/{sceneId}/versions/{versionId}/files/{fileId}/content/{fileName}`

直接使用详情返回的 `downloadPath`，不要自己拼。`fileName` 是文件 basename 的 URI 编码，仅用于保留扩展名，服务端会与记录比对，不符 `404`。

| 请求头 | 行为 |
|---|---|
| 无 | `200`，完整文件，带 `Accept-Ranges: bytes`、`Content-Length`、强 `ETag`（值为登记的 SHA256） |
| `Range: bytes=a-b` / `bytes=a-` / `bytes=-n` | `206` 与 `Content-Range`。只支持单段；无效或多段 Range 会被忽略并返回 `200` 完整文件 |
| 起点越界 | `416`，`Content-Range: bytes */<总长>` |
| `If-Range: <ETag>` | 与当前 ETag 一致才按 Range 返回，否则 `200` 完整文件 |
| `HEAD` | 不带 body，`Content-Length` 为完整长度 |

`Content-Type` 只按扩展名：`.json` 为 `application/json`，jpg/jpeg/png/webp、wav、webm 为对应 MIME，模型和未知扩展名为 `application/octet-stream`。响应不带 `Content-Disposition`，可直接交给 `UnityWebRequest`、音视频播放器。后端不解码模型，不保证内容一定能被某个播放器加载。

## 4. 推荐调用流程

1. `GET /scenes` 取列表，展示 `name`。
2. 用户选场景后 `GET /scenes/{id}`，记下 `versionId`。
3. 客户端按自身逻辑决定需要哪些文件（按 `relativePath`），用各自的 `downloadPath` 请求；在线加载可用 Range 分块。
4. **完整下载**：对所需文件逐个 GET 保存。边写边算 SHA256，与 `files[].sha256` 比对，不符则丢弃该文件重下。
5. **断点续传**：保存 `.part` 和响应的 `ETag`；重连时发 `Range: bytes=<已有长度>-` 与 `If-Range: <ETag>`。返回 `206` 就追加（校验 `Content-Range` 起点等于已有长度）；返回 `200` 就清空 `.part` 从头写。
6. 全部所需文件校验通过后才标记该版本为可用（本地建议原子写一个完成标记）。

参考实现：`scripts/download_scene.py`（Python，匿名、下载整个版本的全部文件、断点续传、版本变化即停）。Unity 实现可对照它的状态与重试语义。

## 5. 状态码与处理

| 状态 | 出现场合 | 客户端处理 |
|---|---|---|
| 200 / 206 | 正常 | — |
| 400 | 参数非法（如 `limit` 超范围、UUID 格式错） | 修正请求，不重试 |
| 404 | 场景/文件不存在、未发布、停用、删除，或 `fileName` 不符 | 回到列表重新获取 |
| 409 | `versionId` 已不是当前发布版本；或服务器上文件缺失、长度不符 | **停止当前下载**，保留已下载的旧版本目录，重新 `GET /scenes/{id}` 获取新清单，用新版本目录下载；不要把新旧版本的文件混在一起。已开始的字节流会允许读完，下一个请求才 409 |
| 416 | Range 越界 | 当文件已完整处理（或丢弃 `.part` 重下） |
| 401/403 | 访问了非客户端路由或写方法 | 说明调用了不该调用的接口 |
| 5xx / 超时 | 服务故障、网络中断 | 保留 `.part` 和 ETag，指数退避后续传；超时不代表失败 |

## 6. 约束与已知边界

- 服务端下载时**不重算** SHA256，磁盘上同长度的损坏只能由客户端校验发现，所以第 4 节的校验不能省。
- 版本替换后旧版本 URL 立即 409，没有历史发布保留层。
- 文件名含 `%` 或 `;` 的文件在创建版本时即被拒绝，不会出现在客户端清单；零字节文件不能上传。
- 暂无分片上传/自定义下载协议，仅标准 HTTP Range。
- 此前桌面 Chrome 参考播放器验证基于已删除的描述，参考播放器当前不可用；手机、Unity 原生解码和音频同步**未验证**。

## 7. 快速自测

```bash
BASE=https://4dgs.elma-gohan.xyz
curl -s "$BASE/api/v1/client/scenes"
SID=<列表里的 id>
curl -s "$BASE/api/v1/client/scenes/$SID"
# 取一个 downloadPath
curl -s -D - -o /dev/null -H 'Range: bytes=0-31' "$BASE<downloadPath>"   # 期望 206, Content-Length: 32
curl -sI "$BASE<downloadPath>"                                           # 期望 200, 带 ETag, 无 body
python3 scripts/download_scene.py --base-url "$BASE" --scene-id "$SID" --output ./dl   # 整个版本写入 ./dl/<sceneId>/<versionId>/payload/
```
