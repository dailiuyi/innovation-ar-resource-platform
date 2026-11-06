<template>
  <div class="app-container">
    <header class="page-head">
      <h2>场景管理</h2>
      <p>一个场景对应一份固定的 4DGS 成品文件清单。文件全部校验入库且场景启用后，客户端即可读取；更换资源请新建场景。</p>
    </header>
    <el-form inline class="toolbar" @submit.prevent="search">
      <el-form-item><el-input v-model="name" clearable placeholder="按名称搜索" @clear="search" /></el-form-item>
      <el-form-item>
        <el-button @click="search">查询</el-button>
        <el-button type="primary" @click="openCreate">新建场景</el-button>
      </el-form-item>
    </el-form>
    <el-table :data="items" v-loading="loading">
      <el-table-column prop="name" label="名称" min-width="220" show-overflow-tooltip />
      <el-table-column label="状态" width="170">
        <template #default="{row}">
          <div class="status-cell">
            <el-tag :type="row.enabled?'success':'info'">{{row.enabled?'启用':'停用'}}</el-tag>
            <el-tag v-if="row.uploadStatus&&row.uploadStatus!=='READY'" :type="uploadStatusType(row.uploadStatus)">{{uploadStates[row.uploadStatus]||row.uploadStatus}}</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="文件" width="90"><template #default="{row}">{{row.availableCount??0}} / {{row.fileCount??0}}</template></el-table-column>
      <el-table-column label="大小" width="100"><template #default="{row}">{{size(row.totalBytes)}}</template></el-table-column>
      <el-table-column label="更新时间" width="160"><template #default="{row}">{{formatTime(row.updatedAt)}}</template></el-table-column>
      <el-table-column label="操作" width="200" fixed="right"><template #default="{row}">
        <div class="scene-actions">
          <el-button link type="primary" @click="openScene(row)">查看</el-button>
          <el-button link type="warning" :disabled="deleting||isDeleteState(row)" @click="toggle(row)">{{row.enabled?'停用':'启用'}}</el-button>
          <el-button link type="danger" :disabled="deleting||row.uploadStatus==='UPLOADING'" @click="remove(row)">{{isDeleteState(row)?'重试删除':'删除'}}</el-button>
        </div>
      </template></el-table-column>
    </el-table>
    <pagination v-show="total>0" :total="total" v-model:page="page" v-model:limit="limit" @pagination="load" />
    <ScenePanel :target="target" @close="closePanel" @created="onCreated" @updated="load" />
  </div>
</template>
<style scoped>
.page-head{margin-bottom:16px}
.page-head h2{margin:0 0 6px;font-size:20px}
.page-head p{margin:0;max-width:640px;color:var(--el-text-color-secondary);font-size:13px;line-height:1.6}
.toolbar{margin-bottom:4px}
.status-cell{display:flex;align-items:center;gap:6px}
.scene-actions{display:flex;align-items:center;flex-wrap:nowrap;gap:12px}
.scene-actions :deep(.el-button+.el-button){margin-left:0}
</style>
<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteScene, listScenes, setSceneEnabled } from '@/api/scene'
import { SCENE_UPLOAD_STATES, formatBytes, formatTime, uploadStatusType } from '@/utils/scenePackage'
import ScenePanel from './ScenePanel.vue'

const route = useRoute(), router = useRouter()
const uploadStates = SCENE_UPLOAD_STATES
const size = formatBytes
const items = ref([]), total = ref(0), page = ref(1), limit = ref(20), name = ref('')
const loading = ref(false), deleting = ref(false), creating = ref(false)
// 面板只有一个目标：'' 关闭，'new' 新建，其余为场景 id。URL 只保存 sceneId，'new' 是页面本地状态。
const target = computed(() => creating.value ? 'new' : String(route.query.sceneId || ''))
function isDeleteState(row) { return ['DELETING', 'DELETE_FAILED'].includes(row.uploadStatus) }
function message(e) { return e?.response?.data?.message || e?.message || '请求失败，请刷新后重试' }
function setSceneQuery(id) {
  const query = { ...route.query }
  if (id) query.sceneId = id
  else delete query.sceneId
  return router.replace({ query })
}
async function load() {
  loading.value = true
  try {
    const result = await listScenes({ name: name.value, limit: limit.value, offset: (page.value - 1) * limit.value })
    items.value = result.items
    total.value = result.total
  } catch (e) { ElMessage.error(message(e)) } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function openCreate() {
  creating.value = true
  if (route.query.sceneId) setSceneQuery('')
}
function openScene(row) {
  creating.value = false
  setSceneQuery(row.id)
}
function closePanel() {
  creating.value = false
  setSceneQuery('')
  load()
}
// 先让路由携带新 sceneId，再清除 creating；否则 target 会短暂变空，面板会把刚创建、正在上传的场景当成关闭。
async function onCreated(scene) {
  await setSceneQuery(scene.id)
  creating.value = false
  load()
}
async function toggle(row) {
  try {
    const { value } = await ElMessageBox.prompt('请填写原因', '确认' + (row.enabled ? '停用' : '启用'), {
      inputValidator: value => !!value?.trim() || '原因不能为空'
    })
    await setSceneEnabled(row.id, { enabled: !row.enabled, expectedVersion: row.lockVersion, reason: value })
    ElMessage.success('状态已更新')
    await load()
  } catch (e) {
    if (e.response?.status === 409) await load()
  }
}
// 物理删除场景与全部文件；失败后行保留为“删除失败”，可再次点击重试。
async function remove(row) {
  if (deleting.value) return
  try {
    await ElMessageBox.confirm(`确认删除场景“${row.name}”吗？将永久删除该场景的全部模型文件，无法恢复。操作记录会保留。`, '删除场景', {
      confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning',
      closeOnClickModal: false, autofocus: false, confirmButtonClass: 'el-button--danger'
    })
  } catch { return }
  deleting.value = true
  try {
    await deleteScene(row.id, row.lockVersion)
    ElMessage.success('场景已删除')
    if (items.value.length === 1 && page.value > 1) page.value--
    await load()
  } catch (e) {
    ElMessage.error(message(e))
    await load()
  } finally { deleting.value = false }
}
load()
</script>
