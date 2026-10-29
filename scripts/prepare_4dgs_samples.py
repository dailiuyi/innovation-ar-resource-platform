"""Write resource.json v1 descriptors for the three real 4DGS sample packages, into --output only.

The sample directory (--source) is only read. Descriptors are written to <output>/<scene>/resource.json; their paths
are relative to <source>/<scene> (the package root passed to scripts/import_scene_package.py). Also written:
<output>/samples-summary.json (referenced bytes per scene and variant, for the disk-space check; not a descriptor).

Playback configuration comes from the reference catalogue (data/bundled-scenes.json) as recorded in the plan:
* wedding:     standard/high/vr, segments (start,duration) = (0,5) (5,3), unit scale.
* dance_color: 15 segments per variant, start = 5*index, duration 5 except the last (3), unit scale, audio at 0,0,0.
  The sample directory names carry the source frame range; segments are ordered by its first number.
* shiku_dtwd:  the reference catalogue has an EMPTY timeOption. 0..5 seconds and scale 1.4 below are an explicit
  DEMO playback window chosen for this sample, NOT a reconstruction-derived production time contract.
"""
import argparse
import json
from pathlib import Path
import re
import sys

SCENES = ('wedding', 'dance_color', 'shiku_dtwd')
FRAME_RANGE = re.compile(r'_seg(\d+)-\d+_')
VARIANTS = (('standard_quality', '标准画质', 'standard_quality'),
            ('high_quality', '高清画质', 'high_quality'),
            ('vr_foreground', 'VR 前景', 'vr_foreground'))


class SampleError(Exception):
    pass


def models(root, directory):
    folder = root / directory
    if not folder.is_dir():
        raise SampleError(f'missing directory {folder}')
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix in ('.ply', '.4dv')]
    if not files:
        raise SampleError(f'no .ply/.4dv model in {folder}')

    def order(path):
        found = FRAME_RANGE.search(path.name)
        return (int(found.group(1)) if found else 0, path.name)
    return [f'{directory}/{p.name}' for p in sorted(files, key=order)]


def segments(paths, windows):
    if len(paths) != len(windows):
        raise SampleError(f'{len(paths)} model files but {len(windows)} time windows')
    return [{'path': p, 'startSeconds': s, 'durationSeconds': d} for p, (s, d) in zip(paths, windows)]


def media(root, names):
    """names: role -> filename inside media_and_settings. Missing optional roles are omitted by the caller."""
    found = {}
    for role, name in names.items():
        path = root / 'media_and_settings' / name
        if not path.is_file():
            raise SampleError(f'missing {path}')
        found[role] = f'media_and_settings/{name}'
    return found


def descriptor(root, scene):
    if scene == 'wedding':
        windows = [(0, 5), (5, 3)]
        variant_dirs = VARIANTS
        common = media(root, {'settings': 'wedding_settings.json', 'poster': 'wedding_1205.jpg',
                              'audio': 'wedding.wav', 'preview': 'wedding.webm'})
        transform = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
        audio_position = [0, 0, 0]
    elif scene == 'dance_color':
        windows = [(5 * i, 5 if i < 14 else 3) for i in range(15)]
        variant_dirs = VARIANTS
        common = media(root, {'settings': 'dance_color_2_settings.json', 'poster': '0512_dance_color.png',
                              'audio': 'dance_color_audio_new.wav', 'preview': '0512_dance_color.webm'})
        transform = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]}
        audio_position = [0, 0, 0]
    else:
        windows = [(0, 5)]
        variant_dirs = VARIANTS[:2]
        common = media(root, {'settings': 'dtwd_settings_1.json', 'poster': 'shiku_dtwd.png', 'preview': 'shiku_dtwd.webm'})
        transform = {'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1.4, 1.4, 1.4]}
        audio_position = None
    result = {'formatVersion': 1, 'defaultVariant': 'standard_quality', 'transform': transform, **common}
    if audio_position is not None:
        result['audioPosition'] = audio_position
    result['variants'] = [{'id': vid, 'name': name, 'format': '4dv-compressed-ply',
                           'segments': segments(models(root, directory), windows)}
                          for vid, name, directory in variant_dirs]
    return result


def referenced(descriptor_value):
    paths = {descriptor_value[k] for k in ('settings', 'poster', 'audio', 'preview') if k in descriptor_value}
    for variant in descriptor_value['variants']:
        paths.update(segment['path'] for segment in variant['segments'])
    return paths


def summarize(root, value):
    sizes = {p: (root / p).stat().st_size for p in referenced(value)}
    common = {value[k] for k in ('settings', 'poster', 'audio', 'preview') if k in value}
    by_variant = {}
    for variant in value['variants']:
        by_variant[variant['id']] = sum(sizes[s['path']] for s in variant['segments'])
    return {'files': len(sizes), 'totalBytes': sum(sizes.values()), 'commonBytes': sum(sizes[p] for p in common),
            'variantModelBytes': by_variant, 'unreferencedAreNotUploaded': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True, help='Sample directory containing wedding, dance_color, shiku_dtwd')
    parser.add_argument('--output', type=Path, required=True, help='Directory for generated descriptors (under .local)')
    args = parser.parse_args(argv)
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents or output in source.parents:
        print('BLOCKED: --output must be separate from the read-only sample directory', file=sys.stderr)
        return 2
    summary = {}
    try:
        built = {scene: descriptor(source / scene, scene) for scene in SCENES}
    except (SampleError, OSError) as error:
        print('BLOCKED: ' + str(error), file=sys.stderr)
        return 2
    for scene, value in built.items():
        (output / scene).mkdir(parents=True, exist_ok=True)
        (output / scene / 'resource.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        summary[scene] = summarize(source / scene, value)
        print(f'{scene}: {summary[scene]["files"]} files, {summary[scene]["totalBytes"]} bytes referenced, '
              f'variants {summary[scene]["variantModelBytes"]}')
    (output / 'samples-summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
