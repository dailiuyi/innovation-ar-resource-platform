<template>
  <el-drawer :model-value="open" :title="title" size="90%" class="scene-panel" :close-on-click-modal="false" :before-close="beforeClose">
    <template v-if="mode==='create'">
      <p class="scene-intro">新建场景后文件清单固定；全部文件校验入库后，启用中的场景即可被客户端读取。要更换资源，请新建另一个场景。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-form label-width="80px" class="scene-meta" @submit.prevent="startCreate">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" maxlength="200" show-word-limit :disabled="busy" placeholder="场景名称" @input="saveDraft()" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" maxlength="2000" show-word-limit :disabled="busy" placeholder="可留空" @input="saveDraft()" />
        </el-form-item>
      </el-form>
      <div class="action-row">
        <el-button type="primary" :disabled="busy" @click="choose('directory')">导入资源目录</el-button>
        <el-button :disabled="busy" @click="choose('files')">导入文件</el-button>
        <el-button type="primary" :loading="busy" :disabled="createDisabled" @click="startCreate">开始上传</el-button>
        <el-button v-if="busy" type="warning" @click="cancel">停止本次传输</el-button>
        <el-button v-if="createPlan" :disabled="busy" @click="createPlan=null">放弃选择</el-button>
        <span class="hint">全部文件原样上传（ZIP 不解压，由 Unity 解压）；目录保留相对路径，文件使用文件名。单文件上限 {{size(config.maxBytes)}}，每个场景最多 {{config.sceneMaxFiles}} 个文件 / {{size(config.sceneMaxBytes)}}。</span>
      </div>
      <section v-if="createPlan" class="import-card">
        <h3>待导入：{{createPlan.pkg.files.length}} 个文件，共 {{size(createPlan.pkg.totalBytes)}}</h3>
        <p class="hint">开始后先计算 SHA-256，再一次性登记场景与文件清单；请保持页面打开。</p>
      </section>
    </template>
    <template v-else-if="mode==='detail'">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <div v-if="!detail" class="action-row">
        <el-button :disabled="busy||removing" @click="refresh">刷新</el-button>
      </div>
      <template v-else>
        <div class="scene-meta">
          <el-form label-width="80px" @submit.prevent="saveMeta">
            <el-form-item label="名称" required>
              <el-input v-model="meta.name" maxlength="200" :disabled="busy||removing||savingMeta" @keydown.enter="submitMeta" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="meta.description" type="textarea" :rows="3" maxlength="2000" :disabled="busy||removing||savingMeta" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingMeta" :disabled="busy||removing" @click="saveMeta">保存修改</el-button>
            </el-form-item>
          </el-form>
        </div>
        <p class="scene-state">
          <el-tag :type="detail.enabled?'success':'info'">{{detail.enabled?'启用':'停用'}}</el-tag>
          <el-tag :type="uploadStatusType(detail.uploadStatus)" class="tag-gap">{{uploadStates[detail.uploadStatus]||detail.uploadStatus}}</el-tag>
          <span class="state-summary">文件 {{detail.availableCount}} / {{detail.fileCount}}<span v-if="detail.failedCount">，失败 {{detail.failedCount}}</span>，共 {{size(detail.totalBytes)}}</span>
          <span class="state-updated">更新于 {{formatTime(detail.updatedAt)}}</span>
        </p>
        <el-alert v-if="detail.uploadStatus==='DELETE_FAILED'" title="删除未完成，场景已保留；请点击“重试删除”继续清理。" type="warning" :closable="false" />
        <el-alert v-else-if="detail.uploadStatus==='DELETING'" title="场景正在删除；完成后会从列表移除。" type="warning" :closable="false" />
        <div class="action-row">
          <el-button v-if="canResume&&sessionForScene" type="primary" :disabled="busy||removing" @click="runSession">继续上传</el-button>
          <el-button v-if="canResume" :type="sessionForScene?'default':'primary'" :disabled="busy||removing" @click="choose('directory')">重新选择目录</el-button>
          <el-button v-if="canResume" :type="sessionForScene?'default':'primary'" :disabled="busy||removing" @click="choose('files')">重新选择文件</el-button>
          <el-button :disabled="busy||removing" @click="refresh">刷新</el-button>
          <el-button v-if="busy" type="warning" @click="cancel">停止本次传输</el-button>
          <el-button type="danger" plain :disabled="busy||removing" @click="removeScene">{{retryDelete?'重试删除':'删除场景'}}</el-button>
        </div>
        <p v-if="canResume" class="hint">中断后请选择原文件或原目录：路径、大小与 SHA-256 必须与该场景登记的一致；已入库的文件不会重传。</p>
        <p v-else-if="detail.uploadStatus==='READY'" class="hint">场景已就绪，文件清单不可修改。要更换资源，请新建另一个场景。</p>
        <el-table :data="detail.files||[]" class="scene-files" size="small" row-key="fileId">
          <el-table-column prop="relativePath" label="文件" min-width="280" show-overflow-tooltip />
          <el-table-column label="大小" width="110"><template #default="{row}">{{size(row.bytes)}}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="fileStatusType(row.status)">{{fileStates[row.status]||row.status}}</el-tag></template></el-table-column>
          <el-table-column label="原因" min-width="180" show-overflow-tooltip><template #default="{row}">{{row.failureReason}}</template></el-table-column>
        </el-table>
      </template>
    </template>
    <p v-if="progressText" role="status">{{progressText}}</p>
    <el-progress v-if="busy" :percentage="progress" />
    <el-table v-if="uploadIssues.length" :data="uploadIssues" class="upload-issues" row-key="relativePath" max-height="280">
      <el-table-column prop="relativePath" label="文件" min-width="260" show-overflow-tooltip />
      <el-table-column prop="kind" label="结果" width="110" />
      <el-table-column prop="reason" label="原因" min-width="300" />
    </el-table>
    <input ref="directoryPicker" type="file" data-import-mode="directory" webkitdirectory directory multiple hidden @change="picked($event,'directory')" />
    <input ref="filePicker" type="file" data-import-mode="files" multiple hidden @change="picked($event,'files')" />
  </el-drawer>
