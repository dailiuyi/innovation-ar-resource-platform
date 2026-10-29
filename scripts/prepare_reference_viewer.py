"""Prepare a task-local copy of the 4DV reference viewer that reads its catalogue from THIS platform.

--source is the reference repository's local-viewer/public (read-only). Only viewer/ and viewer-static/ are copied (no
models, no network access). The copy is checked against the fixed build 20261016/230726 and fails loudly if a required
file is missing or the main bundle no longer imports the catalogue module at the recorded place; there is no fallback to
the built-in static scene list.

The reference source does NOT contain the page that boots the bundle (viewer/index.html) nor the service worker
(viewer/sw.js): only the hashed build directory is there. This tool therefore writes viewer/index.html from
scripts/reference_viewer/index.html, a minimal shell for the fixed build (module script, stylesheet, manifest and the
#dropArea mount point the bundle renders into), and installs no service worker. The page is NOT the original upstream
file and no upstream page is fetched.

In the copy: Drq6wweV.js (the built-in scene map module) is replaced by scripts/reference_viewer/catalog-adapter.js;
the reference origin http://127.0.0.1:8787 becomes --origin; the local build suffix is updated; a same-origin CSP is set
on the pages (and recorded in the marker file so the isolated gateway can send it as a header, which also covers
workers); viewer/platform.html and platform.js (scene/variant launcher) are added. Never edits the reference repository.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import urllib.parse

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / 'reference_viewer'
BUILD = Path('viewer/20261016/230726')
CATALOG_MODULE = BUILD / 'js/Drq6wweV.js'
MAIN_BUNDLE = BUILD / 'js/D8TV3hLS.js'
MAIN_BUNDLE_IMPORT_LINE = 46
REQUIRED = (str(MAIN_BUNDLE), str(BUILD / 'js/DfIBC3Nc.js'), str(CATALOG_MODULE), str(BUILD / 'assets/main.D9zuS0dI.css'),
            str(BUILD / 'manifest.webmanifest'), str(BUILD / 'assets/worker-Cmdae1oK.js'), str(BUILD / 'assets/worker-Cn3mf7d7.js'))
REFERENCE_ORIGIN = 'http://127.0.0.1:8787'
BUILD_TAG = re.compile(r'(20261016230726-5a40c21)-local1')
BUILD_TAG_REPLACEMENT = r'\1-platform1'
TEXT_SUFFIXES = {'.js', '.css', '.json', '.html', '.webmanifest'}
MODEL_SUFFIXES = {'.ply', '.4dv'}
MARKER = '.prepared-reference-viewer.json'
FOREIGN_HOST = re.compile(r'https?://[a-z0-9.-]*(?:4dv|posthog|sentry|googleapis|google-analytics|googletagmanager)[a-z0-9./?=_-]*', re.I)
# 'unsafe-eval' is required by the bundle itself: its self-defence code obtains the global object with Function(...) and
# falls back to `window`, which does not exist in the decode workers ("window is not defined", models never load) when
# eval is blocked. The reference server's own policy allows it too. Exfiltration stays closed by connect-src 'self'.
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:; worker-src 'self' blob:; "
       "connect-src 'self' blob: data:; img-src 'self' blob: data:; media-src 'self' blob: data:; "
       "style-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")


class Blocked(Exception):
    pass


def validate_origin(origin):
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise Blocked(f'--origin must be a bare http(s) origin, got {origin!r}')
    return f'{parsed.scheme}://{parsed.netloc}'


def check_source(source):
    if not source.is_dir():
        raise Blocked(f'reference viewer source {source} does not exist; it is not fetched or substituted '
                      '(expected the reference repository local-viewer/public)')
    missing = [name for name in REQUIRED if not (source / name).is_file()]
    if not (source / 'viewer-static').is_dir():
        missing.append('viewer-static/')
    if not any((source / BUILD).rglob('*.wasm')):
        missing.append(f'{BUILD}/**/*.wasm (decoder WASM)')
    if missing:
        raise Blocked(f'{source} is not the fixed build 20261016/230726; missing: ' + ', '.join(missing))
    lines = (source / MAIN_BUNDLE).read_text(encoding='utf-8').split('\n')
    if len(lines) < MAIN_BUNDLE_IMPORT_LINE or 'Drq6wweV.js' not in lines[MAIN_BUNDLE_IMPORT_LINE - 1]:
        raise Blocked(f'{MAIN_BUNDLE} line {MAIN_BUNDLE_IMPORT_LINE} no longer imports Drq6wweV.js; '
                      'the catalogue module is not where this tool replaces it')


def copy_tree(source, destination):
    skipped = []
    for top in ('viewer', 'viewer-static'):
        for path in sorted((source / top).rglob('*')):
            relative = path.relative_to(source)
            if path.is_dir():
                (destination / relative).mkdir(parents=True, exist_ok=True)
            elif path.suffix.lower() in MODEL_SUFFIXES:
                skipped.append(str(relative))
            else:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    return skipped


def rewrite_text(destination, origin):
    """Origin and build-suffix rewrite in every copied text file. Returns files changed."""
    changed = []
    for path in sorted(destination.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        original = path.read_text(encoding='utf-8')
        text = BUILD_TAG.sub(BUILD_TAG_REPLACEMENT, original.replace(REFERENCE_ORIGIN, origin))
        if text != original:
            path.write_text(text, encoding='utf-8')
            changed.append(str(path.relative_to(destination)))
    return changed


def install_pages(destination, origin):
    """Catalogue module, launcher page and the viewer shell (the source has no index.html)."""
    template = (TEMPLATES / 'catalog-adapter.js').read_text(encoding='utf-8')
    if '__PLATFORM_ORIGIN__' not in template:
        raise Blocked('catalog-adapter.js template lost its origin placeholder')
    (destination / CATALOG_MODULE).write_text(template.replace('__PLATFORM_ORIGIN__', origin), encoding='utf-8')
    (destination / 'viewer/platform.js').write_text((TEMPLATES / 'platform.js').read_text(encoding='utf-8'), encoding='utf-8')
    for page in ('platform.html', 'index.html'):
        text = (TEMPLATES / page).read_text(encoding='utf-8')
        if '__PLATFORM_CSP__' not in text:
            raise Blocked(f'{page} template lost its CSP placeholder')
        (destination / 'viewer' / page).write_text(text.replace('__PLATFORM_CSP__', CSP), encoding='utf-8')


def prepare(source, origin, output):
    origin = validate_origin(origin)
    check_source(source)
    if output.exists():
        if not (output / MARKER).is_file():
            if any(output.iterdir()):
                raise Blocked(f'{output} exists and was not created by this tool; not touching it')
        else:
            shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    skipped = copy_tree(source, output)
    changed = rewrite_text(output, origin)
    install_pages(output, origin)
    foreign = sorted({m.group(0) for path in output.rglob('*') if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
                      for m in FOREIGN_HOST.finditer(path.read_text(encoding='utf-8', errors='replace'))})
    manifest = {'origin': origin, 'source': str(source), 'csp': CSP, 'rewrittenFiles': changed, 'skippedModelFiles': skipped,
                'entryPage': 'viewer/index.html written from scripts/reference_viewer/index.html (absent from the source)',
                'serviceWorker': 'none (viewer/sw.js absent from the source)',
                'remainingForeignHostReferences': foreign, 'files': sum(1 for p in output.rglob('*') if p.is_file())}
    (output / MARKER).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for path in [output, *output.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True, help='Reference repository local-viewer/public (read-only)')
    parser.add_argument('--origin', required=True, help='Platform origin, e.g. http://127.0.0.1:18082')
    parser.add_argument('--output', type=Path, required=True, help='Directory for the prepared copy (under .local)')
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.source.resolve(), args.origin, args.output.resolve())
    except (Blocked, OSError, UnicodeDecodeError) as error:
        print('BLOCKED: ' + str(error), file=sys.stderr)
        return 2
    print(f'prepared {manifest["files"]} files; foreign host references left (blocked by CSP): '
          f'{len(manifest["remainingForeignHostReferences"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
