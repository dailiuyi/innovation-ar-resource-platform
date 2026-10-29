# 客户端接口对接文件

适用：Unity / 任何 HTTP 客户端读取已发布的 4DGS 场景。版本 `4DGS Scene Resource API 0.4.0`；机器可读定义见 [OpenAPI](../contracts/openapi.yaml)（只看带 `客户端` 标签的三个操作）和 [resource.json Schema](../contracts/schemas/resource-descriptor.schema.json)。本文只描述已实现并在隔离实例上验证过的行为。

## 1. 基本信息

| 项 | 值 |
|---|---|
| Base URL | 当前日常实例 `http://127.0.0.1:18081`（仅本机）。手机或同事访问需要管理员把 `AR_BIND_ADDRESS` 改成主机 LAN 地址后重建 gateway，地址以管理员告知为准 |
| 前缀 | `/api/v1/client/`，与管理后台同源 |
| 认证 | 无。不要发送 `Authorization`、Cookie。三个路由只开放 GET，文件路由另开放 HEAD |
| 传输 | HTTP/1.1，JSON 为 UTF-8；文件为二进制流。当前为明文 HTTP，Android 9+ / iOS ATS 需要按各自平台放行明文或另行上 HTTPS |
| 错误体 | 所有错误统一为 `{"code":"AR_<状态码>","message":"…","traceId":"…"}`，按 HTTP 状态码判断，`message` 仅用于日志 |
| 缓存 | 文件响应为 `Cache-Control: no-store, no-transform`；客户端自行缓存，用版本号和 SHA256 判断 |

## 2. 数据模型

- **场景（scene）**：一个独立 4DGS 重建成品，有 `id`（UUID）、`name`。
- **版本（version）**：场景在任一时刻只有一个“当前发布版本”，不可变。发布新版本后旧版本即不可经客户端读取。
- **档位（variant）**：同一版本里并列的多套模型（如 `standard_quality`、`high_quality`、`vr_foreground`），ID 为开放字符串（`^[a-z][a-z0-9_-]{0,63}$`），不保证固定四档，也不保证各档段数相同。
- **段（segment）**：档位下按时间顺序的模型文件，含 `startSeconds`、`durationSeconds`。
- **文件**：每个文件有 `fileId`、相对路径、字节数、SHA256、可直接请求的 `downloadPath`。

## 3. 接口

### 3.1 列表 `GET /api/v1/client/scenes`

查询参数：`name`（可选，名称筛选，≤200 字符）、`limit`（默认 20，1–100）、`offset`（默认 0）。

```json
{
  "items": [
    {
      "id": "UUID",
      "name": "wedding",
      "versionId": "UUID",
      "versionNo": 2,
      "defaultVariant": "standard_quality",
      "variants": [
        {"id": "standard_quality", "name": "标准画质", "segmentCount": 2, "durationSeconds": 8},
        {"id": "high_quality", "name": "高清画质", "segmentCount": 2, "durationSeconds": 8}
      ],
      "posterUrl": "/api/v1/client/scenes/<sceneId>/versions/<versionId>/files/<fileId>/content/wedding_1205.jpg"
    }
  ],
  "total": 1
}
```

- 只返回已启用、未删除且有完整当前发布版本的场景。没有数据时返回 `200` 与 `{"items":[],"total":0}`。
- `posterUrl` 仅在描述声明了封面时出现；它是相对路径，拼 Base URL 即可直接 GET。
- 列表不打开任何模型文件，可频繁调用。

### 3.2 详情 `GET /api/v1/client/scenes/{sceneId}`

