// scenePackage.js 的消费者行为测试：目录归根、引用校验、路径冲突、与已固定版本的比对和展示分组。
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PackageError, checkDigests, checkLimits, checkSelection, createRequest, describeVersion,
  normalizePaths, readPackage, uploadPlan
} from '../frontend/src/utils/scenePackage.js'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)

function descriptor(overrides = {}) {
  return {
    formatVersion: 1,
    defaultVariant: 'standard',
    transform: { position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] },
    settings: 'settings.json',
    poster: 'media/poster.jpg',
    variants: [
      { id: 'standard', name: '标准', format: '4dv-compressed-ply', segments: [
        { path: 'models/std-0.c.ply', startSeconds: 0, durationSeconds: 5 },
        { path: 'models/std-1.c.ply', startSeconds: 5, durationSeconds: 3 }] },
      { id: 'high', name: '高清', format: '4dv-compressed-ply', segments: [
        { path: 'models/high-0.c.ply', startSeconds: 0, durationSeconds: 8 }] }
    ],
    ...overrides
  }
}

// 模拟浏览器 webkitdirectory 选择结果：路径带顶层目录名。
function entry(path, size = 10, text = '') {
  return { webkitRelativePath: path, size, text: async () => text }
}

function directory(desc = descriptor(), { top = 'wedding', extra = [], omit = [] } = {}) {
  const referenced = ['settings.json', 'media/poster.jpg', 'models/std-0.c.ply', 'models/std-1.c.ply', 'models/high-0.c.ply']
    .filter(path => !omit.includes(path))
  return [
    entry(`${top}/resource.json`, 1, JSON.stringify(desc)),
    ...referenced.map(path => entry(`${top}/${path}`)),
    ...extra
  ]
}

async function rejects(files, pattern) {
  await assert.rejects(() => readPackage(files), error => {
    assert.ok(error instanceof PackageError, `unexpected ${error}`)
    assert.match(error.message, pattern)
    return true
  })
}

test('目录归根并只收集被引用的文件，未引用文件不上传', async () => {
  const pkg = await readPackage(directory(descriptor(), { extra: [entry('wedding/报告.md', 99), entry('wedding/models/unused.c.ply', 99)] }))
  assert.deepEqual(pkg.files.map(item => item.relativePath), [
    'media/poster.jpg', 'models/high-0.c.ply', 'models/std-0.c.ply', 'models/std-1.c.ply', 'settings.json'])
  assert.equal(pkg.totalBytes, 50)
  assert.deepEqual(pkg.variants, [
    { id: 'standard', name: '标准', segmentCount: 2, seconds: 8 },
    { id: 'high', name: '高清', segmentCount: 1, seconds: 8 }])
  assert.equal(pkg.commonCount, 2)
})

test('不同档位共用同一路径只登记一份', async () => {
  const shared = descriptor()
  shared.variants[1].segments[0].path = 'models/std-0.c.ply'
  const pkg = await readPackage(directory(shared, { omit: ['models/high-0.c.ply'] }))
  assert.equal(pkg.files.filter(item => item.relativePath === 'models/std-0.c.ply').length, 1)
  assert.equal(pkg.files.length, 4)
})

test('缺少根 resource.json 或出现大小写变体时拒绝', async () => {
  await rejects(directory().slice(1), /缺少 resource\.json/)
  const renamed = directory()
  renamed[0] = entry('wedding/Resource.json', 1, JSON.stringify(descriptor()))
  await rejects(renamed, /有且只有一个 resource\.json/)
  await rejects([entry('resource.json')], /请选择包含 resource\.json 的资源目录/)
})

test('子目录里的 resource.json 不是根描述', async () => {
  const files = directory().slice(1)
  files.push(entry('wedding/nested/resource.json'))
  await rejects(files, /缺少 resource\.json/)
})

test('缺失引用指出 JSON 字段和路径', async () => {
  await rejects(directory(descriptor(), { omit: ['models/std-1.c.ply'] }), /\$\.variants\[0\]\.segments\[1\]\.path.*models\/std-1\.c\.ply/)
  await rejects(directory(descriptor(), { omit: ['settings.json'] }), /\$\.settings.*settings\.json/)
})

