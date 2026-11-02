"""Check original source stayed unchanged and export the prototype delta."""
import argparse
import difflib
import hashlib
import json
import pathlib

repo = pathlib.Path(__file__).resolve().parents[1]
provenance = json.loads((repo / 'vendor/nodrop-provenance.json').read_text(encoding='utf-8'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=pathlib.Path, help='NoDrop baseline working tree matching the provenance hashes')
source = parser.parse_args().source.expanduser().resolve()
target = repo / 'vendor/nodrop'
baseline = {entry['path']: entry for entry in provenance['files']}
diff = []
for name, entry in baseline.items():
    original = source / name
    assert hashlib.sha256(original.read_bytes()).hexdigest() == entry['sha256'], f'Original source changed: {name}'
    updated = target / name
    diff.extend(difflib.unified_diff(original.read_text(encoding='utf-8').splitlines(True), updated.read_text(encoding='utf-8').splitlines(True),
                                   'a/' + name, 'b/' + name))
for path in target.rglob('*'):
    name = path.relative_to(target).as_posix()
    if path.is_file() and name not in baseline and path.suffix in ('.c', '.h'):
        diff.extend(difflib.unified_diff([], path.read_text(encoding='utf-8').splitlines(True), '/dev/null', 'b/' + name))
(repo / 'vendor/pi-nodrop.patch').write_text(''.join(
    line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in diff), encoding='utf-8', newline='\n')
print(json.dumps({'original_source_unchanged': True, 'baseline_files': len(baseline), 'patch_lines': len(diff)}))
