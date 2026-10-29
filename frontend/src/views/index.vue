<template>
  <div class="app-container home-page">
    <section class="hero" aria-labelledby="home-title">
      <div class="hero-text">
        <p class="eyebrow">4DGS 场景成品管理</p>
        <h1 id="home-title">把一个 4DGS 成品，发布给客户端</h1>
        <p class="lead">导入资源目录，校验入库，发布为场景的当前版本。客户端只会读到已发布的版本。</p>
        <el-button v-if="canOpen(entries[0])" type="primary" size="large" @click="router.push(entries[0].path)">进入场景管理</el-button>
      </div>
      <svg class="hero-art" viewBox="0 0 220 160" role="img" aria-label="一个场景，含多个画质档位和分段模型" focusable="false">
        <ellipse cx="110" cy="136" rx="82" ry="14" class="art-floor" />
        <ellipse cx="110" cy="136" rx="54" ry="8.5" class="art-floor art-floor-inner" />
        <g class="art-stack">
          <rect x="62" y="82" width="96" height="30" rx="9" class="art-layer art-layer-3" />
          <rect x="62" y="62" width="96" height="30" rx="9" class="art-layer art-layer-2" />
          <rect x="62" y="42" width="96" height="30" rx="9" class="art-layer art-layer-1" />
        </g>
        <g class="art-dots">
          <circle cx="78" cy="57" r="3" /><circle cx="90" cy="57" r="3" /><circle cx="102" cy="57" r="3" />
          <circle cx="78" cy="77" r="3" /><circle cx="90" cy="77" r="3" />
          <circle cx="78" cy="97" r="3" />
        </g>
        <path d="M110 36V16m0 0-7 7m7-7 7 7" class="art-arrow" />
      </svg>
    </section>

    <section aria-labelledby="guide-title">
      <h2 id="guide-title">四步完成一次发布</h2>
      <ol class="flow">
        <li v-for="(step, index) in steps" :key="step.title" class="flow-step" :class="{ 'is-final': index === steps.length - 1 }">
          <div class="flow-badge">
            <svg viewBox="0 0 48 48" class="flow-icon" aria-hidden="true" focusable="false" v-html="step.icon"></svg>
            <span class="flow-number">{{ index + 1 }}</span>
          </div>
          <h3>{{ step.title }}</h3>
          <p>{{ step.description }}</p>
          <p class="flow-where"><span>在哪里</span>{{ step.path }}</p>
        </li>
      </ol>
    </section>

    <aside class="notice" role="note">
      <svg viewBox="0 0 24 24" class="notice-icon" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="9.25" fill="none" stroke="currentColor" stroke-width="1.6" />
        <path d="M12 7.5v5.5M12 16.4v.1" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </svg>
      <ul>
        <li>文件全部入库后，还需要点“发布”，客户端才读得到。</li>
        <li>版本创建后内容固定；要更新资源，导入新版本再发布。</li>
        <li>同一场景只有一个当前发布版本。</li>
      </ul>
    </aside>

    <section v-if="visibleEntries.length" aria-labelledby="entry-title">
      <h2 id="entry-title">常用入口</h2>
      <div class="entry-grid">
        <a v-for="entry in visibleEntries" :key="entry.path" class="entry" :href="router.resolve(entry.path).href" @click.prevent="router.push(entry.path)">
          <span class="entry-title">{{ entry.title }}</span>
          <span class="entry-desc">{{ entry.description }}</span>
          <svg viewBox="0 0 24 24" class="entry-arrow" aria-hidden="true" focusable="false"><path d="M5 12h14m0 0-5-5m5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </a>
      </div>
    </section>
  </div>
</template>

<script setup name="Index">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import auth from '@/plugins/auth'