test('跨目录引用：越出目录根或来自不同顶层目录都拒绝', async () => {
  const escaping = descriptor()
  escaping.variants[1].segments[0].path = '../other/high-0.c.ply'
  await rejects(directory(escaping), /\$\.variants\[1\]\.segments\[0\]\.path：.*越界/)
  const absolute = descriptor({ settings: '/etc/settings.json' })
  await rejects(directory(absolute), /\$\.settings：.*绝对路径/)
  const mixed = directory()
  mixed[2] = entry('other-folder/media/poster.jpg')
  await rejects(mixed, /不属于同一个目录/)
})

test('重复档位与形状错误定位到字段', async () => {
  const duplicate = descriptor()
  duplicate.variants[1].id = 'standard'
  await rejects(directory(duplicate), /\$\.variants\[1\]\.id.*重复/)
  await rejects(directory(descriptor({ defaultVariant: 'missing' })), /\$\.defaultVariant/)
  const overlap = descriptor()
  overlap.variants[0].segments[1].startSeconds = 4
  await rejects(directory(overlap), /\$\.variants\[0\]\.segments\[1\]\.startSeconds/)
  const zero = descriptor()
  zero.variants[1].segments[0].durationSeconds = 0
  await rejects(directory(zero), /durationSeconds/)
  await rejects(directory(descriptor({ audioPosition: [0, 0, 0] })), /\$\.audioPosition/)
  await rejects(directory(descriptor({ poster: '' })), /\$\.poster/)
  await rejects(directory(descriptor({ transform: { position: [0, 0, 0], rotation: [0, 0], scale: [1, 1, 1] } })), /\$\.transform\.rotation/)
})

test('路径冲突：大小写冲突、文件与目录同名', async () => {
  const caseClash = descriptor()
  caseClash.variants[1].segments[0].path = 'Models/STD-0.c.ply'
  await rejects(directory(caseClash, { extra: [entry('wedding/Models/STD-0.c.ply')] }), /大小写冲突/)
  const dirClash = descriptor({ poster: 'models' })
  await rejects(directory(dirClash, { extra: [entry('wedding/models')] }), /文件与目录路径冲突/)
  assert.throws(() => normalizePaths(['a/b', 'a/b']), PackageError)
  assert.deepEqual(normalizePaths(['a/b', 'a/c']), ['a/b', 'a/c'])
})

test('引用 resource.json 自身或损坏的 JSON 拒绝', async () => {
  await rejects(directory(descriptor({ settings: 'resource.json' })), /resource\.json 本身/)
  const broken = directory()
  broken[0] = entry('wedding/resource.json', 1, '{not json')
  await rejects(broken, /不是合法的 JSON/)
})

test('本地上限与空文件检查', async () => {
  const pkg = await readPackage(directory())
  const limits = { maxBytes: 100, versionMaxFiles: 5, versionMaxBytes: 1000 }
  checkLimits(pkg, limits)
  assert.throws(() => checkLimits(pkg, { ...limits, versionMaxFiles: 4 }), /文件数量/)
  assert.throws(() => checkLimits(pkg, { ...limits, maxBytes: 9 }), /单文件大小上限/)
  assert.throws(() => checkLimits(pkg, { ...limits, versionMaxBytes: 49 }), /总大小/)
  const empty = await readPackage(directory(descriptor(), { extra: [] }).map(item => item.webkitRelativePath.endsWith('std-0.c.ply') ? entry(item.webkitRelativePath, 0) : item))
  assert.throws(() => checkLimits(empty, limits), /空文件/)
})

async function fixture() {
  const pkg = await readPackage(directory())
  const digests = new Map(pkg.files.map((item, index) => [item.relativePath, (index % 2 ? SHA_A : SHA_B)]))
  const request = createRequest(pkg, digests, { requestKey: '11111111-1111-4111-8111-111111111111', description: '测试' })
  const version = {
    id: 'v1', descriptor: structuredClone(request.descriptor),
    files: request.files.map((file, index) => ({ fileId: `f${index}`, status: 'PENDING', attempts: 0, ...file }))
  }
  return { pkg, digests, request, version }
}

