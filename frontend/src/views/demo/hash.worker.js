import { sha256 } from 'js-sha256'
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
