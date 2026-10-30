# Unity 对接技术文档

## 0. 给 Unity 同事的上手说明（先读这一节）

### 0.1 我们提供了什么

平台是一台服务器，里面存着做好的 4DGS 场景（动态高斯重建的三维成品）。你的 Unity 程序只需要做三件事，都是普通的 HTTPS 请求，不用登录：

1. 问服务器“有哪些场景”，拿到名字和当前版本号。
2. 选一个场景，问服务器“这个场景有哪些文件”，拿到每个文件的下载地址、大小和校验码（SHA256）。
3. 按地址把文件下载到手机或电脑本地，校验码对得上就交给你们的 4DGS 播放组件。

接口有三个，都只读：场景列表、场景详情、文件下载。文件很大（一个标准档约 69 MB），所以下载支持“断了接着下”（HTTP Range）。服务器只保存上传目录里的文件清单，不保存描述文件：哪些文件属于哪个画质档位、分段顺序和时间、坐标变换、封面/音频用途，都由 Unity 侧按文件相对路径自行决定。服务器不负责播放、不判断设备性能、不改模型坐标。

“接口”可以理解为：你访问一个网址，服务器返回一段 JSON 文字或一个文件。先用浏览器或命令行试一次，就能看出它长什么样：

```bash
BASE=https://4dgs.elma-gohan.xyz
curl -s "$BASE/api/v1/client/scenes"   # 能看到 JSON 说明通了
```

### 0.2 给 AI agent 的提示词

把下面整段贴给 agent，并让它能读到本仓库的 `docs/21-client-api.md` 和 `docs/22-unity-integration.md`：

```text
你在 Unity 项目里实现 4DGS 场景下载与加载。请先完整阅读 docs/21-client-api.md 和 docs/22-unity-integration.md，严格以这两份文档为准，不要凭经验猜接口。

要做的事：
1. 写 PlatformConfig（BaseUrl 可配置）和第 4 节的数据结构，用 Newtonsoft.Json 解析。
2. 实现：获取场景列表、获取场景详情、按 Unity 侧定义的规则（按 relativePath）列出需要下载的文件（第 5 节）。
3. 实现下载器（第 6 节）：用 DownloadHandlerFile 写 .part 文件，保存 ETag，用 Range 和 If-Range 断点续传，处理 200/206/416/409，下载完流式校验 SHA256，全部完成后写 ready 标记。
4. 下载完成后把目录路径交给播放组件；播放组件的接入点先留接口，不要自己实现渲染。

约束：
- 不要把整个文件读进内存；不要对列表接口轮询；不要二次编码 downloadPath；需要的文件在清单中找不到就报错，不要猜替代文件。
- 按 HTTP 状态码处理错误，不解析 message。
- 文档里标“待验证”的内容（坐标系、音画同步、流式输入、webm 播放）不要当成已确认，写代码时留开关或注释，并在最后列出来。
- 完成后告诉我：改了哪些文件、实际运行过什么、哪些没验证。可以参考 scripts/download_scene.py 的目录布局和退出码，但它是 Python 联调参考，不是要移植的 SDK。
```

### 0.3 怎么操作平台（管理端）

Unity 侧读到的场景，都是管理员先在后台上传并发布的。要自己放测试内容，按下面做：

1. 打开管理后台：`https://4dgs.elma-gohan.xyz`（和客户端接口同一个地址）。账号和密码向管理员要，不要写进文档或聊天。
2. 登录后进入场景列表，没有场景就先新建一个；每行有“版本与文件”，点进去。
3. 准备资源目录，或准备一个或多个独立文件（类型不限，可以是打包好的 ZIP）；不需要 `resource.json`，空文件会被拒绝。
4. 点“导入资源目录”保留目录内相对路径，或点“导入文件”多选文件（清单路径为各文件名，不能重名）。一次选择创建一个版本，填写说明后点“开始导入”，页面计算校验码并逐文件上传。ZIP 原样保存，平台不解压，Unity 下载并校验 SHA256 后自行解压。上传中断后可直接“继续上传”；刷新页面后使用“重新选择目录”或“重新选择文件”，选择完整原始集合，路径、大小和摘要须一致，已上传的不会重传。
5. 全部文件显示可用后，把这个版本“发布”。每个场景同一时刻只有一个发布版本，客户端只能读到它。
6. 回到 Unity 或用 `curl $BASE/api/v1/client/scenes` 检查，应该能看到这个场景。

