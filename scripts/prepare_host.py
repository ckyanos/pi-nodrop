"""Prepare reproducible dependencies on WSL, not in the audited guest."""
import subprocess
import tarfile
import urllib.request
import shutil
from lab_config import HOST_STAGE, ROOT, RUNTIME_ARCHIVE, node_binary

repo = ROOT
stage = HOST_STAGE
stage.mkdir(parents=True, exist_ok=True)
shutil.copy2(repo / 'package.json', stage / 'package.json')
shutil.copy2(repo / 'package-lock.json', stage / 'package-lock.json')
subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund',
                '--registry=https://registry.npmjs.org'], cwd=stage, check=True)
deps = stage / 'deps'
deps.mkdir(exist_ok=True)
for name, url in [
    ('musl-1.2.3.tar.gz', 'https://musl.libc.org/releases/musl-1.2.3.tar.gz'),
    ('lua-5.4.6.tar.gz', 'https://www.lua.org/ftp/lua-5.4.6.tar.gz'),
    ('zlib-1.3.1.tar.gz', 'https://zlib.net/fossils/zlib-1.3.1.tar.gz'),
]:
    path = deps / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
RUNTIME_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open(RUNTIME_ARCHIVE, 'w:gz') as tar:
    tar.add(node_binary(), arcname='node', recursive=False)
    tar.add(stage / 'node_modules', arcname='node_modules')
    tar.add(deps, arcname='deps')
print('Runtime archive:', RUNTIME_ARCHIVE, flush=True)
