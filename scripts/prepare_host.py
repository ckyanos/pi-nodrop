"""Prepare reproducible dependencies on WSL, not in the audited guest."""
import pathlib
import subprocess
import tarfile
import urllib.request
import shutil

repo = pathlib.Path(__file__).resolve().parents[1]
stage = pathlib.Path('/root/pi-nodrop-host')
stage.mkdir(exist_ok=True)
shutil.copy2(repo / 'package.json', stage / 'package.json')
subprocess.run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund',
                '--registry=https://registry.npmjs.org'], cwd=stage, check=True)
shutil.copy2(stage / 'package-lock.json', repo / 'package-lock.json')
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
with tarfile.open('/tmp/pi-nodrop-runtime.tar.gz', 'w:gz') as tar:
    tar.add('/usr/local/bin/node', arcname='node', recursive=False)
    tar.add(stage / 'node_modules', arcname='node_modules')
    tar.add(deps, arcname='deps')
print('Runtime archive: /tmp/pi-nodrop-runtime.tar.gz', flush=True)
