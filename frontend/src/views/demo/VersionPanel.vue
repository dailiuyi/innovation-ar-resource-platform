<template>
  <el-drawer :model-value="!!sceneId" :title="sceneName?'版本与文件 · '+sceneName:'版本与文件'" size="90%" :close-on-click-modal="false" :before-close="close">
    <p>所属场景：{{sceneName||sceneId||''}}<span v-if="sceneName">（编号 {{sceneId}}）</span></p>
    <p>每个场景是一个独立的 4DGS 成品。版本创建后说明之外的文件清单固定；需要改变模型、配置或路径时导入新版本，再发布切换。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <div v-if="error" class="action-row">
      <el-button :disabled="busy" @click="refresh">刷新状态</el-button>
      <el-button v-if="session" type="primary" :disabled="busy" @click="runSession">继续上传</el-button>
    </div>
    <section class="published-card" :class="{empty:!published}">
      <div class="published-head">
        <h3>当前发布版本</h3>
        <el-tag v-if="published" type="success">已发布</el-tag>
      </div>
      <template v-if="published">
        <p><span class="meta-label">版本</span>v{{published.versionNo}}　{{published.description || '（无说明）'}}</p>
        <p><span class="meta-label">发布</span>{{formatTime(published.publishedAt)}}，{{published.publishedByName}}</p>
        <p class="published-note">已发布版本的文件清单固定，仅可修改说明；导入新版本不会改变它。</p>
        <el-button link type="primary" @click="selectVersion(published.id)">查看详情</el-button>
      </template>
      <p v-else class="published-empty">该场景尚未发布</p>
    </section>
    <div class="action-row">
      <el-button type="primary" :disabled="busy||removing" @click="chooseDirectory">导入资源目录</el-button>
      <el-button :disabled="busy||removing" @click="refresh">刷新</el-button>
      <el-button v-if="busy" type="warning" @click="cancel">停止本次传输</el-button>
      <span class="hint">所选目录下的全部文件都会上传；单文件上限 {{size(config.maxBytes)}}，每个版本最多 {{config.versionMaxFiles}} 个文件 / {{size(config.versionMaxBytes)}}。</span>
      <input ref="picker" type="file" webkitdirectory directory multiple hidden @change="picked" />
    </div>
    <section v-if="importPlan" class="import-card">
      <h3>待导入：{{importPlan.pkg.files.length}} 个文件，共 {{size(importPlan.pkg.totalBytes)}}</h3>
      <el-form inline @submit.prevent="startImport">
        <el-form-item label="版本说明"><el-input v-model="importPlan.description" maxlength="2000" placeholder="可留空" style="width:320px" /></el-form-item>
        <el-form-item>
          <el-button type="primary" @click="startImport">开始导入</el-button>
          <el-button @click="importPlan=null">放弃</el-button>
        </el-form-item>
      </el-form>
    </section>
    <p v-if="progressText" role="status">{{progressText}}</p>
    <el-progress v-if="busy" :percentage="progress" />
    <el-table v-if="uploadIssues.length" :data="uploadIssues" row-key="relativePath" max-height="280">
      <el-table-column prop="relativePath" label="文件" min-width="260" show-overflow-tooltip />
      <el-table-column prop="kind" label="结果" width="110" />
      <el-table-column prop="reason" label="原因" min-width="300" />
    </el-table>
    <el-table :data="versions" highlight-current-row :current-row-key="selected?.id" row-key="id">
      <el-table-column label="版本" width="70"><template #default="{row}">v{{row.versionNo}}</template></el-table-column>
      <el-table-column prop="description" label="版本说明" min-width="100" show-overflow-tooltip />
      <el-table-column label="状态" width="200"><template #default="{row}"><el-tag :type="statusType(row.uploadStatus)">{{uploadStates[row.uploadStatus]}}</el-tag><el-tag v-if="row.published" type="success" class="tag-gap">当前发布</el-tag></template></el-table-column>
      <el-table-column label="文件" width="110"><template #default="{row}">{{row.availableCount}} / {{row.fileCount}}<span v-if="row.failedCount">，失败 {{row.failedCount}}</span></template></el-table-column>
      <el-table-column label="总大小" width="90"><template #default="{row}">{{size(row.totalBytes)}}</template></el-table-column>
      <el-table-column label="创建时间" width="140"><template #default="{row}">{{formatTime(row.createdAt)}}</template></el-table-column>
      <el-table-column label="操作" width="200"><template #default="{row}">
        <el-button link type="primary" :disabled="busy||removing" @click="selectVersion(row.id)">查看</el-button>
        <el-button v-if="row.published" link disabled>当前发布</el-button>
        <el-button v-else link type="primary" :disabled="busy||removing||publishing||row.uploadStatus!=='READY'" @click="publish(row)">{{published?'替换发布':'发布'}}</el-button>
        <el-button link type="danger" :disabled="busy||removing||row.published" @click="remove(row)">{{retryDelete(row)?'重试删除':'删除'}}</el-button>
      </template></el-table-column>
    </el-table>
    <pagination v-show="total>20" :total="total" v-model:page="page" :limit="20" @pagination="reloadList" />
    <section v-if="selected" class="version-detail">
      <h3>v{{selected.versionNo}} 详情 · {{selected.id}}</h3>
      <el-alert v-if="selected.published" title="当前为发布版本，文件清单固定，仅可修改说明" type="info" :closable="false" />
      <el-alert v-if="selected.uploadStatus==='DELETE_FAILED'" title="整版删除失败，版本已保留；请点击“重试删除”" type="warning" :closable="false" />
      <p>状态：<el-tag :type="statusType(selected.uploadStatus)">{{uploadStates[selected.uploadStatus]}}</el-tag>　已入库 {{selected.availableCount}} / {{selected.fileCount}}，失败 {{selected.failedCount}}，共 {{size(selected.totalBytes)}}</p>
      <el-form inline @submit.prevent="saveDescription">
        <el-form-item label="版本说明"><el-input v-model="editDescription" maxlength="2000" :disabled="busy||removing" style="width:320px" /></el-form-item>
        <el-form-item><el-button type="primary" :disabled="busy||removing" :loading="saving" @click="saveDescription">保存说明</el-button></el-form-item>
      </el-form>
      <div class="action-row">
        <el-button v-if="canResume&&sessionForSelected" type="primary" :disabled="busy" @click="runSession">继续上传</el-button>
        <el-button v-if="canResume" :type="sessionForSelected?'default':'primary'" :disabled="busy" @click="chooseFor(selected.id)">{{sessionForSelected?'重新选择目录':'继续上传'}}</el-button>
        <span v-if="canResume" class="hint">继续上传需要选择同一个资源目录；已入库的文件不会重复传输。</span>
        <el-button v-if="!selected.published" type="primary" :disabled="busy||removing||publishing||selected.uploadStatus!=='READY'" @click="publish(selected)">{{published?'替换发布':'发布'}}</el-button>
        <el-button type="danger" plain :disabled="busy||removing||selected.published" @click="remove(selected)">{{retryDelete(selected)?'重试删除':'删除整个版本'}}</el-button>
      </div>
      <el-table :data="selected.files" size="small" row-key="fileId">
        <el-table-column type="expand"><template #default="{row}"><file-detail :file="row" /></template></el-table-column>
        <el-table-column prop="relativePath" label="文件" min-width="280" show-overflow-tooltip />
        <el-table-column label="大小" width="110"><template #default="{row}">{{size(row.bytes)}}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="fileType(row.status)">{{fileStates[row.status]}}</el-tag></template></el-table-column>
        <el-table-column label="错误" min-width="180" show-overflow-tooltip><template #default="{row}">{{row.failureReason}}</template></el-table-column>
      </el-table>
    </section>
  </el-drawer>