const router = useRouter()
const entries = [
  { title: '场景管理', path: '/admin/scenes', permission: 'ar:scene:list', description: '新建场景，进入“版本与文件”' },
  { title: '账号管理', path: '/account/accounts', permission: 'system:user:list', description: '团队账号、状态和密码' },
  { title: '场景操作记录', path: '/admin/audits', permission: 'ar:audit:list', description: '谁在什么时候改了什么' }
]
// 与现有权限工具及服务端下发的动态路由保持一致。
function canOpen(entry) {
  return auth.hasPermi(entry.permission) && router.getRoutes().some(route => route.path === entry.path)
}
const visibleEntries = computed(() => entries.filter(canOpen))
// 线性图标，统一 48x48、1.8 描边、currentColor，随主题取色。
const stroke = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
const steps = [
  {
    title: '选一个场景',
    description: '一个场景就是一个独立的成品。没有就先新建。',
    path: '场景管理 → 场景列表',
    icon: `<g ${stroke}><path d="M24 6 7 15v18l17 9 17-9V15z"/><path d="M7 15l17 9 17-9M24 24v18"/></g>`
  },
  {
    title: '导入资源目录',
    description: '选根目录带 resource.json 的文件夹，确认档位和文件数后开始。',
    path: '该行的“版本与文件” → 导入资源目录',
    icon: `<g ${stroke}><path d="M6 14a3 3 0 0 1 3-3h10l4 5h16a3 3 0 0 1 3 3v17a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3z"/><path d="M24 33V22m0 0-5 5m5-5 5 5"/></g>`
  },
  {
    title: '等文件校验入库',
    description: '逐个文件上传并校验。中断了就点“继续上传”，已入库的不会重传。',
    path: '版本详情 → 继续上传',
    icon: `<g ${stroke}><path d="M24 6 9 12v11c0 9 6 16 15 19 9-3 15-10 15-19V12z"/><path d="m17 24 5 5 9-10"/></g>`
  },
  {
    title: '发布版本',
    description: '全部就绪后点“发布”，客户端从这一刻起读到它。',
    path: '版本列表 → 发布 / 替换发布',
    icon: `<g ${stroke}><path d="M24 4c6 5 9.5 12 9.5 20.5V32h-19v-7.5C14.5 16 18 9 24 4z"/><circle cx="24" cy="19.5" r="3.4"/><path d="M14.5 26 8.5 33v6l6-3.2M33.5 26l6 7v6l-6-3.2"/><path d="M20 36.5c0 3 1.7 5.5 4 7.5 2.3-2 4-4.5 4-7.5"/></g>`
  }
]
</script>

<style scoped>
.home-page {
  display: grid;
  gap: 32px;
  width: 100%;
  color: var(--el-text-color-primary);
  line-height: 1.7;
  overflow-wrap: anywhere;
}
h1, h2, h3 { margin: 0; line-height: 1.35; }
h2 { font-size: 20px; margin-bottom: 18px; }
h3 { font-size: 16px; margin-bottom: 6px; }
p { margin: 0; color: var(--el-text-color-regular); }

