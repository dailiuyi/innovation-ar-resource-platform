import request from '@/utils/request'

export function getScene(sceneId) {
  return request.get(`/api/v1/scenes/${sceneId}`)
}

export function getVersionConfig() {
  return request.get('/api/v1/scene-versions/config')
}

export function listVersions(sceneId, { limit, offset }) {
  return request.get(`/api/v1/scenes/${sceneId}/versions`, { params: { limit, offset } })
}

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

export function uploadVersionFile(versionId, fileId, file, { signal, onUploadProgress }) {
  return request.put(`/api/v1/scene-versions/${versionId}/files/${fileId}/content`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    timeout: 0,
    signal,
    onUploadProgress
  })
}

export function publishVersion(versionId, expectedSceneVersion) {
  return request.post(`/api/v1/scene-versions/${versionId}/publish`, { expectedSceneVersion })
}

export function deleteVersion(versionId) {
  return request.delete(`/api/v1/scene-versions/${versionId}`)
}
