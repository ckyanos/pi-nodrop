"""Snapshot the explicitly selected working tree, including uncommitted source."""
import hashlib
import json
import pathlib
import shutil
import subprocess

source = pathlib.Path('/root/nodrop-latest-20261009/NoDrop')
dest = pathlib.Path('/mnt/d/桌面/pi-nodrop/vendor/nodrop')
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
    'wsl_distribution': 'Ubuntu-22.04', 'source': str(source),
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