/* 英雄区：一句话说明 + 主按钮 */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) clamp(220px, 28%, 340px);
  align-items: center;
  gap: 24px;
  padding: 36px 44px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 16px;
  background: linear-gradient(135deg, color-mix(in srgb, var(--el-color-primary) 11%, var(--el-bg-color)), var(--el-bg-color) 70%);
}
.eyebrow { font-size: 13px; font-weight: 600; letter-spacing: .08em; color: var(--el-color-primary); margin-bottom: 8px; }
.hero h1 { font-size: clamp(28px, 2.2vw, 36px); margin-bottom: 12px; }
.lead { margin-bottom: 24px; max-width: 36em; font-size: 15px; }
.hero-art { width: 100%; height: auto; color: var(--el-color-primary); }
.art-floor { fill: none; stroke: currentColor; stroke-opacity: .22; stroke-width: 1.4; }
.art-floor-inner { stroke-opacity: .35; }
.art-layer { fill: var(--el-bg-color); stroke: currentColor; stroke-width: 1.8; }
.art-layer-1 { fill: color-mix(in srgb, currentColor 18%, var(--el-bg-color)); }
.art-layer-2 { fill: color-mix(in srgb, currentColor 9%, var(--el-bg-color)); stroke-opacity: .75; }
.art-layer-3 { stroke-opacity: .5; }
.art-dots circle { fill: currentColor; opacity: .55; }
.art-arrow { fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

/* 四步流程：横向串联，末步强调 */
.flow { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 20px; counter-reset: none; }
.flow-step {
  position: relative;
  padding: 20px 18px 18px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  background: var(--el-bg-color);
}
.flow-step:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 44px;
  left: calc(100% + 1px);
  width: 18px;
  height: 2px;
  background: repeating-linear-gradient(90deg, var(--el-color-primary) 0 4px, transparent 4px 7px);
}
.flow-badge { position: relative; width: 56px; height: 56px; margin-bottom: 14px; }
.flow-icon {
  width: 56px; height: 56px; padding: 10px; box-sizing: border-box;
  border-radius: 14px;
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 12%, var(--el-bg-color));
}
.flow-number {
  position: absolute; top: -8px; right: -8px;
  width: 24px; height: 24px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700;
  color: #fff; background: var(--el-color-primary);
  box-shadow: 0 0 0 3px var(--el-bg-color);
}
.flow-step p { font-size: 14px; }
.flow-where {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color);
  font-size: 12.5px !important;
  color: var(--el-text-color-secondary) !important;
}
.flow-where span {
  display: inline-block; margin-right: 6px; padding: 0 6px;
  border-radius: 4px; font-size: 12px; font-weight: 600;
  color: var(--el-color-primary); background: color-mix(in srgb, var(--el-color-primary) 12%, var(--el-bg-color));
}
.flow-step.is-final { border-color: var(--el-color-primary); box-shadow: 0 6px 20px color-mix(in srgb, var(--el-color-primary) 16%, transparent); }
.flow-step.is-final .flow-icon { color: #fff; background: var(--el-color-primary); }
.flow-step.is-final .flow-number { background: var(--el-color-success); }

/* 提示条 */
.notice {
  display: flex; gap: 14px; align-items: flex-start;
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid var(--el-color-warning-light-5);
  background: color-mix(in srgb, var(--el-color-warning) 9%, var(--el-bg-color));
  color: var(--el-text-color-primary);
}
.notice-icon { flex: none; width: 22px; height: 22px; margin-top: 2px; color: var(--el-color-warning); }
.notice ul { margin: 0; padding-left: 18px; color: var(--el-text-color-regular); }
.notice li + li { margin-top: 2px; }

/* 常用入口 */
.entry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 14px; }
.entry {
  position: relative; display: grid; gap: 2px;
  padding: 16px 44px 16px 18px;
  border: 1px solid var(--el-border-color-light); border-radius: 12px;
  color: inherit; text-decoration: none; background: var(--el-bg-color);
  transition: border-color .15s, transform .15s;
}
.entry:hover, .entry:focus-visible { border-color: var(--el-color-primary); transform: translateY(-1px); outline: none; }
.entry-title { font-weight: 600; font-size: 15px; }
.entry-desc { font-size: 13px; color: var(--el-text-color-secondary); }
.entry-arrow { position: absolute; right: 16px; top: 50%; width: 20px; height: 20px; margin-top: -10px; color: var(--el-color-primary); }

/* 中等宽度：流程两列；窄屏：竖排并把连线改为竖向 */
@media (max-width: 1100px) {
  .flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .flow-step:nth-child(2)::after { display: none; }
}
@media (max-width: 720px) {
  .home-page { padding: 16px; gap: 24px; }
  .hero { grid-template-columns: 1fr; padding: 24px 20px; }
  .hero-art { display: none; }
  .hero h1 { font-size: 24px; }
  .flow { grid-template-columns: 1fr; gap: 26px; }
  .flow-step:not(:last-child)::after {
    top: calc(100% + 1px); left: 36px; width: 2px; height: 24px;
    background: repeating-linear-gradient(180deg, var(--el-color-primary) 0 4px, transparent 4px 7px);
  }
  .flow-step:nth-child(2)::after { display: block; }
}
</style>
