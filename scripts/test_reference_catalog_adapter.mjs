// Consumer-behaviour tests for scripts/reference_viewer/catalog-adapter.js against a fake platform client API.
// Run: node --test scripts/test_reference_catalog_adapter.mjs
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';

const ORIGIN = 'http://127.0.0.1:18082';
const directory = mkdtempSync(join(tmpdir(), 'catalog-adapter-'));
const source = readFileSync(new URL('./reference_viewer/catalog-adapter.js', import.meta.url), 'utf8');
writeFileSync(join(directory, 'adapter.mjs'), source.replaceAll('__PLATFORM_ORIGIN__', ORIGIN));
const adapter = await import(pathToFileURL(join(directory, 'adapter.mjs')).href);

const dl = (scene, path) => `/api/v1/client/scenes/${scene}/versions/v1/files/${path.replace(/\//g, '_')}/content/${encodeURIComponent(path.split('/').pop())}`;

function detail(sceneId, { audio = true, variants } = {}) {
  const segs = (prefix, n) => Array.from({ length: n }, (_, i) => ({ path: `${prefix}/${String(i).padStart(2, '0')}.c.ply`, startSeconds: 5 * i, durationSeconds: 5 }));
  const list = variants ?? [
    { id: 'standard_quality', name: 'S', format: '4dv-compressed-ply', segments: segs('standard', 2) },
    { id: 'high_quality', name: 'H', format: '4dv-compressed-ply', segments: segs('high', 2) },
  ];
  const paths = new Set(['media/settings.json', 'media/poster.jpg', 'media/preview.webm', ...(audio ? ['media/a,b.wav'] : [])]);
  list.forEach((v) => v.segments.forEach((s) => paths.add(s.path)));
  const descriptor = {
    formatVersion: 1, defaultVariant: 'standard_quality',
    transform: { position: [0, 1, 2], rotation: [0, 90, 0], scale: [1.4, 1.4, 1.4] },
    settings: 'media/settings.json', poster: 'media/poster.jpg', preview: 'media/preview.webm',
    ...(audio ? { audio: 'media/a,b.wav', audioPosition: [1, 2, 3] } : {}), variants: list,
  };
  return { sceneId, name: sceneId, descriptor, files: [...paths].map((p) => ({ relativePath: p, downloadPath: dl(sceneId, p) })) };
}

function fakeFetch(scenes, log = []) {
  const byId = new Map(scenes.map((s) => [s.sceneId, s]));
  return async (url) => {
    log.push(url);
    const u = new URL(url);
    assert.equal(u.origin, ORIGIN, 'every request goes to the platform origin');
    const list = u.pathname === '/api/v1/client/scenes';
    if (list) {
      const limit = Number(u.searchParams.get('limit')), offset = Number(u.searchParams.get('offset'));
      const items = scenes.slice(offset, offset + limit).map((s) => ({ id: s.sceneId }));
      return { ok: true, status: 200, json: async () => ({ items, total: scenes.length }) };
    }
    const found = byId.get(u.pathname.split('/').pop());
    return found ? { ok: true, status: 200, json: async () => found } : { ok: false, status: 404, json: async () => ({}) };
  };
}

test('entry uses the selected variant for every device path and omits highPlyPath', () => {
  const entry = adapter.sceneEntry(detail('s1'), 'high_quality');
  const models = entry.plyPath.split(',');
  assert.equal(models.length, 2);
  assert.ok(models.every((m) => m.startsWith(ORIGIN + '/api/v1/client/scenes/s1/') && m.endsWith('.c.ply')));
  assert.ok(models[0].includes('00.c.ply') && models[1].includes('01.c.ply'));
  assert.equal(entry.lowPlyPath, entry.plyPath);
  assert.equal(entry.lowVRPlyPath, entry.plyPath);
  assert.equal('highPlyPath' in entry, false);
  assert.equal(entry.timeOption, '0,5,5,5');
  assert.equal(entry.config_name, 's1');
  assert.equal(entry.position, '0,1,2');
  assert.equal(entry.rotation, '0,90,0');
  assert.equal(entry.scale, '1.4,1.4,1.4');
  assert.equal(entry.audioPosition, '1,2,3');
  assert.ok(entry.audioPath.endsWith('/content/a%2Cb.wav'), 'comma in basename stays encoded');
  assert.equal(entry.settingPath, ORIGIN + dl('s1', 'media/settings.json'));
});

test('missing audio gives empty audio fields; nothing is defaulted from other variants', () => {
  const entry = adapter.sceneEntry(detail('s2', { audio: false }), 'standard_quality');
  assert.equal(entry.audioPath, '');
  assert.equal(entry.audioPosition, '');
  assert.ok(!entry.plyPath.includes('/files/high_'));
});

test('unknown variant is an error, not a fallback', () => {
  assert.throws(() => adapter.sceneEntry(detail('s3'), 'vr_foreground'), /no variant "vr_foreground".*standard_quality, high_quality/);
});

test('catalogue pages through the whole list, replaces rather than merges, and only the page scene uses its variant', async () => {
  const scenes = Array.from({ length: 120 }, (_, i) => detail(`scene-${i}`));
  const log = [];
  const map = await adapter.buildCatalog(fakeFetch(scenes, log), { sceneId: 'scene-5', variantId: 'high_quality' });
  assert.equal(Object.keys(map).length, 120);
  assert.ok(map['scene-5'].plyPath.includes('/files/high_') && !map['scene-5'].plyPath.includes('/files/standard_'));
  assert.ok(map['scene-6'].plyPath.includes('/files/standard_') && !map['scene-6'].plyPath.includes('/files/high_'));
  const high = adapter.sceneEntry(scenes[5], 'high_quality');
  assert.equal(map['scene-5'].plyPath, high.plyPath);
  assert.equal(map['scene-6'].plyPath, adapter.sceneEntry(scenes[6], 'standard_quality').plyPath);
  assert.equal(log.filter((u) => u.includes('/api/v1/client/scenes?')).length, 2);
  assert.ok(!('rocket' in map) && !('wedding' in map));
});

test('empty catalogue stays empty', async () => {
  assert.deepEqual(await adapter.buildCatalog(fakeFetch([]), null), {});
});

test('requested scene missing from catalogue is an error', async () => {
  await assert.rejects(adapter.buildCatalog(fakeFetch([detail('a')]), { sceneId: 'b', variantId: null }), /not in the platform catalogue/);
});

test('requested variant missing on the page scene is an error, other scenes unaffected', async () => {
  await assert.rejects(adapter.buildCatalog(fakeFetch([detail('a'), detail('b')]), { sceneId: 'a', variantId: 'nope' }), /no variant "nope"/);
});

test('location parsing', () => {
  const id = '0f0f0f0f-1111-2222-3333-444444444444';
  assert.deepEqual(adapter.requestedFromLocation({ pathname: `/viewer/${id}`, search: '?showdemo=4dv&variant=high_quality' }), { sceneId: id, variantId: 'high_quality' });
  assert.deepEqual(adapter.requestedFromLocation({ pathname: `/viewer/${id}`, search: '' }), { sceneId: id, variantId: null });
  assert.equal(adapter.requestedFromLocation({ pathname: '/viewer/platform.html', search: '' }), null);
});