</template>
<script setup>
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createScene, deleteScene, getScene, getSceneConfig, getSceneFile, updateScene, uploadSceneFile } from '@/api/scene'
import {
  SCENE_FILE_STATES, SCENE_UPLOAD_STATES, UPLOAD_CONCURRENCY, checkDigests, checkLimits,
  checkSelection, createRequest, fileStatusType, formatBytes, formatTime, readPackage, runUploads,
  uploadPlan, uploadStatusType
} from '@/utils/scenePackage'
import cache from '@/plugins/cache'
import useUserStore from '@/store/modules/user'

// 一个场景 = 一个固定的文件清单。新建时名称/描述与文件同一次登记；就绪后不再提供替换或追加文件。
const props = defineProps({ sceneId: { type: String, default: '' }, creating: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'created', 'updated'])
const mode = ref('closed')
const activeId = ref('')
const detail = ref(null)
const meta = reactive({ name: '', description: '' })
const createForm = reactive({ name: '', description: '' })
const createPlan = shallowRef(null)
const session = shallowRef(null)
const config = ref({ maxBytes: 0, sceneMaxFiles: 0, sceneMaxBytes: 0 })
const directoryPicker = ref(null), filePicker = ref(null)
const busy = ref(false), savingMeta = ref(false), removing = ref(false)
const error = ref(''), progress = ref(0), progressText = ref('')
const uploadIssues = ref([])
const uploadStates = SCENE_UPLOAD_STATES, fileStates = SCENE_FILE_STATES
const size = formatBytes
const draftStorageKey = 'ar:new-scene-draft:' + useUserStore().id
const open = computed(() => mode.value !== 'closed')
const title = computed(() => mode.value === 'create' ? '新建场景' : detail.value?.name ? '场景 · ' + detail.value.name : '场景')
const canResume = computed(() => !!detail.value && (detail.value.files?.length ?? 0) > 0
  && ['PENDING', 'UPLOADING', 'FAILED'].includes(detail.value.uploadStatus))
const sessionForScene = computed(() => !!session.value && session.value.sceneId === activeId.value)
const retryDelete = computed(() => ['DELETING', 'DELETE_FAILED'].includes(detail.value?.uploadStatus))
const createDisabled = computed(() => busy.value || !createForm.name.trim() || !createPlan.value)

let configLoaded = false, worker = null, rejectHash = null, cancelled = false, runToken = 0
const controllers = new Set()
// 请求序号只阻止过期响应覆盖当前视图，不撤销服务端已完成的创建或上传。
let detailRequest = 0
// 视图代次在打开/关闭/卸载时递增，用于丢弃迟到的详情或元数据响应。
let viewToken = 0

