import request from '@/utils/request'

// request 按环境补网关前缀（开发 /dev-api，生产 /prod-api）；这里仅使用业务路径。
// 场景 = 一个固定文件清单；只封装 HTTP，文件选择、哈希、重试规划由 ScenePanel / scenePackage 负责。

/** 上传上限配置：单文件、文件数、总大小。 */
export function getSceneConfig() {
  return request.get('/api/v1/scenes/config')
}

export function listScenes({ name, limit, offset }) {
  return request.get('/api/v1/scenes', { params: { name, limit, offset } })
}

/** 一个事务登记场景与固定文件清单；同一 requestKey 重试返回同一场景。 */
export function createScene(body) {
  return request.post('/api/v1/scenes', body)
}

export function getScene(sceneId) {
  return request.get(`/api/v1/scenes/${sceneId}`)
}

/** 只修改名称与描述，不能改变文件清单。 */
export function updateScene(sceneId, body) {
  return request.put(`/api/v1/scenes/${sceneId}`, body)
}

/** 启用/停用；上传与恢复流程不会改变启用状态。 */
export function setSceneEnabled(sceneId, body) {
  return request.put(`/api/v1/scenes/${sceneId}/enabled`, body)
}

/** 整场景物理删除；失败后重新调用同一 URL 继续。 */
export function deleteScene(sceneId, expectedVersion) {
  return request.delete(`/api/v1/scenes/${sceneId}`, { params: { expectedVersion } })
}

export function getSceneFile(sceneId, fileId) {
  return request.get(`/api/v1/scenes/${sceneId}/files/${fileId}`)
}

/** 原始文件正文，不使用 multipart；进度回调表示已发送字节，返回的状态才用于确认入库。 */
export function uploadSceneFile(sceneId, fileId, file, { signal, onUploadProgress }) {
  return request.put(`/api/v1/scenes/${sceneId}/files/${fileId}/content`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    timeout: 0,
    signal,
    onUploadProgress
  })
}
