// 对应 SceneService / SceneVersionService 写入 ar_audit 的动作；仅转换展示文案。
const auditActionLabels = Object.freeze({
  CREATE: '创建场景',
  UPDATE: '编辑场景',
  DELETE: '删除场景',
  SET_ENABLED: '设置场景启用状态',
  VERSION_CREATE: '创建版本',
  VERSION_EDIT: '编辑版本说明',
  VERSION_PUBLISH: '发布版本',
  VERSION_DELETE_REQUEST: '请求删除版本',
  VERSION_DELETE: '删除版本',
  VERSION_DELETE_FAILED: '版本删除失败',
  FILE_UPLOAD_START: '开始上传文件',
  FILE_AVAILABLE: '文件可用',
  FILE_FAILED: '文件入库失败',
  FILE_RECONCILE: '文件启动对账'
})

export function auditActionLabel(action) {
  return Object.prototype.hasOwnProperty.call(auditActionLabels, action)
    ? auditActionLabels[action]
    : action
}