注意：版本创建后内容不可修改，要改模型或配置就新建版本再发布；发布新版本后，客户端正在下载旧版本会收到 409，按第 6 节处理即可。删除版本是整版物理删除，不可恢复。

---

## 1. 平台提供什么，不提供什么

提供：场景目录、当前发布版本的完整文件清单（相对路径、大小、SHA256、content type、下载地址）、文件的 HTTP Range 下载、强 ETag。不提供：档位、分段时间、变换、文件用途等描述，这些由 Unity 侧定义。

## 2. 总体流程

```mermaid
sequenceDiagram
    participant U as Unity
    participant S as 平台 /api/v1/client
    U->>S: GET /scenes
    S-->>U: 场景列表 + 版本号
    U->>S: GET /scenes/{id}
    S-->>U: files(含 relativePath、SHA256 与 downloadPath)
    loop Unity 按自身规则选出的文件
        U->>S: GET downloadPath (可带 Range / If-Range)
        S-->>U: 200 / 206 + ETag
    end
    U->>U: 校验 SHA256 → 交给 4DGS 播放组件
```

## 3. 配置项

```csharp
public static class PlatformConfig {
    public const string BaseUrl = "https://4dgs.elma-gohan.xyz"; // 开发机经反向隧道对外提供；开发机离线时不可用
}
```

- 当前是 HTTPS（Let's Encrypt 证书），Android 和 iOS 都不需要放行明文流量。若以后改回内网明文地址，Android 需在 manifest 允许明文流量（`usesCleartextTraffic`），iOS 需配置 ATS 例外。
- `downloadPath` 是以 `/` 开头的相对路径，用 `new Uri(new Uri(BaseUrl), path)` 拼绝对地址。路径里已含 URI 编码，不要二次编码。

## 4. 数据结构（C#）

字段名用 camelCase，与 JSON 对应。Unity 自带 `JsonUtility` 不支持顶层数组和可选字段，建议用 Newtonsoft.Json（`com.unity.nuget.newtonsoft-json`）。不要用位置式 `record`：Unity 2022.3 支持 C# 9，但默认运行库没有 `System.Runtime.CompilerServices.IsExternalInit`，这些声明编不过。

```csharp
public class SceneList {
    public List<SceneItem> items;
    public int total;
}
public class SceneItem {
    public string id, name, versionId;
    public int versionNo;
}
public class SceneDetail {
    public string sceneId, name, versionId;
    public int versionNo, fileCount;
    public long totalBytes;
    public List<FileEntry> files;
}
public class FileEntry {
    public string fileId, relativePath, sha256, contentType, downloadPath;
    public long bytes;
}
```

## 5. 选择文件

平台返回整个版本的文件清单，Unity 侧按自己的规则（例如目录前缀表示档位、文件名序号表示分段）以 `relativePath` 选出需要的文件：

```csharp
IEnumerable<FileEntry> FilesFor(SceneDetail d, IEnumerable<string> neededPaths) {
    var byPath = d.files.ToDictionary(f => f.relativePath);
    foreach (var p in neededPaths) yield return byPath[p];   // 找不到就报错，不要猜替代文件
}
```

手机与 VR 用哪些文件由你们产品决定，平台不做设备判断。

## 6. 下载与断点续传

不要用一次性 `UnityWebRequest.Get` 把几十到几百 MB 读进内存。用 `DownloadHandlerFile` 直接写文件（`appendToFile` 可续写），再用 `ComputeHash` 流式校验。要点：

1. 目标文件 `<name>.part` 与 `<name>.etag` 放在 `Application.persistentDataPath/<sceneId>/<versionId>/` 下，按 `relativePath` 保留子目录。
2. 首次：普通 GET，保存响应头 `ETag`。
3. 续传：`SetRequestHeader("Range", $"bytes={partLength}-")` 和 `If-Range: <保存的 ETag>`。
   - 返回 `206`：检查 `Content-Range` 起点等于 `partLength`，追加写入。
   - 返回 `200`：服务器忽略了 Range 或版本内容变了，**清空 .part 从头写**。
   - 返回 `416`：.part 异常，删除重下。
