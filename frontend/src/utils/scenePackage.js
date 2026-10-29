// 成品目录解析：目录归根、resource.json v1 形状检查、描述引用与文件的双向映射。
// 纯函数、不依赖浏览器或 Vue；服务端 ResourceDescriptorValidator 才是最终校验边界，
// 这里只做上传前的快速检查，路径规则与后端 RelativePath 保持一致。

export const DESCRIPTOR_FILE = 'resource.json'
export const VARIANT_FORMAT = '4dv-compressed-ply'
const MAX_PATH = 1024
const MAX_SEGMENT = 255
const MAX_DEPTH = 32
const RESERVED = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$/i
const VARIANT_ID = /^[a-z][a-z0-9_-]{0,63}$/

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

function isObject(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function isVector(value) { return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite) }

/**
 * resource.json v1 的形状检查，错误信息带 JSON 字段位置。
 * 返回按声明顺序排列的引用 [{path, role, field, variantId?}]，同一路径可出现多次；role 取
 * settings/poster/audio/preview/segment。
 */
export function descriptorReferences(descriptor) {
  if (!isObject(descriptor)) fail('resource.json 必须是 JSON 对象')
  if (descriptor.formatVersion !== 1) fail('$.formatVersion 必须是整数 1')
  if (!isObject(descriptor.transform)) fail('$.transform 必须是对象')
  for (const name of ['position', 'rotation', 'scale']) {
    if (!isVector(descriptor.transform[name])) fail(`$.transform.${name} 必须是三个有限数值`)
  }
  const references = []
  const reference = (field, role) => {
    const value = descriptor[field]
    if (typeof value !== 'string' || value === '') fail(`$.${field} 必须是非空相对路径字符串`)
    references.push({ path: value, role, field: `$.${field}` })
  }
  reference('settings', 'settings')
  for (const field of ['poster', 'audio', 'preview']) {
    if (field in descriptor) reference(field, field)
  }
  if ('audioPosition' in descriptor) {
    if (!('audio' in descriptor)) fail('$.audioPosition 只能在声明 $.audio 时提供')
    if (!isVector(descriptor.audioPosition)) fail('$.audioPosition 必须是三个有限数值')
  }
  if (!Array.isArray(descriptor.variants) || descriptor.variants.length === 0) fail('$.variants 必须是非空数组')
  const ids = new Set()
  descriptor.variants.forEach((variant, index) => {
    const at = `$.variants[${index}]`
    if (!isObject(variant)) fail(`${at} 必须是对象`)
    if (typeof variant.id !== 'string' || !VARIANT_ID.test(variant.id)) fail(`${at}.id 必须匹配 ${VARIANT_ID.source}`)
    if (ids.has(variant.id)) fail(`${at}.id 与前面的档位重复：${variant.id}`)
    ids.add(variant.id)
    if (typeof variant.name !== 'string' || variant.name.trim() === '') fail(`${at}.name 必须是非空展示名`)
    if (variant.format !== VARIANT_FORMAT) fail(`${at}.format 必须是 ${VARIANT_FORMAT}`)
    if (!Array.isArray(variant.segments) || variant.segments.length === 0) fail(`${at}.segments 必须是非空数组`)
    let end = null
    variant.segments.forEach((segment, position) => {
      const where = `${at}.segments[${position}]`
      if (!isObject(segment)) fail(`${where} 必须是对象`)
      if (typeof segment.path !== 'string' || segment.path === '') fail(`${where}.path 必须是非空相对路径字符串`)
      if (!Number.isFinite(segment.startSeconds) || segment.startSeconds < 0) fail(`${where}.startSeconds 必须是不小于 0 的有限数值`)
      if (!Number.isFinite(segment.durationSeconds) || segment.durationSeconds <= 0) fail(`${where}.durationSeconds 必须是大于 0 的有限数值`)
      if (end !== null && segment.startSeconds < end) fail(`${where}.startSeconds 必须晚于前一段结束且不重叠`)
      end = segment.startSeconds + segment.durationSeconds
      references.push({ path: segment.path, role: 'segment', field: `${where}.path`, variantId: variant.id })
    })
  })
  if (typeof descriptor.defaultVariant !== 'string' || !ids.has(descriptor.defaultVariant)) fail('$.defaultVariant 必须是 variants 中的档位 id')
  return references
}

/** 目录选择结果 -> [{relativePath(去掉顶层目录名), file}]；所有文件必须来自同一个顶层目录。 */
export function rootEntries(files) {
  const list = Array.from(files)
  if (list.length === 0) fail('没有选择任何文件')
  let top = null
  return list.map(file => {
    const full = file.webkitRelativePath
    const slash = typeof full === 'string' ? full.indexOf('/') : -1
    if (slash <= 0) fail('请选择包含 resource.json 的资源目录，而不是单个文件')
    const name = full.slice(0, slash)
    if (top === null) top = name
    else if (name !== top) fail('所选文件不属于同一个目录')
    return { relativePath: full.slice(slash + 1).normalize('NFC'), file }
  })
}

/**
 * 读取并校验目录。返回
 * {descriptor, references, files:[{relativePath,file,bytes}](仅被引用的文件，按路径排序), totalBytes, variants:[{id,name,segmentCount,seconds}], commonCount}。
 * 未被 resource.json 引用的文件不会出现在结果里，也不上传。
 */
