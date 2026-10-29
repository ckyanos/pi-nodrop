import json
import pathlib

root = pathlib.Path(__file__).resolve().parents[1]
workers = []
for path in pathlib.Path('/proc').iterdir():
    if not path.name.isdigit(): continue
    try:
        args = (path / 'cmdline').read_bytes().decode(errors='replace').split('\0')
    except (FileNotFoundError, PermissionError, ProcessLookupError): continue
    if any(arg.endswith('/pi-nodrop/src/worker.mjs') for arg in args): workers.append(int(path.name))
result = {'module_unloaded': not pathlib.Path('/sys/module/nodrop').exists(), 'remaining_worker_pids': workers}
(root / 'results/postflight.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
assert result['module_unloaded'] and not workers
