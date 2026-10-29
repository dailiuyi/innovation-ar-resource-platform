// Platform catalogue for the 4DV reference viewer. prepare_reference_viewer.py copies this file over the viewer's
// built-in scene module (viewer/20261016/230726/js/Drq6wweV.js), whose default export is the scene map the main
// bundle reads, and replaces __PLATFORM_ORIGIN__ with the --origin value.
//
// The map is built only from this platform's anonymous client API: GET /api/v1/client/scenes (all pages), then
// GET /api/v1/client/scenes/{id} per scene. It is NOT merged with the built-in demo scenes; an empty catalogue
// stays empty. The selected variant feeds every device entry (plyPath, lowPlyPath, lowVRPlyPath) and highPlyPath
// is left out, so the player cannot switch to a quality the user did not pick.
const ORIGIN = '__PLATFORM_ORIGIN__';
const PAGE = 100;
const UUID = /^\/viewer\/([0-9a-fA-F-]{36})\/?$/;

export class CatalogError extends Error {}

export const absolute = (path) => new URL(path, ORIGIN).href;
const csv = (values) => values.join(',');

async function getJson(fetchFn, path) {
  const response = await fetchFn(absolute(path), { headers: { Accept: 'application/json' }, cache: 'no-store' });
  if (!response.ok) throw new CatalogError(`${path}: HTTP ${response.status}`);
  return response.json();
}

export async function listScenes(fetchFn) {
  const items = [];
  for (let offset = 0; ; offset += PAGE) {
    const page = await getJson(fetchFn, `/api/v1/client/scenes?limit=${PAGE}&offset=${offset}`);
    items.push(...page.items);
    if (page.items.length === 0 || items.length >= page.total) return items;
  }
}

/** One viewer map entry for `variantId` of a scene detail; throws when the variant does not exist. */
export function sceneEntry(detail, variantId) {
  const descriptor = detail.descriptor;
  const variant = descriptor.variants.find((candidate) => candidate.id === variantId);
  if (!variant) {
    const known = descriptor.variants.map((candidate) => candidate.id).join(', ');
    throw new CatalogError(`Scene ${detail.sceneId} has no variant "${variantId}" (available: ${known})`);
  }
  const byPath = new Map(detail.files.map((file) => [file.relativePath, file]));
  const url = (relativePath) => {
    const file = byPath.get(relativePath);
    if (!file) throw new CatalogError(`Scene ${detail.sceneId}: ${relativePath} is not in the file list`);
    return absolute(file.downloadPath);
  };
  const optional = (relativePath) => (relativePath ? url(relativePath) : '');
  const models = csv(variant.segments.map((segment) => url(segment.path)));
  const entry = {
    plyPath: models,
    lowPlyPath: models,
    lowVRPlyPath: models,
    timeOption: csv(variant.segments.flatMap((segment) => [segment.startSeconds, segment.durationSeconds])),
    settingPath: url(descriptor.settings),
    posterPath: optional(descriptor.poster),
    paramsPath: '',
    audioPath: optional(descriptor.audio),
    previewPath: optional(descriptor.preview),
    position: csv(descriptor.transform.position),
    rotation: csv(descriptor.transform.rotation),
    scale: csv(descriptor.transform.scale),
    audioPosition: descriptor.audio ? csv(descriptor.audioPosition ?? [0, 0, 0]) : '',
    remark: null,
    trackOptionPath: '',
    config_name: detail.sceneId,
  };
  return entry;
}

/** The complete map, keyed by scene UUID. `requested` is {sceneId, variantId} for the page's own scene, if any. */
export async function buildCatalog(fetchFn, requested) {
  const scenes = await listScenes(fetchFn);
  const map = {};
  for (const scene of scenes) {
    const detail = await getJson(fetchFn, `/api/v1/client/scenes/${scene.id}`);
    const own = requested && requested.sceneId === scene.id;
    map[scene.id] = sceneEntry(detail, own && requested.variantId ? requested.variantId : detail.descriptor.defaultVariant);
  }
  if (requested && !map[requested.sceneId]) {
    throw new CatalogError(`Scene ${requested.sceneId} is not in the platform catalogue (unpublished, disabled or deleted)`);
  }
  return map;
}

export function requestedFromLocation(location) {
  const match = UUID.exec(location.pathname);
  if (!match) return null;
  return { sceneId: match[1].toLowerCase(), variantId: new URLSearchParams(location.search).get('variant') };
}

function showError(error) {
  const box = document.createElement('pre');
  box.id = 'platform-catalog-error';
  box.textContent = `Platform catalogue error: ${error.message}`;
  box.style.cssText = 'position:fixed;inset:auto 0 0 0;margin:0;padding:12px;background:#300;color:#fdd;z-index:2147483647;font:14px monospace;white-space:pre-wrap';
  document.documentElement.appendChild(box);
}

let catalog;
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  try {
    catalog = await buildCatalog(window.fetch.bind(window), requestedFromLocation(window.location));
  } catch (error) {
    showError(error);
    throw error;
  }
}

export default catalog;