export async function readPackage(files) {
  const entries = rootEntries(files)
  const roots = entries.filter(entry => entry.relativePath.toLowerCase() === DESCRIPTOR_FILE)
  if (roots.length === 0) fail('目录根缺少 resource.json')
  if (roots.length > 1 || roots[0].relativePath !== DESCRIPTOR_FILE) fail('目录根必须有且只有一个 resource.json')
  let descriptor
  try { descriptor = JSON.parse(await roots[0].file.text()) } catch { fail('resource.json 不是合法的 JSON') }
  const references = descriptorReferences(descriptor)
  const unique = []
  const seen = new Set()
  for (const { path, field } of references) {
    let normalized
    try { normalized = normalizePath(path) } catch (e) { fail(`${field}：${e.message}`) }
    if (normalized !== path) fail(`${field}：路径必须已是规范形式`)
    if (!seen.has(normalized)) { seen.add(normalized); unique.push(normalized) }
  }
  normalizePaths(unique)
  if (seen.has(DESCRIPTOR_FILE)) fail('resource.json 本身不能作为模型或配置文件被引用')
  const byPath = new Map()
  for (const entry of entries) {
    const bucket = byPath.get(entry.relativePath)
    if (bucket) bucket.push(entry.file)
    else byPath.set(entry.relativePath, [entry.file])
  }
  for (const { path, field } of references) {
    const found = byPath.get(path)
    if (!found) fail(`${field} 引用的文件不在所选目录中：${path}`)
    if (found.length > 1) fail(`${field} 引用的路径在所选目录中不唯一：${path}`)
  }
  const referenced = unique.sort().map(path => ({ relativePath: path, file: byPath.get(path)[0], bytes: byPath.get(path)[0].size }))
  const variants = descriptor.variants.map(variant => {
    const last = variant.segments[variant.segments.length - 1]
    return { id: variant.id, name: variant.name, segmentCount: variant.segments.length, seconds: last.startSeconds + last.durationSeconds }
  })
  return {
    descriptor,
    references,
    files: referenced,
    totalBytes: referenced.reduce((sum, item) => sum + item.bytes, 0),
    variants,
    commonCount: references.filter(item => item.role !== 'segment').length
  }
}

/** 本地数量/大小上限检查；服务端对同一上限返回 413。 */
export function checkLimits(pkg, { maxBytes, versionMaxFiles, versionMaxBytes }) {
  if (pkg.files.length > versionMaxFiles) fail(`文件数量 ${pkg.files.length} 超过每个版本 ${versionMaxFiles} 个的上限`)
  const oversize = pkg.files.find(item => item.bytes > maxBytes)
  if (oversize) fail(`${oversize.relativePath} 超过单文件大小上限`)
  if (pkg.totalBytes > versionMaxBytes) fail('文件总大小超过每个版本的上限')
  const empty = pkg.files.find(item => item.bytes === 0)
  if (empty) fail(`${empty.relativePath} 是空文件，不能上传`)
}

function digestOf(digests, relativePath) {
  const digest = digests.get(relativePath)
  if (!digest) fail(`缺少 ${relativePath} 的 SHA-256`)
  return digest
}

/** 创建版本请求体：descriptor 原样内容，files 为被引用文件的路径/大小/摘要。digests: Map(relativePath -> sha256)。 */
export function createRequest(pkg, digests, { requestKey, description }) {
  return {
    requestKey,
    description,
    descriptor: pkg.descriptor,
    files: pkg.files.map(item => ({ relativePath: item.relativePath, bytes: item.bytes, sha256: digestOf(digests, item.relativePath) }))
  }
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (isObject(value)) return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`
  return JSON.stringify(value)
}

/** 重新选择目录后，先不看摘要：描述、路径集合和大小必须与已固定的版本一致。 */
export function checkSelection(pkg, version) {
  if (canonical(pkg.descriptor) !== canonical(version.descriptor)) fail('所选目录的 resource.json 与该版本固定的描述不一致')
  const fixed = new Map(version.files.map(item => [item.relativePath, item]))
  for (const item of pkg.files) {
    const expected = fixed.get(item.relativePath)
    if (!expected) fail(`${item.relativePath} 不在该版本的文件清单中`)
    if (expected.bytes !== item.bytes) fail(`${item.relativePath} 的大小与该版本登记的不一致`)
  }
  if (fixed.size !== pkg.files.length) {
    const present = new Set(pkg.files.map(item => item.relativePath))
    fail(`所选目录缺少该版本登记的文件：${[...fixed.keys()].find(path => !present.has(path))}`)
  }
}

/** 摘要计算完成后，逐文件与固定清单比较。 */
export function checkDigests(pkg, digests, version) {
  const fixed = new Map(version.files.map(item => [item.relativePath, item]))
  for (const item of pkg.files) {
    if (digestOf(digests, item.relativePath) !== fixed.get(item.relativePath).sha256) {
      fail(`${item.relativePath} 的内容与该版本登记的 SHA-256 不一致，请选择原目录`)
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

/** 把版本描述与服务端文件清单对应起来，供详情按档位分组展示。 */
export function describeVersion(descriptor, files) {
  const byPath = new Map(files.map(file => [file.relativePath, file]))
  const used = new Set()
  const take = path => { used.add(path); return byPath.get(path) ?? null }
  const common = []
  for (const role of ['settings', 'poster', 'audio', 'preview']) {
    if (typeof descriptor[role] === 'string') common.push({ role, path: descriptor[role], file: take(descriptor[role]) })
  }
  const variants = descriptor.variants.map(variant => {
    const segments = variant.segments.map(segment => ({
      path: segment.path, startSeconds: segment.startSeconds, durationSeconds: segment.durationSeconds, file: take(segment.path)
    }))
    return {
      id: variant.id,
      name: variant.name,
      isDefault: variant.id === descriptor.defaultVariant,
      segments,
      bytes: segments.reduce((sum, item) => sum + (item.file?.bytes ?? 0), 0)
    }
  })
  return { common, variants, unreferenced: files.filter(file => !used.has(file.relativePath)) }
}
