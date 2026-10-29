"""Read-only inventory of candidate NoDrop source trees in a WSL distribution."""
import datetime
import json
import pathlib
import subprocess

roots = [p for p in pathlib.Path('/root').iterdir()
         if p.is_dir() and ('nodrop' in p.name.lower() or p.name in ('ndu', 'nd515', 'nd515-legacy'))]
for root in roots:
    for source in (root, root / 'NoDrop'):
        if not (source / 'kmodule').is_dir():
            continue
        files = [p for area in ('kmodule', 'monitor', 'include')
                 for p in (source / area).rglob('*')
                 if p.is_file() and p.suffix in ('.c', '.h', '.in', '.txt')]
        latest = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        print(json.dumps({'source': str(source), 'latest': [
            {'file': str(p.relative_to(source)), 'mtime': datetime.datetime.fromtimestamp(
                p.stat().st_mtime, datetime.timezone.utc).isoformat()} for p in latest]}, ensure_ascii=False))
        if (source / '.git').exists():
            for args in (['rev-parse', 'HEAD'], ['status', '--short']):
                result = subprocess.run(['git', '-C', str(source), *args], text=True, capture_output=True)
                print(result.stdout[:5000])
