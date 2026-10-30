// 资源选择解析：目录以所选目录为根，文件以文件名为相对路径；全部原样上传。
// 纯函数、不依赖浏览器或 Vue；服务端才是最终校验边界，
// 这里只做上传前的快速检查，路径规则与后端 RelativePath 保持一致。

const MAX_PATH = 1024
const MAX_SEGMENT = 255
const MAX_DEPTH = 32
const RESERVED = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$/i

export class PackageError extends Error {
  constructor(message) {
    super(message)
    this.name = 'PackageError'
  }
}

function fail(message) { throw new PackageError(message) }

export function normalizePath(raw) {
  if (typeof raw !== 'string' || raw === '') fail('相对路径不能为空')
  if (raw.includes('\0')) fail('相对路径不能包含空字符')
  if (raw.length > MAX_PATH) fail('相对路径过长')
  if (raw.startsWith('/') || raw.startsWith('\\') || /^\p{L}:/u.test(raw)) fail('相对路径不能为绝对路径')
  if (raw.includes('\\')) fail('相对路径不能包含反斜杠')
  const path = raw.normalize('NFC')
  if (path.startsWith('/') || path.endsWith('/') || path.includes('//')) fail('相对路径格式不合法')
  const parts = path.split('/')
  if (parts.length > MAX_DEPTH) fail('相对路径层级不合法')
  for (const part of parts) validateSegment(part)
  return path
}

function validateSegment(segment) {
  if (segment === '') fail('相对路径含有空片段')
  if (segment.length > MAX_SEGMENT) fail('路径片段过长')
  if (segment === '.' || segment === '..') fail('相对路径不能包含越界片段')
  if (segment.startsWith(' ') || segment.endsWith(' ') || segment.endsWith('.')) fail('路径片段不能以空格开头，也不能以空格或点号结尾')
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f<>:"|?*]/.test(segment)) fail('路径包含不能安全还原的字符')
  if (RESERVED.test(segment)) fail('路径包含目标环境保留名称')
}

/** 逐个规范化并检查重复、大小写冲突、文件与目录同名冲突；返回规范化后的路径，顺序同输入。 */
export function normalizePaths(paths) {
  const result = paths.map(normalizePath)
  const seen = new Set()
  const seenLower = new Set()
  for (const path of [...result].sort()) {
    if (seen.has(path)) fail(`相对路径重复：${path}`)
    seen.add(path)
    const lower = path.toLowerCase()
    if (seenLower.has(lower)) fail(`相对路径存在规范化或大小写冲突：${path}`)
    seenLower.add(lower)
  }
  const folded = result.map(path => path.toLowerCase()).sort()
  for (let i = 0; i < folded.length; i++) {
    for (let j = i + 1; j < folded.length; j++) {
      if (!folded[j].startsWith(folded[i])) break
      if (folded[j].startsWith(folded[i] + '/')) fail(`文件与目录路径冲突：${folded[i]}`)
    }
  }
  return result
}

/** 目录选择结果 -> [{relativePath(去掉顶层目录名), file}]；所有文件必须来自同一个顶层目录。 */
export function rootEntries(files) {
  const list = Array.from(files)
  if (list.length === 0) fail('所选目录为空，没有可上传的文件')
  let top = null
  return list.map(file => {
    const full = file.webkitRelativePath
    const slash = typeof full === 'string' ? full.indexOf('/') : -1
    if (slash <= 0) fail('请选择资源目录，而不是单个文件')
    const name = full.slice(0, slash)
    if (top === null) top = name
    else if (name !== top) fail('所选文件不属于同一个目录')
    return { relativePath: full.slice(slash + 1).normalize('NFC'), file }
  })
}

/** mode 显式区分目录与文件选择；默认保留现有目录调用行为，不读取或解压文件内容。 */
export async function readPackage(files, { mode = 'directory' } = {}) {
  let entries
  if (mode === 'directory') entries = rootEntries(files)
  else if (mode === 'files') {
    entries = Array.from(files, file => ({ relativePath: file.name, file }))
    if (!entries.length) fail('未选择可上传的文件')
    for (const entry of entries) {
      if (typeof entry.relativePath === 'string' && /[/\\]/.test(entry.relativePath)) fail('文件名不能包含路径分隔符')
    }
  } else fail('未知的资源选择模式')
  const paths = normalizePaths(entries.map(entry => entry.relativePath))
  entries.forEach((entry, index) => { entry.relativePath = paths[index] })
  const sorted = entries
    .map(({ relativePath, file }) => ({ relativePath, file, bytes: file.size }))
    .sort((a, b) => (a.relativePath < b.relativePath ? -1 : a.relativePath > b.relativePath ? 1 : 0))
  const empty = sorted.find(item => item.bytes === 0)
  if (empty) fail(`空文件无法上传：${empty.relativePath}`)
  return { files: sorted, totalBytes: sorted.reduce((sum, item) => sum + item.bytes, 0) }
}