```json
{
  "sceneId": "UUID", "name": "wedding", "versionId": "UUID", "versionNo": 2,
  "descriptor": { "…见第 4 节…" },
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

- `files` 是该版本去重后的**全部**文件，含所有档位。客户端按所选档位的 `segments[].path` 加上公共文件 `settings`/`poster`/`audio`/`preview` 在 `files` 中按 `relativePath` 取子集；不要下载未选档位。
- `descriptor` 里所有路径都能在 `files[].relativePath` 找到。
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

`Content-Type`：模型 `application/octet-stream`，settings `application/json`，jpg/png/webp、wav、webm 为对应 MIME，未知为 `application/octet-stream`。响应不带 `Content-Disposition`，可直接交给 `UnityWebRequest`、音视频播放器。

## 4. 场景描述 `descriptor`（resource.json v1）

```json
{
  "formatVersion": 1,
  "defaultVariant": "standard_quality",
  "transform": {"position": [0,0,0], "rotation": [0,0,0], "scale": [1,1,1]},
  "settings": "media_and_settings/wedding_settings.json",
  "poster": "media_and_settings/wedding_1205.jpg",
  "audio": "media_and_settings/wedding.wav",
  "audioPosition": [0,0,0],
  "preview": "media_and_settings/wedding.webm",
  "variants": [
    {"id": "standard_quality", "name": "标准画质", "format": "4dv-compressed-ply",
     "segments": [
       {"path": "standard_quality/00.c.ply", "startSeconds": 0, "durationSeconds": 5},
       {"path": "standard_quality/01.c.ply", "startSeconds": 5, "durationSeconds": 3}
     ]}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `formatVersion` | 固定 `1`，客户端遇到其他值应拒绝加载 |
| `defaultVariant` | 必为 `variants` 中的真实 id |
| `transform` | 必填。`position` 为位置，`rotation` 单位为**度**，`scale` 为缩放，均为 3 元数组。后端不做默认值，值怎么写就怎么用 |
| `settings` | 必填相对路径，播放器配置 JSON（相机轨道、背景色等），后端不改写 |
| `poster`/`audio`/`preview` | 可选；缺少则字段不存在，不会是空字符串 |
| `audioPosition` | 有 `audio` 时可选，缺省视为 `[0,0,0]` |
| `variants[].format` | 当前唯一值 `4dv-compressed-ply`（可由 `.c.ply` 或 `.4dv` 文件承载，不要靠扩展名判断编码） |
| `segments` | 按 `startSeconds` 升序、相邻区间不重叠；每档总时长 = 最后一段的 `startSeconds + durationSeconds`。播放顺序以数组顺序和时间为准，不按文件名推断 |

后端不解码模型，不保证内容一定能被某个播放器加载。

## 5. 推荐调用流程

1. `GET /scenes` 取列表，展示 `name`、`posterUrl`、`variants`。
2. 用户选场景和档位后 `GET /scenes/{id}`，记下 `versionId`。
3. **在线按段加载**：按 `segments` 顺序，用 `downloadPath` 逐段请求（可用 Range 分块）；`settings`、`audio` 等公共文件各请求一次。
4. **完整下载**：对选中档位的段文件加公共文件，逐个 GET 保存。边写边算 SHA256，与 `files[].sha256` 比对，不符则丢弃该文件重下。
5. **断点续传**：保存 `.part` 和响应的 `ETag`；重连时发 `Range: bytes=<已有长度>-` 与 `If-Range: <ETag>`。返回 `206` 就追加（校验 `Content-Range` 起点等于已有长度）；返回 `200` 就清空 `.part` 从头写。
6. 全部文件校验通过后才标记该版本为可用（本地建议原子写一个完成标记）。

参考实现：`scripts/download_scene.py`（Python，匿名、按档位、断点续传、版本变化即停）。Unity 实现可对照它的状态与重试语义。

## 6. 状态码与处理

| 状态 | 出现场合 | 客户端处理 |
|---|---|---|
| 200 / 206 | 正常 | — |
| 400 | 参数非法（如 `limit` 超范围、UUID 格式错） | 修正请求，不重试 |
| 404 | 场景/文件不存在、未发布、停用、删除，或 `fileName` 不符 | 回到列表重新获取 |
| 409 | `versionId` 已不是当前发布版本；或服务器上文件缺失、长度不符 | **停止当前下载**，保留已下载的旧版本目录，重新 `GET /scenes/{id}` 获取新描述，用新版本目录下载；不要把新旧版本的文件混在一起。已开始的字节流会允许读完，下一个请求才 409 |
| 416 | Range 越界 | 当文件已完整处理（或丢弃 `.part` 重下） |
| 401/403 | 访问了非客户端路由或写方法 | 说明调用了不该调用的接口 |
| 5xx / 超时 | 服务故障、网络中断 | 保留 `.part` 和 ETag，指数退避后续传；超时不代表失败 |

## 7. 约束与已知边界

- 服务端下载时**不重算** SHA256，磁盘上同长度的损坏只能由客户端校验发现，所以第 5 节的校验不能省。
- 版本替换后旧版本 URL 立即 409，没有历史发布保留层。
- 文件名含 `%` 或 `;` 的文件在创建版本时即被拒绝，不会出现在客户端清单。
- 暂无分片上传/自定义下载协议，仅标准 HTTP Range。
- 已在桌面 Chrome（RTX 4060）上用参考播放器验证 wedding 标准/高清、dance_color 标准跨 5 秒分段加载；手机、Unity 原生解码和音频同步**未验证**。
- shiku_dtwd 样例的 0–5 秒窗口和 1.4 缩放是样例播放配置，不是重建出来的生产时间契约。

## 8. 快速自测

```bash
BASE=http://127.0.0.1:18081
curl -s "$BASE/api/v1/client/scenes"
SID=<列表里的 id>
curl -s "$BASE/api/v1/client/scenes/$SID"
# 取一个 downloadPath
curl -s -D - -o /dev/null -H 'Range: bytes=0-31' "$BASE<downloadPath>"   # 期望 206, Content-Length: 32
curl -sI "$BASE<downloadPath>"                                           # 期望 200, 带 ETag, 无 body
python3 scripts/download_scene.py --base-url "$BASE" --scene-id "$SID" --variant standard_quality --output ./dl
```
