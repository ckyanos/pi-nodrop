"""Build the prototype against the guest's running Linux headers."""
import hashlib
import json
import pathlib
import shutil
import subprocess
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/nodrop'
build = ROOT / 'build'
build.mkdir(exist_ok=True)
expected = json.loads((ROOT / 'vendor/dependencies.json').read_text())
for filename, digest in expected.items():
    assert hashlib.sha256((ROOT / 'deps' / filename).read_bytes()).hexdigest() == digest, filename
for name, version, target in [('lua', '5.4.6', 'lua'), ('zlib', '1.3.1', 'zlib')]:
    if not (SOURCE / target).exists():
        with tarfile.open(ROOT / 'deps' / f'{name}-{version}.tar.gz') as tar:
            tar.extractall(build / 'libsrc', filter='data')
        src = build / 'libsrc' / f'{name}-{version}'
        shutil.copytree(src / 'src' if name == 'lua' else src, SOURCE / target)
lua_init = SOURCE / 'lua/linit.c'
text = lua_init.read_text()
text = text.replace('  {LUA_LOADLIBNAME, luaopen_package},', '  /* package loader disabled in injected monitor */')
lua_init.write_text(text)
template = (SOURCE / 'scripts/getmusl.sh').read_text().split('<< EOF\n', 1)[1].split('\nEOF', 1)[0]
prefix = build / 'musl'
template = template.replace('$incdir', str(prefix / 'include')).replace('$libdir', str(prefix / 'lib'))
template = template.replace('$ldso', '/lib/ld-musl-x86_64.so.1')
(SOURCE / 'monitor/musl.specs').write_text(template + '\n')
subprocess.run(['cmake', '-S', str(SOURCE), '-B', str(build / 'nodrop'), '-DPKEY_SUPPORT=OFF',
                '-DBUFFER_SIZE=1048576', '-DSTORE_PATH=' + str(ROOT / 'results/audit'),
                '-DMONITOR_PATH=' + str(build / 'nodrop/monitor/monitor')], check=True)
subprocess.run(['cmake', '--build', str(build / 'nodrop'), '--target', 'kmodule', 'monitor', 'ctrl', '-j2'], check=True)
subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-DNODE_GYP_MODULE_NAME=context',
                '-I' + str(build / 'node-include'), '-I' + str(SOURCE / 'include'),
                str(ROOT / 'native/context.c'), '-o', str(build / 'context.node')], check=True)
print('BUILD COMPLETE', flush=True)
