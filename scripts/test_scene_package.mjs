// scenePackage.js 的消费者行为测试：目录归根、全部文件登记、路径冲突、与已固定版本的比对。
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PackageError, checkDigests, checkLimits, checkSelection, createRequest,
  normalizePaths, readPackage, uploadPlan
} from '../frontend/src/utils/scenePackage.js'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)
const PATHS = ['settings.json', 'media/poster.jpg', 'models/std-0.c.ply', 'models/std-1.c.ply', 'models/high-0.c.ply']

// 模拟浏览器 webkitdirectory 选择结果：路径带顶层目录名。
function entry(path, size = 10) {
  return { webkitRelativePath: path, size }
}

function directory({ top = 'wedding', extra = [] } = {}) {
  return [...PATHS.map(path => entry(`${top}/${path}`)), ...extra]
}

async function rejects(files, pattern) {
  await assert.rejects(() => readPackage(files), error => {
    assert.ok(error instanceof PackageError, `unexpected ${error}`)
    assert.match(error.message, pattern)
    return true
  })
}

test('目录归根，目录下每个文件都登记并按路径排序', async () => {
  const pkg = await readPackage(directory({ extra: [entry('wedding/报告.md', 99), entry('wedding/resource.json', 1)] }))
  assert.deepEqual(pkg.files.map(item => item.relativePath), [
    'media/poster.jpg', 'models/high-0.c.ply', 'models/std-0.c.ply', 'models/std-1.c.ply', 'resource.json', 'settings.json', '报告.md'])
  assert.equal(pkg.totalBytes, 150)
  assert.deepEqual(Object.keys(pkg).sort(), ['files', 'totalBytes'])
})

test('空目录、单个文件或混合顶层目录拒绝', async () => {
  await rejects([], /目录为空/)
  await rejects([entry('settings.json')], /请选择资源目录/)
  const mixed = directory()
  mixed[2] = entry('other-folder/models/std-0.c.ply')
  await rejects(mixed, /不属于同一个目录/)
})

test('目录中有空文件时指出路径并拒绝', async () => {
  await rejects(directory({ extra: [entry('wedding/notes/blank.txt', 0)] }), /空文件无法上传：notes\/blank\.txt/)
})

test('路径不合法：保留字符、保留名称、越界片段', async () => {
  await rejects(directory({ extra: [entry('wedding/notes/a?b.txt')] }), /不能安全还原/)
  await rejects(directory({ extra: [entry('wedding/CON.txt')] }), /保留名称/)
  await rejects(directory({ extra: [entry('wedding/x/../y')] }), /越界/)
  await rejects(directory({ extra: [entry(`wedding/${'a'.repeat(256)}`)] }), /过长/)
})

test('路径冲突：大小写冲突、Unicode 规范化冲突、文件与目录同名', async () => {
  await rejects(directory({ extra: [entry('wedding/Models/STD-0.c.ply')] }), /大小写冲突/)
  await rejects(directory({ extra: [entry('wedding/caf\u00e9'), entry('wedding/cafe\u0301')] }), /重复/)
  await rejects(directory({ extra: [entry('wedding/models/std-0.c.ply/x')] }), /文件与目录路径冲突/)
  assert.throws(() => normalizePaths(['a/b', 'a/b']), PackageError)
  assert.deepEqual(normalizePaths(['a/b', 'a/c']), ['a/b', 'a/c'])
})

test('本地上限检查', async () => {
  const pkg = await readPackage(directory())
  const limits = { maxBytes: 100, versionMaxFiles: 5, versionMaxBytes: 1000 }
  checkLimits(pkg, limits)
  assert.throws(() => checkLimits(pkg, { ...limits, versionMaxFiles: 4 }), /文件数量/)
  assert.throws(() => checkLimits(pkg, { ...limits, maxBytes: 9 }), /单文件大小上限/)
  assert.throws(() => checkLimits(pkg, { ...limits, versionMaxBytes: 49 }), /总大小/)
})

async function fixture() {
  const pkg = await readPackage(directory())
  const digests = new Map(pkg.files.map((item, index) => [item.relativePath, (index % 2 ? SHA_A : SHA_B)]))
  const request = createRequest(pkg, digests, { requestKey: '11111111-1111-4111-8111-111111111111', description: '测试' })
  const version = {
    id: 'v1',
    files: request.files.map((file, index) => ({ fileId: `f${index}`, status: 'PENDING', attempts: 0, ...file }))
  }
  return { pkg, digests, request, version }
}

test('创建请求只含 requestKey、说明与全部文件的路径/大小/摘要', async () => {
  const { pkg, request } = await fixture()
  assert.deepEqual(Object.keys(request), ['requestKey', 'description', 'files'])
  assert.deepEqual(request.files.map(file => Object.keys(file)), pkg.files.map(() => ['relativePath', 'bytes', 'sha256']))
  assert.equal(request.files.length, PATHS.length)
  assert.throws(() => createRequest(pkg, new Map(), { requestKey: 'k', description: '' }), /缺少.*SHA-256/)
})

test('重新选择目录与已固定版本一致时通过', async () => {
  const { pkg, digests, version } = await fixture()
  checkSelection(pkg, version)
  checkDigests(pkg, digests, version)
})

test('重新选择不匹配：路径集合、大小、摘要任一不同都拒绝', async () => {
  const { pkg, digests, version } = await fixture()
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
