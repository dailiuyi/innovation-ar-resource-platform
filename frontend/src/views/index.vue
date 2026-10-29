<template>
  <div class="app-container home-page">
    <el-card shadow="never" class="intro-card">
      <h1>innovation-ar-resource-platform</h1>
      <p>管理 4DGS 场景成品、导入并校验资源目录、发布场景版本，以及管理团队账号和查看操作记录。</p>
      <el-button v-if="canOpen(entries[0])" type="primary" @click="router.push(entries[0].path)">进入场景管理</el-button>
    </el-card>

    <section aria-labelledby="guide-title">
      <h2 id="guide-title">操作步骤</h2>
      <ol class="step-grid">
        <li v-for="(step, index) in steps" :key="step.title">
          <el-card shadow="never" class="step-card">
            <span class="step-number" aria-hidden="true">{{ index + 1 }}</span>
            <h3>{{ step.title }}</h3>
            <p>{{ step.description }}</p>
            <p class="operation-path"><strong>操作位置：</strong>{{ step.path }}</p>
          </el-card>
        </li>
      </ol>
    </section>

    <section v-if="visibleEntries.length" aria-labelledby="entry-title">
      <h2 id="entry-title">常用入口</h2>
      <div class="entry-grid">
        <el-card v-for="entry in visibleEntries" :key="entry.path" shadow="never">
          <el-link :href="router.resolve(entry.path).href" :underline="'hover'" @click.prevent="router.push(entry.path)">{{ entry.title }} →</el-link>
          <p>{{ entry.description }}</p>
        </el-card>
      </div>
    </section>

    <el-card shadow="never" class="notes-card">
      <h2>发布前请留意</h2>
      <ul>
        <li>目录文件全部校验入库后，还需要执行版本发布。</li>
        <li>同一场景只有一个当前发布版本。</li>
        <li>版本创建后描述和文件固定；更新资源需要导入新版本再发布。</li>
        <li>当前后台发布不代表客户端已经下载或加载资源。</li>
      </ul>
    </el-card>
  </div>
</template>

<script setup name="Index">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import auth from '@/plugins/auth'

const router = useRouter()
const entries = [
  { title: '场景管理', path: '/admin/scenes', permission: 'ar:scene:list', description: '维护场景信息；列表每行分别提供“场景信息”和“版本与文件”入口。' },
  { title: '账号管理', path: '/account/accounts', permission: 'system:user:list', description: '管理团队账号、账号状态和密码。' },
  { title: '场景操作记录', path: '/admin/audits', permission: 'ar:audit:list', description: '查看场景、版本和文件的操作记录。' }
]
// 与现有权限工具及服务端下发的动态路由保持一致。
function canOpen(entry) {
  return auth.hasPermi(entry.permission) && router.getRoutes().some(route => route.path === entry.path)
}
const visibleEntries = computed(() => entries.filter(canOpen))
const steps = [
  { title: '选择场景', description: '每个场景是一个独立的 4DGS 成品；进入场景管理，从列表的“场景信息”修改名称，或进入“版本与文件”。', path: '场景管理 → 场景列表' },
  { title: '导入资源目录', description: '在“版本与文件”面板点击“导入资源目录”，选择根目录含 resource.json 的成品目录，确认档位和文件总量后开始导入。', path: '场景列表的“版本与文件” → 导入资源目录' },
  { title: '上传并检查文件', description: '文件按目录逐个上传并校验入库；中断后点击“继续上传”重新选择同一目录，已入库的文件不会重复传输。', path: '版本与文件 → 版本详情的“继续上传”' },
  { title: '发布版本', description: '全部文件就绪后发布该版本，或替换该场景当前发布版本。', path: '版本与文件 → 版本列表的“发布”或“替换发布”' }
]
</script>

<style scoped>
.home-page {
  display: grid;
  gap: 24px;
  color: var(--el-text-color-primary);
  line-height: 1.7;
  overflow-wrap: anywhere;
}
h1, h2, h3 { margin: 0 0 12px; line-height: 1.4; }
h1 { font-size: 28px; }
h2 { font-size: 20px; }
h3 { font-size: 17px; }
p { margin: 0; color: var(--el-text-color-regular); }
.intro-card { border-top: 3px solid var(--el-color-primary); }
.intro-card p { margin-bottom: 20px; }
.step-grid, .entry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 16px;
}
.step-grid { list-style: none; padding: 0; margin: 0; }
.step-grid li, .entry-grid > * { min-width: 0; }
.step-card { height: 100%; }
.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-bottom: 12px;
  border-radius: 50%;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
}
.operation-path { margin-top: 16px; font-size: 13px; }
.entry-grid .el-link { font-size: 16px; font-weight: 600; }
.entry-grid p { margin-top: 8px; font-size: 14px; }
.notes-card ul { margin: 0; padding-left: 22px; color: var(--el-text-color-regular); }
.notes-card li + li { margin-top: 6px; }
@media (max-width: 600px) {
  .home-page { padding: 16px; gap: 20px; }
}
</style>
