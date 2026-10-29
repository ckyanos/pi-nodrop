"""Environment configuration shared by build and VM transport scripts."""
import os
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST_STAGE = pathlib.Path(os.environ.get('PI_NODROP_HOST_STAGE', ROOT / 'build/host')).expanduser().resolve()
RUNTIME_ARCHIVE = ROOT / 'build/pi-nodrop-runtime.tar.gz'
SOURCE_ARCHIVE = ROOT / 'build/pi-nodrop-source.tar.gz'


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise SystemExit(f'Set {name} before running this command')
    return value


def guest_dir():
    value = required('PI_NODROP_GUEST_DIR')
    path = pathlib.PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise SystemExit('PI_NODROP_GUEST_DIR must be an absolute project directory')
    return str(path)


def node_binary():
    value = shutil.which('node')
    if not value:
        raise SystemExit('Node.js must be available on PATH')
    return pathlib.Path(value).resolve()


def node_include():
    value = os.environ.get('PI_NODROP_NODE_INCLUDE')
    path = pathlib.Path(value).expanduser().resolve() if value else node_binary().parent.parent / 'include/node'
    if not (path / 'node_api.h').is_file():
        raise SystemExit('Set PI_NODROP_NODE_INCLUDE to the directory containing node_api.h')
    return path