/** 本地数量/大小上限检查；服务端对同一上限返回 413。 */
export function checkLimits(pkg, { maxBytes, versionMaxFiles, versionMaxBytes }) {
  if (pkg.files.length > versionMaxFiles) fail(`文件数量 ${pkg.files.length} 超过每个版本 ${versionMaxFiles} 个的上限`)
  const oversize = pkg.files.find(item => item.bytes > maxBytes)
  if (oversize) fail(`${oversize.relativePath} 超过单文件大小上限`)
  if (pkg.totalBytes > versionMaxBytes) fail('文件总大小超过每个版本的上限')
}

function digestOf(digests, relativePath) {
  const digest = digests.get(relativePath)
  if (!digest) fail(`缺少 ${relativePath} 的 SHA-256`)
  return digest
}

/** 创建版本请求体：files 为目录下全部文件的路径/大小/摘要。digests: Map(relativePath -> sha256)。 */
export function createRequest(pkg, digests, { requestKey, description }) {
  return {
    requestKey,
    description,
    files: pkg.files.map(item => ({ relativePath: item.relativePath, bytes: item.bytes, sha256: digestOf(digests, item.relativePath) }))
  }
}

/** 重新选择资源后，先不看摘要：路径集合和大小必须与已固定的版本一致。 */
export function checkSelection(pkg, version) {
  const fixed = new Map(version.files.map(item => [item.relativePath, item]))
  for (const item of pkg.files) {
    const expected = fixed.get(item.relativePath)
    if (!expected) fail(`${item.relativePath} 不在该版本的文件清单中`)
    if (expected.bytes !== item.bytes) fail(`${item.relativePath} 的大小与该版本登记的不一致`)
  }
  if (fixed.size !== pkg.files.length) {
    const present = new Set(pkg.files.map(item => item.relativePath))
    fail(`所选资源缺少该版本登记的文件：${[...fixed.keys()].find(path => !present.has(path))}`)
  }
}

/** 摘要计算完成后，逐文件与固定清单比较。 */
export function checkDigests(pkg, digests, version) {
  const fixed = new Map(version.files.map(item => [item.relativePath, item]))
  for (const item of pkg.files) {
    if (digestOf(digests, item.relativePath) !== fixed.get(item.relativePath).sha256) {
      fail(`${item.relativePath} 的内容与该版本登记的 SHA-256 不一致，请选择原文件或原目录`)
    }
  }
}

/** 按文件状态规划上传：AVAILABLE 跳过，UPLOADING 处理中不重复发送，FAILED/PENDING 完整重传。 */
export function uploadPlan(versionFiles) {
  const plan = { upload: [], processing: [], done: 0 }
  for (const file of versionFiles) {
    if (file.status === 'AVAILABLE') plan.done++
    else if (file.status === 'UPLOADING') plan.processing.push(file)
    else plan.upload.push(file)
  }
  const byPath = (a, b) => (a.relativePath < b.relativePath ? -1 : a.relativePath > b.relativePath ? 1 : 0)
  plan.upload.sort(byPath)
  plan.processing.sort(byPath)
  return plan
}

/** 网页上传固定三路，不依赖 HTTP/2 的复用能力。 */
export const UPLOAD_CONCURRENCY = 3

/**
 * 以至多 limit 个并发执行 upload(record)。单个失败不影响其余记录；stopped() 为真后不再派发新记录，在途的照常完成。
 * 返回按 records 原顺序排列的失败 [{ record, error }]。
 */
export async function runUploads(records, limit, upload, stopped) {
  const failures = []
  let next = 0
  async function lane() {
    while (next < records.length && !stopped()) {
      const index = next++
      try { await upload(records[index]) } catch (error) { failures.push({ index, record: records[index], error }) }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, records.length) }, lane))
  return failures.sort((a, b) => a.index - b.index).map(({ record, error }) => ({ record, error }))
}
