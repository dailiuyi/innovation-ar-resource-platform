<template>
  <div class="app-container">
    <h2>场景管理</h2><p>场景列表分别提供“场景信息”和“版本与文件”入口：前者维护名称、地址、坐标，后者直接打开该场景的资源管理面板。点击版本与文件可直接管理该场景资源。</p>
    <el-form inline @submit.prevent="search">
      <el-form-item label="场景名称"><el-input v-model="name" clearable placeholder="搜索场景" /></el-form-item>
      <el-form-item>
        <el-button @click="search">查询</el-button><el-button type="primary" @click="create">新建场景</el-button>
      </el-form-item>
    </el-form>
    <el-table :data="items" v-loading="loading">
      <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="address" label="地址" min-width="320" show-overflow-tooltip />
      <el-table-column label="状态" width="80"><template #default="{row}"><el-tag :type="row.enabled?'success':'info'">{{row.enabled?'启用':'停用'}}</el-tag></template></el-table-column>
      <el-table-column prop="lockVersion" label="修订号" width="80" />
      <el-table-column label="操作" width="300" fixed="right"><template #default="{row}">
        <div class="scene-actions">
          <el-button link type="primary" @click="edit(row)">场景信息</el-button>
          <el-button link type="primary" @click="openDrafts(row)">版本与文件</el-button>
          <el-button link type="warning" @click="toggle(row)">{{row.enabled?'停用':'启用'}}</el-button>
          <el-button link type="danger" :disabled="deleting" @click="remove(row)">删除</el-button>
        </div>
      </template></el-table-column>
    </el-table>
    <pagination v-show="total>0" :total="total" v-model:page="page" v-model:limit="limit" @pagination="load" />
    <el-dialog v-model="visible" :title="form.id?'场景信息':'新建场景'" width="600px" :close-on-click-modal="false">
      <el-form label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" maxlength="200" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" maxlength="1000" /></el-form-item>
        <el-form-item label="经度"><el-input-number v-model="form.longitude" :min="-180" :max="180" :controls="false" /></el-form-item>
        <el-form-item label="纬度"><el-input-number v-model="form.latitude" :min="-90" :max="90" :controls="false" /></el-form-item>
        <el-form-item label="坐标类型"><el-select v-model="form.geoCrs" clearable><el-option v-for="c in ['WGS84','GCJ02','BD09']" :key="c" :value="c" :label="c" /></el-select></el-form-item>
        <el-form-item v-if="form.id" label="场景编号"><span>{{form.id}}</span></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible=false">关闭</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
    <DraftPanel :scene-id="draftScene" @close="closeDrafts" @scene-updated="load" />
  </div>
</template>
<style scoped>
.scene-actions{display:flex;align-items:center;flex-wrap:nowrap;gap:12px}
.scene-actions :deep(.el-button+.el-button){margin-left:0}
</style>
<script setup>
import request from '@/utils/request'
import DraftPanel from './DraftPanel.vue'
import { useRoute, useRouter } from 'vue-router'
const route=useRoute(),router=useRouter()
const draftScene=computed(()=>String(route.query.draftScene||''))
function openDrafts(row){const query={...route.query,draftScene:row.id};delete query.draftId;router.replace({query})}
function closeDrafts(){const query={...route.query};delete query.draftScene;delete query.draftId;router.replace({query});load()}
import { ElMessage, ElMessageBox } from 'element-plus'
const deleting=ref(false)
const items=ref([]),total=ref(0),page=ref(1),limit=ref(20),name=ref(''),loading=ref(false),visible=ref(false),saving=ref(false),form=ref({})
async function load(){loading.value=true;try{const r=await request.get('/api/v1/scenes',{params:{name:name.value,limit:limit.value,offset:(page.value-1)*limit.value}});items.value=r.items;total.value=r.total}finally{loading.value=false}}
function search(){page.value=1;load()}
function create(){form.value={name:'',address:'',longitude:undefined,latitude:undefined,geoCrs:''};visible.value=true}
async function edit(row){form.value=await request.get('/api/v1/scenes/'+row.id);visible.value=true}
async function save(){
  if(!form.value.name?.trim()) return ElMessage.warning('请填写场景名称')
  const s=form.value,lon=s.longitude??null,lat=s.latitude??null
  if((lon===null)!=(lat===null)||lon!==null&&!s.geoCrs) return ElMessage.warning('请同时填写经纬度和坐标类型')
  const data={name:s.name,address:s.address||null,longitude:lon,latitude:lat,geoCrs:lon===null?null:s.geoCrs,expectedVersion:s.lockVersion}
  saving.value=true
  try{await request({url:'/api/v1/scenes'+(s.id?'/'+s.id:''),method:s.id?'put':'post',data});visible.value=false;ElMessage.success('场景已保存');await load()}
  catch(e){if(e.response?.status===409){await load();visible.value=false}}
  finally{saving.value=false}
}
async function toggle(row){
  try{const {value}=await ElMessageBox.prompt('请填写原因','确认'+(row.enabled?'停用':'启用'),{inputValidator:v=>!!v?.trim()||'原因不能为空'});await request.put('/api/v1/scenes/'+row.id+'/enabled',{enabled:!row.enabled,expectedVersion:row.lockVersion,reason:value});ElMessage.success('状态已更新');await load()}
  catch(e){if(e.response?.status===409) await load()}
}
async function remove(row){
  if(deleting.value) return
  deleting.value=true
  try{
    await ElMessageBox.confirm(`确认删除场景“${row.name}”吗？删除后将从列表移除，操作记录仍会保留。`,'删除场景',{
      confirmButtonText:'确认删除',cancelButtonText:'取消',type:'warning',
      closeOnClickModal:false,autofocus:false,confirmButtonClass:'el-button--danger'
    })
    await request.delete('/api/v1/scenes/'+row.id,{params:{expectedVersion:row.lockVersion}})
    ElMessage.success('场景已删除')
    if(items.value.length===1 && page.value>1) page.value--
    await load()
  }catch(e){
    if(e.response?.status===409 || e.response?.status===404) await load()
  }finally{deleting.value=false}
}
load()
</script>