</template>
<script setup>
import { computed, defineComponent, h, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createVersion, deleteVersion, getScene, getVersion, getVersionConfig, getVersionFile, listVersions, publishVersion, updateVersion, uploadVersionFile } from '@/api/scene'
import { PackageError, UPLOAD_CONCURRENCY, checkDigests, checkLimits, checkSelection, createRequest, readPackage, runUploads, uploadPlan } from '@/utils/scenePackage'
const props=defineProps({sceneId:String})
const emit=defineEmits(['close','sceneUpdated'])
const route=useRoute(),router=useRouter()
const PAGE=20
const config=ref({maxBytes:0,versionMaxFiles:0,versionMaxBytes:0})
const versions=ref([]),total=ref(0),page=ref(1),sceneLockVersion=ref(0),published=ref(null),sceneName=ref('')
const selected=ref(null),editDescription=ref('')
const picker=ref(null),importPlan=shallowRef(null),session=shallowRef(null)
const busy=ref(false),saving=ref(false),publishing=ref(false),removing=ref(false)
const error=ref(''),progress=ref(0),progressText=ref('')
const uploadIssues=ref([])
const uploadStates={PENDING:'待上传',UPLOADING:'上传中',FAILED:'有失败',READY:'已就绪',DELETING:'正在删除',DELETE_FAILED:'删除失败'}
const fileStates={PENDING:'待上传',UPLOADING:'处理中',AVAILABLE:'已入库',FAILED:'失败'}
let worker,rejectHash,cancelled=false,runToken=0,resumeId=null
const controllers=new Set()
let sceneRequest=0,listRequest=0,detailRequest=0
const FileDetail=defineComponent({props:{file:Object},setup:props=>()=>
  h('div',{class:'file-detail'},[h('div',['SHA-256：',h('code',{class:'digest'},props.file.sha256)]),h('div',`文件编号 ${props.file.fileId}，上传尝试 ${props.file.attempts} 次，${props.file.bytes} 字节`)])})
