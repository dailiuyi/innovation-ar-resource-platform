import { sha256 } from 'js-sha256'
// 只做本地 SHA-256 预计算：每次消息处理一个 File，逐块报告累计已读字节，最后返回十六进制摘要。
// 服务端接收上传时仍会独立校验大小和 SHA256；此结果不能代替服务端入库确认。
self.onmessage = async ({ data: file }) => {
  try {
    const hash = sha256.create()
    const chunkSize = 2 * 1024 * 1024
    for (let offset = 0; offset < file.size; offset += chunkSize) {
      hash.update(await file.slice(offset, offset + chunkSize).arrayBuffer())
      self.postMessage({ loaded: Math.min(offset + chunkSize, file.size) })
    }
    self.postMessage({ digest: hash.hex() })
  } catch { self.postMessage({ error: '无法读取文件，请重新选择' }) }
}