4. 下完比对 SHA256 与 `FileEntry.sha256`，一致才重命名为正式文件；不一致删除 `.part` 和 `.etag` 后重下该文件。
5. 全部文件完成后再写 `ready` 标记（同目录原子写），Unity 只加载有 `ready` 标记的目录。
6. 409：当前版本已被替换。停止，保留旧目录（可继续使用），重新拉详情走新 `versionId` 目录；不要混用。

`DownloadHandlerFile` 的 `removeFileOnAbort` 在续传场景要设为 `false`。

参考实现在 `scripts/download_scene.py`（下载整个版本的全部文件），目录布局、状态文件和退出码语义可以直接对照（Python，仅作联调参考，不是 SDK）。

## 7. 在线分段加载（边下边播）

- 分段文件和起止时间由 Unity 侧定义（平台不提供）。播放时按顺序预取下一段，当前段播放结束前就应已就绪。
- 每段文件走第 6 节同样的流程，可以只读到本地缓存再交给播放组件，也可以用 Range 分块边读边解码——这取决于你们的 4DGS 组件是否支持流式输入，**待验证**。
- 段内时间与模型内部时间的换算由播放组件负责，平台不改写模型。此前参考播放器（4DV 的 PlayCanvas viewer）在旧描述基线上验证过跨段时间连续推进；该适配自 2026-10-29 去掉描述后不可用，结果只作历史参考。

## 8. 变换、音频、封面

- 位置、旋转、缩放由 Unity 侧定义，先应用到场景根节点，再叠加你们的 AR 锚点。Unity 与参考播放器的坐标系（手系、Y 轴方向）不一定一致，**待验证**，平台不做转换。
- 播放器配置 JSON（如 `xrCamera`、`camera`、`animTracks`，`animTracks.duration` 是相机轨道时长，不等于模型总时长）若随目录上传，按普通文件下载，是否使用由你们的播放组件决定。
- 音频文件用于空间音频；参考验证里无头 Chrome 的音频没有启动，音画同步**未验证**。
- 封面图片和预览视频（webm）同样是普通文件，由 Unity 侧按路径识别。Unity 对 webm 的支持因平台而异，必要时只用封面。

## 9. 错误与重试

- 按 HTTP 状态码处理，不解析 `message`（见 21 号文档第 5 节表格）。
- 超时、断网：保留 `.part` 和 `ETag`，指数退避后续传，不要自动拉全量文件列表。
- 平台没有限流，但也不要对列表接口做秒级轮询；场景列表只在进入页面时刷新。

## 10. 联调清单

1. 手机浏览器能打开 `https://4dgs.elma-gohan.xyz/api/v1/client/scenes`，返回场景列表 JSON；打不开先确认开发机在线、反向隧道在运行。
2. `GET /scenes` 能返回至少一个场景；用 `curl` 先对照 21 号文档第 7 节。
3. 下载 dance_color 标准档所需文件（`standard_quality/` 下分段加公共文件，约 337 MB），SHA256 全部通过。当前服务上只有这个示例场景。
4. 手动断网后续传：`.part` 后继续，最终 SHA256 一致。
5. 管理端发布新版本后，旧 `versionId` 的下一个请求应得到 409，客户端按第 6 节处理。
6. 在 Unity 中加载并显示首帧；记录 GPU/内存占用（样例参数分析见项目外的《4DGS模型高斯参数与内存显存规格分析报告》）。
7. 手机真机：LAN 访问、下载速度、解码、渲染帧率、音画同步。

## 11. 本轮已验证与未验证

| 项 | 状态 |
|---|---|
| 匿名目录/详情/文件、Range、If-Range、HEAD | 0.4.0 在隔离实例上已验证；0.5.0（2026-10-29）在隔离实例上实测目录、详情与单段 Range |
| Python 参考下载器：断点续传、版本变化 409、损坏文件重下 | 0.5.0 整版下载在隔离实例上实测完成并逐文件核对 SHA-256；续传、409、损坏重下由 `scripts/test_download_scene.py` 假接口覆盖 |
| 桌面 Chrome 参考播放器：wedding 标准/高清、dance_color 标准跨段 | 旧描述基线上已验证；2026-10-29 去掉描述后参考播放器不可用 |
| Unity 编辑器/手机下载与加载 | **未验证** |
| 手机端解码、帧率、音频、坐标系对齐 | **未验证** |
| HTTPS | 已启用（Let's Encrypt，经 elma-gohan 反代） |
| CDN、长缓存 | 未实现 |
