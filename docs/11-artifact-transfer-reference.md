# 资源传输参考工具

## 当前边界

当前业务格式是 `resource.json` v1 描述加固定文件清单，接口见 [资源入库闭环](12-resource-ingestion.md)。本页只说明 Python 3.11+ 标准库传输工具和独立的打包扩展接口，不另设业务契约。

场景级下载使用 `scripts/download_scene.py`：按当前发布版本和所选档位固定清单，分离 `payload/` 与控制区，复用 `artifact_transfer.download` 的 Range 续传逻辑。后台上传按文件重试，已入库文件跳过，不整包重传，也没有分片上传协议。匿名客户端读取不带管理员认证；这些工具是联调参考，不是手机 SDK。

## 工具边界

| 层 | 当前提供 | 使用边界 |
|---|---|---|
| 通用打包扩展 | `scripts/artifact_packaging.py` 中的 `PackageCodec` Protocol，无具体编解码实现 | 独立开发工具，当前 4DGS 目录上传/下载不调用它，也不要求 ZIP 或 Unity AssetBundle |
| 单文件传输 | `scripts/artifact_transfer.py` 的 `download` 与本机测试服务 | 固定 URL、大小与摘要，提供 Range/If-Range 参考；不解析模型 |
| 场景与版本下载 | `scripts/download_scene.py` | 经匿名目录/详情选取一个档位的模型与公共文件，完成校验后才写 `ready.json`；版本变化 409 即停止 |

`PackageCodec.pack`/`unpack` 仅表达可选生产工具的扩展职责，没有实现格式验证、安全解包或容量限制，不应当作已可用功能。通用 `restore-manifest` 命令仍能消费调用者提供的文件清单，但旧管理员清单接口已删除，当前业务完整下载使用 `download_scene.py`。

## 格式无关的传输约定

调用方提供访问 URL、准确字节数和小写十六进制 SHA-256。它们是函数输入，不代表最终业务清单的字段命名。摘要用于完整性验证，不替代身份认证或 HTTPS。

- 下载固定内容；更新资源应生成新文件，不能在下载过程中原地替换。
- 使用固定缓冲区写入 `.part`，不将整包载入内存；默认与目标文件相邻并按目标 SHA-256 隔离。`download` 的 `control_dir`/`control_key` 参数把 `.part`、验证器和锁移到独立控制目录（按 fileId 定位），使目标目录只出现完成的文件。
- 保存强 ETag。断线后以 `Range: bytes=N-` 和 `If-Range` 请求剩余字节。
- `206`：验证 ETag、Content-Range 起止/总量和 Content-Length，符合后才追加。
- `200`：忽略旧偏移，截断临时文件重新写入，不能把完整响应追加到旧字节后面。
- 没有强 ETag、检查点损坏或弱 ETag 时从头下载。ETag 视为不透明值，不假设所有服务器都使用 SHA-256。
- 已下载长度等于期望长度时先本地校验；超长重新开始。`416` 和其他 HTTP 错误上抛，保留原有部分数据，不无限重试。
- 完成后核对大小和整包 SHA-256，通过才交付最终文件：从 0 开始的下载（含 200 截断重写）在写入时同步计算摘要，不再整文件重读；续传完成后整文件校验一次。摘要错误删除部分文件，下次重下。
- 参考下载器每次执行只尝试一次，超时默认 30 秒；中断后重跑相同命令即可续传。自动退避、进度 UI、凭证续期由正式客户端后续实现。

服务返回原始字节，禁止传输压缩/内容转换。参考客户端要求单段响应覆盖偏移至文件结尾。HTTP 规则依据 [RFC 9110 If-Range](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.5) 和 [Range Requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-14)。

## 本机验证

传入任意合成二进制文件即可，无需 AR 包。下面路径均为示例，先准备文件，再以实际长度和摘要替换占位符：

```powershell
python scripts/artifact_transfer.py serve .local/sample.bin --port 18083
# 另一终端；填写可信来源提供的实际大小与 SHA-256。
python scripts/artifact_transfer.py download http://127.0.0.1:18083/artifact .local/client/sample.bin --bytes <BYTES> --sha256 <SHA256>
# 当前业务下载；使用实际网关、sceneId 和档位。
python scripts/download_scene.py --base-url https://4dgs.elma-gohan.xyz --scene-id <UUID> --variant standard_quality --output .local/downloads
python scripts/test_artifact_transfer.py
python scripts/test_download_scene.py
```

`serve` 只绑定 127.0.0.1，仅开放单文件 `/artifact`，支持 GET、HEAD、单段 Range 和越界 416。其他 Range 形式忽略并返回完整 200。没有鉴权、上传或目录列表，不能用作现场数百人的正式服务。运行期间不得修改源文件。

下载输出位于操作者独占的本地普通目录，当前以同卷硬链接实现完整文件不可覆盖交付；文件系统不支持则明确失败。参考工具不防御其他本机进程篡改目录的竞态。

同一目标用操作系统文件锁（Linux/macOS `fcntl.flock`，Windows `msvcrt.locking`）排除并行写入，锁文件 `<名称>.download.lock`（或控制目录中的 `<key>.lock`）保留为空文件，不靠文件是否存在判断占用：进程退出或被强杀后系统释放锁，残留的空文件不会卡住下一次运行；另一个活动进程持有时抛出 `DownloadBusy`。暂不引入任务调度、自动恢复或清理服务。

## 验证边界

单文件本机测试只证明通用传输规则；真实网关、版本变化和样包的既有验证见 [资源入库闭环](12-resource-ingestion.md) 与 [真实样包验收记录](20-4dgs-sample-validation.md)。它们不证明手机解码、可选打包/解包、现场网络容量或数百人承载能力；这些需要对应客户端与真实环境验收。
