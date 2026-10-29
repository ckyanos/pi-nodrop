"""Build the pinned musl dependency on WSL; package for the guest path."""
import hashlib
import json
import os
import subprocess
import tarfile
from lab_config import HOST_STAGE, ROOT, RUNTIME_ARCHIVE, guest_dir, node_binary, node_include

root = HOST_STAGE
guest = guest_dir()
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
with tarfile.open(RUNTIME_ARCHIVE, 'w:gz') as tar:
    tar.add(node_binary(), arcname='node')
    tar.add(node_include(), arcname='build/node-include')
    tar.add(root / 'node_modules', arcname='node_modules')
    tar.add(root / 'deps', arcname='deps')
    tar.add(str(root / 'sysroot') + prefix, arcname='build/musl')
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'deps').iterdir()}
out = ROOT / 'vendor/dependencies.json'
out.write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared runtime and musl:', RUNTIME_ARCHIVE, flush=True)