const canResume=computed(()=>['PENDING','UPLOADING','FAILED'].includes(selected.value?.uploadStatus))
const sessionForSelected=computed(()=>!!session.value&&session.value.versionId===selected.value?.id)
function randomKey(){
  const b=crypto.getRandomValues(new Uint8Array(16));b[6]=b[6]&15|64;b[8]=b[8]&63|128
  const x=Array.from(b,v=>v.toString(16).padStart(2,'0')).join('')
  return `${x.slice(0,8)}-${x.slice(8,12)}-${x.slice(12,16)}-${x.slice(16,20)}-${x.slice(20)}`
}
function size(n){n=n??0;return n>=1073741824?`${(n/1073741824).toFixed(2)} GiB`:n>=1048576?`${(n/1048576).toFixed(1)} MiB`:`${n} B`}
function message(e){return e.response?.data?.message||e.message||'请求失败，请刷新核对后重试'}
function statusType(s){return s==='READY'?'success':['FAILED','DELETE_FAILED'].includes(s)?'danger':'warning'}
function fileType(s){return s==='AVAILABLE'?'success':s==='FAILED'?'danger':'warning'}
function retryDelete(v){return ['DELETING','DELETE_FAILED'].includes(v.uploadStatus)}
function formatTime(value){
  if(!value) return ''
  const d=new Date(value)
  if(Number.isNaN(d.getTime())) return value
  const p=n=>String(n).padStart(2,'0')
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
async function loadVersions(){
  const sequence=++listRequest,sceneId=props.sceneId
  const r=await listVersions(sceneId,{limit:PAGE,offset:(page.value-1)*PAGE})
  if(sequence!==listRequest||sceneId!==props.sceneId)return
  versions.value=r.items;total.value=r.total;sceneLockVersion.value=r.sceneLockVersion;published.value=r.published??null
}
function reloadList(){loadVersions().catch(e=>{error.value=message(e)})}
async function loadDetail(id){
  const sequence=++detailRequest,sceneId=props.sceneId
  const version=await getVersion(id)
  if(sequence!==detailRequest||sceneId!==props.sceneId)return null
  if(version.sceneId!==sceneId)throw new Error('该版本不属于当前场景，请重新选择')
  selected.value=version;editDescription.value=version.description??''
  return version
}
function setQuery(versionId){
  const query={...route.query,sceneId:props.sceneId}
  if(versionId)query.versionId=versionId;else delete query.versionId
  return router.replace({query})
}
async function selectVersion(id){
  selected.value=null
  try{
    const version=await loadDetail(id)
    if(!version)return null
    await setQuery(id)
    return version
  }catch(e){error.value=message(e);return null}
}
async function selectInitial(restored){
  if(restored){
    if(await selectVersion(restored))return
    error.value=''
  }
  const latest=versions.value.reduce((best,item)=>!best||item.versionNo>best.versionNo?item:best,null)
  const initial=published.value?.id??latest?.id
  if(initial)await selectVersion(initial);else await setQuery(null)
}
// reload 保留已显示的错误；refresh 是用户主动“刷新状态”，先清掉旧错误。
async function refresh(){
  error.value=''
  await reload()
}
async function reload(){
  try{
    await loadVersions()
    if(selected.value)await loadDetail(selected.value.id)
  }catch(e){error.value=message(e)}
}
async function saveDescription(){
  saving.value=true
  try{
    await updateVersion(selected.value.id,{description:editDescription.value,expectedVersion:selected.value.lockVersion})
    await refresh();ElMessage.success('说明已保存')
  }catch(e){error.value=message(e);if(e.response?.status===409)await reload()}
  finally{saving.value=false}
}
async function publish(version){
  const sequence=sceneRequest
  publishing.value=true
  try{
    const current=published.value
    await ElMessageBox.confirm(
      current
        ? `当前发布版本是 v${current.versionNo}。确认将 v${version.versionNo} 切换为该场景的当前发布版本吗？原发布版本仍可在后台查看或整版删除，但不再供客户端读取。`
        : `确认将 v${version.versionNo} 发布为该场景的当前发布版本吗？发布后文件清单固定，仅可修改说明。`,
      current?'替换发布版本':'发布版本',
      {confirmButtonText:current?'确认替换':'确认发布',cancelButtonText:'取消',type:'warning',closeOnClickModal:false})
    if(sequence!==sceneRequest)return
    await publishVersion(version.id,sceneLockVersion.value)
    if(sequence!==sceneRequest)return
    await loadVersions()
    if(sequence!==sceneRequest)return
    await selectVersion(published.value?.id??version.id)
    emit('sceneUpdated')
    ElMessage.success(current?'已替换发布版本':'已发布')
  }catch(e){if(e!=='cancel'&&e!=='close'){error.value=message(e);if(e.response?.status===409)await loadVersions().catch(()=>{})}}
  finally{publishing.value=false}
}
async function remove(version){
  const sequence=sceneRequest
  removing.value=true
  try{
    await ElMessageBox.confirm(`确认永久删除 v${version.versionNo} 吗？将删除该版本的全部模型和配置文件，无法恢复。操作审计会保留。`,'永久删除版本',{confirmButtonText:'永久删除',cancelButtonText:'取消',type:'warning',closeOnClickModal:false})
    await deleteVersion(version.id)
    if(sequence!==sceneRequest)return
    if(session.value?.versionId===version.id)session.value=null
    const wasSelected=selected.value?.id===version.id
    if(wasSelected){selected.value=null;++detailRequest}
    if(versions.value.length===1&&page.value>1)page.value--
    await loadVersions()
    if(wasSelected&&sequence===sceneRequest)await selectInitial(null)
    ElMessage.success('版本已永久删除')
  }catch(e){
    if(e!=='cancel'&&e!=='close'){error.value=message(e);await reload()}
  }finally{removing.value=false}
}
function chooseDirectory(){resumeId=null;picker.value.value='';picker.value.click()}
function chooseFor(versionId){resumeId=versionId;picker.value.value='';picker.value.click()}
async function picked(event){
  const files=Array.from(event.target.files||[]);if(!files.length)return
  const target=resumeId;resumeId=null
  error.value=''
  try{
    const pkg=await readPackage(files)
    checkLimits(pkg,config.value)
    if(!target){importPlan.value={pkg,description:''};return}
    if(selected.value?.id!==target)return
    checkSelection(pkg,selected.value)
    session.value={sceneId:props.sceneId,versionId:target,pkg,digests:null,expect:selected.value,requestKey:null,description:selected.value.description}
    await runSession()
  }catch(e){error.value=message(e)}
}
async function startImport(){
  const plan=importPlan.value
  if(!plan)return
  importPlan.value=null
  session.value={sceneId:props.sceneId,versionId:null,pkg:plan.pkg,digests:null,expect:null,requestKey:randomKey(),description:plan.description}
  await runSession()
}
function digest(file){
  return new Promise((resolve,reject)=>{
    rejectHash=reject
    worker=new Worker(new URL('./hash.worker.js',import.meta.url),{type:'module'})
    worker.onmessage=({data})=>{
      if(data.error){worker.terminate();reject(new Error(data.error))}
      else if(data.digest){worker.terminate();resolve(data.digest)}
      else progress.value=data.progress
    }
    worker.onerror=()=>reject(new Error('摘要计算失败'))
    worker.postMessage(file)
  })
}
async function hashAll(pkg){
  const digests=new Map()
  for(let i=0;i<pkg.files.length;i++){
    if(cancelled)throw new Error('已取消')
    const item=pkg.files[i]
    progress.value=0;progressText.value=`正在计算 ${i+1}/${pkg.files.length} ${item.relativePath} 的 SHA-256`
    digests.set(item.relativePath,await digest(item.file))
  }
  return digests
}
function cancel(){cancelled=true;worker?.terminate();rejectHash?.(new Error('已取消'));for(const c of controllers)c.abort()}
// 查询失败或服务端仍在处理时，上传结果无法确认；与“请求失败”分开列出。
class UploadUnconfirmedError extends Error {}
// 网关超时、断线或主动取消都不代表服务端失败：先读该文件状态，再决定下一步。
async function reconcile(versionId,record){
  let state
  try{state=await getVersionFile(versionId,record.fileId)}
  catch{throw new UploadUnconfirmedError('上传结果未确认，请刷新状态')}
  if(state.status==='AVAILABLE')return
  if(state.status==='UPLOADING')throw new UploadUnconfirmedError('服务端仍在处理，请稍后点击“刷新状态”')
  throw new Error(`上传未完成${state.failureReason?'：'+state.failureReason:''}，可继续上传`)
}
async function uploadOne(versionId,record,file,onProgress){
  const controller=new AbortController()
  controllers.add(controller)
  try{
    const result=await uploadVersionFile(versionId,record.fileId,file,{signal:controller.signal,onUploadProgress:e=>onProgress(Math.min(e.loaded,file.size))})
    if(result.status==='AVAILABLE')return
  }catch(e){
    if(e.response&&![502,504].includes(e.response.status))throw e
  }finally{controllers.delete(controller)}
  await reconcile(versionId,record)
}
async function runSession(){
  const s=session.value
  if(!s)return
  const token=++runToken
  const live=()=>token===runToken
  busy.value=true;cancelled=false;error.value='';uploadIssues.value=[]
  try{
    if(!s.digests){
      s.digests=await hashAll(s.pkg)
      if(s.expect){checkDigests(s.pkg,s.digests,s.expect);s.expect=null}
    }
    if(cancelled)throw new Error('已取消')
    if(!s.versionId){
      progressText.value='正在创建版本'
      const created=await createVersion(s.sceneId,createRequest(s.pkg,s.digests,{requestKey:s.requestKey,description:s.description}))
      if(!live())return
      s.versionId=created.id
      await loadVersions()
      if(!live())return
      await selectVersion(created.id)
      if(!live())return
    }
    const detail=await getVersion(s.versionId)
    if(!live())return
    if(selected.value?.id===detail.id)selected.value=detail
    const plan=uploadPlan(detail.files)
    const local=new Map(s.pkg.files.map(item=>[item.relativePath,item.file]))
    const totalBytes=detail.files.reduce((n,f)=>n+f.bytes,0)
    let done=plan.done
    let doneBytes=detail.files.filter(f=>f.status==='AVAILABLE').reduce((n,f)=>n+f.bytes,0)
    const sending=new Map()
    // 字节发送百分比不等于入库确认；入库数单独显示。
    const refreshProgress=()=>{
      if(!live())return
      let sent=0
      for(const item of sending.values())sent+=item.loaded
      progress.value=totalBytes?Math.min(100,Math.floor((doneBytes+sent)/totalBytes*100)):100
      const flying=[...sending].map(([path,item])=>item.loaded>=item.bytes?`${path}（等待服务端校验）`:path)
      progressText.value=`已入库 ${done}/${detail.files.length}${flying.length?'；在途：'+flying.join('、'):''}`
    }
    const upload=async record=>{
      const item={loaded:0,bytes:record.bytes}
      sending.set(record.relativePath,item)
      refreshProgress()
      try{
        await uploadOne(s.versionId,record,local.get(record.relativePath),loaded=>{
          item.loaded=loaded
          if(sending.get(record.relativePath)===item)refreshProgress()
        })
        done++;doneBytes+=record.bytes
      }finally{sending.delete(record.relativePath);refreshProgress()}
    }
    const failures=await runUploads(plan.upload,UPLOAD_CONCURRENCY,upload,()=>cancelled||!live())
    if(!live())return
    if(cancelled)throw new Error('已取消')
    const issues=failures.map(({record,error:cause})=>({relativePath:record.relativePath,
      kind:cause instanceof UploadUnconfirmedError?'结果未确认':'请求失败',reason:message(cause)}))
    for(const record of plan.processing)issues.push({relativePath:record.relativePath,kind:'结果未确认',reason:'本轮开始时服务端仍在处理，未重复上传；请刷新确认'})
    uploadIssues.value=issues
    if(issues.length){
      const failed=issues.filter(i=>i.kind==='请求失败').length
      throw new Error(`本轮请求失败 ${failed} 个，结果未确认 ${issues.length-failed} 个。完整列表见下方；刷新状态后继续上传，已入库和处理中不会重复发送。`)
    }
    session.value=null
    progressText.value='全部文件已校验入库，可以发布'
  }catch(e){
    if(!live())return
    if(e instanceof PackageError)session.value=null
    error.value=cancelled?'已停止本次传输，上传结果未确认。已入库的文件会保留；请刷新状态后继续上传':message(e)
    progressText.value='本次操作未确认全部完成'
  }finally{
    if(live()){
      worker?.terminate();rejectHash=null;controllers.clear();busy.value=false
      await reload()
    }
  }
}
function close(done){if(busy.value||removing.value){ElMessage.warning('请等待上传结束或先停止传输');return}emit('close');done?.()}
async function loadSceneName(id,sequence){
  try{
    const scene=await getScene(id)
    if(sequence!==sceneRequest)return
    sceneName.value=scene?.name||''
  }catch{if(sequence===sceneRequest)sceneName.value=''}
}
watch(()=>props.sceneId,async id=>{
  const sequence=++sceneRequest
  ++listRequest;++detailRequest
  cancel();++runToken
  session.value=null;importPlan.value=null;busy.value=false
  selected.value=null;versions.value=[];total.value=0;published.value=null;sceneLockVersion.value=0;page.value=1
  error.value='';progressText.value='';sceneName.value='';uploadIssues.value=[]
  if(!id)return
  loadSceneName(id,sequence)
  const restored=route.query.versionId?String(route.query.versionId):null
  try{
    const cfg=await getVersionConfig()
    if(sequence!==sceneRequest)return
    config.value=cfg
    await loadVersions()
    if(sequence!==sceneRequest)return
    await selectInitial(restored)
  }catch(e){if(sequence===sceneRequest)error.value=message(e)}
},{immediate:true})
onBeforeUnmount(()=>{cancel();++runToken})
</script>
<style scoped>
.version-detail{margin-top:24px}.action-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}.hint{color:var(--el-text-color-secondary)}.el-alert{margin-bottom:16px}
.digest{word-break:break-all}.file-detail{padding:4px 16px;line-height:1.8}.tag-gap{margin-left:8px}
.import-card{border:1px solid var(--el-color-primary-light-5);background:color-mix(in srgb,var(--el-color-primary) 10%,var(--el-bg-color));color:var(--el-text-color-primary);border-radius:4px;padding:16px 20px;margin:8px 0 20px}
.import-card h3{margin:0 0 12px;font-size:16px}
.published-card{border:1px solid var(--el-color-success-light-5);background:color-mix(in srgb,var(--el-color-success) 10%,var(--el-bg-color));color:var(--el-text-color-primary);border-radius:4px;padding:16px 20px;margin:8px 0 20px}
.published-card.empty{border-color:var(--el-border-color-light);background:var(--el-fill-color-light)}
.published-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
.published-card h3{margin:0;font-size:16px}
.published-card p{margin:6px 0}
.meta-label{display:inline-block;width:72px;color:var(--el-text-color-secondary)}
.published-note,.published-empty{color:var(--el-text-color-secondary)}
.published-empty{text-align:center;margin:24px 0}
:deep(.el-table--enable-row-hover .el-table__body tr.current-row>td.el-table__cell),:deep(.el-table__body tr.current-row>td.el-table__cell){background-color:color-mix(in srgb,var(--el-color-primary) 14%,var(--el-bg-color))}
</style>