function message(e) {
  return e?.response?.data?.message || e?.response?.data?.detail || e?.message || (typeof e === 'string' ? e : '请求失败，请刷新核对后重试')
}
function randomKey() {
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = b[6] & 15 | 64
  b[8] = b[8] & 63 | 128
  const x = Array.from(b, v => v.toString(16).padStart(2, '0')).join('')
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`
}
function readDraft() {
  try { return cache.local.getJSON(draftStorageKey) || null } catch { return null }
}
function saveDraft(extra) {
  const current = readDraft() || {}
  cache.local.setJSON(draftStorageKey, { ...current, name: createForm.name, description: createForm.description, ...(extra || {}) })
}
function clearDraft() { cache.local.remove(draftStorageKey) }
function manifestOf(pkg, digests) {
  return pkg.files.map(item => ({ relativePath: item.relativePath, bytes: item.bytes, sha256: digests.get(item.relativePath) }))
}
function sameManifest(left, right) {
  if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false
  return left.every((item, index) => item.relativePath === right[index].relativePath
    && item.bytes === right[index].bytes && item.sha256 === right[index].sha256)
}
function draftKeyMatches(draft, files, name, description) {
  return !!draft?.requestKey && draft.name === name && (draft.description ?? '') === description && sameManifest(draft.manifest, files)
}
async function loadConfig() {
  if (configLoaded) return
  try {
    config.value = await getSceneConfig()
    configLoaded = true
  } catch (e) { if (!error.value) error.value = message(e) }
}
function applyDetail(value, { syncMeta = false } = {}) {
  detail.value = value
  if (syncMeta) {
    meta.name = value.name ?? ''
    meta.description = value.description ?? ''
  }
}
async function loadDetail(id, { syncMeta = false } = {}) {
  const sequence = ++detailRequest
  try {
    const value = await getScene(id)
    if (sequence !== detailRequest || id !== activeId.value) return null
    applyDetail(value, { syncMeta })
    return value
  } catch (e) {
    if (sequence === detailRequest && id === activeId.value) error.value = message(e)
    return null
  }
}
function openCreate() {
  stopFlow()
  mode.value = 'create'
  activeId.value = ''
  detail.value = null
  createPlan.value = null
  session.value = null
  const draft = readDraft()
  createForm.name = draft?.name ?? ''
  createForm.description = draft?.description ?? ''
  error.value = ''
  loadConfig()
}
function openDetail(id) {
  stopFlow()
  mode.value = 'detail'
  activeId.value = id
  detail.value = null
  meta.name = ''
  meta.description = ''
  error.value = ''
  loadConfig()
  loadDetail(id, { syncMeta: true })
}
function stopFlow() {
  ++viewToken
  savingMeta.value = false
  cancel()
  ++runToken
  busy.value = false
  session.value = null
  createPlan.value = null
  controllers.clear()
  progress.value = 0
  progressText.value = ''
  uploadIssues.value = []
}
function requestClose() {
  if (busy.value || removing.value) {
    ElMessage.warning('请等待上传结束或先停止传输')
    return false
  }
  if (mode.value === 'create') saveDraft()
  ++viewToken
  savingMeta.value = false
  mode.value = 'closed'
  emit('close')
  return true
}
function beforeClose(done) { if (requestClose()) done() }
function submitMeta(event) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  saveMeta()
}
async function saveMeta() {
  if (savingMeta.value || !detail.value) return
  const targetId = activeId.value
  const targetVersion = detail.value.lockVersion
  const token = viewToken
  const name = meta.name.trim()
  if (!name) return ElMessage.warning('请填写场景名称')
  savingMeta.value = true
  try {
    const updated = await updateScene(targetId, { name, description: meta.description, expectedVersion: targetVersion })
    if (token !== viewToken || mode.value !== 'detail' || targetId !== activeId.value) return
    if (updated?.files) applyDetail(updated, { syncMeta: true })
    else await loadDetail(targetId, { syncMeta: true })
    emit('updated')
    ElMessage.success('场景信息已保存')
  } catch (e) {
    if (token !== viewToken || mode.value !== 'detail' || targetId !== activeId.value) return
    error.value = message(e)
    if (e.response?.status === 409) await loadDetail(targetId, { syncMeta: true })
  } finally {
    if (token === viewToken) savingMeta.value = false
  }
}
async function refresh() {
  error.value = ''
  await loadDetail(activeId.value, { syncMeta: true })
}
async function removeScene() {
  if (busy.value || removing.value || !detail.value) return
  const target = detail.value
  try {
    await ElMessageBox.confirm(`确认删除场景“${target.name}”吗？将永久删除该场景的全部模型文件，无法恢复。操作记录会保留。`, '删除场景', {
      confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning',
      closeOnClickModal: false, autofocus: false, confirmButtonClass: 'el-button--danger'
    })
  } catch { return }
  removing.value = true
  try {
    await deleteScene(target.id, target.lockVersion)
    ElMessage.success('场景已删除')
    emit('updated')
    removing.value = false
    requestClose()
  } catch (e) {
    error.value = message(e)
    if ([409, 404, 503].includes(e.response?.status)) await loadDetail(activeId.value)
    emit('updated')
  } finally { removing.value = false }
}
function choose(kind) {
  if (busy.value || removing.value) return
  const input = kind === 'files' ? filePicker.value : directoryPicker.value
  input.value = ''
  input.click()
}
async function picked(event, kind) {
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  error.value = ''
  try {
    await loadConfig()
    if (!configLoaded) throw new Error('无法读取上传限制，请刷新后重试')
    const pkg = await readPackage(files, { mode: kind })
    checkLimits(pkg, config.value)
    if (mode.value === 'create') {
      createPlan.value = { pkg }
      return
    }
    if (mode.value !== 'detail' || !detail.value || !canResume.value) return
    checkSelection(pkg, detail.value)
    session.value = {
      sceneId: activeId.value, pkg, digests: null, expect: detail.value,
      name: detail.value.name, description: detail.value.description ?? '', requestKey: null
    }
    await runSession()
  } catch (e) { error.value = message(e) }
}
async function startCreate() {
  if (busy.value) return
  await loadConfig()
  if (!configLoaded) return
  const name = createForm.name.trim()
  if (!name) return ElMessage.warning('请填写场景名称')
  if (!createPlan.value?.pkg) return ElMessage.warning('请选择资源文件')
  const current = session.value
  if (!current || current.sceneId || current.pkg !== createPlan.value.pkg
    || current.name !== name || current.description !== createForm.description) {
    session.value = {
      sceneId: '', pkg: createPlan.value.pkg, digests: null, expect: null,
      name, description: createForm.description, requestKey: null
    }
  }
  await runSession()
}
// 每个文件单独启用 Worker；大文件分块读取，避免在 Vue 主线程一次读入整个文件。
function digest(file, onProgress) {
  return new Promise((resolve, reject) => {
    rejectHash = reject
    worker = new Worker(new URL('./hash.worker.js', import.meta.url), { type: 'module' })
    worker.onmessage = ({ data }) => {
      if (data.error) { stopWorker(); reject(new Error(data.error)) }
      else if (data.digest) { stopWorker(); resolve(data.digest) }
      else onProgress(data.loaded)
    }
    worker.onerror = () => { stopWorker(); reject(new Error('摘要计算失败')) }
    worker.postMessage(file)
  })
}
function stopWorker() {
  worker?.terminate()
  worker = null
  rejectHash = null
}
async function hashAll(pkg, live) {
  const digests = new Map()
  let hashedBytes = 0
  for (let i = 0; i < pkg.files.length; i++) {
    if (cancelled || !live()) throw new Error('已取消')
    const item = pkg.files[i]
    const showProgress = loaded => {
      if (!live()) return
      const bytes = hashedBytes + loaded
      progress.value = Math.floor(bytes / pkg.totalBytes * 100)
      progressText.value = `准备校验：已读取 ${size(bytes)} / ${size(pkg.totalBytes)}；正在计算 ${i + 1}/${pkg.files.length} ${item.relativePath} 的 SHA-256`
    }
    showProgress(0)
    digests.set(item.relativePath, await digest(item.file, showProgress))
    if (!live()) throw new Error('已取消')
    showProgress(item.file.size)
    hashedBytes += item.file.size
  }
  return digests
}
// 停止本地哈希、后续派发和在途 HTTP；不删除已经登记的固定清单，也不能据此判定服务端失败。
function cancel() {
  cancelled = true
  worker?.terminate()
  worker = null
  rejectHash?.(new Error('已取消'))
  rejectHash = null
  for (const controller of controllers) controller.abort()
}
class UploadUnconfirmedError extends Error {}
async function reconcile(sceneId, record, onState) {
  let state
  try { state = await getSceneFile(sceneId, record.fileId) }
  catch { throw new UploadUnconfirmedError('上传结果未确认，请刷新状态') }
  onState(state)
  if (state.status === 'AVAILABLE') return
  if (state.status === 'UPLOADING') throw new UploadUnconfirmedError('服务端仍在处理，请稍后点击“刷新”')
  throw new Error(`上传未完成${state.failureReason ? '：' + state.failureReason : ''}，可继续上传`)
}
// 明确的业务错误直接交给本轮汇总；无响应/502/504 或非 AVAILABLE 响应，再查单文件确认结果。
async function uploadOne(sceneId, record, file, onProgress, onState) {
  const controller = new AbortController()
  controllers.add(controller)
  try {
    const result = await uploadSceneFile(sceneId, record.fileId, file, {
      signal: controller.signal,
      onUploadProgress: e => onProgress(Math.min(e.loaded, file.size))
    })
    onState(result)
    if (result.status === 'AVAILABLE') return
  } catch (e) {
    if (e.response && ![502, 504].includes(e.response.status)) throw e
  } finally { controllers.delete(controller) }
  await reconcile(sceneId, record, onState)
}
/**
 * 同一 session 可继续执行：摘要已取得就复用，按服务端最新状态规划上传。
 * 创建只发生一次；发送进度到 100% 不算成功，必须再读详情确认 READY 且全部文件 AVAILABLE。
 */
async function runSession() {
  const s = session.value
  if (!s || busy.value || removing.value) return
  if (s.sceneId && s.sceneId !== activeId.value) return
  const token = ++runToken
  const live = () => token === runToken && (!s.sceneId || s.sceneId === activeId.value)
  let createdNow = false
  busy.value = true
  cancelled = false
  error.value = ''
  uploadIssues.value = []
  progress.value = 0
  try {
    await loadConfig()
    if (!configLoaded) throw new Error('无法读取上传限制，请刷新后重试')
    if (!s.digests) {
      s.digests = await hashAll(s.pkg, live)
      if (!live()) return
      if (s.expect) { checkDigests(s.pkg, s.digests, s.expect); s.expect = null }
    }
    if (cancelled) throw new Error('已取消')
    if (!s.sceneId) {
      const files = manifestOf(s.pkg, s.digests)
      if (!s.requestKey) {
        const draft = readDraft()
        s.requestKey = draftKeyMatches(draft, files, s.name, s.description) ? draft.requestKey : randomKey()
      }
      // 请求发出前先持久化；响应丢失后重新选择同一批文件可复用请求标识。
      saveDraft({ requestKey: s.requestKey, manifest: files, name: s.name, description: s.description })
      progressText.value = '正在登记场景'
      const created = await createScene(createRequest(s.pkg, s.digests, {
        requestKey: s.requestKey, name: s.name, description: s.description
      }))
      if (!live()) return
      s.sceneId = created.id
      clearDraft()
      createPlan.value = null
      mode.value = 'detail'
      activeId.value = created.id
      detail.value = null
      meta.name = created.name ?? s.name
      meta.description = created.description ?? s.description
      emit('created', created)
      createdNow = true
      if (!live()) return
      if (cancelled) throw new Error('已取消')
    }
    const snapshot = await getScene(s.sceneId)
    if (!live()) return
    applyDetail(snapshot)
    const current = detail.value
    const plan = uploadPlan(current.files)
    const local = new Map(s.pkg.files.map(item => [item.relativePath, item.file]))
    const totalBytes = current.files.reduce((sum, file) => sum + file.bytes, 0)
    let done = plan.done
    let doneBytes = current.files.filter(file => file.status === 'AVAILABLE').reduce((sum, file) => sum + file.bytes, 0)
    const sending = new Map()
    const syncSummary = () => {
      if (!live()) return
      const files = current.files
      const availableCount = files.filter(file => file.status === 'AVAILABLE').length
      const failedCount = files.filter(file => file.status === 'FAILED').length
      const uploadStatus = sending.size || files.some(file => file.status === 'UPLOADING') ? 'UPLOADING'
        : failedCount ? 'FAILED' : availableCount === files.length ? 'READY' : 'PENDING'
      Object.assign(current, { availableCount, failedCount, uploadStatus, totalBytes })
    }
    const refreshProgress = () => {
      if (!live()) return
      let sent = 0
      for (const item of sending.values()) sent += item.loaded
      progress.value = totalBytes ? Math.min(100, Math.floor((doneBytes + sent) / totalBytes * 100)) : 100
      const flying = [...sending].map(([path, item]) => item.loaded >= item.bytes ? `${path}（等待服务端校验）` : path)
      progressText.value = `传输进度：${size(doneBytes + sent)} / ${size(totalBytes)}；已入库 ${done}/${current.files.length}${flying.length ? '；在途：' + flying.join('、') : ''}`
    }
    const upload = async record => {
      const item = { loaded: 0, bytes: record.bytes }
      sending.set(record.relativePath, item)
      syncSummary()
      refreshProgress()
      try {
        await uploadOne(s.sceneId, record, local.get(record.relativePath), loaded => {
          item.loaded = loaded
          if (sending.get(record.relativePath) === item) refreshProgress()
        }, state => {
          if (!live()) return
          Object.assign(record, state)
          syncSummary()
        })
        done++
        doneBytes += record.bytes
      } finally {
        sending.delete(record.relativePath)
        syncSummary()
        refreshProgress()
      }
    }
    const failures = await runUploads(plan.upload, UPLOAD_CONCURRENCY, upload, () => cancelled || !live())
    if (!live()) return
    if (cancelled) throw new Error('已取消')
    const issues = failures.map(({ record, error: cause }) => ({
      relativePath: record.relativePath,
      kind: cause instanceof UploadUnconfirmedError ? '结果未确认' : '请求失败',
      reason: message(cause)
    }))
    for (const record of plan.processing) issues.push({
      relativePath: record.relativePath, kind: '结果未确认', reason: '本轮开始时服务端仍在处理，未重复上传；请刷新确认'
    })
    uploadIssues.value = issues
    if (issues.length) {
      const failed = issues.filter(issue => issue.kind === '请求失败').length
      throw new Error(`本轮请求失败 ${failed} 个，结果未确认 ${issues.length - failed} 个。完整列表见下方；刷新状态后继续上传，已入库和处理中不会重复发送。`)
    }
    const complete = await getScene(s.sceneId)
    if (!live()) return
    if (cancelled) throw new Error('已取消')
    if (complete.uploadStatus !== 'READY' || !complete.files.every(file => file.status === 'AVAILABLE')) {
      throw new UploadUnconfirmedError('场景尚未确认全部就绪，请刷新状态后继续上传')
    }
    applyDetail(complete)
    session.value = null
    progressText.value = '全部文件已校验入库' + (complete.enabled ? '，场景已启用，客户端可读' : '；场景当前停用，启用后客户端可读')
    emit('updated')
    ElMessage.success('全部文件已校验入库')
  } catch (e) {
    if (!live()) return
    emit('updated')
    if (createdNow) {
      error.value = `场景已创建，但文件尚未全部入库：${message(e)}。已入库的文件会保留，可刷新后继续上传。`
      progressText.value = '文件尚未全部入库'
    } else {
      error.value = cancelled
        ? '已停止本次传输，上传结果未确认。已登记的文件会保留；请刷新状态后继续上传'
        : message(e)
      progressText.value = '本次操作未确认全部完成'
    }
  } finally {
    if (live()) {
      stopWorker()
      controllers.clear()
      busy.value = false
      if (mode.value === 'detail' && activeId.value) {
        const latest = await loadDetail(activeId.value)
        if (!live()) return
        if (latest) applyDetail(latest)
      }
    }
  }
}
watch(() => props.creating, value => {
  if (value) {
    if (mode.value !== 'create') openCreate()
  } else if (mode.value === 'create') {
    mode.value = 'closed'
  }
}, { immediate: true })
watch(() => props.sceneId, id => {
  if (props.creating) return
  if (id && id === activeId.value && mode.value === 'detail') return
  if (id) openDetail(id)
  else if (mode.value === 'detail') {
    stopFlow()
    mode.value = 'closed'
    activeId.value = ''
    detail.value = null
    error.value = ''
    progress.value = 0
    progressText.value = ''
  }
}, { immediate: true })
onBeforeUnmount(() => { if (mode.value === 'create') saveDraft(); ++viewToken; cancel(); ++runToken })
</script>
<style scoped>
.scene-intro{margin:0 0 16px;color:var(--el-text-color-secondary)}
.scene-meta{margin:0 0 16px}
.scene-state{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px}
.state-summary,.state-updated{color:var(--el-text-color-secondary);font-size:13px}
.state-updated{margin-left:auto}
.action-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}
.hint{color:var(--el-text-color-secondary)}
.el-alert{margin-bottom:16px}
.tag-gap{margin-left:0}
.import-card{border:1px solid var(--el-color-primary-light-5);background:color-mix(in srgb,var(--el-color-primary) 10%,var(--el-bg-color));color:var(--el-text-color-primary);border-radius:4px;padding:16px 20px;margin:8px 0 20px}
.import-card h3{margin:0 0 12px;font-size:16px}
.scene-files{margin-top:8px}
</style>