test('创建请求携带原描述与被引用文件的路径/大小/摘要', async () => {
  const { pkg, request } = await fixture()
  assert.deepEqual(request.descriptor, pkg.descriptor)
  assert.deepEqual(request.files.map(file => Object.keys(file)), pkg.files.map(() => ['relativePath', 'bytes', 'sha256']))
  assert.equal(request.requestKey, '11111111-1111-4111-8111-111111111111')
  assert.throws(() => createRequest(pkg, new Map(), { requestKey: 'k', description: '' }), /缺少.*SHA-256/)
})

test('重新选择目录与已固定版本一致时通过，字段顺序不同也算相同', async () => {
  const { pkg, digests, version } = await fixture()
  const reordered = structuredClone(version)
  const reverse = value => Array.isArray(value) ? value.map(reverse)
    : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, reverse(item)])) : value
  reordered.descriptor = reverse(version.descriptor)
  assert.notDeepEqual(Object.keys(reordered.descriptor), Object.keys(version.descriptor))
  checkSelection(pkg, reordered)
  checkDigests(pkg, digests, reordered)
})

test('重新选择不匹配：描述、路径集合、大小、摘要任一不同都拒绝', async () => {
  const { pkg, digests, version } = await fixture()
  const changedDescriptor = structuredClone(version)
  changedDescriptor.descriptor.variants[0].name = '改名'
  assert.throws(() => checkSelection(pkg, changedDescriptor), /描述不一致/)
  const missing = structuredClone(version)
  missing.files.pop()
  assert.throws(() => checkSelection(pkg, missing), /不在该版本的文件清单中/)
  const extra = structuredClone(version)
  extra.files.push({ fileId: 'fx', relativePath: 'models/extra.c.ply', bytes: 10, sha256: SHA_A, status: 'PENDING' })
  assert.throws(() => checkSelection(pkg, extra), /缺少该版本登记的文件：models\/extra\.c\.ply/)
  const resized = structuredClone(version)
  resized.files[0].bytes = 11
  assert.throws(() => checkSelection(pkg, resized), /大小/)
  const wrong = new Map(digests)
  wrong.set(pkg.files[2].relativePath, 'c'.repeat(64))
  assert.throws(() => checkDigests(pkg, wrong, version), new RegExp(`${pkg.files[2].relativePath.replace(/\./g, '\\.')}.*SHA-256`))
})

test('上传规划：已入库跳过，处理中不重发，失败与待上传按路径顺序重传', () => {
  const files = [
    { relativePath: 'b', status: 'FAILED' }, { relativePath: 'a', status: 'PENDING' },
    { relativePath: 'c', status: 'AVAILABLE' }, { relativePath: 'd', status: 'UPLOADING' }]
  const plan = uploadPlan(files)
  assert.deepEqual(plan.upload.map(file => file.relativePath), ['a', 'b'])
  assert.deepEqual(plan.processing.map(file => file.relativePath), ['d'])
  assert.equal(plan.done, 1)
})

test('版本详情按档位分组，共享文件在各档位都出现，公共配置单独成组', async () => {
  const shared = descriptor()
  shared.variants[1].segments[0].path = 'models/std-0.c.ply'
  const files = ['settings.json', 'media/poster.jpg', 'models/std-0.c.ply', 'models/std-1.c.ply'].map((relativePath, index) => ({
    fileId: `f${index}`, relativePath, bytes: 10 * (index + 1), sha256: SHA_A, status: index === 3 ? 'FAILED' : 'AVAILABLE', failureReason: null, attempts: 1 }))
  files.push({ fileId: 'fz', relativePath: 'stray.bin', bytes: 1, sha256: SHA_B, status: 'PENDING', attempts: 0 })
  const view = describeVersion(shared, files)
  assert.deepEqual(view.common.map(item => [item.role, item.path, item.file?.fileId]), [['settings', 'settings.json', 'f0'], ['poster', 'media/poster.jpg', 'f1']])
  assert.deepEqual(view.variants.map(item => [item.id, item.isDefault, item.segments.length, item.bytes]), [['standard', true, 2, 70], ['high', false, 1, 30]])
  assert.equal(view.variants[1].segments[0].file.fileId, 'f2')
  assert.deepEqual(view.unreferenced.map(file => file.relativePath), ['stray.bin'])
  const missing = describeVersion(shared, files.slice(0, 3))
  assert.equal(missing.variants[0].segments[1].file, null)
})
