"""Build the pinned musl dependency on WSL; package for the guest path."""
import hashlib
import json
import os
import pathlib
import subprocess
import tarfile

root = pathlib.Path('/root/pi-nodrop-host')
guest = '/home/kmoddebug/pi-nodrop'
prefix = guest + '/build/musl'
archive = root / 'deps/musl-1.2.3.tar.gz'
with tarfile.open(archive) as tar:
    tar.extractall(root / 'libsrc', filter='data')
source = root / 'libsrc/musl-1.2.3'
env = dict(os.environ, CFLAGS='-fPIE')
subprocess.run(['./configure', '--prefix=' + prefix, '--disable-shared', '--enable-optimize', '--disable-wrapper'],
               cwd=source, env=env, check=True)
subprocess.run(['make', '-j4'], cwd=source, check=True, stdout=subprocess.DEVNULL)
subprocess.run(['make', 'install', 'DESTDIR=' + str(root / 'sysroot')], cwd=source, check=True,
               stdout=subprocess.DEVNULL)
with tarfile.open('/tmp/pi-nodrop-runtime.tar.gz', 'w:gz') as tar:
    tar.add(pathlib.Path('/usr/local/bin/node').resolve(), arcname='node')
    tar.add('/usr/local/include/node', arcname='build/node-include')
    tar.add(root / 'node_modules', arcname='node_modules')
    tar.add(root / 'deps', arcname='deps')
    tar.add(str(root / 'sysroot') + prefix, arcname='build/musl')
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'deps').iterdir()}
out = pathlib.Path(__file__).resolve().parents[1] / 'vendor/dependencies.json'
out.write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared runtime and musl: /tmp/pi-nodrop-runtime.tar.gz', flush=True)
