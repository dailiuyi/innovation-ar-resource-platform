import request from '@/utils/request'

// request 按环境补网关前缀（开发 /dev-api，生产 /prod-api）；这里仅使用业务路径。
// 只封装 HTTP，选择文件、重试规划和自动发布由 VersionPanel / scenePackage 负责。

export function getScene(sceneId) {
  return request.get(`/api/v1/scenes/${sceneId}`)
}

export function getVersionConfig() {
  return request.get('/api/v1/scene-versions/config')
}

export function listVersions(sceneId, { limit, offset }) {
  return request.get(`/api/v1/scenes/${sceneId}/versions`, { params: { limit, offset } })
}

/** 只登记不可变文件清单，不发送文件内容；同次导入重试复用 body.requestKey。 */
export function createVersion(sceneId, body) {
  return request.post(`/api/v1/scenes/${sceneId}/versions`, body)
}

export function getVersion(versionId) {
  return request.get(`/api/v1/scene-versions/${versionId}`)
}

export function updateVersion(versionId, body) {
  return request.put(`/api/v1/scene-versions/${versionId}`, body)
}

export function getVersionFile(versionId, fileId) {
  return request.get(`/api/v1/scene-versions/${versionId}/files/${fileId}`)
}

/** 原始文件正文，不使用 multipart；进度回调表示已发送字节，返回的状态才用于确认入库。 */
export function uploadVersionFile(versionId, fileId, file, { signal, onUploadProgress }) {
  return request.put(`/api/v1/scene-versions/${versionId}/files/${fileId}/content`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    timeout: 0,
    signal,
    onUploadProgress
  })
}

/** 发布校验场景修订号；修改版本说明则传版本自己的 expectedVersion。 */
export function publishVersion(versionId, expectedSceneVersion) {
  return request.post(`/api/v1/scene-versions/${versionId}/publish`, { expectedSceneVersion })
}

/** 整版本物理删除；失败后重新调用同一 URL 继续，当前发布版本不能删除。 */
export function deleteVersion(versionId) {
  return request.delete(`/api/v1/scene-versions/${versionId}`)
}
