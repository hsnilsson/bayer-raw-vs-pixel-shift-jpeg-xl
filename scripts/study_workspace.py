"""Set up a relocatable editable study without changing the frozen archive."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'archive/study-20260917'
WORK = ROOT / 'work/study'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    if path.resolve().is_relative_to((ROOT/'archive').resolve()):
        raise ValueError('The archive is immutable')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def key(value):
    return str(value).replace('\\', '/').rstrip('/').casefold()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def scratch_path(value):
    path = Path(value)
    path = (ROOT/path).resolve() if not path.is_absolute() else path.resolve()
    if path == ROOT or path == Path(path.anchor) or path.is_relative_to((ROOT/'archive').resolve()) or path.is_relative_to(ROOT/'.git'):
        raise ValueError('Scratch must be a dedicated mutable subdirectory outside the archive and .git')
    return path


def setup(scratch=None):
    aliases = read(ARCHIVE/'manifests/path-map.json')['aliases']
    old = read(WORK/'restore.json') if (WORK/'restore.json').exists() else {}
    previous = old.get('paths', {}).get('report')
    scratch = scratch_path(scratch or old.get('scratch_setting', 'work/scratch'))
    scratch.mkdir(parents=True, exist_ok=True)
    destination = ROOT/'results/verified_report'
    initialized = not destination.exists()
    if initialized:
        shutil.copytree(ARCHIVE/'records/current-private', destination)
    old_roots = ['C:/a/GitHub/jpegxl-vs-dngpixelshift',
                 'C:/Users/henri/.codex/worktrees/048c/jpegxl-vs-dngpixelshift',
                 'C:/Users/henri/.codex/worktrees/8db0/jpegxl-vs-dngpixelshift']
    def relocate(value):
        if isinstance(value, dict):
            return {relocate(k): relocate(v) for k,v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if not isinstance(value, str):
            return value
        normalized = key(value)
        if previous and key(previous) != key(ROOT) and normalized.startswith(key(previous)+'/'):
            return str(ROOT/value.replace('\\','/')[len(key(previous))+1:])
        for original in old_roots:
            if normalized.startswith(key(original)+'/'):
                suffix = value.replace('\\','/')[len(key(original))+1:]
                if suffix.startswith(('site/','results/verified_report/')):
                    return str(ROOT/suffix)
        if normalized in aliases:
            return str(ARCHIVE/aliases[normalized])
        return value
    changes = []
    if initialized or not previous or key(previous) != key(ROOT):
        for path in destination.rglob('*.json'):
            before = read(path); after = relocate(before)
            if before != after:
                write(path, after); changes.append(path.relative_to(ROOT).as_posix())
    for short, original in [('lossy','D:/jpegxl-muimg-qualification/qualification.json'),
                            ('lossless','D:/jpegxl-muimg-lossless-qualification/qualification.json')]:
        path = WORK/'qualifications'/(short+'.json')
        if not path.exists():
            write(path, relocate(read(ARCHIVE/aliases[key(original)])))
        elif previous and key(previous) != key(ROOT):
            write(path, relocate(read(path)))
    if previous and key(previous) != key(ROOT):
        options = WORK/'runtime-settings/rawtherapee/options'
        if options.exists():
            text = options.read_text(encoding='utf-8-sig')
            text = text.replace(previous, str(ROOT)).replace(previous.replace('\\','\\\\'), str(ROOT).replace('\\','\\\\'))
            options.write_text(text, encoding='utf-8')
    paths = dict(archive=str(ARCHIVE), report=str(ROOT),
                 archive_checkout=str(ARCHIVE/'payload/C/a/GitHub/jpegxl-vs-dngpixelshift'),
                 python=str(ARCHIVE/'tooling/python/python.exe'), tools=str(ARCHIVE/'tooling/libjxl/bin'),
                 exiftool=str(ARCHIVE/'tooling/exiftool/ExifTool.exe'),
                 rawtherapee=str(ARCHIVE/'tooling/rawtherapee/rawtherapee-cli.exe'),
                 rgb16_root=str(ARCHIVE/'payload/D/CodexTemp/jpegxl-vs-dngpixelshift/rendered_ps16_jxl_matrix_rgb16'),
                 f45_root=str(ARCHIVE/'payload/D/CodexTemp/jpegxl-vs-dngpixelshift/verified-report-rebuild/retained-f45'),
                 controlled_sources=str(ARCHIVE/'payload/D/camera scanning/test-110-slides/test-laowa'),
                 crop_plan=str(ARCHIVE/aliases[key('C:/a/GitHub/jpegxl-vs-dngpixelshift/results/break_even_crop_guides/crop_plan.json')]),
                 scratch=str(scratch))
    setting = str(scratch.relative_to(ROOT)) if scratch.is_relative_to(ROOT) else str(scratch)
    write(WORK/'restore.json', dict(schema=1, paths=paths, scratch_setting=setting,
                                   original_records_preserved=True, initialized_from_frozen_records=initialized,
                                   relocated_json_files=changes))
    print('Workspace ready:', ROOT, '\nScratch:', scratch, flush=True)


def check():
    dependencies = read(ARCHIVE/'validation/dependencies.json')
    manifest = {r['path']:r for r in read(ARCHIVE/'manifests/files.json')['files']}
    checked = set()
    for row in dependencies['checks']:
        relative = row['archive_path']; path = (ARCHIVE/relative).resolve()
        if not path.is_relative_to(ARCHIVE.resolve()):
            raise ValueError('Dependency escapes archive: '+relative)
        if manifest[relative]['sha256'] != row['sha256']:
            raise ValueError('Saved dependency identity differs: '+relative)
        if path.stat().st_size != manifest[relative]['bytes']:
            raise ValueError('Dependency size differs: '+relative)
        with path.open('rb') as stream:
            stream.read(16)
        checked.add(relative)
    frames = read(ROOT/'results/verified_report/private_inventory.json')['frames']
    referenced = []
    for frame in frames:
        referenced.extend(frame[k] for k in ('source_manifest','raw_source','dng_source','reference','source_render','raw_render'))
        referenced.extend(frame['candidates'].values())
    for value in referenced:
        path=Path(value).resolve()
        if not path.is_relative_to(ARCHIVE.resolve()) or not path.is_file():
            raise ValueError('Working inventory input unavailable or outside archive: '+value)
    frozen_code=read(ARCHIVE/'records/current-private/environment.json')['code']
    changed=[rel for rel,expected in frozen_code.items() if digest(ROOT/rel)!=expected]
    result=dict(archive=str(ARCHIVE), project=str(ROOT), dependency_files=len(checked), frames=len(frames),
                measurement_rows_covered=dependencies['rendered_measurement_rows_covered'],
                frozen_analysis_code_changed=changed, measurement_recomputation_performed=False)
    write(WORK/'dependency-check.json',result)
    print(json.dumps(result,indent=2),flush=True)
    if changed:
        raise ValueError('Frozen results require unchanged analysis code. Use a new research results set for changed analysis: '+', '.join(changed))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['setup','check'])
    parser.add_argument('--scratch')
    args=parser.parse_args()
    if args.action=='setup': setup(args.scratch)
    else: check()
