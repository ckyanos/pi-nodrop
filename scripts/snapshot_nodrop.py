"""Snapshot a NoDrop working tree with file hashes and its baseline patch."""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=pathlib.Path, help='NoDrop source working tree')
parser.add_argument('--destination', type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parents[1] / 'vendor/nodrop')
args = parser.parse_args()
source = args.source.expanduser().resolve()
dest = args.destination.expanduser().resolve()
assert not dest.exists(), f'Refusing to overwrite {dest}'
dest.mkdir(parents=True)
paths = [pathlib.Path(s) for s in subprocess.check_output(
    ['git', '-C', str(source), 'ls-files'], text=True).splitlines()]
selected = [p for p in paths if p.parts[0] in
            ('include', 'kmodule', 'monitor', 'scripts', 'CMakeLists.txt', 'LICENSE', 'README.md', '.gitignore')]
manifest = []
for relative in selected:
    src = source / relative
    if not src.is_file():
        continue
    dst = dest / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    manifest.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(src.read_bytes()).hexdigest(),
                     'mtime_ns': src.stat().st_mtime_ns})
provenance = {
    'source_kind': 'working-tree',
    'commit': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
    'status': subprocess.check_output(['git', '-C', str(source), 'status', '--short'], text=True),
    'files': manifest,
}
out = dest.parent / 'nodrop-provenance.json'
out.write_text(json.dumps(provenance, indent=2) + '\n')
(dest.parent / 'nodrop-baseline.patch').write_bytes(subprocess.check_output(
    ['git', '-C', str(source), 'diff', 'HEAD', '--', *[str(p) for p in selected]]))
print(json.dumps({'files': len(manifest), 'bytes': sum((dest / p).stat().st_size for p in selected if (dest / p).is_file()),
                  'commit': provenance['commit'], 'destination': str(dest)}))
